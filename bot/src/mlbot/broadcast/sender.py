"""Sending a broadcast: one delivery function, a resumable loop.

Preview and real sending both go through `deliver` — otherwise "this is how it
will look" and "this is how it looks" drift apart. Side benefit: broken HTML
fails on the admin, before the confirm button ever appears.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

log = logging.getLogger("broadcast")

# Pause between sends. Telegram allows about 30 messages a second, but there is
# no hurry, and at the limit it starts asking us to wait.
PAUSE = 0.05
# How often to edit the progress message. No faster: an edit is an API call too.
PROGRESS_EVERY = 3.0


async def guard(factory):
    """Retry on "wait N seconds". Extracted from `announce.py`."""
    while True:
        try:
            return await factory()
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)


async def deliver(bot: Bot, chat_id: int, draft: dict):
    """Deliver one letter. The only way a broadcast is sent."""
    if draft["kind"] == "copy" and draft.get("src_chat"):
        return await guard(lambda: bot.copy_message(
            chat_id=chat_id, from_chat_id=draft["src_chat"],
            message_id=draft["src_msg"]))
    return await guard(lambda: bot.send_message(
        chat_id, draft["body"] or "", disable_web_page_preview=True))


async def run(bot: Bot, store, cast_id: int, on_progress=None) -> dict[str, int]:
    """Send the remainder. Safe to call again after an interruption."""
    draft = await store.broadcast(cast_id)
    if draft is None:
        return {}
    last_report = 0.0
    while True:
        batch = await store.pending_targets(cast_id, limit=200)
        if not batch:
            break
        for target in batch:
            try:
                await deliver(bot, target["tg_id"], draft)
            except TelegramForbiddenError:
                # Blocked the bot or deleted the account. Retrying is pointless,
                # so this recipient does not stay in "pending".
                await store.mark_target(cast_id, target["tg_id"], "blocked")
            except Exception as exc:
                await store.mark_target(cast_id, target["tg_id"], "failed",
                                        f"{type(exc).__name__}: {exc}"[:300])
                log.warning("broadcast %s → %s: %s", cast_id, target["tg_id"], exc)
            else:
                await store.mark_target(cast_id, target["tg_id"], "sent")
            await asyncio.sleep(PAUSE)
            now = asyncio.get_event_loop().time()
            if on_progress and now - last_report > PROGRESS_EVERY:
                last_report = now
                await on_progress(await store.broadcast_stats(cast_id))
    stats = await store.broadcast_stats(cast_id)
    await store.finish_broadcast(cast_id, "done")
    if on_progress:
        await on_progress(stats)
    return stats
