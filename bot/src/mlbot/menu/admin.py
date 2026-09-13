"""Админка деревом. Четыре группы вместо одиннадцати кнопок в столбик.

Тела экранов переехали из `handlers/admin.py` почти дословно: они и раньше были
устроены как «собрать строки → нарезать → отправить». Побочная польза от
переезда — у длинных экранов впервые появилось «назад».

Права здесь — свойство узла (`visible=ADMIN`), и `core.show` проверяет его до
вызова рендерера. Обработчики, у которых экрана нет (диалоги, решения по
заявкам), остались в `handlers/admin.py` под фильтром `AdminOnly`.
"""

from __future__ import annotations

import csv
import io
import json


from .. import texts
from aiogram.types import InlineKeyboardButton

from ..render import escape, to_html
from ..season3.deadline import show as show_deadline
from .core import ADMIN, Ctx, Screen, cb, node


@node("adm", "Админка", label="🛠 Админка", visible=ADMIN, order=9,
      kids=("a.stat", "a.ppl", "a.cast", "a.s3", "a.dev"))
async def root(ctx: Ctx) -> Screen:
    """Заголовок сообщает режим: в песочнице студентам ничего не уходит.

    Режим вычисляется здесь, а не запоминается: иначе экран, открытый до
    перезапуска, врал бы про боевой режим после него.
    """
    return Screen(text=texts.ADMIN_ROOT.format(
        mode="🧪 <b>ПЕСОЧНИЦА</b> · сообщения студентам не уходят"
        if ctx.cfg.safe_mode else "🔴 <b>БОЕВОЙ РЕЖИМ</b> · сообщения уходят студентам"))


# --- 📈 аналитика ----------------------------------------------------------------

@node("a.stat", "Аналитика", "adm", label="📈 Аналитика", visible=ADMIN,
      kids=("a.stat.sum", "a.stat.hw", "a.stat.use", "a.stat.att"))
async def stats(ctx: Ctx) -> Screen:
    return Screen(text="📈 <b>Аналитика</b>\n\nЧто с потоком, что с темами, "
                       "что читают и что требует решения.")


@node("a.stat.sum", "Сводка по потоку", "a.stat", label="📊 Сводка по потоку", visible=ADMIN)
async def summary(ctx: Ctx) -> Screen:
    course, store = ctx.course, ctx.store
    dist = course.passed_distribution
    subs = sum(len(s.submitted()) for s in course.active)
    passed = sum(1 for s in course.active
                 for h in s.homeworks.values() if h["status"] == "passed")
    bound = len(await store.all_bindings())
    lines = [
        "📈 <b>Сводка по потоку</b>", "",
        f"В форме: <b>{len(course.students)}</b>",
        f"Проверено: <b>{len(course.active)}</b>   исключено: {len(course.excluded)}",
        f"Сдач: <b>{subs}</b>, из них зачтено <b>{passed}</b>",
        f"Сертификатов: <b>{course.certificates}</b> из {len(course.active)}",
        f"Медиана закрытых тем: <b>{course.median_passed:g}</b> из {course.total_graded}",
        f"Привязалось к боту: <b>{bound}</b>", "",
        "<b>Распределение по числу зачтённых</b>",
    ]
    for n in sorted(dist, reverse=True):
        lines.append(f"<code>{n:2}</code> │ {'█' * min(dist[n], 40)} {dist[n]}")
    return Screen(text="\n".join(lines))


@node("a.stat.hw", "По темам", "a.stat", label="📚 По темам", visible=ADMIN)
async def by_topic(ctx: Ctx) -> Screen:
    course = ctx.course
    lines = ["📚 <b>По темам</b>", ""]
    for hw_id, st in course.hw_stats.items():
        if not st["submitted"]:
            continue
        names = ", ".join((course.article(c).title if course.article(c) else c)[:34]
                          for c, _ in st["codes"].most_common(2))
        share = round(100 * st["passed"] / st["submitted"])
        lines.append(f"<b>{hw_id}</b> {escape(course.title(hw_id)[:28])}\n"
                     f"   сдач {st['submitted']}, зачтено {st['passed']} ({share}%)\n"
                     f"   <i>{escape(names)}</i>")
    return Screen(text="\n".join(lines))


