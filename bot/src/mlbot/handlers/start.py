"""Онбординг и привязка аккаунта к записи студента.

Проверка двухфакторная: нужны и ссылка на репозиторий, и ФИО, и они должны
указывать на одну строку формы. Порядок любой — что прислали первым, то и
считаем первым фактором.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import texts
from ..config import Config
from ..data import Course
from ..keyboards import confirm_self, support
from ..menu import core as menu
from ..render import escape
from ..matching import (find_by_fio, find_by_repo, find_by_username, fio_matches,
                        looks_like_repo)
from ..store import Store

router = Router()

# Обычный текст, а не команда. Без этого фильтра состояние онбординга съедало
# и /admin с /help: они матчились как текст и до своих обработчиков не доходили.
_PLAIN = F.text & ~F.text.startswith("/")


def _who(user) -> dict:
    """Кто написал: по одному id администратора не сопоставить с человеком."""
    return {"username": user.username, "name": user.full_name}


class Onboarding(StatesGroup):
    confirming_self = State()
    waiting_id = State()
    waiting_fio = State()
    waiting_repo = State()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext, course: Course,
                store: Store, cfg: Config) -> None:
    await state.clear()
    binding = await store.binding(message.from_user.id)
    if binding and binding.student_key in course.students:
        student = course.students[binding.student_key]
        await store.log(message.from_user.id, "start", _who(message.from_user))
        await message.answer(
            texts.BOUND.format(fio=student.fio) + "\n\n" + texts.MENU_HINT,
            reply_markup=menu.keyboard_for(cfg, message.from_user, student),
        )
        return
    # Администратор — это преподаватель, записи студента у него нет, и гнать
    # его через привязку незачем: он бы застрял в онбординге без выхода.
    # Состояние онбординга ему не ставим: иначе «Тест ФИО» ушёл бы в поиск по
    # ФИО как попытка привязаться. Глазами студента он смотрит через тестер-режим.
    if cfg.is_admin(message.from_user.id, message.from_user.username):
        from .admin import test_examples
        cert, fail = test_examples(course)
        await store.log(message.from_user.id, "start_admin", _who(message.from_user))
        await message.answer(
            texts.ADMIN_WELCOME.format(cert_fio=escape(cert.fio), fail_fio=escape(fail.fio)),
            reply_markup=menu.keyboard_for(cfg, message.from_user),
        )
        return

    # Форма регистрации на курс даёт username → ФИО, так что большинству
    # достаточно нажать «да». Молча не привязываем: username мог освободиться
    # и достаться другому человеку.
    guess = find_by_username(course, message.from_user.username)
    if guess and not await store.binding_of_student(guess.key):
        await state.set_state(Onboarding.confirming_self)
        await state.update_data(candidate=guess.key)
        await message.answer(texts.ASK_SELF_CONFIRM.format(
            fio=guess.fio, repo=guess.repo or ""), reply_markup=confirm_self())
        return

    await state.set_state(Onboarding.waiting_id)
    await store.log(message.from_user.id, "start", _who(message.from_user))
    await message.answer(
        texts.WELCOME,
        reply_markup=menu.keyboard_for(cfg, message.from_user,
                                       placeholder="Пришли ссылку на репозиторий"),
    )


@router.callback_query(Onboarding.confirming_self, F.data == "ident:yes")
async def confirm_self_yes(call: CallbackQuery, state: FSMContext, course: Course,
                           store: Store, cfg: Config) -> None:
    data = await state.get_data()
    student = course.students.get(data.get("candidate", ""))
    await call.answer()
    if student is None:
        await state.set_state(Onboarding.waiting_id)
        await call.message.answer(texts.ASK_REPO)
        return
    await store.log(call.from_user.id, "bind_by_username", {"key": student.key})
    await _finish(call.message, state, store, cfg, course, student,
                  actor=call.from_user)


@router.callback_query(Onboarding.confirming_self, F.data == "ident:no")
async def confirm_self_no(call: CallbackQuery, state: FSMContext) -> None:
    await call.answer()
    await state.set_state(Onboarding.waiting_id)
    await call.message.answer(texts.WELCOME)


async def _notify_admins(bot, cfg: Config, store: Store, student, actor,
                         expected: str | None, claim_id: int) -> None:
    """Сообщить администраторам о заявке. По username id не знаем — только по ADMIN_IDS."""
    reason = (f"В форме закреплён: @{escape(expected)} — <b>не совпадает</b>"
              if expected else
              "В форме регистрации телеграма нет — сверить не с чем")
    text = (f"🔑 <b>Заявка на доступ #{claim_id}</b>\n\n"
            f"Запись: <b>{escape(student.fio)}</b>\n"
            f"{reason}\n"
            f"Просит доступ: @{escape(actor.username or '—')} "
            f"({escape(actor.full_name or '')}, id {actor.id})\n"
            f"Репозиторий записи: {escape(student.repo or '—')}\n\n"
            f"Разобрать — «🛠 Админка» → «🔑 Заявки на доступ».")
    for admin_id in cfg.admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            continue


async def _finish(message: Message, state: FSMContext, store: Store, cfg: Config,
                  course: Course, student, actor=None) -> None:
    """Привязывает аккаунт и показывает меню.

    `actor` нужен там, где решение пришло нажатием кнопки: у сообщения бота
    `from_user` — это сам бот, а привязывать надо того, кто нажал.
    """
    actor = actor or message.from_user
    taken = await store.binding_of_student(student.key)
    if taken and taken.tg_id != actor.id:
        await state.clear()
        await message.answer(texts.STUDENT_TAKEN.format(fio=student.fio),
                             reply_markup=support(cfg.support_username))
        return

    # Мгновенно привязываем только там, где username доказывает владение:
    # он принадлежит аккаунту, который пишет боту, и совпадает с закреплённым за
    # записью в форме регистрации. ФИО и ссылка на репозиторий доказательством не
    # являются — и то и другое известно однокурсникам, и в первую же неделю
    # посторонний аккаунт так открыл чужой разбор. Всё остальное ждёт человека:
    # и записи с другим username, и те 47, где username в форме нет вовсе.
    expected = course.expected_username(student.key)
    if not expected or (actor.username or "").lower() != expected.lower():
        claim_id = await store.add_claim(actor.id, student.key, actor.username,
                                         actor.full_name, expected)
        await store.log(actor.id, "claim", {"key": student.key, "claim": claim_id})
        await state.clear()
        template = texts.CLAIM_CREATED if expected else texts.CLAIM_CREATED_NO_USERNAME
        await message.answer(
            template.format(fio=escape(student.fio), support=cfg.support_username),
            reply_markup=support(cfg.support_username))
        await _notify_admins(message.bot, cfg, store, student, actor, expected, claim_id)
        return

    await store.bind(actor.id, student.key, actor.username, actor.full_name)
    await store.log(actor.id, "bind", {"key": student.key})
    await state.clear()

    number = await store.binding_number(actor.id)
    tail = f"\n\nКстати, ты {number}-й, кто сюда добрался." if number else ""
    await message.answer(
        texts.BOUND.format(fio=student.fio) + tail + "\n\n" + texts.MENU_HINT,
        reply_markup=menu.keyboard_for(cfg, actor, student),
    )


@router.message(Onboarding.confirming_self, _PLAIN)
async def typed_instead_of_confirming(message: Message, state: FSMContext, course: Course,
                                      store: Store, cfg: Config) -> None:
    """Вместо кнопки прислали ссылку или ФИО — значит, узнали не того."""
    await state.set_state(Onboarding.waiting_id)
    await got_identifier(message, state, course, store, cfg)


@router.message(Onboarding.waiting_id, _PLAIN)
async def got_identifier(message: Message, state: FSMContext, course: Course,
                         store: Store, cfg: Config) -> None:
    text = message.text.strip()
    # Нажали кнопку меню, а не прислали ссылку — отдаём событие дальше, тому,
    # кому кнопка принадлежит. Список берётся из реестра узлов: захардкоженный
    # кортеж разошёлся бы с меню молча, и админ снова застрял бы в онбординге.
    if text in menu.root_labels():
        raise SkipHandler

    if looks_like_repo(text):
        student = find_by_repo(course, text)
        if not student:
            await message.answer(texts.REPO_NOT_FOUND)
            return
        await state.update_data(candidate=student.key)
        await state.set_state(Onboarding.waiting_fio)
        await message.answer(texts.ASK_FIO_CONFIRM)
        return

    matches = find_by_fio(course, text)
    if not matches:
        await message.answer(texts.FIO_NOT_FOUND)
        return
    if not matches[0].confident or (len(matches) > 1 and matches[1].confident):
        await message.answer(texts.ASK_REPO)
        return
    await state.update_data(candidate=matches[0].student.key)
    await state.set_state(Onboarding.waiting_repo)
    await message.answer(
        "Кажется, нашёл. Подтверди: пришли <b>ссылку на свой репозиторий</b>."
    )


@router.message(Onboarding.waiting_fio, _PLAIN)
async def confirm_fio(message: Message, state: FSMContext, course: Course,
                      store: Store, cfg: Config) -> None:
    data = await state.get_data()
    student = course.students.get(data.get("candidate", ""))
    if student is None:
        await state.set_state(Onboarding.waiting_id)
        await message.answer(texts.ASK_REPO)
        return
    if not fio_matches(student, message.text):
        await store.log(message.from_user.id, "bind_fail", {"key": student.key})
        await message.answer(texts.FIO_MISMATCH, reply_markup=support(cfg.support_username))
        return
    await _finish(message, state, store, cfg, course, student)


@router.message(Onboarding.waiting_repo, _PLAIN)
async def confirm_repo(message: Message, state: FSMContext, course: Course,
                       store: Store, cfg: Config) -> None:
    data = await state.get_data()
    student = course.students.get(data.get("candidate", ""))
    found = find_by_repo(course, message.text)
    if student is None or found is None or found.key != student.key:
        await store.log(message.from_user.id, "bind_fail",
                        {"key": student.key if student else None})
        await message.answer(
            "Ссылка не совпадает с той, что записана за этой фамилией.\n\n"
            "Проверь адрес — он должен быть тот же, что ты сдавал в форме.",
            reply_markup=support(cfg.support_username),
        )
        return
    await _finish(message, state, store, cfg, course, student)
