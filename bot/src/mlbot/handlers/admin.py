"""Admin work that has no screen of its own: tester mode, dialogues, decisions.

The screens themselves are nodes in `menu/admin.py`. What stays here is what is
not a screen: answering the bot's question, resolving a claim, stepping into
someone else's shoes.

Rights come from a filter on both router observers. A check inside a handler
rests on nobody forgetting it; the filter makes an unprotected handler in this
router impossible.
"""

from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from .. import texts
from ..config import Config
from ..data import STATUS_ICON, Course, Student
from ..menu import core as menu
from ..season3.deadline import parse as deadline_of
from ..matching import find_by_fio
from ..render import escape, split
from ..store import Store

from ..menu.filters import AdminOnly

router = Router()
router.message.filter(AdminOnly())
router.callback_query.filter(AdminOnly())


class Admin(StatesGroup):
    finding_student = State()
    test_fio = State()
    broadcast_text = State()
    answering_support = State()
    homework_text = State()


def _is_admin(cfg: Config, user) -> bool:
    """Rights by telegram id or by username — see Config.is_admin."""
    return cfg.is_admin(user.id, user.username)


# --- tester mode: looking at the bot through a student's eyes ---------------------

_TEST_PREFIX = re.compile(r"^\s*(?:/test|тест|test)\b[\s:—-]*(.*)$", re.I | re.S)
_TEST_OFF = {"", "off", "стоп", "стop", "выход", "выйти", "exit", "stop"}


def test_examples(course: Course) -> tuple[Student, Student]:
    """Two examples for the hint: one with a certificate, one without.

    The strongest student and the most "typical" one who fell short — several
    submissions but no certificate. Deterministic, so the hint does not jump.
    """
    ok = sorted(course.active, key=lambda s: (-s.passed, s.fio))
    with_cert = next((s for s in ok if s.certificate), ok[0])
    without = next((s for s in ok if not s.certificate and s.passed > 0),
                   next((s for s in ok if not s.certificate), ok[-1]))
    return with_cert, without


def _tag(course: Course, st: Student) -> str:
    if not st.ok:
        return " — репозиторий недоступен"
    return (" — сертификат есть" if st.certificate
            else f" — {st.passed} из {course.total_graded}, без сертификата")


@router.message(Command("test"))
@router.message(F.text.regexp(_TEST_PREFIX))
async def test_mode(message: Message, cfg: Config, course: Course, store: Store) -> None:
    m = _TEST_PREFIX.match(message.text or "")
    await _enter_test(message, cfg, course, store, (m.group(1) if m else "").strip())


async def _enter_test(message: Message, cfg: Config, course: Course, store: Store,
                      query: str) -> None:
    """Turn the student's-eye view on, switch it, or turn it off.

    Rights are checked here too, although both callers already did: this helper
    writes to test_views, and such a row substitutes the student on every other
    screen.
    """
    if not _is_admin(cfg, message.from_user):
        return
    if query.lower() in _TEST_OFF:
        await store.clear_test_view(message.from_user.id)
        await message.answer(texts.TEST_OFF,
                             reply_markup=menu.keyboard_for(cfg, message.from_user))
        return

    matches = find_by_fio(course, query)
    cert, fail = test_examples(course)
    if not matches:
        await message.answer(texts.TEST_NOT_FOUND.format(cert_fio=escape(cert.fio)))
        return
    if not matches[0].confident or (len(matches) > 1 and matches[1].confident
                                    and matches[1].score == matches[0].score):
        options = "\n".join(f"<code>Тест {escape(mt.student.fio)}</code>"
                             for mt in matches[:5])
        await message.answer(texts.TEST_AMBIGUOUS.format(options=options))
        return

    st = matches[0].student
    await store.set_test_view(message.from_user.id, st.key)
    await store.log(message.from_user.id, "test_mode", {"key": st.key})
    await message.answer(
        texts.TEST_ON.format(fio=escape(st.fio), tag=_tag(course, st)),
        reply_markup=menu.keyboard_for(cfg, message.from_user, st),
    )