@node("a.stat.use", "Что читают", "a.stat", label="📖 Что читают", visible=ADMIN)
async def usage(ctx: Ctx) -> Screen:
    """Демо-нажатия сюда не попадают: `store` помечает их при записи."""
    course, store = ctx.course, ctx.store
    totals = await store.event_totals()

    def label(payload: str) -> str:
        try:
            code = json.loads(payload).get("code", payload)
        except Exception:
            code = payload
        art = course.article(code)
        return art.title if art else code

    lines = ["📖 <b>Что читают</b>", "", "<b>Активность</b>"]
    lines += [f"• {k}: {v}" for k, v in list(totals.items())[:12]]
    for title, kind in (("Статьи справочника", "article"),
                        ("Свои замечания открывают", "finding")):
        top = await store.top_events(kind, 12)
        if top:
            lines += ["", f"<b>{title}</b>"]
            lines += [f"• {escape(label(p))} — {c}" for p, c in top]
    return Screen(text="\n".join(lines))


@node("a.stat.att", "Требует решения", "a.stat", label="⚠️ Требует решения", visible=ADMIN)
async def attention(ctx: Ctx) -> Screen:
    if not ctx.course.attention:
        return Screen(alert="Файл attention.md не найден")
    return Screen(text=to_html(ctx.course.attention))


# --- 👥 люди ----------------------------------------------------------------------

@node("a.ppl", "Люди", "adm", label="👥 Люди", visible=ADMIN,
      kids=("a.ppl.find", "a.ppl.cov", "a.ppl.tg", "a.ppl.claims", "a.ppl.sup"))
async def people(ctx: Ctx) -> Screen:
    return Screen(text="👥 <b>Люди</b>\n\nНайти студента, посмотреть охват "
                       "привязок, разобрать заявки и обращения.")


@node("a.ppl.find", "Найти студента", "a.ppl", label="🔍 Найти студента", visible=ADMIN)
async def find(ctx: Ctx) -> Screen:
    """Ответ ловит `handlers/admin.py` — узел только задаёт вопрос."""
    from ..handlers.admin import Admin
    if ctx.state is not None:
        await ctx.state.set_state(Admin.finding_student)
    return Screen(text="Напиши ФИО или логин GitHub. Отменить — /cancel")


@node("a.ppl.cov", "Кто привязался", "a.ppl", label="🔗 Кто привязался", visible=ADMIN)
async def coverage(ctx: Ctx) -> Screen:
    bindings = await ctx.store.all_bindings()
    bound = {b.student_key for b in bindings}
    missing = [s for s in ctx.course.active if s.key not in bound]
    with_cert = [s for s in missing if s.certificate]
    lines = [
        "🔗 <b>Кто привязался</b>", "",
        f"Привязано: <b>{len(bound)}</b> из {len(ctx.course.active)}",
        f"Не привязались: <b>{len(missing)}</b>, "
        f"из них с сертификатом: <b>{len(with_cert)}</b>", "",
        "<i>Не привязались, но сертификат заслужили:</i>",
    ]
    lines += [f"• {escape(s.fio)}" for s in with_cert[:40]] or ["— таких нет"]
    return Screen(text="\n".join(lines))


@node("a.ppl.tg", "Телеграмы", "a.ppl", label="📇 Телеграмы", visible=ADMIN)
async def telegrams(ctx: Ctx) -> Screen:
    """ФИО ↔ телеграм: из формы регистрации плюс закреплённое ботом.

    Форма сдачи username не спрашивала, поэтому к следующему сезону такая
    таблица — единственный способ не собирать его заново.
    """
    from mlcheck.telegram import read_map

    links = {lk.key: lk for lk in read_map(ctx.cfg.out_dir / "telegram_map.csv")}
    claimed = {b.student_key: b for b in await ctx.store.all_bindings()}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["fio", "repo", "username_формы", "существует",
                "username_подтверждённый", "источник"])
    stats = {"форма": 0, "бот": 0, "нет": 0}
    for st in ctx.course.students.values():
        lk, b = links.get(st.key), claimed.get(st.key)
        confirmed = (b.username or "") if b else ""
        source = "бот" if confirmed else ("форма" if lk and lk.usable else "нет")
        stats[source] += 1
        w.writerow([st.fio, st.repo or "", lk.username if lk else "",
                    lk.exists if lk else "", confirmed, source])
    caption = (f"📇 Телеграмы\n\nИз формы регистрации: <b>{stats['форма']}</b>\n"
               f"Подтверждено в боте: <b>{stats['бот']}</b>\n"
               f"Пока нигде: <b>{stats['нет']}</b>")
    return Screen(blobs=[(caption, buf.getvalue().encode("utf-8-sig"), "telegrams.csv")])


