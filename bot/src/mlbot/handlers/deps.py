"""Shared by handlers: get the student bound to an account."""

from __future__ import annotations

from aiogram.types import CallbackQuery, Message

from .. import texts
from ..data import Course, Student
from ..store import Store


async def _resolve(tg_id: int, course: Course, store: Store) -> Student | None:
    # Tester mode comes first: an admin is looking through a student's eyes.
    # Only an admin handler can write it, so for an ordinary account this branch
    # is always empty.
    key = await store.test_view(tg_id)
    if key and key in course.students:
        return course.students[key]
    binding = await store.binding(tg_id)
    return course.students.get(binding.student_key) if binding else None


async def bound_student(event: Message | CallbackQuery, course: Course,
                        store: Store) -> Student | None:
    """The student for this account, or None plus a hint to the user."""
    student = await _resolve(event.from_user.id, course, store)
    if student is not None:
        return student
    if isinstance(event, CallbackQuery):
        await event.answer(texts.NOT_BOUND, show_alert=True)
    else:
        await event.answer(texts.NOT_BOUND)
    return None


async def student_of(tg_id: int, course: Course, store: Store) -> Student | None:
    """The student for this account without messaging the user — for background use."""
    return await _resolve(tg_id, course, store)
