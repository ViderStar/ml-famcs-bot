"""Механика дерева меню: реестр узлов, сборка клавиатур, единственная точка вывода.

Зачем реестр. Раньше цена нового раздела на три уровня — три клавиатуры, три
обработчика, три захардкоженных литерала «назад» и правки в двух местах
онбординга. Забытый литерал не ломает тесты: кнопка просто уводит не туда.
Здесь родитель объявлен один раз в узле, и «назад» строится из него — ошибиться
негде.

Второе, ради чего это затевалось: по реестру можно **пройтись**. Тест обходит
дерево целиком и проверяет узлы, которых на момент написания теста ещё не было.

Стек навигации в состоянии отвергнут: `MemoryStorage` не переживает перезапуск
контейнера, а инлайновые кнопки живут в истории чата вечно — человек нажмёт
прошлогоднюю, и стек ей ничем не поможет. Поэтому «назад» — свойство дерева, а
не истории.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Sequence

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup)

from ..render import split

# Префикс всех кнопок дерева. Один символ — в 64 байта callback_data и так тесно.
PREFIX = "m"
ROOT = ""  # условный корень: его «экран» — обычная клавиатура снизу

Row = list[InlineKeyboardButton]


@dataclass
class Ctx:
    """Всё, что нужно рендереру. Собирается роутером на каждое нажатие."""

    cfg: object
    user: object
    course: object = None
    store: object = None
    arg: str = ""
    student: object | None = None
    demo: object | None = None
    bot: object | None = None
    state: object | None = None   # FSM: узлам, начинающим диалог

    @property
    def is_admin(self) -> bool:
        return bool(self.cfg.is_admin(self.user.id, self.user.username))


@dataclass
class Screen:
    """Что показать. Рендерер не знает ни про «назад», ни про отправку."""

    text: str = ""
    rows: list[Row] = field(default_factory=list)
    docs: list[tuple[str, Path, str]] = field(default_factory=list)
    blobs: list[tuple[str, bytes, str]] = field(default_factory=list)  # подпись, файл, имя
    alert: str | None = None
    back: str | None = None          # переопределить «назад» у параметрического узла
    keep_parent: bool = True
    preview: bool = False            # разворачивать ли ссылки в тексте


Renderer = Callable[[Ctx], Awaitable[Screen]]
Kids = Callable[[Ctx], Sequence[tuple[str, str, str]]]  # (подпись, узел, аргумент)


def PUBLIC(ctx: Ctx) -> bool:
    return True


def ADMIN(ctx: Ctx) -> bool:
    return ctx.is_admin


@dataclass(frozen=True)
class Node:
    id: str
    title: str
    parent: str | None
    render: Renderer
    kids: tuple[str, ...] | Kids = ()
    visible: Callable[[Ctx], bool] = PUBLIC
    needs_student: bool = False
    label: str = ""           # подпись кнопки, если отличается от заголовка экрана
    order: int = 0            # порядок среди соседей; иначе им правит порядок импорта

    @property
    def button(self) -> str:
        return self.label or self.title


NODES: dict[str, Node] = {}


def node(id: str, title: str, parent: str | None = ROOT, *,
         kids: tuple[str, ...] | Kids = (), visible=PUBLIC,
         needs_student: bool = False, label: str = "", order: int = 0):
    """Объявить узел. Рендерер пишется тут же — иначе они разъезжаются."""

    def wrap(render: Renderer) -> Renderer:
        if id in NODES:
            msg = f"узел {id!r} объявлен дважды"
            raise ValueError(msg)
        NODES[id] = Node(id, title, parent, render, kids, visible, needs_student,
                         label, order)
        return render

    return wrap


# --- callback_data -------------------------------------------------------------

LIMIT = 64  # жёсткое ограничение телеграма, в байтах


def cb(node_id: str, arg: str = "") -> str:
    """Единственное место сборки callback_data во всём боте."""
    data = f"{PREFIX}:{node_id}:{arg}"
    if len(data.encode()) > LIMIT:
        # Молча обрезать нельзя: кнопка станет вести не туда, и заметить это
        # можно будет только по жалобе студента.
        msg = f"callback_data длиннее {LIMIT} байт: {data!r}"
        raise ValueError(msg)
    return data


def parse(data: str) -> tuple[str, str] | None:
    """Разобрать нажатие. Аргумент может содержать двоеточия — режем на три."""
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != PREFIX:
        return None
    return parts[1], parts[2]


# --- клавиатуры ----------------------------------------------------------------

def children(n: Node, ctx: Ctx) -> list[tuple[str, str, str]]:
    if callable(n.kids):
        return list(n.kids(ctx))
    out = []
    for kid_id in n.kids:
        kid = NODES[kid_id]
        if kid.visible(ctx):
            out.append((kid.button, kid_id, ""))
    return out


def nav_row(n: Node, ctx: Ctx, back: str | None) -> Row:
    """Кнопка «назад». Подпись — заголовок родителя, чтобы было видно куда."""
    if back:
        parent_title = ""
        parsed = parse(back)
        if parsed and parsed[0] in NODES:
            parent_title = NODES[parsed[0]].button
        return [InlineKeyboardButton(text=f"◀ {parent_title or 'Назад'}", callback_data=back)]
    if n.parent in (None, ROOT):
        return []
    parent = NODES[n.parent]
    return [InlineKeyboardButton(text=f"◀ {parent.button}", callback_data=cb(parent.id))]


def keyboard(n: Node, ctx: Ctx, screen: Screen) -> InlineKeyboardMarkup | None:
    rows: list[Row] = [list(r) for r in screen.rows]
    for label, kid_id, arg in children(n, ctx):
        rows.append([InlineKeyboardButton(text=label, callback_data=cb(kid_id, arg))])
    nav = nav_row(n, ctx, screen.back)
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def paginate(node_id: str, arg_prefix: str, index: int, total: int) -> Row:
    """◀ 3/7 ▶ — обобщение пагинатора из карточки замечания."""
    row: Row = []
    if index > 0:
        row.append(InlineKeyboardButton(
            text="◀", callback_data=cb(node_id, f"{arg_prefix}{index - 1}")))
    row.append(InlineKeyboardButton(text=f"{index + 1}/{total}", callback_data=cb("noop")))
    if index + 1 < total:
        row.append(InlineKeyboardButton(
            text="▶", callback_data=cb(node_id, f"{arg_prefix}{index + 1}")))
    return row


def links_rows(links: Iterable[tuple[str, str]], limit: int = 4) -> list[Row]:
    return [[InlineKeyboardButton(text=title[:40], url=url)]
            for title, url in list(links)[:limit] if url.startswith("http")]


# --- корень: обычная клавиатура снизу -------------------------------------------

def roots(ctx: Ctx) -> list[Node]:
    """Порядок задаётся полем `order`, а не тем, какой модуль импортировался первым."""
    return sorted((n for n in NODES.values() if n.parent == ROOT and n.visible(ctx)),
                  key=lambda n: (n.order, n.id))


def root_labels(ctx: Ctx | None = None) -> tuple[str, ...]:
    """Подписи корневых кнопок — для онбординга, который обязан их пропускать."""
    return tuple(n.button for n in NODES.values() if n.parent == ROOT)


def root_keyboard(ctx: Ctx, placeholder: str = "Выбери раздел") -> ReplyKeyboardMarkup:
    """Строится из детей корня по `visible` — отдельного списка для гостя нет.

    Раньше их было три: `main_menu`, `guest_menu`, `admin_guest_menu`. Они
    расходились, и гостю показывали кнопку, которая ему отвечала «сначала
    привяжись».
    """
    labels = [n.button for n in roots(ctx)]
    rows = [[KeyboardButton(text=label) for label in labels[i:i + 2]]
            for i in range(0, len(labels), 2)]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True,
                               input_field_placeholder=placeholder)


def keyboard_for(cfg, user, student=None, placeholder: str = "Выбери раздел"):
    """Корневая клавиатура там, где контекста узла ещё нет: онбординг, админка."""
    return root_keyboard(Ctx(cfg=cfg, user=user, student=student), placeholder)


def by_label(label: str) -> Node | None:
    return next((n for n in NODES.values() if n.parent == ROOT and n.button == label), None)


# --- единственная точка вывода --------------------------------------------------

async def show_screen(event, screen: Screen, ctx: Ctx, node_id: str) -> None:
    """Показать готовый экран от имени узла.

    Нужно там, где ответ пришёл сообщением, а не нажатием: рендерер уже
    отработал, а нарезка, клавиатура и «назад» должны остаться теми же.
    """
    await _emit(event, NODES[node_id], ctx, screen)


async def show(event: Message | CallbackQuery, n: Node, ctx: Ctx) -> None:
    """Отрисовать узел. Всё, что бот показывает деревом, проходит здесь.

    Одна точка — чтобы длинный текст резался, «назад» добавлялось и события
    писались одинаково везде, а не как получилось в каждом обработчике.
    """
    if not n.visible(ctx):
        await _quiet(event)
        return
    if n.needs_student and ctx.student is None:
        from .. import texts
        await _say(event, texts.NOT_BOUND, alert=True)
        return

    screen = await n.render(ctx)
    await _emit(event, n, ctx, screen)


async def _emit(event, n: Node, ctx: Ctx, screen: Screen) -> None:
    if screen.alert:
        await _say(event, screen.alert, alert=True)
        return

    markup = keyboard(n, ctx, screen)
    chunks = split(screen.text) if screen.text else [""]
    target = event.message if isinstance(event, CallbackQuery) else event

    first_sent = False
    if isinstance(event, CallbackQuery) and chunks[0]:
        try:
            await target.edit_text(
                chunks[0], disable_web_page_preview=not screen.preview,
                reply_markup=markup if len(chunks) == 1 else None)
            first_sent = True
        except TelegramBadRequest:
            # Сообщение могло быть документом или не измениться ни на символ.
            # Ошибка прав из предохранителя сюда не попадает — она не отсюда.
            first_sent = False

    start = 1 if first_sent else 0
    for i in range(start, len(chunks)):
        if not chunks[i]:
            continue
        last = i == len(chunks) - 1
        await target.answer(chunks[i], disable_web_page_preview=not screen.preview,
                            reply_markup=markup if last else None)

    for caption, path, filename in screen.docs:
        from aiogram.types import FSInputFile
        await target.answer_document(FSInputFile(path, filename=filename or None),
                                     caption=caption)
    for caption, blob, filename in screen.blobs:
        from aiogram.types import BufferedInputFile
        await target.answer_document(BufferedInputFile(blob, filename), caption=caption)
    if isinstance(event, CallbackQuery):
        await event.answer()


async def _say(event, text: str, alert: bool = False) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer(text[:200], show_alert=alert)
    else:
        await event.answer(text)


async def _quiet(event) -> None:
    if isinstance(event, CallbackQuery):
        await event.answer()
