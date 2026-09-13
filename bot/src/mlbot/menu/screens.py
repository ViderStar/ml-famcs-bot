"""The screen tree. One node is one declaration with its renderer beside it.

Text is still assembled by `views.py`: tests run it over every student and every
finding, and duplicating that assembly here is not allowed — such a copy once
drifted from the original and crashed the topic card for everyone.
"""

from __future__ import annotations

import random

from aiogram.types import InlineKeyboardButton

from .. import texts
from ..data import SEVERITY_ICON, SEVERITY_ORDER, STATUS_ICON
from ..render import escape, to_html
from ..views import (article_text, external_links, finding_text, hw_card_text,
                     plan_text, results_text, sorted_findings, strengths_text)
from .core import Ctx, Screen, cb, links_rows, node, paginate

# Where to go next — taken from the course channel posts.
NEXT_STEPS = (
    ("Яндекс.Хендбук по машинному обучению", "https://education.yandex.ru/handbook/ml"),
    ("Открытый курс ODS на Хабре", "https://habr.com/ru/companies/ods/articles/322626/"),
    ("Kaggle Learn", "https://www.kaggle.com/learn"),
)


def _write_to_teacher(ctx: Ctx) -> list:
    """The "write to the teacher" button, if there is anyone to write to."""
    if not ctx.cfg.support_username:
        return []
    return [[InlineKeyboardButton(
        text=f"✉️ Написать @{ctx.cfg.support_username}",
        url=f"https://t.me/{ctx.cfg.support_username}")]]


# --- housekeeping ---------------------------------------------------------------

@node("noop", "—", parent=None)
async def noop(ctx: Ctx) -> Screen:
    """The "3/7" paginator counter: the button must be pressable and do nothing."""
    return Screen(alert=" ")


# --- season 2 ---------------------------------------------------------------------

@node("s2", "Второй сезон", label="🎓 Второй сезон", order=1,
      kids=("s2.res", "s2.hw", "s2.plan", "s2.lib", "s2.crt"),
      visible=lambda ctx: ctx.student is not None)
async def season2(ctx: Ctx) -> Screen:
    st = ctx.student
    if st is None:
        return Screen(text=texts.SEASON2_GUEST)
    if not st.ok:
        return Screen(text=texts.EXCLUDED.format(fio=escape(st.fio),
                                                 reason=escape(st.reason)))
    from ..handlers.easter import night_note
    return Screen(text=texts.SEASON2.format(
        fio=escape(st.fio), passed=st.passed, total=st.total,
        cert="есть" if st.certificate else "нет") + (night_note() or ""))


@node("s2.res", "Результаты", "s2", label="📊 Результаты",
      kids=("s2.str",), needs_student=True)
async def results(ctx: Ctx) -> Screen:
    st = ctx.student
    await ctx.store.log(ctx.user.id, "results")
    if not st.ok:
        return Screen(
            text=texts.EXCLUDED.format(fio=escape(st.fio), reason=escape(st.reason)),
            rows=_write_to_teacher(ctx))
    return Screen(text=results_text(ctx.course, st))


@node("s2.str", "Сильные стороны", "s2.res", label="💪 Сильные стороны",
      needs_student=True,
      visible=lambda ctx: ctx.student is not None and bool(ctx.student.strengths()))
async def strengths(ctx: Ctx) -> Screen:
    await ctx.store.log(ctx.user.id, "strengths")
    return Screen(text=strengths_text(ctx.course, ctx.student))


def _homeworks(ctx: Ctx):
    out = []
    for hw_id in sorted(ctx.course.rubrics):
        hw = ctx.student.hw(hw_id) if ctx.student else None
        icon = STATUS_ICON.get(hw["status"] if hw else "missing", "—")
        suffix = "" if ctx.course.rubrics[hw_id].graded else " · вне зачёта"
        title = ctx.course.title(hw_id)
        out.append((f"{icon} {hw_id} {title[:26]}{suffix}", "s2.hw.card", hw_id))
    return out