@node("a.ppl.claims", "Заявки на доступ", "a.ppl", label="🔑 Заявки на доступ",
      visible=ADMIN)
async def claims(ctx: Ctx) -> Screen:
    """Заявки на записи с закреплённым username: кто-то менял телеграм — или не он."""
    from ..keyboards import claim_card

    rows = await ctx.store.pending_claims()
    if not rows:
        return Screen(alert="Открытых заявок нет")
    # Каждую заявку — отдельным сообщением: у неё свои кнопки решения.
    out = [f"🔑 <b>Заявок на доступ: {len(rows)}</b>"]
    for c in rows:
        st = ctx.course.students.get(c["student_key"])
        reason = (f"В форме: @{escape(c['expected'])} — <b>не совпадает</b>"
                  if c["expected"] else "В форме телеграма нет — сверить не с чем")
        await ctx.bot.send_message(
            ctx.user.id,
            f"<b>#{c['id']}</b> · {escape(st.fio if st else c['student_key'])}\n"
            f"{reason}\n"
            f"Просит: @{escape(c['username'] or '—')} "
            f"({escape(c['tg_name'] or '')}, id {c['tg_id']})\n"
            f"Репозиторий: {escape(st.repo if st else '—')}\n"
            f"<i>{c['at']}</i>",
            reply_markup=claim_card(c["id"]))
    return Screen(text="\n".join(out))


@node("a.ppl.sup", "Обращения", "a.ppl", label="✉️ Обращения", visible=ADMIN)
async def support_list(ctx: Ctx) -> Screen:
    """У каждого обращения есть кнопка ответа.

    Раньше флаг `answered` только читался: пометить обращение отвеченным было
    нечем, и список открытых рос вечно, даже когда преподаватель отвечал в личке.
    """
    rows = await ctx.store.open_support()
    if not rows:
        return Screen(alert="Открытых обращений нет")
    lines = ["✉️ <b>Обращения</b>", ""]
    buttons = []
    for r in rows[:10]:
        who = f"@{r['username']}" if r["username"] else r["tg_id"]
        lines.append(f"<b>#{r['id']}</b> {escape(str(who))} · {r['at']}\n"
                     f"{escape(r['text'][:400])}\n")
        buttons.append([InlineKeyboardButton(
            text=f"✍️ Ответить #{r['id']}", callback_data=cb("a.ppl.sup.re", str(r["id"])))])
    return Screen(text="\n".join(lines), rows=buttons)


@node("a.ppl.sup.re", "Ответить", "a.ppl.sup", visible=ADMIN)
async def support_reply(ctx: Ctx) -> Screen:
    from ..handlers.admin import Admin
    if ctx.state is not None:
        await ctx.state.set_state(Admin.answering_support)
        await ctx.state.update_data(ticket=ctx.arg)
    return Screen(text=texts.SUPPORT_REPLY.format(id=ctx.arg))


