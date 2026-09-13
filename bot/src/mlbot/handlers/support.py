"""Поддержка: прямая ссылка на преподавателя и приём вопроса через бота."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from .. import texts
from ..config import Config
from ..data import Course
from ..keyboards import support as support_kb
from ..render import escape
from ..store import Store
from .deps import student_of

router = Router()


class Ask(StatesGroup):
    waiting_text = State()


@router.message(F.text == "🆘 Поддержка")
@router.message(Command("support"))
async def support_entry(message: Message, state: FSMContext, cfg: Config, store: Store) -> None:
    await store.log(message.from_user.id, "support")
    await state.set_state(Ask.waiting_text)
    await message.answer(texts.SUPPORT.format(username=cfg.support_username),
                         reply_markup=support_kb(cfg.support_username))


@router.message(Ask.waiting_text, F.text)
async def receive_question(message: Message, state: FSMContext, cfg: Config,
                           course: Course, store: Store) -> None:
    await state.clear()
    student = await student_of(message.from_user.id, course, store)
    ticket = await store.add_support(
        message.from_user.id, message.from_user.username, message.text)

    who = student.fio if student else message.from_user.full_name
    tag = f"@{message.from_user.username}" if message.from_user.username else message.from_user.id
    for admin_id in cfg.admin_ids:
        try:
            await message.bot.send_message(
                admin_id,
                f"✉️ <b>Обращение #{ticket}</b>\nОт: {escape(str(who))} ({escape(str(tag))})\n\n"
                f"{escape(message.text)}",
            )
        except Exception:
            continue
    await message.answer(texts.SUPPORT_SENT)
