"""Точка входа в дерево: одно нажатие — один узел.

Здесь же живут переводчики старых кнопок. Инлайновые кнопки остаются в истории
чата навсегда: студент пролистает переписку за май и нажмёт `hw:hw03`. Такое
нажатие должно открывать домашку, а не молчать.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from ..config import Config
from ..data import Course
from ..store import Store
from ..handlers.deps import student_of
from . import admin, core, screens, season3  # noqa: F401 — импорт наполняет реестр

router = Router()

# Команда → узел. Кнопки под полем ввода дублируются командами: у кого-то
# клавиатура свёрнута, кто-то пришёл по ссылке из канала.
COMMANDS = {
    "results": "s2.res",
    "strengths": "s2.str",
    "homeworks": "s2.hw",
    "improve": "s2.plan",
    "materials": "s2.lib",
    "certificate": "s2.crt",
    "reference": "ref",
    "support": "help.ask",
    "menu": "s2",
    "help": "help.cmd",
    "whoami": "help.who",
    "admin": "adm",
    "season3": "s3",
    "apply": "s3.reg",
}


def legacy(data: str) -> tuple[str, str] | None:
    """Старый формат callback_data → узел и аргумент."""
    exact = {
        "hw:list": ("s2.hw", ""),
        "ref:list": ("ref", ""),
        "res:strengths": ("s2.str", ""),
        "cert:pdf": ("s2.crt.pdf", ""),
        "cert:photo": ("s2.crt.photo", ""),
        "learn:random": ("ref.rnd", ""),
        "noop": ("noop", ""),
    }
    if data in exact:
        return exact[data]
    head, sep, rest = data.partition(":")
    if not sep:
        return None
    prefixes = {"hw": "s2.hw.card", "f": "s2.f", "task": "s2.tsk",
                "mat": "s2.mat", "read": "s2.rd"}
    if head in prefixes:
        return prefixes[head], rest
    if head == "ref":
        kind, _, arg = rest.partition(":")
        if kind == "hw":
            return "ref.hw", arg
        if kind == "art":
            return "ref.a", arg
    return None


async def context(event, cfg: Config, course: Course, store: Store,
                  demo: Course | None = None, state=None, arg: str = "") -> core.Ctx:
    student = await student_of(event.from_user.id, course, store)
    return core.Ctx(cfg=cfg, course=course, store=store, user=event.from_user,
                    arg=arg, student=student, demo=demo, bot=event.bot, state=state)


async def _leave_support(state) -> None:
    """Кнопка меню отменяет вопрос в поддержку — но не онбординг.

    Онбординг тоже держит состояние, и гость, заглянувший в справочник посреди
    привязки, должен вернуться и дослать ссылку.
    """
    if state is None:
        return
    from ..handlers.support import Ask
    if await state.get_state() == Ask.waiting_text.state:
        await state.clear()


async def _open(event, node_id: str, arg: str, cfg, course, store, demo, state) -> None:
    n = core.NODES.get(node_id)
    if n is None:
        if isinstance(event, CallbackQuery):
            await event.answer()
        return
    ctx = await context(event, cfg, course, store, demo, state, arg)
    await core.show(event, n, ctx)


@router.callback_query(F.data.startswith(f"{core.PREFIX}:"))
async def button(call: CallbackQuery, cfg: Config, course: Course, store: Store,
                 state=None, demo: Course | None = None) -> None:
    parsed = core.parse(call.data)
    if parsed is None:
        await call.answer()
        return
    await _open(call, parsed[0], parsed[1], cfg, course, store, demo, state)


@router.callback_query(F.func(lambda c: legacy(c.data or "") is not None))
async def old_button(call: CallbackQuery, cfg: Config, course: Course, store: Store,
                     state=None, demo: Course | None = None) -> None:
    """Кнопка из старой переписки. Перевод, а не вторая реализация экрана."""
    node_id, arg = legacy(call.data)
    await _open(call, node_id, arg, cfg, course, store, demo, state)


@router.message(F.text.func(lambda t: core.by_label(t or "") is not None))
async def root_button(message: Message, cfg: Config, course: Course, store: Store,
                      state=None, demo: Course | None = None) -> None:
    await _leave_support(state)
    await _open(message, core.by_label(message.text).id, "", cfg, course, store, demo, state)


@router.message(Command(commands=list(COMMANDS)))
async def command(message: Message, command: CommandObject, cfg: Config, course: Course,
                  store: Store, state=None, demo: Course | None = None) -> None:
    await _leave_support(state)
    await _open(message, COMMANDS[command.command], (command.args or "").strip(),
                cfg, course, store, demo, state)


@router.message(Command("find"))
async def find(message: Message, command: CommandObject, cfg: Config, course: Course,
               store: Store, state=None, demo: Course | None = None) -> None:
    await _open(message, "ref.find", (command.args or "").strip(),
                cfg, course, store, demo, state)
