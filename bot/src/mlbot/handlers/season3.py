"""Свободный ввод третьего сезона: ответы анкеты и ссылка на репозиторий.

Один обработчик на все текстовые шаги — какой именно шаг отвечают, лежит в
состоянии. Двенадцать обработчиков здесь не нужны: шаги описаны данными.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from .. import texts
from ..config import Config
from ..data import Course
from ..render import escape
from ..season3 import wizard
from ..store import Store

router = Router()


class Form(StatesGroup):
    answer = State()
    repo = State()


@router.message(Form.answer, F.text & ~F.text.startswith("/"))
async def got_answer(message: Message, state: FSMContext, cfg: Config,
                     course: Course, store: Store, demo=None) -> None:
    from ..menu import core
    from ..menu.router import context
    from ..menu.season3 import _advance

    data = await state.get_data()
    step = wizard.step(data.get("step", ""))
    if step is None:
        await state.clear()
        await message.answer(texts.S3_LOST)
        return

    value = message.text.strip()
    problem = step.validate(value) if step.validate else None
    if problem:
        # Состояние не снимаем: человек отвечает тем же сообщением ещё раз.
        await message.answer(f"{problem}\n\nПопробуй ещё раз или /cancel")
        return

    await state.clear()
    ctx = await context(message, cfg, course, store, demo, state)
    screen = await _advance(ctx, step.id, value)
    await core.show_screen(message, screen, ctx, "s3.reg")


@router.message(Form.repo, F.text & ~F.text.startswith("/"))
async def got_repo(message: Message, state: FSMContext, cfg: Config,
                   store: Store) -> None:
    """Привязка не блокируется проверкой.

    404 от GitHub не отличить от приватного репозитория, и отказывать по нему
    значило бы отвергать честные работы. Проверка — подсказка, а не вахтёр.
    """
    from .. import github

    await state.clear()
    repo, found, code = await github.check(cfg, store, message.text)
    if repo is None:
        await message.answer(texts.S3_REPO_BAD)
        return
    await store.bind_repo(message.from_user.id, repo.html, repo.owner, repo.name)
    await store.log(message.from_user.id, "s3_repo", {"repo": repo.full})
    if found is True:
        note = texts.S3_REPO_OK
    elif found is False:
        note = texts.S3_REPO_UNSEEN
    else:
        note = texts.S3_REPO_UNKNOWN
    await message.answer(texts.S3_REPO_SAVED.format(
        url=escape(repo.html), note=note))
