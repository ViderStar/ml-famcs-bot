"""Стенд: настоящий диспетчер, поддельная сессия телеграма.

Нужен, чтобы проверять бота **поведением, а не грепом по исходникам**. Текстовые
проверки («в файле есть подстрока `_is_admin(cfg`») перестают что-либо значить,
как только код переезжает в другой модуль: они не падают — они молча проходят.

Апдейты идут через `dp.feed_update`, то есть через все мидлвари, фильтры и
роутеры в их настоящем порядке. Исходящие вызовы перехватывает `Recorder` —
подмена на уровне сессии, ровно там же, где стоит `SafeMode`, поэтому в тестах
виден и результат его работы.
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
    """Отпустить роутеры от диспетчера, собранного раньше.

    Роутеры — синглтоны уровня модуля, и аиограм намеренно запрещает
    подключить один роутер к двум диспетчерам: в бою это почти всегда
    ошибка. В тестах диспетчер собирается заново — иногда дважды внутри
    одного теста, — поэтому прежнего владельца снимаем.
    """
    for module in ROUTERS:
        module.router._parent_router = None


@dataclass
class Sent:
    """Один исходящий вызов в удобном для проверок виде."""

    api: str
    chat_id: int | None
    text: str
    markup: Any = None

    @property
    def buttons(self) -> list[tuple[str, str | None]]:
        """Подписи и `callback_data` кнопок: инлайновых и обычных."""
        if isinstance(self.markup, InlineKeyboardMarkup):
            return [(b.text, b.callback_data)
                    for row in self.markup.inline_keyboard for b in row]
        if isinstance(self.markup, ReplyKeyboardMarkup):
            return [(b.text, None) for row in self.markup.keyboard for b in row]
        return []


class Recorder(BaseSession):
    """Сессия, которая ничего не отправляет, а складывает вызовы в список."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[Sent] = []
        self._ids = itertools.count(9000)

    async def close(self) -> None:  # pragma: no cover — сессия ничего не держит
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
    """Один пользователь, разговаривающий с ботом."""

    def __init__(self, cfg, course, store, demo=None, *,
                 user_id: int = 777, username: str | None = None,
                 safe: bool = False) -> None:
        detach_routers()
        self.session = Recorder()
        self.bot = Bot(token=TOKEN, session=self.session)
        # Предохранитель ставится там же, где в бою: мидлварью сессии, то есть
        # на пути каждого вызова API. Без него тест проверял бы не того бота.
        if safe:
            from mlbot.safety import SafeMode
            self.safe = SafeMode(cfg)
            self.bot.session.middleware(self.safe)
        self.dp = build_dispatcher(cfg, course, store, demo)
        # Троттлинг рассчитан на живого человека: 0.4 с между нажатиями. Тест
        # жмёт кнопки за микросекунды, и без этого половина нажатий утонула бы
        # в «Не так быстро». Сама мидлварь остаётся на месте — проверка её
        # регистрации живёт в test_tester_mode.py.
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
        """`entities` — разметка так, как её присылает телеграм: не в тексте, а рядом."""
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
        """Весь текст последнего ответа одной строкой."""
        return "\n".join(s.text for s in self.screens)

    @property
    def buttons(self) -> list[tuple[str, str | None]]:
        return [b for s in self.screens for b in s.buttons]


@dataclass
class Crawl:
    """Итог обхода: что нажали, что увидели."""

    pressed: set[str] = field(default_factory=set)
    sent: list[Sent] = field(default_factory=list)
    labels: set[str] = field(default_factory=set)

    @property
    def payloads(self) -> set[str]:
        """Все `callback_data`, которые бот когда-либо показал."""
        return {d for s in self.sent for _, d in s.buttons if d}


async def crawl(bench: Bench, start: str = "/start", *, limit: int = 400) -> Crawl:
    """Обойти всё, до чего можно дожать кнопками.

    Обход по кнопкам, а не по реестру меню: так тест видит бота ровно тем же,
    чем его видит студент, и не зависит от того, как меню устроено внутри —
    поэтому переживает любую перестройку.

    Кнопки обычной клавиатуры — это текстовые сообщения, и некоторые из них
    начинают диалог («введите фамилию»). Перед каждой шлём `/cancel`, иначе
    следующее нажатие уедет в ответ на вопрос, а не в меню.
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
