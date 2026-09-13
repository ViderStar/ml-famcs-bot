"""Фильтр прав, который нельзя забыть.

Проверка внутри обработчика держится на дисциплине: новый обработчик пишут,
а строчку `if not _is_admin(...)` — забывают, и тест, который её искал грепом,
ничего не заметит. Фильтр вешается на обсервер роутера один раз, и тогда
незащищённый обработчик в этом роутере физически невозможен.
"""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from ..config import Config


class AdminOnly(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery, cfg: Config) -> bool:
        user = event.from_user
        return bool(user and cfg.is_admin(user.id, user.username))