@node("s2.hw", "Домашки", "s2", label="📚 Домашки", kids=_homeworks, needs_student=True)
async def homeworks(ctx: Ctx) -> Screen:
    st = ctx.student
    await ctx.store.log(ctx.user.id, "hw_list")
    return Screen(text=(
        f"Твои работы. Засчитано <b>{st.passed} из {st.total}</b>.\n"
        f"{STATUS_ICON['passed']} зачтено · {STATUS_ICON['failed']} не зачтено · "
        f"{STATUS_ICON['missing']} не сдано"))


@node("s2.hw.card", "Домашка", "s2.hw", needs_student=True)
async def hw_card(ctx: Ctx) -> Screen:
    hw_id = ctx.arg
    if hw_id not in ctx.course.rubrics:
        return Screen(alert="Такой темы нет")
    await ctx.store.log(ctx.user.id, "hw_open", {"hw": hw_id})
    hw = ctx.student.hw(hw_id)
    findings = sorted_findings(hw) if hw and hw["status"] != "missing" else []

    rows = [[InlineKeyboardButton(
        text=f"{SEVERITY_ICON.get(f['severity'], '•')} {f['title'][:52]}",
        callback_data=cb("s2.f", f"{hw_id}:{i}"))] for i, f in enumerate(findings[:12])]
    extras = []
    if ctx.course.task_text(hw_id):
        extras.append(InlineKeyboardButton(text="📄 Задание", callback_data=cb("s2.tsk", hw_id)))
    if ctx.course.materials(hw_id):
        extras.append(InlineKeyboardButton(text="📊 Лекция", callback_data=cb("s2.mat", hw_id)))
    if ctx.course.reading(hw_id):
        extras.append(InlineKeyboardButton(text="📚 Почитать", callback_data=cb("s2.rd", hw_id)))
    if extras:
        rows.append(extras)
    return Screen(text=hw_card_text(ctx.course, ctx.student, hw_id, texts.NO_SUBMISSIONS),
                  rows=rows)


@node("s2.f", "Замечание", "s2.hw.card", needs_student=True)
async def finding(ctx: Ctx) -> Screen:
    hw_id, _, raw = ctx.arg.partition(":")
    hw = ctx.student.hw(hw_id)
    findings = sorted_findings(hw) if hw else []
    index = int(raw) if raw.isdigit() else 0
    if not findings or index >= len(findings):
        return Screen(alert="Замечание не найдено")

    f = findings[index]
    await ctx.store.log(ctx.user.id, "finding", {"code": f["code"]})
    seen = await ctx.store.count_event(ctx.user.id, "finding", f'"{f["code"]}"')
    rows = links_rows(external_links(f))
    rows.append(paginate("s2.f", f"{hw_id}:", index, len(findings)))
    return Screen(text=finding_text(ctx.course, hw_id, f, seen, hw), rows=rows,
                  back=cb("s2.hw.card", hw_id))


@node("s2.plan", "Что подтянуть", "s2", label="🎯 Что подтянуть", needs_student=True)
async def plan(ctx: Ctx) -> Screen:
    await ctx.store.log(ctx.user.id, "plan")
    text, links = plan_text(ctx.course, ctx.student)
    return Screen(text=text, rows=links_rows(links, limit=5))


# --- season materials: available even to those who submitted nothing --------------

def _topics_with_materials(ctx: Ctx):
    out = []
    for hw_id in sorted(ctx.course.rubrics):
        if (ctx.course.materials(hw_id) or ctx.course.task_text(hw_id)
                or ctx.course.reading(hw_id)):
            out.append((f"{hw_id} · {ctx.course.title(hw_id)[:28]}", "s2.lib.hw", hw_id))
    return out


@node("s2.lib", "Материалы сезона", "s2", label="📦 Материалы сезона",
      kids=_topics_with_materials)
async def library(ctx: Ctx) -> Screen:
    """Slides and assignments used to live only inside the homework card.

    Which meant someone who had not submitted it could not reach them at all —
    though they are exactly who needs them.
    """
    return Screen(text=texts.LIBRARY)