@router.callback_query(F.data.startswith("adm:claim:"))
async def resolve_claim(call: CallbackQuery, cfg: Config, course: Course,
                        store: Store) -> None:
    _, _, verdict, raw_id = call.data.split(":", 3)
    c = await store.claim(int(raw_id))
    if c is None or c["status"] != "pending":
        await call.answer("Заявка уже разобрана", show_alert=True)
        return
    st = course.students.get(c["student_key"])
    fio = st.fio if st else c["student_key"]

    if verdict == "ok":
        taken = await store.binding_of_student(c["student_key"])
        if taken and taken.tg_id != c["tg_id"]:
            await call.answer("Запись уже привязана к другому аккаунту", show_alert=True)
            return
        await store.bind(c["tg_id"], c["student_key"], c["username"], c["tg_name"])
        await store.resolve_claim(c["id"], "approved")
        await store.log(call.from_user.id, "claim_approved", {"claim": c["id"]})
        note = f"✅ #{c['id']}: доступ к записи {escape(fio)} открыт для @{escape(c['username'] or '—')}"
        reply = texts.CLAIM_APPROVED.format(fio=escape(fio), support=cfg.support_username)
    else:
        await store.resolve_claim(c["id"], "rejected")
        await store.log(call.from_user.id, "claim_rejected", {"claim": c["id"]})
        note = f"❌ #{c['id']}: заявка на запись {escape(fio)} отклонена"
        reply = texts.CLAIM_REJECTED.format(fio=escape(fio), support=cfg.support_username)

    try:
        await call.bot.send_message(c["tg_id"], reply)
    except Exception:
        note += "\n<i>(сообщить студенту не удалось — он не писал боту)</i>"
    await call.message.edit_text(note)
    await call.answer()


@router.message(Admin.finding_student, F.text)
async def find_student(message: Message, state: FSMContext, cfg: Config,
                       course: Course, store: Store) -> None:
    await state.clear()
    from ..matching import find_by_fio, find_by_repo

    query = message.text.strip()
    student = find_by_repo(course, query) or course.students.get(query.lower())
    if student is None:
        matches = find_by_fio(course, query, limit=5)
        if not matches:
            await message.answer("Не нашёл. Попробуй иначе.")
            return
        if len(matches) > 1 and matches[1].confident:
            names = "\n".join(f"• {escape(m.student.fio)} — <code>{m.student.key}</code>"
                              for m in matches)
            await message.answer(f"Нашлось несколько:\n{names}")
            return
        student = matches[0].student

    binding = await store.binding_of_student(student.key)
    lines = [
        f"<b>{escape(student.fio)}</b>  <code>{student.key}</code>",
        f"{student.repo or '—'}",
        f"Статус: {'проверен' if student.ok else 'исключён — ' + escape(student.reason)}",
    ]
    if student.ok:
        lines += [
            f"Зачтено: <b>{student.passed}</b> из {student.total} · "
            f"сертификат: {'да' if student.certificate else 'нет'}",
            f"Телеграм: {'@' + binding.username if binding and binding.username else 'не привязан'}",
            "",
        ]
        for hw_id in sorted(student.homeworks):
            h = student.homeworks[hw_id]
            icon = STATUS_ICON[h["status"]]
            extra = f" · {len(h['findings'])} замеч." if h["status"] != "missing" else ""
            lines.append(f"{icon} {hw_id} {escape(course.title(hw_id)[:26])}{extra}")
    for chunk in split("\n".join(lines)):
        await message.answer(chunk, disable_web_page_preview=True)



# --- broadcast: typed text → frozen recipient list → preview ----------------------

