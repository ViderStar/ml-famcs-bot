"""A test bench: the real dispatcher, a fake Telegram session.

It exists so the bot can be checked **by behaviour, not by grepping the source**.
Text checks ("the file contains `_is_admin(cfg`") stop meaning anything the
moment the code moves to another module: they do not fail — they pass silently.

Updates go through `dp.feed_update`, so through every middleware, filter and
router in their real order. Outgoing calls are caught by `Recorder` — a
substitution at session level, exactly where `SafeMode` sits, so its effect is
visible in tests too.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import TelegramMethod
from aiogram.types import (
    CallbackQuery,
    Chat,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    Update,
    User,
)

from mlbot.__main__ import ROUTERS, build_dispatcher
from mlbot.middlewares import Throttle

TOKEN = "42:TESTTESTTESTTESTTESTTESTTESTTESTTES"


def detach_routers() -> None:
    """Detach the routers from a dispatcher built earlier.

    Routers are module-level singletons, and aiogram deliberately forbids
    attaching one router to two dispatchers: in production that is almost always
    a bug. In tests the dispatcher is rebuilt — sometimes twice inside one test —
    so the previous owner is released.
    """
    for module in ROUTERS:
        module.router._parent_router = None


@dataclass
class Sent:
    """One outgoing call in a shape convenient for assertions."""

    api: str
    chat_id: int | None
    text: str
    markup: Any = None

    @property
    def buttons(self) -> list[tuple[str, str | None]]:
        """Button captions and `callback_data`: inline and reply alike."""
        if isinstance(self.markup, InlineKeyboardMarkup):
            return [(b.text, b.callback_data)
                    for row in self.markup.inline_keyboard for b in row]
        if isinstance(self.markup, ReplyKeyboardMarkup):
            return [(b.text, None) for row in self.markup.keyboard for b in row]
        return []


class Recorder(BaseSession):
    """A session that sends nothing and collects the calls in a list."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[Sent] = []
        self._ids = itertools.count(9000)

    async def close(self) -> None:  # pragma: no cover — the session holds nothing
        pass

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        yield b""

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):
        api = type(method).__name__
        chat_id = getattr(method, "chat_id", None)
        text = getattr(method, "text", None) or getattr(method, "caption", None) or ""
        self.calls.append(Sent(api, chat_id, str(text), getattr(method, "reply_markup", None)))
        if api.startswith(("Send", "Copy", "Forward")):
            return Message(
                message_id=next(self._ids),
                date=datetime.now(timezone.utc),
                chat=Chat(id=int(chat_id or 0), type="private"),
            )
        return True


class Bench:
    """One user talking to the bot."""

    def __init__(self, cfg, course, store, demo=None, *,
                 user_id: int = 777, username: str | None = None,
                 safe: bool = False) -> None:
        detach_routers()
        self.session = Recorder()
        self.bot = Bot(token=TOKEN, session=self.session)
        # The safety catch goes where it goes in production: a session
        # middleware, on the path of every API call. Without it the test would be
        # checking a different bot.
        if safe:
            from mlbot.safety import SafeMode
            self.safe = SafeMode(cfg)
            self.bot.session.middleware(self.safe)
        self.dp = build_dispatcher(cfg, course, store, demo)
        # Throttling is sized for a human: 0.4 s between presses. A test presses
        # buttons in microseconds, and without this half of them would drown in
        # "not so fast". The middleware itself stays in place — the check that it
        # is registered lives in test_tester_mode.py.
        for observer in (self.dp.message, self.dp.callback_query):
            for mw in observer.outer_middleware:
                if isinstance(mw, Throttle):
                    mw.interval = 0.0
        self.user = User(id=user_id, is_bot=False, first_name="Тест", username=username)
        self.chat = Chat(id=user_id, type="private")
        self._ids = itertools.count(1)
        self.screens: list[Sent] = []

    async def _feed(self, update: Update) -> list[Sent]:
        before = len(self.session.calls)
        await self.dp.feed_update(self.bot, update)
        fresh = self.session.calls[before:]
        self.screens = fresh
        return fresh

    async def send(self, text: str, entities=None) -> list[Sent]:
        """`entities` — formatting the way Telegram sends it: beside the text, not in it."""
        message = Message(
            message_id=next(self._ids),
            date=datetime.now(timezone.utc),
            chat=self.chat,
            from_user=self.user,
            text=text,
            entities=entities,
        )
        return await self._feed(Update(update_id=next(self._ids), message=message))

    async def press(self, data: str) -> list[Sent]:
        carrier = Message(
            message_id=next(self._ids),
            date=datetime.now(timezone.utc),
            chat=self.chat,
        )
        call = CallbackQuery(
            id=str(next(self._ids)),
            from_user=self.user,
            chat_instance="test",
            data=data,
            message=carrier,
        )
        return await self._feed(Update(update_id=next(self._ids), callback_query=call))

    @property
    def text(self) -> str:
        """All the text of the last reply as one string."""
        return "\n".join(s.text for s in self.screens)

    @property
    def buttons(self) -> list[tuple[str, str | None]]:
        return [b for s in self.screens for b in s.buttons]


@dataclass
class Crawl:
    """The traversal result: what was pressed, what was seen."""

    pressed: set[str] = field(default_factory=set)
    sent: list[Sent] = field(default_factory=list)
    labels: set[str] = field(default_factory=set)

    @property
    def payloads(self) -> set[str]:
        """Every `callback_data` the bot ever showed."""
        return {d for s in self.sent for _, d in s.buttons if d}


async def crawl(bench: Bench, start: str = "/start", *, limit: int = 400) -> Crawl:
    """Walk everything reachable by pressing buttons.

    By buttons rather than by the menu registry: this way the test sees the bot
    exactly as a student does and does not depend on how the menu is built
    inside — so it survives any restructuring.

    Reply-keyboard buttons are text messages, and some of them start a dialogue
    ("type a surname"). `/cancel` is sent before each, otherwise the next press
    would land as an answer to the question rather than in the menu.
    """
    out = Crawl()
    seen_data: set[str] = set()
    seen_label: set[str] = set()
    queue: list[tuple[str, str]] = []

    def collect(batch: list[Sent]) -> None:
        out.sent += batch
        for s in batch:
            for label, data in s.buttons:
                out.labels.add(label)
                if data is not None:
                    if data not in seen_data:
                        seen_data.add(data)
                        queue.append(("cb", data))
                elif label not in seen_label:
                    seen_label.add(label)
                    queue.append(("txt", label))

    collect(await bench.send(start))
    while queue and len(out.pressed) < limit:
        kind, arg = queue.pop(0)
        out.pressed.add(arg)
        if kind == "cb":
            collect(await bench.press(arg))
        else:
            await bench.send("/cancel")
            collect(await bench.send(arg))
    return out