@node("s2.lib.hw", "Тема", "s2.lib")
async def library_topic(ctx: Ctx) -> Screen:
    hw_id = ctx.arg
    if hw_id not in ctx.course.rubrics:
        return Screen(alert="Такой темы нет")
    rows = []
    if ctx.course.task_text(hw_id):
        rows.append([InlineKeyboardButton(text="📄 Текст задания",
                                          callback_data=cb("s2.tsk", hw_id))])
    if ctx.course.materials(hw_id):
        rows.append([InlineKeyboardButton(text="📊 Слайды и конспект",
                                          callback_data=cb("s2.mat", hw_id))])
    if ctx.course.reading(hw_id):
        rows.append([InlineKeyboardButton(text="📚 Что почитать",
                                          callback_data=cb("s2.rd", hw_id))])
    return Screen(text=f"<b>{hw_id} · {escape(ctx.course.title(hw_id))}</b>", rows=rows)


@node("s2.tsk", "Задание", "s2.lib.hw")
async def task(ctx: Ctx) -> Screen:
    text = ctx.course.task_text(ctx.arg)
    if not text:
        return Screen(alert="Текст задания по этой теме не сохранился")
    await ctx.store.log(ctx.user.id, "task", {"hw": ctx.arg})
    return Screen(text=to_html(text), back=cb("s2.lib.hw", ctx.arg))


@node("s2.mat", "Слайды", "s2.lib.hw")
async def materials(ctx: Ctx) -> Screen:
    files = ctx.course.materials(ctx.arg)
    if not files:
        return Screen(alert="Материалов по этой теме нет")
    await ctx.store.log(ctx.user.id, "materials", {"hw": ctx.arg})
    return Screen(docs=[(label, path, "") for label, path in files],
                  back=cb("s2.lib.hw", ctx.arg))


@node("s2.rd", "Что почитать", "s2.lib.hw")
async def reading(ctx: Ctx) -> Screen:
    links = ctx.course.reading(ctx.arg)
    if not links:
        return Screen(alert="Подборки по этой теме нет")
    await ctx.store.log(ctx.user.id, "reading", {"hw": ctx.arg})
    return Screen(
        text=f"📚 <b>Что почитать по теме «{escape(ctx.course.title(ctx.arg))}»</b>",
        rows=links_rows(links, limit=5), back=cb("s2.lib.hw", ctx.arg))


# --- certificate ------------------------------------------------------------------

def _awards(ctx: Ctx):
    st = ctx.student
    if st is None or not st.certificate:
        return []
    out = []
    if ctx.course.certificate_file(st.key):
        out.append(("📜 Получить сертификат", "s2.crt.pdf", ""))
    if ctx.course.ceremony_photo(st.key):
        out.append(("📸 Фото с вручения", "s2.crt.photo", ""))
    return out


@node("s2.crt", "Сертификат", "s2", label="🏆 Сертификат", kids=_awards, needs_student=True)
async def certificate(ctx: Ctx) -> Screen:
    st = ctx.student
    await ctx.store.log(ctx.user.id, "certificate")
    total, need = ctx.course.total_graded, ctx.course.required_passed
    if not st.ok:
        return Screen(text=texts.EXCLUDED.format(fio=escape(st.fio),
                                                 reason=escape(st.reason)))
    if st.certificate:
        body, rows = texts.CERT_YES.format(passed=st.passed, total=total, need=need), []
    else:
        body = texts.CERT_NO.format(passed=st.passed, total=total, need=need,
                                    gap=need - st.passed)
        rows = links_rows(NEXT_STEPS, limit=3)
    return Screen(text=body + "\n\n" + texts.CERT_RULE.format(total=total, need=need),
                  rows=rows)


@node("s2.crt.pdf", "Сертификат", "s2.crt", needs_student=True)
async def certificate_file(ctx: Ctx) -> Screen:
    """Who gets the file is decided by the binding, not by the button's contents."""
    st = ctx.student
    path = ctx.course.certificate_file(st.key) if st.certificate else None
    if path is None:
        return Screen(text=texts.NO_CERT_FILE.format(support=ctx.cfg.support_username))
    await ctx.store.log(ctx.user.id, "certificate_file")
    return Screen(docs=[(texts.CERT_FILE_CAPTION.format(fio=escape(st.fio)), path,
                         f"Сертификат ML FAMCS — {st.fio}.pdf")])