@node("a.dev.health", "Здоровье бота", "a.dev", label="🩺 Здоровье бота", visible=ADMIN)
async def health(ctx: Ctx) -> Screen:
    """Та же диагностика, что `python -m mlbot.selfcheck`, но прямо в чате."""
    course, cfg = ctx.course, ctx.cfg
    from . import core as _core

    stalled = [b["id"] for b in await ctx.store.recent_broadcasts(30)
               if b["status"] == "stalled"]
    try:
        cfg.export_dir.mkdir(parents=True, exist_ok=True)
        probe = cfg.export_dir / ".health"
        probe.write_text("ok")
        probe.unlink()
        export = f"✓ пишется ({cfg.export_dir})"
    except OSError as exc:
        export = f"✗ не пишется: {exc}"

    lines = [
        "🩺 <b>Здоровье бота</b>", "",
        f"Предохранитель: {'🧪 песочница' if cfg.safe_mode else '🔴 боевой режим'}",
        f"Студентов: {len(course.students)}, проверено {len(course.active)}, "
        f"сертификатов {course.certificates}",
        f"Каталог: {len(course.catalog)} статей, тем {len(course.rubrics)}",
        f"Вымышленных записей: {len(ctx.demo.students) if ctx.demo else 0}",
        f"Узлов меню: {len(_core.NODES)}",
        f"Каталог выгрузок: {export}",
        f"Привязок: {len(await ctx.store.all_bindings())}",
        f"Открытых обращений: {len(await ctx.store.open_support())}",
        f"Заявок на доступ: {len(await ctx.store.pending_claims())}",
        f"Оборванных рассылок: {len(stalled)}"
        + (f" — {', '.join(f'#{i}' for i in stalled)}" if stalled else ""),
        f"attention.md: {'есть' if course.attention else 'нет'}",
    ]
    return Screen(text="\n".join(lines))


# --- 🛠 отладка -------------------------------------------------------------------

@node("a.dev", "Отладка", "adm", label="🛠 Отладка", visible=ADMIN,
      kids=("a.dev.as", "a.dev.demo", "a.dev.health", "a.dev.reload"))
async def dev(ctx: Ctx) -> Screen:
    return Screen(text=texts.ADMIN_DEV)


@node("a.dev.as", "Глазами студента", "a.dev", label="👓 Глазами студента", visible=ADMIN)
async def as_student(ctx: Ctx) -> Screen:
    from ..handlers.admin import test_examples
    cert, fail = test_examples(ctx.course)
    return Screen(text=texts.TEST_HOWTO.format(cert_fio=escape(cert.fio),
                                               fail_fio=escape(fail.fio)))


def _demo_students(ctx: Ctx):
    """Подпись сразу говорит, какое состояние экранов проверяет эта запись."""
    if ctx.demo is None:
        return []
    out = []
    # Порядок — от самого полного экрана к самому пустому.
    for st in sorted(ctx.demo.students.values(), key=lambda s: (not s.ok, -s.passed)):
        if not st.ok:
            mark = "🚫 репозиторий недоступен"
        elif st.certificate:
            mark = f"🏆 сертификат, {st.passed} из {st.total}"
        elif st.submitted():
            mark = f"📕 без сертификата, {st.passed} из {st.total}"
        else:
            mark = "🕳 ни одной сдачи"
        out.append((f"{st.fio} — {mark}", "a.dev.demo.as", st.key))
    out.append(("↩️ Выйти из тест-режима", "a.dev.demo.off", ""))
    return out


@node("a.dev.demo", "Вымышленные студенты", "a.dev", label="🧪 Вымышленные студенты",
      visible=ADMIN, kids=_demo_students)
async def demo_list(ctx: Ctx) -> Screen:
    """Четыре выдуманные записи закрывают все состояния экранов.

    Они лежат в отдельном каталоге и своём объекте `Course`, поэтому не входят
    ни в медиану, ни в число сертификатов, а их нажатия помечаются в базе и не
    едут в «Что читают».
    """
    if ctx.demo is None:
        return Screen(text=texts.DEMO_MISSING)
    return Screen(text=texts.DEMO_LIST)


@node("a.dev.demo.as", "Войти", "a.dev.demo", visible=ADMIN)
async def demo_enter(ctx: Ctx) -> Screen:
    if ctx.demo is None or ctx.arg not in ctx.demo.students:
        return Screen(alert="Такой записи нет")
    st = ctx.demo.students[ctx.arg]
    await ctx.store.set_test_view(ctx.user.id, st.key)
    from . import core
    await ctx.bot.send_message(
        ctx.user.id, texts.TEST_ON.format(fio=escape(st.fio), tag=" — вымышленная запись"),
        reply_markup=core.keyboard_for(ctx.cfg, ctx.user, st))
    return Screen(alert=f"Смотришь глазами: {st.fio}")


@node("a.dev.demo.off", "Выйти", "a.dev.demo", visible=ADMIN)
async def demo_leave(ctx: Ctx) -> Screen:
    from . import core
    await ctx.store.clear_test_view(ctx.user.id)
    await ctx.bot.send_message(ctx.user.id, texts.TEST_OFF,
                               reply_markup=core.keyboard_for(ctx.cfg, ctx.user))
    return Screen(alert="Вышел из тест-режима")


