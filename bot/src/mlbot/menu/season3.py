"""Третий сезон: направления, анкета, репозиторий.

Анкета — двенадцать шагов, но обработчиков у неё не двенадцать: шаги описаны
данными в `season3/wizard.py`, а здесь одна функция отрисовки шага и по одному
узлу на вид ответа.

Черновик живёт в SQLite, а не в состоянии: `MemoryStorage` не переживает
перезапуск контейнера, и человек, заполнивший десять шагов, начинал бы заново.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton

from .. import texts
from ..render import escape
from ..season3 import current_season, wizard
from ..season3.deadline import show as show_deadline
from .core import Ctx, Screen, cb, node

BACK_TO_FORM = "◀ К анкете"


def _btn(text: str, data: str) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(text=text, callback_data=data)]


def _tracks(ctx: Ctx):
    season = current_season(ctx.cfg.tracks_path)
    return [(t.button, "s3.trk.one", t.id) for t in season.open]


@node("s3", "Третий сезон", label="🚀 Третий сезон", order=0,
      kids=("s3.trk", "s3.reg", "s3.hw", "s3.me"))
async def season3(ctx: Ctx) -> Screen:
    season = current_season(ctx.cfg.tracks_path)
    app = await ctx.store.application(ctx.user.id)
    if app and app["status"] == "submitted":
        state = texts.S3_STATE_DONE
    elif app:
        state = texts.S3_STATE_DRAFT
    else:
        state = texts.S3_STATE_NEW
    return Screen(text=texts.S3_ROOT.format(
        title=escape(season.title), starts=escape(season.starts),
        about=escape(season.about), tracks=len(season.open), state=state))


@node("s3.trk", "Направления", "s3", label="🧭 Направления", kids=_tracks)
async def tracks(ctx: Ctx) -> Screen:
    await ctx.store.log(ctx.user.id, "s3_tracks")
    return Screen(text=texts.S3_TRACKS)


@node("s3.trk.one", "Направление", "s3.trk")
async def track_card(ctx: Ctx) -> Screen:
    season = current_season(ctx.cfg.tracks_path)
    track = season.get(ctx.arg)
    if track is None:
        return Screen(alert="Такого направления нет")
    await ctx.store.log(ctx.user.id, "s3_track", {"track": track.id})
    counts = await ctx.store.track_counts()
    teacher = f"\nПреподаватель: <b>{escape(track.teacher)}</b>" if track.teacher else ""
    return Screen(text=(
        f"{track.emoji} <b>{escape(track.title)}</b>\n\n"
        f"{escape(track.about)}\n\n"
        f"Занятий: <b>{track.lessons}</b>{teacher}\n"
        f"Уже записалось: <b>{counts.get(track.id, 0)}</b>"))


# --- анкета -------------------------------------------------------------------------

async def _render_step(ctx: Ctx, step, answers: dict) -> Screen:
    """Один шаг анкеты. Вид ответа определяет, что нарисовать."""
    i = wizard.index(step.id) + 1
    head = texts.S3_STEP.format(i=i, n=len(wizard.STEPS), prompt=step.prompt)
    if step.hint:
        head += f"\n\n<i>{step.hint}</i>"
    rows: list[list[InlineKeyboardButton]] = []

    if step.kind == "choice":
        for value, label in step.choices(answers):
            rows.append(_btn(label, cb("s3.a", f"{step.id}:{value}")))
        if step.allow_other:
            rows.append(_btn("✏️ Другое — напишу сам", cb("s3.o", step.id)))
    elif step.kind == "multi":
        chosen = set(answers.get(step.id) or [])
        for value, label in step.choices(answers):
            mark = "☑️" if value in chosen else "▫️"
            rows.append(_btn(f"{mark} {label}", cb("s3.m", f"{step.id}:{value}")))
        enough = len(chosen) >= step.min_choices
        rows.append(_btn("Дальше ▶" if enough else f"Выбери хотя бы {step.min_choices}",
                         cb("s3.nx", step.id) if enough else cb("noop")))
    else:
        # Свободный ввод: ждём следующее сообщение. Состояние ставит тот, кто
        # рисует шаг, — иначе ответ уехал бы в меню или в поддержку.
        from ..handlers.season3 import Form
        if ctx.state is not None:
            await ctx.state.set_state(Form.answer)
            await ctx.state.update_data(step=step.id)
        head += "\n\n" + texts.S3_TYPE_IT

    if step.optional:
        rows.append(_btn("Пропустить", cb("s3.sk", step.id)))
    if i > 1:
        rows.append(_btn("📋 Сводка", cb("s3.sum")))
    return Screen(text=head, rows=rows)


async def _advance(ctx: Ctx, step_id: str, value, answers: dict | None = None) -> Screen:
    """Записать ответ и показать следующий шаг — либо сводку, если шаги кончились."""
    answers = await ctx.store.save_answer(ctx.user.id, step_id, value)
    nxt = wizard.next_step(step_id, answers)
    if nxt is None:
        return await _summary(ctx, answers)
    await ctx.store.save_answer(ctx.user.id, None, None, next_step=nxt.id)
    return await _render_step(ctx, nxt, answers)


@node("s3.reg", "Заполнить анкету", "s3", label="📝 Записаться на сезон")
async def register(ctx: Ctx) -> Screen:
    """Начать анкету или вернуться туда, где остановились."""
    app = await ctx.store.application(ctx.user.id)
    if app and app["status"] == "submitted":
        return await _summary(ctx, app["answers"], submitted=True)
    answers = app["answers"] if app else {}
    step = wizard.step(app["step"]) if app and app["step"] else None
    if step is None:
        step = next((s for s in wizard.missing(answers)), None) or wizard.first()
    await ctx.store.save_answer(ctx.user.id, None, None, next_step=step.id)
    await ctx.store.log(ctx.user.id, "s3_form", {"step": step.id})
    return await _render_step(ctx, step, answers)


@node("s3.a", "Ответ", "s3.reg")
async def answer_choice(ctx: Ctx) -> Screen:
    step_id, _, value = ctx.arg.partition(":")
    step = wizard.step(step_id)
    if step is None:
        return Screen(alert="Шага уже нет")
    return await _advance(ctx, step_id, value)


@node("s3.m", "Отметить", "s3.reg")
async def answer_toggle(ctx: Ctx) -> Screen:
    step_id, _, value = ctx.arg.partition(":")
    step = wizard.step(step_id)
    if step is None:
        return Screen(alert="Шага уже нет")
    app = await ctx.store.application(ctx.user.id)
    answers = app["answers"] if app else {}
    chosen = list(answers.get(step_id) or [])
    if value in chosen:
        chosen.remove(value)
    else:
        chosen.append(value)
    answers = await ctx.store.save_answer(ctx.user.id, step_id, chosen, next_step=step_id)
    return await _render_step(ctx, step, answers)


@node("s3.nx", "Дальше", "s3.reg")
async def answer_next(ctx: Ctx) -> Screen:
    step = wizard.step(ctx.arg)
    if step is None:
        return Screen(alert="Шага уже нет")
    app = await ctx.store.application(ctx.user.id)
    answers = app["answers"] if app else {}
    if len(answers.get(step.id) or []) < step.min_choices:
        return Screen(alert=f"Выбери хотя бы {step.min_choices}")
    return await _advance(ctx, step.id, answers.get(step.id) or [])


@node("s3.sk", "Пропустить", "s3.reg")
async def answer_skip(ctx: Ctx) -> Screen:
    step = wizard.step(ctx.arg)
    if step is None or not step.optional:
        return Screen(alert="Этот шаг пропустить нельзя")
    return await _advance(ctx, step.id, "" if step.kind != "multi" else [])


@node("s3.o", "Другое", "s3.reg")
async def answer_other(ctx: Ctx) -> Screen:
    """«Другое» переводит шаг с кнопок на свободный ввод."""
    step = wizard.step(ctx.arg)
    if step is None:
        return Screen(alert="Шага уже нет")
    from ..handlers.season3 import Form
    if ctx.state is not None:
        await ctx.state.set_state(Form.answer)
        await ctx.state.update_data(step=step.id)
    return Screen(text=f"{step.prompt}\n\n{texts.S3_TYPE_IT}")


# --- сводка и отправка ----------------------------------------------------------------

async def _summary(ctx: Ctx, answers: dict, submitted: bool = False) -> Screen:
    lines = [texts.S3_SUMMARY_DONE if submitted else texts.S3_SUMMARY, ""]
    rows: list[list[InlineKeyboardButton]] = []
    edits: list[InlineKeyboardButton] = []
    for s in wizard.STEPS:
        if s.id == "faculty" and not s.choices(answers):
            continue
        shown = wizard.label_of(s, answers.get(s.id), answers)
        lines.append(f"• <b>{escape(s.name)}:</b> {escape(shown)}")
        if not submitted:
            # В кнопку кладём номер шага, а не ответ: персональным данным в
            # callback_data не место — они видны и подделываются.
            edits.append(InlineKeyboardButton(
                text=f"✏️ {s.name}", callback_data=cb("s3.ed", str(wizard.index(s.id)))))
    if submitted:
        return Screen(text="\n".join(lines))
    # Кнопки правки по две в ряд: тринадцать в столбик — это экран, который
    # надо прокручивать, чтобы дойти до «отправить».
    rows += [edits[i:i + 2] for i in range(0, len(edits), 2)]
    gaps = wizard.missing(answers)
    if gaps:
        lines += ["", texts.S3_GAPS.format(
            what=", ".join(escape(g.name) for g in gaps))]
        rows.insert(0, _btn("▶ Дозаполнить", cb("s3.ed", str(wizard.index(gaps[0].id)))))
    else:
        rows.insert(0, _btn("✅ Отправить заявку", cb("s3.go")))
    return Screen(text="\n".join(lines), rows=rows)


@node("s3.sum", "Сводка", "s3.reg", label="📋 Сводка")
async def summary(ctx: Ctx) -> Screen:
    app = await ctx.store.application(ctx.user.id)
    return await _summary(ctx, app["answers"] if app else {},
                          submitted=bool(app and app["status"] == "submitted"))


@node("s3.ed", "Править", "s3.sum")
async def edit(ctx: Ctx) -> Screen:
    i = int(ctx.arg) if ctx.arg.isdigit() else -1
    if not 0 <= i < len(wizard.STEPS):
        return Screen(alert="Такого шага нет")
    step = wizard.STEPS[i]
    app = await ctx.store.application(ctx.user.id)
    answers = app["answers"] if app else {}
    await ctx.store.save_answer(ctx.user.id, None, None, next_step=step.id)
    return await _render_step(ctx, step, answers)


@node("s3.go", "Отправить заявку", "s3.sum")
async def submit(ctx: Ctx) -> Screen:
    app = await ctx.store.application(ctx.user.id)
    if app is None:
        return Screen(alert="Анкеты ещё нет")
    if app["status"] == "submitted":
        return Screen(alert="Заявка уже отправлена")
    answers = app["answers"]
    if wizard.missing(answers):
        return Screen(alert="Не все обязательные поля заполнены")
    await ctx.store.touch_person(ctx.user.id, ctx.user.username,
                                 getattr(ctx.user, "full_name", None))
    await ctx.store.submit_application(ctx.user.id, list(answers.get("tracks") or []))
    await ctx.store.log(ctx.user.id, "s3_submitted", {"tracks": answers.get("tracks")})
    season = current_season(ctx.cfg.tracks_path)
    picked = ", ".join((season.get(t).button if season.get(t) else t)
                       for t in answers.get("tracks") or [])
    return Screen(text=texts.S3_SUBMITTED.format(tracks=escape(picked)))


@node("s3.me", "Моя заявка", "s3", label="🪪 Моя заявка", kids=("s3.repo",))
async def mine(ctx: Ctx) -> Screen:
    app = await ctx.store.application(ctx.user.id)
    if app is None:
        return Screen(text=texts.S3_NO_APPLICATION)
    season = current_season(ctx.cfg.tracks_path)
    picked = [season.get(t) for t in (app["answers"].get("tracks") or [])]
    repo = await ctx.store.repo_of(ctx.user.id)
    lines = [
        texts.S3_MINE_HEAD.format(
            state="отправлена" if app["status"] == "submitted" else "черновик",
            when=(app["submitted_at"] or app["updated_at"] or "")[:16]),
        "",
        f"Направления: <b>{escape(', '.join(t.button for t in picked if t) or '—')}</b>",
        f"Репозиторий: {escape(repo['url']) if repo else '—'}",
    ]
    return Screen(text="\n".join(lines))


@node("s3.repo", "Репозиторий", "s3.me", label="🔗 Привязать репозиторий")
async def repo(ctx: Ctx) -> Screen:
    from ..handlers.season3 import Form
    if ctx.state is not None:
        await ctx.state.set_state(Form.repo)
    current = await ctx.store.repo_of(ctx.user.id)
    now = (f"\n\nСейчас записан: {escape(current['url'])}" if current else "")
    return Screen(text=texts.S3_REPO_ASK + now)


# --- домашки сезона -------------------------------------------------------------------

@node("s3.hw", "Домашки сезона", "s3", label="📚 Домашки сезона",
      visible=lambda ctx: True)
async def homeworks(ctx: Ctx) -> Screen:
    """Домашки по направлениям, на которые человек записан.

    Показываем их и здесь, а не только в момент рассылки: сообщение легко
    потерять в переписке, а задание нужно всю неделю.
    """
    rows = await ctx.store.homeworks_for(ctx.user.id)
    if not rows:
        return Screen(text=texts.S3_HW_NONE)
    buttons = [[InlineKeyboardButton(
        text=f"{'#' + str(h['num']) if h['num'] else ''} {h['title'][:44]}".strip(),
        callback_data=cb("s3.hw.one", str(h["id"])))] for h in rows[:20]]
    return Screen(text=texts.S3_HW_LIST.format(n=len(rows)), rows=buttons)


@node("s3.hw.one", "Домашка", "s3.hw")
async def homework_card(ctx: Ctx) -> Screen:
    mine = {str(h["id"]): h for h in await ctx.store.homeworks_for(ctx.user.id)}
    hw = mine.get(ctx.arg)
    if hw is None:
        # Не «нет такой», а «не твоя»: чужую домашку по номеру не открыть.
        return Screen(alert="Этой домашки нет среди твоих направлений")
    await ctx.store.log(ctx.user.id, "s3_hw_open", {"id": hw["id"]})
    return Screen(text=texts.S3_HW_MESSAGE.format(
        num=f"#{hw['num']}" if hw["num"] else "", title=escape(hw["title"]),
        body=hw["body"], deadline=escape(show_deadline(hw["deadline"]))))