@node("s2.crt.photo", "Фото с вручения", "s2.crt", needs_student=True)
async def ceremony_photo(ctx: Ctx) -> Screen:
    st = ctx.student
    path = ctx.course.ceremony_photo(st.key) if st.certificate else None
    if path is None:
        return Screen(text=texts.NO_PHOTO_FILE.format(support=ctx.cfg.support_username))
    await ctx.store.log(ctx.user.id, "ceremony_photo")
    # As a document, not a photo: Telegram would recompress a 5712x4284 shot.
    return Screen(docs=[(texts.PHOTO_CAPTION.format(fio=escape(st.fio)), path,
                         f"Вручение ML FAMCS — {st.fio}.jpg")])


# --- reference --------------------------------------------------------------------

def _reference_topics(ctx: Ctx):
    out = [("⚙️ Общие ошибки", "ref.hw", "common")]
    for hw_id in sorted(ctx.course.rubrics):
        out.append((f"{hw_id} {ctx.course.title(hw_id)[:30]}", "ref.hw", hw_id))
    return out


@node("ref", "Справочник", label="🔎 Справочник", order=2, kids=_reference_topics)
async def reference(ctx: Ctx) -> Screen:
    await ctx.store.log(ctx.user.id, "reference")
    return Screen(text=texts.REFERENCE_INTRO)


@node("ref.hw", "Тема", "ref")
async def reference_topic(ctx: Ctx) -> Screen:
    hw_id = ctx.arg
    items = sorted(
        ((c, a.title) for c, a in ctx.course.catalog.items() if c.startswith(f"{hw_id}.")),
        key=lambda x: (SEVERITY_ORDER.get(ctx.course.catalog[x[0]].severity, 3), x[1]),
    )
    if not items:
        return Screen(alert="Пусто")
    title = "Общие ошибки" if hw_id == "common" else f"{hw_id} · {ctx.course.title(hw_id)}"
    rows = [[InlineKeyboardButton(text=t[:56], callback_data=cb("ref.a", c))]
            for c, t in items[:30]]
    return Screen(text=f"<b>{escape(title)}</b>\nВыбери ошибку:", rows=rows)


@node("ref.a", "Статья", "ref.hw")
async def article(ctx: Ctx) -> Screen:
    art = ctx.course.article(ctx.arg)
    if art is None:
        return Screen(alert="Статья не найдена")
    await ctx.store.log(ctx.user.id, "article", {"code": ctx.arg})
    return Screen(text=article_text(ctx.course, ctx.arg), rows=links_rows(art.links, 5),
                  back=cb("ref.hw", art.hw))


@node("ref.find", "Поиск", "ref")
async def find(ctx: Ctx) -> Screen:
    query = ctx.arg.strip().lower()
    if len(query) < 3:
        return Screen(text="Напиши, что искать: <code>/find утечка</code>")
    hits = sorted(((c, a.title) for c, a in ctx.course.catalog.items()
                   if query in a.title.lower() or query in a.body.lower()),
                  key=lambda x: x[1])
    await ctx.store.log(ctx.user.id, "find", {"q": query})
    if not hits:
        return Screen(text=texts.FIND_EMPTY)
    rows = [[InlineKeyboardButton(text=t[:56], callback_data=cb("ref.a", c))]
            for c, t in hits[:30]]
    return Screen(text=f"Нашёл {len(hits)} статей по запросу «{escape(query)}»:", rows=rows)


@node("ref.rnd", "Ещё один разбор", "ref")
async def random_article(ctx: Ctx) -> Screen:
    art = random.choice(list(ctx.course.catalog.values()))
    await ctx.store.log(ctx.user.id, "article", {"code": art.code})
    return Screen(text="🎲 " + article_text(ctx.course, art.code),
                  rows=[[InlineKeyboardButton(text="🎲 Ещё один",
                                              callback_data=cb("ref.rnd"))]])


# --- help -------------------------------------------------------------------------

@node("help", "Помощь", label="🆘 Помощь", order=3, kids=("help.ask", "help.who", "help.data", "help.cmd"))
async def help_root(ctx: Ctx) -> Screen:
    await ctx.store.log(ctx.user.id, "help")
    return Screen(text=texts.HELP_ROOT.format(username=ctx.cfg.support_username))