@node("a.dev.reload", "Перечитать данные", "a.dev", label="♻️ Перечитать данные",
      visible=ADMIN)
async def reload(ctx: Ctx) -> Screen:
    ctx.course.refresh()
    return Screen(text=texts.RELOAD_DONE.format(students=len(ctx.course.students),
                                                articles=len(ctx.course.catalog)))


# --- 📣 рассылки ------------------------------------------------------------------

def _audience_buttons(ctx: Ctx):
    from ..broadcast import audiences
    return [(a.title, "a.cast.to", a.id) for a in audiences.available(ctx.cfg)]


@node("a.cast", "Рассылки", "adm", label="📣 Рассылки", visible=ADMIN,
      kids=("a.cast.new", "a.cast.log"))
async def casts(ctx: Ctx) -> Screen:
    unfinished = [b for b in await ctx.store.recent_broadcasts(20)
                  if b["status"] == "stalled"]
    tail = (f"\n\n⚠️ Оборвалось на середине: <b>{len(unfinished)}</b>. "
            "Открой «История» — там есть «продолжить»." if unfinished else "")
    return Screen(text=texts.CAST_ROOT + tail)


@node("a.cast.new", "Новая рассылка", "a.cast", label="✏️ Новая рассылка",
      visible=ADMIN, kids=_audience_buttons)
async def cast_new(ctx: Ctx) -> Screen:
    from ..broadcast import audiences
    if ctx.cfg.safe_mode:
        hidden = len(audiences.REGISTRY) - len(audiences.available(ctx.cfg))
        note = texts.CAST_SANDBOX.format(hidden=hidden)
    else:
        note = texts.CAST_LIVE
    return Screen(text=texts.CAST_PICK + "\n\n" + note)


@node("a.cast.to", "Аудитория", "a.cast.new", visible=ADMIN)
async def cast_to(ctx: Ctx) -> Screen:
    """Считаем аудиторию сразу: видеть «кому» надо до того, как писать текст."""
    from ..broadcast import audiences
    from ..handlers.admin import Admin

    if ctx.arg not in {a.id for a in audiences.available(ctx.cfg)}:
        return Screen(alert="Эта аудитория сейчас недоступна")
    targets, unreachable = await audiences.resolve(
        ctx.arg, ctx.cfg, ctx.course, ctx.store, who=ctx.user.id)
    if ctx.state is not None:
        await ctx.state.set_state(Admin.broadcast_text)
        await ctx.state.update_data(audience=ctx.arg)
    miss = (f"\nНедостижимы: <b>{len(unreachable)}</b> — они не писали боту, "
            "первым он написать не может." if unreachable else "")
    return Screen(text=texts.CAST_COMPOSE.format(
        title=audiences.REGISTRY[ctx.arg].title, count=len(targets)) + miss)


@node("a.cast.log", "История", "a.cast", label="🗂 История", visible=ADMIN,
      kids=lambda ctx: [])
async def cast_log(ctx: Ctx) -> Screen:
    rows = await ctx.store.recent_broadcasts(12)
    if not rows:
        return Screen(text=texts.CAST_EMPTY)
    lines = ["🗂 <b>История рассылок</b>", ""]
    buttons = []
    mark = {"done": "✅", "sending": "⏳", "stalled": "⚠️", "draft": "✏️",
            "cancelled": "🚫"}
    for b in rows:
        stats = await ctx.store.broadcast_stats(b["id"])
        flag = "🧪 " if b["sandbox"] else ""
        lines.append(
            f"{mark.get(b['status'], '•')} <b>#{b['id']}</b> {flag}{b['audience']} · "
            f"{b['created_at']}\n"
            f"   отправлено {stats.get('sent', 0)}, "
            f"осталось {stats.get('pending', 0)}, "
            f"недоставлено {stats.get('failed', 0) + stats.get('blocked', 0)}")
        if b["status"] == "stalled":
            buttons.append([InlineKeyboardButton(
                text=f"▶️ Продолжить #{b['id']}", callback_data=cb("a.cast.go", str(b["id"])))])
    return Screen(text="\n".join(lines), rows=buttons)


