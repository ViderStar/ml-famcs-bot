"""Общее для обработчиков: получить студента, привязанного к аккаунту."""

from __future__ import annotations

from aiogram.types import CallbackQuery, Message

from .. import texts
from ..data import Course, Student
from ..store import Store


async def _resolve(tg_id: int, course: Course, store: Store) -> Student | None:
    # Тестер-режим идёт первым: администратор смотрит на бота глазами студента.
    # Записать его может только админский обработчик, так что для обычного
    # аккаунта эта ветка всегда пуста.
    key = await store.test_view(tg_id)
    if key and key in course.students:
        return course.students[key]
    binding = await store.binding(tg_id)
    return course.students.get(binding.student_key) if binding else None


async def bound_student(event: Message | CallbackQuery, course: Course,
                        store: Store) -> Student | None:
    """Студент этого аккаунта, либо None с подсказкой пользователю."""
    student = await _resolve(event.from_user.id, course, store)
    if student is not None:
        return student
    if isinstance(event, CallbackQuery):
        await event.answer(texts.NOT_BOUND, show_alert=True)
    else:
        await event.answer(texts.NOT_BOUND)
    return None


async def student_of(tg_id: int, course: Course, store: Store) -> Student | None:
    """Студент этого аккаунта без сообщений пользователю — для фоновых мест."""
    return await _resolve(tg_id, course, store)