@router.message(Admin.broadcast_text, F.text)
async def broadcast_compose(message: Message, state: FSMContext, cfg: Config,
                            course: Course, store: Store) -> None:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    from ..broadcast import audiences, sender
    from ..menu.core import cb

    data = await state.get_data()
    audience_id = data.get("audience", "")
    await state.clear()
    if audience_id not in audiences.REGISTRY:
        await message.answer("Аудитория потерялась — начни заново.")
        return

    # html_text, not text. Bold, italics and links typed in Telegram live in
    # entities rather than in the text: with `message.text` the formatting
    # vanished silently, and a stray "<" broke delivery for everyone at once
    # under parse_mode=HTML.
    body = message.html_text
    targets, unreachable = await audiences.resolve(
        audience_id, cfg, course, store, who=message.from_user.id)
    if not targets:
        await message.answer("В этой аудитории сейчас никого.")
        return

    cast_id = await store.create_broadcast(
        created_by=message.from_user.id, audience=audience_id, kind="text",
        body=body, targets=targets, sandbox=cfg.safe_mode)

    draft = await store.broadcast(cast_id)
    # Preview through the same function as sending: otherwise "this is how it
    # will look" and "this is how it looks" drift apart. Broken markup fails
    # here, on the admin.
    try:
        await sender.deliver(message.bot, message.from_user.id, draft)
    except Exception as exc:
        await store.cancel_broadcast(cast_id)
        await message.answer(f"Телеграм не принял это сообщение: {escape(str(exc))}\n\n"
                             "Поправь разметку и пришли заново.")
        return

    send_label = (f"🧪 Прогнать в песочнице ({len(targets)})" if cfg.safe_mode
                  else f"📣 Отправить {len(targets)} студентам")
    await message.answer(
        texts.CAST_PREVIEW.format(count=len(targets))
        + (f"\nНедостижимы: {len(unreachable)}." if unreachable else ""),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=send_label, callback_data=cb("a.cast.go", str(cast_id))),
            InlineKeyboardButton(text="Отмена", callback_data=cb("a.cast.no", str(cast_id))),
        ]]))


@router.message(Command("broadcast"))
async def broadcast_cmd(message: Message, cfg: Config, course: Course,
                        store: Store, state: FSMContext) -> None:
    """A shortcut into the same tree — so an old habit keeps working."""
    from ..menu import core
    from ..menu.router import context

    ctx = await context(message, cfg, course, store, state=state)
    await core.show(message, core.NODES["a.cast.new"], ctx)


@router.message(Admin.answering_support, F.text)
async def send_support_answer(message: Message, state: FSMContext, cfg: Config,
                              store: Store) -> None:
    """The reply goes to the student and the ticket is marked answered.

    In the sandbox the letter is redirected to the admin — the safety catch sits
    on every API call, and this one is no exception.
    """
    data = await state.get_data()
    await state.clear()
    ticket = await store.answer_support(int(data.get("ticket", 0) or 0))
    if ticket is None:
        await message.answer("Обращение не нашлось.")
        return
    try:
        await message.bot.send_message(
            ticket["tg_id"],
            texts.SUPPORT_ANSWER.format(text=message.html_text,
                                        username=cfg.support_username))
    except Exception as exc:
        await message.answer(f"Не доставлено: {escape(str(exc))}\n"
                             f"Обращение #{ticket['id']} всё равно помечено отвеченным.")
        return
    await message.answer(f"✅ Ответ на #{ticket['id']} отправлен.")


# --- season 3 homework ------------------------------------------------------------------

@router.message(Admin.homework_text, F.text)
async def got_homework(message: Message, state: FSMContext, cfg: Config,
                       course: Course, store: Store, demo=None) -> None:
    from ..menu import core
    from ..menu.router import context

    data = await state.get_data()
    tracks = list(data.get("hw_tracks") or [])
    await state.clear()
    if not tracks:
        await message.answer("Направления потерялись — начни заново.")
        return

    lines = message.html_text.split("\n")
    deadline = None
    while lines and not lines[-1].strip():
        lines.pop()
    if lines:
        found = deadline_of(lines[-1])
        if found:
            deadline = found
            lines.pop()
    title = lines[0].strip() if lines else "Домашка"
    body = "\n".join(lines[1:]).strip()

    published = await store.homeworks("published")
    hw_id = await store.create_homework(
        title=title, body=body, tracks=tracks, created_by=message.from_user.id,
        num=len(published) + 1, deadline=deadline)
    await store.log(message.from_user.id, "s3_homework", {"id": hw_id})

    ctx = await context(message, cfg, course, store, demo, state, arg=str(hw_id))
    await core.show(message, core.NODES["a.s3.one"], ctx)