@node("a.cast.go", "Отправить", "a.cast", visible=ADMIN)
async def cast_go(ctx: Ctx) -> Screen:
    """Запуск. Переход в «отправляется» атомарный, поэтому двойной клик безвреден."""
    import asyncio

    from ..broadcast import sender

    cast_id = int(ctx.arg) if ctx.arg.isdigit() else 0
    draft = await ctx.store.broadcast(cast_id)
    if draft is None:
        return Screen(alert="Такой рассылки нет")
    if not await ctx.store.start_broadcast(cast_id):
        return Screen(alert="Уже отправляется или закончена")

    status = await ctx.bot.send_message(ctx.user.id, texts.CAST_STARTED.format(id=cast_id))
    shown = {"last": ""}

    async def progress(stats: dict) -> None:
        line = (f"📣 <b>Рассылка #{cast_id}</b>\n\n"
                f"Отправлено: <b>{stats.get('sent', 0)}</b>\n"
                f"Осталось: {stats.get('pending', 0)}\n"
                f"Не доставлено: {stats.get('failed', 0) + stats.get('blocked', 0)}")
        if line == shown["last"]:
            return
        shown["last"] = line
        try:
            await status.edit_text(line)
        except Exception:
            pass

    # Отправка — фоновой задачей, а не в обработчике нажатия: иначе телеграм
    # отвалится по таймауту колбэка на первой же сотне писем.
    asyncio.create_task(sender.run(ctx.bot, ctx.store, cast_id, progress))
    return Screen(alert="Запустил")


@node("a.cast.no", "Отменить", "a.cast", visible=ADMIN)
async def cast_no(ctx: Ctx) -> Screen:
    cast_id = int(ctx.arg) if ctx.arg.isdigit() else 0
    if ctx.state is not None:
        await ctx.state.clear()
    ok = await ctx.store.cancel_broadcast(cast_id)
    return Screen(alert="Отменил" if ok else "Уже не отменить")


# --- 🚀 третий сезон ----------------------------------------------------------------

@node("a.s3", "Третий сезон", "adm", label="🚀 Третий сезон", visible=ADMIN,
      kids=("a.s3.apps", "a.s3.trk", "a.s3.hw", "a.s3.sync"))
async def s3_root(ctx: Ctx) -> Screen:
    apps = await ctx.store.applications("submitted")
    drafts = await ctx.store.applications("draft")
    return Screen(text=texts.A_S3_ROOT.format(done=len(apps), drafts=len(drafts)))


@node("a.s3.apps", "Заявки", "a.s3", label="📋 Заявки", visible=ADMIN)
async def s3_applications(ctx: Ctx) -> Screen:
    from ..sinks.csv_file import render

    apps = await ctx.store.applications("submitted")
    if not apps:
        return Screen(alert="Заявок пока нет")
    lines = [f"📋 <b>Заявок: {len(apps)}</b>", ""]
    for a in apps[:25]:
        ans = a["answers"]
        lines.append(f"• <b>{escape(ans.get('fio', '—'))}</b> "
                     f"{('@' + a['username']) if a.get('username') else ''}\n"
                     f"  {escape(ans.get('university', '—'))} · "
                     f"{escape(', '.join(a['tracks']) or '—')}")
    blob = render(apps).encode("utf-8-sig")
    return Screen(text="\n".join(lines),
                  blobs=[(f"📋 Заявки третьего сезона: {len(apps)}", blob,
                          "s3_applications.csv")])


@node("a.s3.trk", "По направлениям", "a.s3", label="🧭 По направлениям", visible=ADMIN)
async def s3_by_track(ctx: Ctx) -> Screen:
    from ..season3 import current_season

    season = current_season(ctx.cfg.tracks_path)
    counts = await ctx.store.track_counts()
    total = len(await ctx.store.applications("submitted"))
    lines = ["🧭 <b>По направлениям</b>", ""]
    for t in season.tracks:
        n = counts.get(t.id, 0)
        bar = "█" * min(n, 30)
        teacher = f" · {escape(t.teacher)}" if t.teacher else " · <i>преподаватель не назначен</i>"
        lines.append(f"{t.button}{teacher}\n<code>{n:3}</code> │ {bar}")
    lines += ["", f"Всего заявок: <b>{total}</b> "
                  f"(люди считаются по разу, направления — по каждому)"]
    return Screen(text="\n".join(lines))


