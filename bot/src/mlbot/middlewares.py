"""Throttling, account memory and course substitution in demo mode."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject


class Throttle(BaseMiddleware):
    """Keeps the bot from being spammed: one action per `interval` seconds per user."""

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
    """Substitutes the course when an admin looks through a fictional student's eyes.

    Demo lives in its own directory and its own `Course` object instead of being
    mixed into the real corpus: otherwise it would seep into the median, the
    percentile and the certificate count, with nothing to notice it by.

    The substitution happens here rather than in handlers: `deps._resolve`
    already consults `test_views`, so putting a different course into the data is
    enough — and **no handler changes**.
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
    """Remembers the account and records username changes.

    A username is an attribute, not a key: it gets released and goes to someone
    else, and in season 2 that is exactly how an outsider opened another
    student's review. The log exists so such a change is visible instead of
    reconstructed from memory.

    The database is written only on change: otherwise every button press would
    cost an `UPDATE`.
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
