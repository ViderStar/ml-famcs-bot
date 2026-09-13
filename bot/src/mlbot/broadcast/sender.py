"""Отправка рассылки: одна функция доставки, возобновляемый цикл.

Предпросмотр и настоящая отправка идут через `deliver` — иначе «так будет
выглядеть» и «так выглядит» разъезжаются. Побочная польза: битая HTML-разметка
падает на администраторе, ещё до появления кнопки подтверждения.
"""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

log = logging.getLogger("broadcast")

# Пауза между отправками. Телеграм разрешает ~30 сообщений в секунду, но
# спешить некуда, а на пределе он начинает просить подождать.
PAUSE = 0.05
# Как часто править сообщение с прогрессом. Чаще нельзя: правка — тоже вызов API.
PROGRESS_EVERY = 3.0


async def guard(factory):
    """Повтор при «подожди столько-то секунд». Вынесено из `announce.py`."""
    while True:
        try:
            return await factory()
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)


async def deliver(bot: Bot, chat_id: int, draft: dict):
    """Доставить одно письмо. Единственный способ отправить рассылку."""
    if draft["kind"] == "copy" and draft.get("src_chat"):
        return await guard(lambda: bot.copy_message(
            chat_id=chat_id, from_chat_id=draft["src_chat"],
            message_id=draft["src_msg"]))
    return await guard(lambda: bot.send_message(
        chat_id, draft["body"] or "", disable_web_page_preview=True))


async def run(bot: Bot, store, cast_id: int, on_progress=None) -> dict[str, int]:
    """Разослать остаток. Безопасно вызывать повторно после обрыва."""
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
                # Заблокировал бота или удалил аккаунт. Повторять бессмысленно,
                # поэтому в «ожидании» такой адресат не остаётся.
                await store.mark_target(cast_id, target["tg_id"], "blocked")
            except Exception as exc:
                await store.mark_target(cast_id, target["tg_id"], "failed",
                                        f"{type(exc).__name__}: {exc}"[:300])
                log.warning("рассылка %s → %s: %s", cast_id, target["tg_id"], exc)
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
