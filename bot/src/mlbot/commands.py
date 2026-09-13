"""Список команд для кнопки «Меню» рядом с полем ввода.

Телеграм показывает его сам, но только если бот прислал список через
setMyCommands. Админские команды видны лишь администраторам — для них список
задаётся отдельно, в области конкретного чата.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault

STUDENT = (
    ("start", "начать заново"),
    ("results", "мои результаты"),
    ("homeworks", "домашки и разбор ошибок"),
    ("improve", "что подтянуть"),
    ("strengths", "сильные стороны за курс"),
    ("materials", "материалы сезона"),
    ("certificate", "сертификат"),
    ("reference", "справочник ошибок"),
    ("find", "искать по справочнику"),
    ("support", "поддержка"),
    ("whoami", "к какой записи я привязан"),
    ("id", "мой telegram-id"),
    ("help", "справка"),
)

ADMIN = (
    ("admin", "панель администратора"),
    ("test", "смотреть глазами студента"),
    ("broadcast", "рассылка"),
    ("cancel", "отменить действие"),
)


def _commands(pairs) -> list[BotCommand]:
    return [BotCommand(command=c, description=d) for c, d in pairs]


async def setup(bot: Bot, admin_ids) -> None:
    await bot.set_my_commands(_commands(STUDENT), scope=BotCommandScopeDefault())
    for admin_id in admin_ids:
        try:
            await bot.set_my_commands(
                _commands(STUDENT + ADMIN),
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            # Админ ещё не писал боту — список подхватится при следующем запуске.
            pass
