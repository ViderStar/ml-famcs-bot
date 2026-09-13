"""Команды, которые должны работать везде и всегда.

Живут отдельно от админки: та целиком под фильтром прав, и `/cancel` оттуда
перестал бы отвечать студенту, застрявшему в диалоге поддержки.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from ..config import Config

router = Router()


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.")


@router.message(Command("id"))
async def my_id(message: Message, cfg: Config) -> None:
    """Свой telegram-id: нужен, чтобы прописать себя в ADMIN_IDS."""
    admin = cfg.is_admin(message.from_user.id, message.from_user.username)
    await message.answer(
        f"Твой telegram-id: <code>{message.from_user.id}</code>\n"
        + ("Права администратора есть." if admin else
           "Прав администратора нет — этот id нужно добавить в <code>ADMIN_IDS</code> "
           "в <code>bot/.env</code> и перезапустить бота.")
    )
