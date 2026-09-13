"""Троттлинг, память об аккаунте и подмена курса в демо-режиме."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class Throttle(BaseMiddleware):
    """Не даёт заспамить бота: одно действие в `interval` секунд на пользователя."""

    def __init__(self, interval: float = 0.4) -> None:
        self.interval = interval
        self._last: dict[int, float] = defaultdict(float)

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is None:
            return await handler(event, data)
        now = time.monotonic()
        if now - self._last[user.id] < self.interval:
            if isinstance(event, CallbackQuery):
                await event.answer("Не так быстро 🙂")
                return None
            if isinstance(event, Message):
                return None
        self._last[user.id] = now
        return await handler(event, data)


class DemoCourse(BaseMiddleware):
    """Подменяет курс, когда админ смотрит глазами вымышленного студента.

    Демо живёт в отдельном каталоге и своём объекте `Course`, а не подмешивается
    к настоящим 205: иначе оно поехало бы в медиану, перцентиль и число
    сертификатов, и заметить это было бы нечем.

    Подмена делается здесь, а не в обработчиках: `deps._resolve` уже смотрит в
    `test_views`, поэтому достаточно положить в данные другой курс — и **ни один
    обработчик не меняется**.
    """

    def __init__(self, demo) -> None:
        self.demo = demo

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        store = data.get("store")
        if user is not None and store is not None and self.demo is not None:
            key = await store.test_view(user.id)
            if key and key in self.demo.students:
                data["course"] = self.demo
                data["demo"] = True
        return await handler(event, data)


class Identity(BaseMiddleware):
    """Помнит аккаунт и записывает смену username.

    Username — атрибут, а не ключ: он освобождается и достаётся другому
    человеку, и во втором сезоне именно на этом посторонний аккаунт открыл
    чужой разбор. Журнал нужен, чтобы такую смену было видно, а не
    восстанавливать по памяти.

    В базу пишем только при изменении: иначе на каждое нажатие кнопки
    приходился бы `UPDATE`.
    """

    def __init__(self) -> None:
        self._seen: dict[int, str] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        store = data.get("store")
        if user is not None and store is not None:
            mark = f"{user.username or ''}|{user.full_name or ''}"
            if self._seen.get(user.id) != mark:
                self._seen[user.id] = mark
                await store.touch_person(user.id, user.username, user.full_name)
        return await handler(event, data)
