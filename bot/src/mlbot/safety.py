"""Safety catch: in the sandbox no message reaches a real student.

Season 2 is over, the bot holds 74 live bindings, and every test of new
behaviour risks mailing junk to real people. So the interception sits **on the
transport**, not in handlers: a handler is easy to forget to wrap, but no
Telegram API call bypasses the session.

Why a session request-middleware and nothing else:

* a dispatcher middleware only sees incoming updates — outgoing calls miss it;
* a `Bot` subclass overriding `send_message` and friends does not help:
  `message.answer()` and `call.message.edit_text()` go through `bot(method)`,
  not through them. The first new call would open a hole;
* `Bot.session.middleware` wraps EVERY API call — the only point where the
  interception is complete by construction.

A message to an outsider is not swallowed but redirected to the admin with a
tag. That gives the catch two jobs at once: it keeps the letter away from the
student and shows the teacher exactly what would have gone out.
"""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import TelegramMethod

from .config import Config

log = logging.getLogger("mlbot.safety")

BADGE = "🧪 ПЕСОЧНИЦА"

# Methods that create a message in someone else's chat. These get redirected.
_SENDING = ("send", "copy", "forward")
# Methods with no addressee at all: answering a callback, setting commands, self-query.
_NO_TARGET = ("answercallbackquery", "getme", "setmycommands", "deletewebhook",
              "getupdates", "setwebhook", "close", "logout", "getfile")


class BlockedBySafeMode(RuntimeError):
    """Editing or deleting a message in someone else's chat. Always a bug.

    Unlike sending, there is nowhere to redirect: you can only edit a message
    that already exists. So a handler decided it owns a foreign chat, and that
    must not stay quiet.
    """

    def __init__(self, method: str, chat_id: Any) -> None:
        super().__init__(f"sandbox: {method} into foreign chat {chat_id}")
        self.method = method
        self.chat_id = chat_id


def api_name(method: TelegramMethod) -> str:
    return getattr(method, "__api_method__", type(method).__name__)


def target_chat(method: TelegramMethod) -> Any | None:
    """Who the call is addressed to. None means no addressee, hence safe."""
    return getattr(method, "chat_id", None)


def is_sending(method: TelegramMethod) -> bool:
    return api_name(method).lower().startswith(_SENDING)


def has_no_target(method: TelegramMethod) -> bool:
    return api_name(method).lower() in _NO_TARGET


def badge(cfg: Config) -> str:
    """Tag for screens. Empty string once the catch is released."""
    return BADGE if cfg.safe_mode else ""


class SafeMode(BaseRequestMiddleware):
    """Intercepts outgoing calls while sandbox mode is on."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.intercepted = 0
        self.last: tuple[Any, str] | None = None      # (who it would reach, method)

    @property
    def allowed(self) -> frozenset[int]:
        return frozenset(self.cfg.admin_ids | self.cfg.sandbox_chat_ids)

    @property
    def sink(self) -> int | None:
        """Where to redirect. The first admin by ascending id."""
        ids = sorted(self.allowed)
        return ids[0] if ids else None

    def _redirect(self, method: TelegramMethod, chat_id: Any) -> TelegramMethod:
        """A copy of the call addressed to the admin, tagged in text or caption."""
        note = f"{BADGE} · ушло бы: id {chat_id}\n\n"
        update: dict[str, Any] = {"chat_id": self.sink}
        if getattr(method, "text", None) is not None:
            update["text"] = note + str(method.text)
        elif getattr(method, "caption", None) is not None:
            update["caption"] = note + str(method.caption)
        # Methods without text (sendChatAction, say) have nowhere to put the tag —
        # swapping the addressee is enough.
        return method.model_copy(update=update)

    async def __call__(self, make_request, bot: Bot, method: TelegramMethod):
        if not self.cfg.safe_mode:
            return await make_request(bot, method)

        chat_id = target_chat(method)
        if chat_id is None or has_no_target(method):
            return await make_request(bot, method)

        try:
            allowed = int(chat_id) in self.allowed
        except (TypeError, ValueError):
            allowed = False                     # @channel or something non-numeric
        if allowed:
            return await make_request(bot, method)

        self.intercepted += 1
        self.last = (chat_id, api_name(method))

        if is_sending(method) and self.sink is not None:
            log.info("sandbox: %s for %s redirected to the admin", api_name(method), chat_id)
            return await make_request(bot, self._redirect(method, chat_id))

        raise BlockedBySafeMode(api_name(method), chat_id)
