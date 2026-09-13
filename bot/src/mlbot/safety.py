"""Предохранитель: в песочнице ни одно сообщение не уходит настоящему студенту.

Второй сезон закончился, у бота 74 живые привязки, и любая проверка нового
функционала — это риск разослать людям мусор. Поэтому перехват стоит **на
транспорте**, а не в обработчиках: обработчик можно забыть обернуть, а мимо
сессии не проходит ни один вызов Telegram API.

Почему именно request-middleware сессии, а не что-то другое:

* мидлварь диспетчера видит только входящие апдейты — исходящие мимо неё;
* подкласс `Bot` с переопределёнными `send_message` и прочими не поможет:
  `message.answer()` и `call.message.edit_text()` идут не через них, а через
  `bot(method)`. Дырка появилась бы при первом же новом вызове;
* `Bot.session.middleware` оборачивает КАЖДЫЙ вызов API — это единственная
  точка, где перехват полный по построению.

Сообщение постороннему не проглатывается, а перенаправляется администратору с
пометкой. Так у предохранителя two в одном: он и не пускает письмо студенту, и
показывает преподавателю ровно то, что ушло бы.
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

# Методы, которые создают сообщение в чужом чате. Их перенаправляем.
_SENDING = ("send", "copy", "forward")
# Методы без адресата вообще: отвечают на колбэк, ставят команды, спрашивают себя.
_NO_TARGET = ("answercallbackquery", "getme", "setmycommands", "deletewebhook",
              "getupdates", "setwebhook", "close", "logout", "getfile")


class BlockedBySafeMode(RuntimeError):
    """Правка или удаление сообщения в чужом чате. Это всегда ошибка в коде.

    В отличие от отправки, тут перенаправлять некуда: редактировать можно только
    то сообщение, которое уже существует. Значит, обработчик решил, что владеет
    чужим чатом, и молчать об этом нельзя.
    """

    def __init__(self, method: str, chat_id: Any) -> None:
        super().__init__(f"песочница: {method} в чужой чат {chat_id}")
        self.method = method
        self.chat_id = chat_id


def api_name(method: TelegramMethod) -> str:
    return getattr(method, "__api_method__", type(method).__name__)


def target_chat(method: TelegramMethod) -> Any | None:
    """Кому адресован вызов. None — адресата нет (значит, безопасно)."""
    return getattr(method, "chat_id", None)


def is_sending(method: TelegramMethod) -> bool:
    return api_name(method).lower().startswith(_SENDING)


def has_no_target(method: TelegramMethod) -> bool:
    return api_name(method).lower() in _NO_TARGET


def badge(cfg: Config) -> str:
    """Пометка для экранов. Пустая строка, когда предохранитель снят."""
    return BADGE if cfg.safe_mode else ""


class SafeMode(BaseRequestMiddleware):
    """Перехватывает исходящие вызовы, пока включён режим песочницы."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.intercepted = 0
        self.last: tuple[Any, str] | None = None      # (кому бы ушло, метод)

    @property
    def allowed(self) -> frozenset[int]:
        return frozenset(self.cfg.admin_ids | self.cfg.sandbox_chat_ids)

    @property
    def sink(self) -> int | None:
        """Куда перенаправлять. Первый администратор по возрастанию id."""
        ids = sorted(self.allowed)
        return ids[0] if ids else None

    def _redirect(self, method: TelegramMethod, chat_id: Any) -> TelegramMethod:
        """Копия вызова, адресованная админу, с пометкой в тексте или подписи."""
        note = f"{BADGE} · ушло бы: id {chat_id}\n\n"
        update: dict[str, Any] = {"chat_id": self.sink}
        if getattr(method, "text", None) is not None:
            update["text"] = note + str(method.text)
        elif getattr(method, "caption", None) is not None:
            update["caption"] = note + str(method.caption)
        # У методов без текста (например, sendChatAction) пометку вставить некуда —
        # достаточно того, что адресат подменён.
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
            allowed = False                     # @канал или что-то нечисловое
        if allowed:
            return await make_request(bot, method)

        self.intercepted += 1
        self.last = (chat_id, api_name(method))

        if is_sending(method) and self.sink is not None:
            log.info("песочница: %s для %s перенаправлен админу", api_name(method), chat_id)
            return await make_request(bot, self._redirect(method, chat_id))

        raise BlockedBySafeMode(api_name(method), chat_id)