@node("help.ask", "Написать преподавателю", "help", label="✉️ Написать преподавателю")
async def ask(ctx: Ctx) -> Screen:
    """The user's next message goes to the teacher."""
    from ..handlers.support import Ask
    if ctx.state is not None:
        await ctx.state.set_state(Ask.waiting_text)
    await ctx.store.log(ctx.user.id, "support")
    return Screen(
        text=texts.SUPPORT.format(username=ctx.cfg.support_username),
        rows=_write_to_teacher(ctx))


@node("help.who", "Кто я для бота", "help", label="🪪 Кто я для бота")
async def whoami(ctx: Ctx) -> Screen:
    # In tester mode `ctx.student` is already the record being looked through:
    # `deps._resolve` does the substitution, no need to reach into the catalog.
    if await ctx.store.test_view(ctx.user.id):
        return Screen(text=texts.WHOAMI_TEST.format(
            fio=escape(ctx.student.fio if ctx.student else "—")))
    if ctx.student is None:
        return Screen(text=texts.NOT_BOUND)
    return Screen(text=texts.WHOAMI.format(
        fio=escape(ctx.student.fio), repo=escape(ctx.student.repo or "—"),
        tg_id=ctx.user.id))


@node("help.cmd", "Команды", "help", label="📖 Команды")
async def commands(ctx: Ctx) -> Screen:
    text = texts.HELP
    if ctx.is_admin:
        text += "\n\n" + texts.HELP_ADMIN
    return Screen(text=text)


# --- what the bot knows about a person ----------------------------------------------

@node("help.data", "Мои данные", "help", label="💾 Мои данные",
      kids=("help.data.dl", "help.data.rm"))
async def my_data(ctx: Ctx) -> Screen:
    """If the bot keeps a binding and a click history, the person may see it.

    By season 3 a form with an email address lands here too — all the more
    reason to show everything up front rather than after the fact.
    """
    about = await ctx.store.about(ctx.user.id)
    b = about["binding"]
    clicks = sum(e["c"] for e in about["events"])
    lines = ["💾 <b>Что я о тебе знаю</b>", ""]
    lines.append(f"Твой telegram-id: <code>{ctx.user.id}</code>")
    if b:
        lines.append(f"Привязан к записи: <b>{escape(str(b['student_key']))}</b> "
                     f"(с {b['bound_at']})")
        lines.append(f"Сохранённый username: {('@' + b['username']) if b['username'] else '—'}")
    else:
        lines.append("Привязки нет.")
    lines.append(f"Нажатий в боте: <b>{clicks}</b>"
                 + (f" (первое {about['events'][-1]['first'][:10]})" if about["events"] else ""))
    if about["support"]:
        lines.append(f"Обращений в поддержку: <b>{len(about['support'])}</b>")
    if about["claims"]:
        lines.append(f"Заявок на доступ: <b>{len(about['claims'])}</b>")
    lines += ["", texts.DATA_NOTE]
    return Screen(text="\n".join(lines))


@node("help.data.dl", "Выгрузить файлом", "help.data", label="📄 Выгрузить файлом")
async def my_data_file(ctx: Ctx) -> Screen:
    import json as _json

    about = await ctx.store.about(ctx.user.id)
    blob = _json.dumps(about, ensure_ascii=False, indent=2).encode()
    return Screen(blobs=[("💾 Всё, что бот о тебе хранит.", blob,
                          f"mlbot-{ctx.user.id}.json")])


@node("help.data.rm", "Удалить мои данные", "help.data", label="🗑 Удалить мои данные",
      kids=("help.data.rm.yes",))
async def my_data_delete(ctx: Ctx) -> Screen:
    return Screen(text=texts.DATA_DELETE)


@node("help.data.rm.yes", "Да, удалить", "help.data.rm", label="🗑 Да, удалить")
async def my_data_delete_yes(ctx: Ctx) -> Screen:
    removed = await ctx.store.forget(ctx.user.id)
    return Screen(text=texts.DATA_DELETED.format(
        clicks=removed.get("events", 0),
        binding="удалена" if removed.get("bindings") else "её и не было"))
