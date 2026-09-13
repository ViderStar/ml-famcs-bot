"""The command list behind the Menu button next to the input field.

Telegram shows it on its own, but only if the bot sent the list through
setMyCommands. Admin commands are visible to admins only — their list is set
separately, scoped to their chat.
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
            # The admin has not written to the bot yet — the list will be picked up next start.
            pass
