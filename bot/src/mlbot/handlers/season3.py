"""Season 3 free text: form answers and the repository link.

One handler for every text step — which step is being answered lives in the
state. Twelve handlers are not needed here: the steps are data.
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
        # The state stays: the person answers again with another message.
        await message.answer(f"{problem}\n\nПопробуй ещё раз или /cancel")
        return

    await state.clear()
    ctx = await context(message, cfg, course, store, demo, state)
    screen = await _advance(ctx, step.id, value)
    await core.show_screen(message, screen, ctx, "s3.reg")


@router.message(Form.repo, F.text & ~F.text.startswith("/"))
async def got_repo(message: Message, state: FSMContext, cfg: Config,
                   store: Store) -> None:
    """Binding is not blocked by the check.

    A GitHub 404 is indistinguishable from a private repository, and refusing on
    it would reject honest work. The check is a hint, not a gatekeeper.
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