@node("a.s3.hw", "Домашки", "a.s3", label="📚 Домашки сезона", visible=ADMIN,
      kids=("a.s3.new",))
async def s3_homeworks(ctx: Ctx) -> Screen:
    rows = await ctx.store.homeworks()
    if not rows:
        return Screen(text=texts.A_S3_HW_EMPTY)
    lines = ["📚 <b>Домашки третьего сезона</b>", ""]
    buttons = []
    for hw in rows[:15]:
        stats = await ctx.store.delivery_stats(hw["id"])
        mark = "✅" if hw["status"] == "published" else "✏️"
        lines.append(f"{mark} <b>#{hw['id']}</b> {escape(hw['title'][:50])}"
                     + (f"\n   выдано {stats.get('sent', 0)}, "
                        f"осталось {stats.get('pending', 0)}" if stats else ""))
        buttons.append([InlineKeyboardButton(
            text=f"{mark} #{hw['id']} {hw['title'][:30]}",
            callback_data=cb("a.s3.one", str(hw["id"])))])
    return Screen(text="\n".join(lines), rows=buttons)


@node("a.s3.one", "Домашка", "a.s3.hw", visible=ADMIN)
async def s3_homework_card(ctx: Ctx) -> Screen:
    from ..season3 import current_season

    hw = await ctx.store.homework(int(ctx.arg)) if ctx.arg.isdigit() else None
    if hw is None:
        return Screen(alert="Такой домашки нет")
    season = current_season(ctx.cfg.tracks_path)
    picked = ", ".join((season.get(t).button if season.get(t) else t) for t in hw["tracks"])
    stats = await ctx.store.delivery_stats(hw["id"])
    rows = []
    if hw["status"] == "draft":
        who = await ctx.store.recipients_for_tracks(hw["tracks"])
        rows.append([InlineKeyboardButton(
            text=f"📤 Выдать {len(who)} студентам",
            callback_data=cb("a.s3.pub", str(hw["id"])))])
    elif stats.get("pending"):
        rows.append([InlineKeyboardButton(
            text=f"▶️ Дослать {stats['pending']}",
            callback_data=cb("a.s3.pub", str(hw["id"])))])
    return Screen(text=texts.A_S3_HW_CARD.format(
        id=hw["id"], title=escape(hw["title"]), tracks=escape(picked),
        status="опубликована" if hw["status"] == "published" else "черновик",
        deadline=escape(show_deadline(hw["deadline"])),
        sent=stats.get("sent", 0), left=stats.get("pending", 0),
        body=escape(hw["body"][:600])), rows=rows)


def _new_hw_tracks(ctx: Ctx):
    from ..season3 import current_season
    return [(t.button, "a.s3.nt", t.id) for t in current_season(ctx.cfg.tracks_path).open]


@node("a.s3.new", "Новая домашка", "a.s3.hw", label="➕ Новая домашка", visible=ADMIN,
      kids=_new_hw_tracks)
async def s3_new_homework(ctx: Ctx) -> Screen:
    """Направления выбираются галочками; получатели считаются сразу."""
    chosen = await _chosen_tracks(ctx)
    who = await ctx.store.recipients_for_tracks(list(chosen))
    return Screen(text=texts.A_S3_HW_NEW.format(
        picked=", ".join(sorted(chosen)) or "пока ничего", count=len(who)),
        rows=[[InlineKeyboardButton(
            text="▶ Дальше: текст задания" if chosen else "Выбери хотя бы одно направление",
            callback_data=cb("a.s3.text") if chosen else cb("noop"))]])


async def _chosen_tracks(ctx: Ctx) -> set[str]:
    if ctx.state is None:
        return set()
    data = await ctx.state.get_data()
    return set(data.get("hw_tracks") or [])


@node("a.s3.nt", "Направление", "a.s3.new", visible=ADMIN)
async def s3_toggle_track(ctx: Ctx) -> Screen:
    chosen = await _chosen_tracks(ctx)
    chosen.symmetric_difference_update({ctx.arg})
    if ctx.state is not None:
        await ctx.state.update_data(hw_tracks=sorted(chosen))
    # Перерисовываем тот же экран: галочки видны в подписях кнопок.
    from . import core as _core
    return await _core.NODES["a.s3.new"].render(ctx)


