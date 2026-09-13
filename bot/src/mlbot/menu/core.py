"""Menu tree mechanics: node registry, keyboard assembly, one output point.

Why a registry. The old price of a new three-level section was three keyboards,
three handlers, three hardcoded "back" literals and edits in two places in
onboarding. A forgotten literal breaks no test: the button simply leads
somewhere else. Here the parent is declared once on the node and "back" is
derived from it — there is nothing left to get wrong.

The second reason: a registry can be **walked**. A test traverses the whole tree
and covers nodes that did not exist when the test was written.

A navigation stack in FSM state was rejected: `MemoryStorage` does not survive a
container restart, and inline buttons live in chat history forever — someone
will press last year's, and a stack will not help them. So "back" is a property
of the tree, not of history.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Sequence

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup)

from ..render import split

# Prefix of every tree button. One character — 64 bytes of callback_data is tight enough.
PREFIX = "m"
ROOT = ""  # notional root: its "screen" is the reply keyboard at the bottom

Row = list[InlineKeyboardButton]


@dataclass
class Ctx:
    """Everything a renderer needs. Built by the router on every press."""

    cfg: object
    user: object
    course: object = None
    store: object = None
    arg: str = ""
    student: object | None = None
    demo: object | None = None
    bot: object | None = None
    state: object | None = None   # FSM, for nodes that start a dialogue

    @property
    def is_admin(self) -> bool:
        return bool(self.cfg.is_admin(self.user.id, self.user.username))


@dataclass
class Screen:
    """What to show. The renderer knows nothing about "back" or about sending."""

    text: str = ""
    rows: list[Row] = field(default_factory=list)
    docs: list[tuple[str, Path, str]] = field(default_factory=list)
    blobs: list[tuple[str, bytes, str]] = field(default_factory=list)  # caption, bytes, filename
    alert: str | None = None
    back: str | None = None          # override "back" for a parametric node
    keep_parent: bool = True
    preview: bool = False            # whether to expand links in the text


Renderer = Callable[[Ctx], Awaitable[Screen]]
Kids = Callable[[Ctx], Sequence[tuple[str, str, str]]]  # (label, node, argument)


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
    label: str = ""           # button caption when it differs from the screen title
    order: int = 0            # order among siblings; otherwise import order decides

    @property
    def button(self) -> str:
        return self.label or self.title


NODES: dict[str, Node] = {}


def node(id: str, title: str, parent: str | None = ROOT, *,
         kids: tuple[str, ...] | Kids = (), visible=PUBLIC,
         needs_student: bool = False, label: str = "", order: int = 0):
    """Declare a node. The renderer is written right here — otherwise they drift apart."""

    def wrap(render: Renderer) -> Renderer:
        if id in NODES:
            msg = f"node {id!r} declared twice"
            raise ValueError(msg)
        NODES[id] = Node(id, title, parent, render, kids, visible, needs_student,
                         label, order)
        return render

    return wrap


# --- callback_data -------------------------------------------------------------

LIMIT = 64  # Telegram's hard limit, in bytes


def cb(node_id: str, arg: str = "") -> str:
    """The only place callback_data is assembled in the whole bot."""
    data = f"{PREFIX}:{node_id}:{arg}"
    if len(data.encode()) > LIMIT:
        # Truncating silently is not an option: the button would lead somewhere
        # else, and the only way to notice would be a student complaining.
        msg = f"callback_data longer than {LIMIT} bytes: {data!r}"
        raise ValueError(msg)
    return data


def parse(data: str) -> tuple[str, str] | None:
    """Parse a press. The argument may contain colons — split into three."""
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != PREFIX:
        return None
    return parts[1], parts[2]


# --- keyboards -----------------------------------------------------------------

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
    """The "back" button. Its caption is the parent's title, so you see where it goes."""
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
    """◀ 3/7 ▶ — the finding-card paginator, generalised."""
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


# --- root: the reply keyboard at the bottom -------------------------------------

def roots(ctx: Ctx) -> list[Node]:
    """Order comes from the `order` field, not from which module was imported first."""
    return sorted((n for n in NODES.values() if n.parent == ROOT and n.visible(ctx)),
                  key=lambda n: (n.order, n.id))


def root_labels(ctx: Ctx | None = None) -> tuple[str, ...]:
    """Captions of the root buttons — for onboarding, which must let them through."""
    return tuple(n.button for n in NODES.values() if n.parent == ROOT)


def root_keyboard(ctx: Ctx, placeholder: str = "Выбери раздел") -> ReplyKeyboardMarkup:
    """Built from the root's children by `visible` — no separate list for guests.

    There used to be three: `main_menu`, `guest_menu`, `admin_guest_menu`. They
    drifted apart, and a guest was shown a button that answered them "bind
    first".
    """
    labels = [n.button for n in roots(ctx)]
    rows = [[KeyboardButton(text=label) for label in labels[i:i + 2]]
            for i in range(0, len(labels), 2)]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True,
                               input_field_placeholder=placeholder)


def keyboard_for(cfg, user, student=None, placeholder: str = "Выбери раздел"):
    """The root keyboard where there is no node context yet: onboarding, admin panel."""
    return root_keyboard(Ctx(cfg=cfg, user=user, student=student), placeholder)


def by_label(label: str) -> Node | None:
    return next((n for n in NODES.values() if n.parent == ROOT and n.button == label), None)


# --- the single output point ------------------------------------------------------

async def show_screen(event, screen: Screen, ctx: Ctx, node_id: str) -> None:
    """Show a ready screen on behalf of a node.

    Needed where the answer arrived as a message rather than a press: the
    renderer has already run, but splitting, keyboard and "back" must stay the
    same.
    """
    await _emit(event, NODES[node_id], ctx, screen)


async def show(event: Message | CallbackQuery, n: Node, ctx: Ctx) -> None:
    """Render a node. Everything the bot shows through the tree passes here.

    One point, so that long text gets split, "back" gets added and events get
    logged the same way everywhere instead of however each handler happened to.
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
            # The message may have been a document, or unchanged to the character.
            # A permission error from the safety catch does not land here — wrong source.
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
