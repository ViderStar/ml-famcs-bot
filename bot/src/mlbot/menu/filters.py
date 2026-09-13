"""A rights filter that cannot be forgotten.

A check inside a handler rests on discipline: the handler gets written and the
`if not _is_admin(...)` line gets forgotten, and a test that grepped for it
notices nothing. The filter goes on the router observer once, and after that an
unprotected handler in that router is physically impossible.
"""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from ..config import Config


class AdminOnly(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, cfg: Config) -> bool:
        user = event.from_user
        return bool(user and cfg.is_admin(user.id, user.username))