@node("a.s3.text", "Текст задания", "a.s3.new", visible=ADMIN)
async def s3_ask_text(ctx: Ctx) -> Screen:
    from ..handlers.admin import Admin
    if ctx.state is not None:
        await ctx.state.set_state(Admin.homework_text)
    return Screen(text=texts.A_S3_HW_TEXT)


@node("a.s3.pub", "Выдать", "a.s3.hw", visible=ADMIN)
async def s3_publish(ctx: Ctx) -> Screen:
    """Выдача возобновляемая: получатели заморожены, отправленные помечены."""
    import asyncio

    from ..broadcast import sender

    hw = await ctx.store.homework(int(ctx.arg)) if ctx.arg.isdigit() else None
    if hw is None:
        return Screen(alert="Такой домашки нет")
    who = await ctx.store.recipients_for_tracks(hw["tracks"])
    if hw["status"] == "draft" and not await ctx.store.publish_homework(hw["id"], who):
        return Screen(alert="Уже опубликована")
    left = await ctx.store.pending_deliveries(hw["id"])
    if not left:
        return Screen(alert="Все уже получили")

    body = texts.S3_HW_MESSAGE.format(
        num=f"#{hw['num']}" if hw["num"] else "", title=escape(hw["title"]),
        body=hw["body"], deadline=escape(show_deadline(hw["deadline"])))

    async def deliver() -> None:
        for tg_id in left:
            try:
                await sender.guard(lambda: ctx.bot.send_message(
                    tg_id, body, disable_web_page_preview=True))
            except Exception as exc:
                await ctx.store.mark_delivery(hw["id"], tg_id, "failed",
                                              f"{type(exc).__name__}"[:200])
            else:
                await ctx.store.mark_delivery(hw["id"], tg_id, "sent")
            await asyncio.sleep(sender.PAUSE)

    asyncio.create_task(deliver())
    return Screen(alert=f"Выдаю {len(left)} студентам")


@node("a.s3.sync", "Синхронизация", "a.s3", label="🔄 Синхронизация", visible=ADMIN)
async def s3_sync(ctx: Ctx) -> Screen:
    """Что разошлось между своей базой, файлом и Notion.

    Расхождения показываем, но ничего не удаляем: два писателя в одну модель
    теряют данные тихо, поэтому обратного импорта здесь нет и не будет.
    """
    health = await ctx.store.outbox_health()
    flags = await ctx.store.open_flags()
    csv_path = ctx.cfg.export_dir / "s3_applications.csv"
    lines = [
        "🔄 <b>Синхронизация</b>", "",
        f"Очередь: ждут <b>{health.get('pending', 0)}</b>, "
        f"доставлено {health.get('done', 0)}, "
        f"разошлось <b>{health.get('diverged', 0)}</b>",
        f"Файл: {'есть' if csv_path.exists() else 'ещё не создан'} "
        f"(<code>{escape(str(csv_path))}</code>)",
        f"Notion: {'настроен' if ctx.cfg.notion_ready else 'нет токена или базы'}",
    ]
    if ctx.cfg.notion_ready:
        from ..sinks import notion
        try:
            remote = await notion.fetch_all(ctx.cfg)
        except Exception as exc:
            lines.append(f"Сверка не вышла: {escape(str(exc)[:200])}")
        else:
            ours = {a["tg_id"] for a in await ctx.store.applications("submitted")}
            theirs = set()
            for page in remote:
                prop = (page.get("properties") or {}).get("tg_id") or {}
                if prop.get("number") is not None:
                    theirs.add(int(prop["number"]))
            lines += [
                "",
                f"Только у нас: <b>{len(ours - theirs)}</b>",
                f"Только в Notion: <b>{len(theirs - ours)}</b> "
                f"<i>(сообщаю, не удаляю)</i>",
            ]
    if flags:
        lines += ["", "⚠️ <b>Требует внимания</b>"]
        lines += [f"• {escape(str(f['payload'])[:150])}" for f in flags[:5]]
    return Screen(text="\n".join(lines))
