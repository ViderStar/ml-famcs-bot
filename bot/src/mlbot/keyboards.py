"""Keyboards. Callback data is short: Telegram limits it to 64 bytes."""

from __future__ import annotations

from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, ReplyKeyboardMarkup)

from .data import SEVERITY_ICON, STATUS_ICON, Course, Student

MAIN = "📊 Мои результаты", "📚 Домашки", "🎯 Что подтянуть", "🏆 Сертификат", \
       "🔎 Справочник ошибок", "🆘 Поддержка"


def main_menu(is_admin: bool = False) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text=MAIN[0]), KeyboardButton(text=MAIN[1])],
        [KeyboardButton(text=MAIN[2]), KeyboardButton(text=MAIN[3])],
        [KeyboardButton(text=MAIN[4]), KeyboardButton(text=MAIN[5])],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="🛠 Админка")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True,
                               input_field_placeholder="Выбери раздел")


def guest_menu() -> ReplyKeyboardMarkup:
    """For an unbound account: only what works without a binding."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=MAIN[4]), KeyboardButton(text=MAIN[5])]],
        resize_keyboard=True,
        input_field_placeholder="Пришли ссылку на репозиторий",
    )


def admin_guest_menu() -> ReplyKeyboardMarkup:
    """For an admin with no binding: they have no student record of their own."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="🛠 Админка")],
                  [KeyboardButton(text=MAIN[4]), KeyboardButton(text=MAIN[5])]],
        resize_keyboard=True,
        input_field_placeholder="Выбери раздел",
    )


def confirm_self() -> InlineKeyboardMarkup:
    """Confirming recognition by username. The student key is not passed here."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да, это я", callback_data="ident:yes"),
        InlineKeyboardButton(text="Нет, я другой", callback_data="ident:no"),
    ]])


def homework_list(course: Course, student: Student) -> InlineKeyboardMarkup:
    rows = []
    for hw_id in sorted(course.rubrics):
        hw = student.hw(hw_id)
        status = hw["status"] if hw else "missing"
        icon = STATUS_ICON.get(status, "—")
        graded = course.rubrics[hw_id].graded
        title = course.title(hw_id)
        suffix = "" if graded else " · вне зачёта"
        rows.append([InlineKeyboardButton(
            text=f"{icon} {hw_id} {title[:26]}{suffix}", callback_data=f"hw:{hw_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def homework_card(course: Course, hw_id: str, findings: list[dict]) -> InlineKeyboardMarkup:
    rows = []
    for i, f in enumerate(findings[:12]):
        icon = SEVERITY_ICON.get(f["severity"], "•")
        rows.append([InlineKeyboardButton(
            text=f"{icon} {f['title'][:52]}", callback_data=f"f:{hw_id}:{i}")])

    extras = []
    if course.task_text(hw_id):
        extras.append(InlineKeyboardButton(text="📄 Задание", callback_data=f"task:{hw_id}"))
    if course.materials(hw_id):
        extras.append(InlineKeyboardButton(text="📊 Лекция", callback_data=f"mat:{hw_id}"))
    if course.reading(hw_id):
        extras.append(InlineKeyboardButton(text="📚 Почитать", callback_data=f"read:{hw_id}"))
    if extras:
        rows.append(extras)
    rows.append([InlineKeyboardButton(text="◀ К списку домашек", callback_data="hw:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def finding_card(hw_id: str, index: int, total: int,
                 links: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=title[:40], url=url)] for title, url in links[:4]]
    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton(text="◀", callback_data=f"f:{hw_id}:{index - 1}"))
    nav.append(InlineKeyboardButton(text=f"{index + 1}/{total}", callback_data="noop"))
    if index + 1 < total:
        nav.append(InlineKeyboardButton(text="▶", callback_data=f"f:{hw_id}:{index + 1}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton(text="◀ К домашке", callback_data=f"hw:{hw_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def article_links(links: list[tuple[str, str]], back: str | None = None) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=title[:40], url=url)] for title, url in links[:5]]
    if back:
        rows.append([InlineKeyboardButton(text="◀ Назад", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reference_topics(course: Course) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="⚙️ Общие ошибки", callback_data="ref:hw:common")]]
    for hw_id in sorted(course.rubrics):
        rows.append([InlineKeyboardButton(
            text=f"{hw_id} {course.title(hw_id)[:30]}", callback_data=f"ref:hw:{hw_id}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reference_articles(codes: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=title[:56], callback_data=f"ref:art:{code}")]
            for code, title in codes[:30]]
    rows.append([InlineKeyboardButton(text="◀ К темам", callback_data="ref:list")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def support(username: str) -> InlineKeyboardMarkup | None:
    """The "write to the teacher" button.

    Without `SUPPORT_USERNAME` there is no button: a `t.me/` link leads nowhere,
    and a broken button is worse than a missing one.
    """
    if not username:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"✉️ Написать @{username}", url=f"https://t.me/{username}")
    ]])


def awards_buttons(has_certificate: bool, has_photo: bool) -> InlineKeyboardMarkup | None:
    """Collecting the documents. The student key stays out of callback data — it comes from the binding."""
    rows = []
    if has_certificate:
        rows.append([InlineKeyboardButton(text="📜 Получить сертификат",
                                          callback_data="cert:pdf")])
    if has_photo:
        rows.append([InlineKeyboardButton(text="📸 Фото с вручения",
                                          callback_data="cert:photo")])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def claim_card(claim_id: int) -> InlineKeyboardMarkup:
    """A claim decision. Callback data carries the claim number only, never the student key."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Это он", callback_data=f"adm:claim:ok:{claim_id}"),
        InlineKeyboardButton(text="❌ Отказать", callback_data=f"adm:claim:no:{claim_id}"),
    ]])


def strengths_button() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="💪 Сильные стороны", callback_data="res:strengths")]])


def learn_more() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🎲 Ещё один разбор", callback_data="learn:random")
    ]])


def admin_menu() -> InlineKeyboardMarkup:
    items = [
        ("📈 Сводка по потоку", "adm:summary"),
        ("📚 По темам", "adm:hw"),
        ("👤 Найти студента", "adm:find"),
        ("👓 Глазами студента", "adm:test"),
        ("🧪 Вымышленные студенты", "adm:demo"),
        ("🔑 Заявки на доступ", "adm:claims"),
        ("🔗 Кто привязался", "adm:coverage"),
        ("📇 Телеграмы", "adm:tg"),
        ("⚠️ Требует решения", "adm:attention"),
        ("📖 Что читают", "adm:usage"),
        ("✉️ Обращения", "adm:support"),
        ("♻️ Перечитать данные", "adm:reload"),
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=t, callback_data=d)] for t, d in items])
