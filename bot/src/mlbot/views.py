"""Сборка текстов экранов. Чистые функции: ни телеграма, ни ввода-вывода.

Вынесено из обработчиков, чтобы прогонять рендер по всему потоку в тестах.
"""

from __future__ import annotations

from .data import SEVERITY_ICON, SEVERITY_ORDER, STATUS_ICON, Course, Student
from .render import escape, progress_bar, to_html

STATUS_WORD = {"passed": "зачтено", "failed": "не зачтено", "missing": "не сдано"}


def place(percentile: int) -> str:
    if percentile >= 90:
        return "это верхние 10% потока"
    if percentile >= 75:
        return "это верхняя четверть потока"
    if percentile >= 50:
        return "это выше медианы по потоку"
    return "по потоку это ниже медианы"


def sorted_findings(hw: dict | None) -> list[dict]:
    if not hw:
        return []
    return sorted(hw.get("findings", []),
                  key=lambda f: (SEVERITY_ORDER.get(f["severity"], 3), f["code"]))


def points_needed(course: Course, hw: dict) -> int:
    """Сколько пунктов задания нужно было закрыть.

    Округление вверх: при пороге 70% от 9 пунктов нужно семь, а не шесть с
    хвостиком. Проверка сравнивает долю с порогом, здесь та же граница, но
    выраженная в пунктах.

    Поправка в 1e-9 — страховка от двоичного округления на ровной границе:
    при нынешних 70% расхождений нет, но, скажем, 0.28 × 25 даёт
    7.000000000000001, и бот потребовал бы восемь пунктов там, где проверка
    засчитывает семь. Цифра в боте и решение проверки должны совпадать всегда.
    """
    from mlcheck.report import points_needed_for

    return points_needed_for(course.hw_pass_ratio, hw["required_total"])


def blockers(course: Course, hw: dict) -> list[dict]:
    """Что именно закрыло зачёт по теме.

    Повторяет решение проверки дословно: заваливают только критичные
    замечания и недобор обязательных пунктов. Замечания уровня «серьёзное» и
    «мелкое» на зачёт не влияют никогда — студенту важно это видеть, иначе
    список из тридцати замечаний читается как тридцать причин незачёта.
    """
    out: list[dict] = []
    if hw["required_total"]:
        need = points_needed(course, hw)
        if hw["required_passed"] < need:
            out.append({
                "kind": "points",
                # Полный текст нужен там, где цифр рядом нет — в списке
                # «из-за чего не зачтены работы». В карточке темы они уже
                # напечатаны строкой выше, поэтому там берётся short.
                "text": (f"Закрыто {hw['required_passed']} из {hw['required_total']} "
                         f"пунктов задания, а нужно не меньше {need}"),
                "short": "Пунктов задания закрыто меньше необходимого",
            })
    for f in hw.get("findings", []):
        if f["severity"] == "critical":
            out.append({"kind": "critical", "code": f["code"], "text": f["title"],
                        "detail": f.get("detail", "")})
    return out


def is_blocking(f: dict) -> bool:
    """Влияло ли это замечание на зачёт по теме."""
    return f["severity"] == "critical"


def verdict_block(course: Course, hw: dict) -> list[str]:
    """Абзац «почему не зачтено» либо «что не повлияло» — для карточки темы."""
    findings = hw.get("findings", [])
    reasons = blockers(course, hw)

    if hw["status"] == "passed":
        if not findings:
            return []
        return ["", f"Замечания есть ({len(findings)}), но на зачёт они не влияли — "
                    "прочитать их всё равно стоит."]

    if not reasons:
        return []

    word = "причина" if len(reasons) == 1 else "причины"
    lines = ["", f"<b>Почему не зачтено</b> — {len(reasons)} {word}:"]
    for i, r in enumerate(reasons, start=1):
        if r["kind"] == "points":
            lines.append(f"{i}. 📉 {escape(r.get('short') or r['text'])}")
        else:
            lines.append(f"{i}. {SEVERITY_ICON['critical']} {escape(r['text'])}")
            if r.get("detail"):
                lines.append(f"    <code>{escape(r['detail'][:120])}</code>")

    rest = len(findings) - sum(1 for r in reasons if r["kind"] == "critical")
    if rest > 0:
        lines.append("")
        lines.append(f"Остальные замечания ({rest}) на зачёт не влияли.")
    lines.append("")
    lines.append("<i>Разбор каждого — кнопками ниже: что не так, почему это важно "
                 "и как надо.</i>")
    return lines


def failed_topics(course: Course, student: Student) -> list[tuple[str, list[dict]]]:
    """Незачтённые зачётные темы вместе с причинами, по порядку тем."""
    out = []
    for hw_id in sorted(course.graded_ids):
        hw = student.hw(hw_id)
        if hw and hw["status"] == "failed":
            out.append((hw_id, blockers(course, hw)))
    return out


def results_text(course: Course, student: Student) -> str:
    sev = student.severity_counts()
    medal = " 🏅" if student.passed == student.total else ""
    lines = [
        f"<b>{escape(student.fio)}</b>{medal}",
        f'<a href="{student.repo}">репозиторий</a>' if student.repo else "",
        "",
        f"<code>{progress_bar(student.passed, student.total)}</code>  "
        f"<b>{student.passed} из {student.total}</b>",
        f"Сертификат: {'да ✅' if student.certificate else 'пока нет'}",
        "",
        f"Сдано работ: {len(student.submitted())}, из них зачтено {student.passed}",
        f"Замечания: {SEVERITY_ICON['critical']} {sev['critical']}   "
        f"{SEVERITY_ICON['major']} {sev['major']}   {SEVERITY_ICON['minor']} {sev['minor']}",
    ]
    # Самый частый вопрос: «залил все домашки, почему зачтено меньше».
    # Отвечаем сразу, не заставляя открывать каждую тему по очереди.
    gap = failed_topics(course, student)
    if gap:
        lines += ["", f"<b>Не зачтено работ: {len(gap)}.</b> Причина у каждой своя — "
                      f"критичное замечание или недобор пунктов задания. "
                      f"Разбор в «📚 Домашки», коротким списком — в «🎯 Что подтянуть»."]
    lines += ["", f"<i>{place(course.percentile(student))}</i>"]
    strengths = student.strengths()
    if student.portrait:
        lines += ["", "<b>Сильные стороны за курс</b>",
                  escape(student.portrait["portrait"][:600]),
                  "<i>Подробнее по темам — кнопка «💪 Сильные стороны» ниже.</i>"]
    elif strengths:
        lines += ["", f"<b>Что отмечено хорошего</b> — в {len(strengths)} темах, "
                      f"кнопка «💪 Сильные стороны» ниже."]
    if student.similarity:
        lines += ["", "⚠️ По некоторым работам есть полное совпадение с чужими — "
                      "преподаватели смотрят такие случаи отдельно."]
    return "\n".join(x for x in lines if x != "" or True)


def hw_card_text(course: Course, student: Student, hw_id: str, missing_note: str) -> str:
    hw = student.hw(hw_id)
    title = course.title(hw_id)
    graded = course.rubrics[hw_id].graded

    if hw is None or hw["status"] == "missing":
        body = [f"<b>{hw_id} · {escape(title)}</b>", "", missing_note]
        if not graded:
            body.append("\nЭта тема в зачёт не входит.")
        return "\n".join(body)

    findings = sorted_findings(hw)
    lines = [
        f"{STATUS_ICON[hw['status']]} <b>{hw_id} · {escape(title)}</b>",
        f"Статус: <b>{STATUS_WORD[hw['status']]}</b>"
        + ("" if graded else " · тема вне зачёта"),
    ]
    if hw["required_total"]:
        need = points_needed(course, hw)
        enough = "✅" if hw["required_passed"] >= need else f"· нужно {need}"
        lines.append(f"Пунктов задания закрыто: {hw['required_passed']} "
                     f"из {hw['required_total']} {enough}")
    if hw.get("notebook") and student.repo:
        url = f"{student.repo}/blob/HEAD/{hw['notebook']}"
        lines.append(f'Файл: <a href="{url}">{escape(hw["notebook"])}</a>')
    if hw.get("summary"):
        lines += ["", escape(hw["summary"])]
    if hw.get("strengths"):
        lines += ["", f"<b>Что хорошо.</b> {escape(hw['strengths'])}"]
    lines += verdict_block(course, hw)
    if not findings:
        lines += ["", "Замечаний нет 🎉"]
    return "\n".join(lines)


WEIGHT = {"critical": 3, "major": 2, "minor": 1}


def why_paragraph(art) -> str:
    """Абзац «Почему это важно» из статьи — самое полезное для рефлексии место."""
    for para in art.body.split("\n\n"):
        if para.startswith("**Почему это важно.**"):
            return para.replace("**Почему это важно.**", "", 1).strip()
    parts = art.body.split("\n\n")
    return parts[1].strip() if len(parts) > 1 else ""


def _prefer_handbook(links: list[tuple[str, str]]) -> list[tuple[str, str]]:
    ext = [(t, u) for t, u in links if u.startswith("http")]
    return sorted(ext, key=lambda x: ("handbook" not in x[1], x[0]))


def best_link(course: Course, art, hw_id: str) -> tuple[str, str] | None:
    """Ссылка «почитать»: Хендбук из статьи, иначе из статей темы, иначе любая."""
    for pool in (art.links, course.reading(art.hw if art.hw != "common" else hw_id)):
        ranked = _prefer_handbook(pool)
        if ranked:
            return ranked[0]
    return None


def plan_text(course: Course, student: Student) -> tuple[str, list[tuple[str, str]]]:
    """«Что подтянуть»: причины незачёта → методология → гигиена одной строкой.

    Раньше сюда попадало «часть ячеек не выполнена» — верно, но для рефлексии
    бесполезно. Теперь советы только по ML/DS-методологии со ссылками на
    Хендбук; дисциплина работы с ноутбуком упоминается одной фразой.
    """
    lines: list[str] = []
    links: list[tuple[str, str]] = []

    gap = failed_topics(course, student)
    if gap:
        lines += ["🚫 <b>Из-за чего не зачтены работы</b>", ""]
        for hw_id, reasons in gap:
            lines.append(f"<b>{hw_id} · {escape(course.title(hw_id))}</b>")
            for r in reasons:
                mark = "📉" if r["kind"] == "points" else SEVERITY_ICON["critical"]
                lines.append(f"   {mark} {escape(r['text'])}")
            lines.append("")

    # Взвешенные коды: только методология. Для общих кодов помним тему,
    # чтобы подобрать ссылку по ней.
    weight: dict[str, int] = {}
    topic_of: dict[str, str] = {}
    hygiene: dict[str, int] = {}
    for hw_id, hw in student.homeworks.items():
        for f in hw.get("findings", []):
            art = course.article(f["code"])
            if art is None:
                continue
            if art.kind == "methodology":
                weight[f["code"]] = weight.get(f["code"], 0) + WEIGHT.get(f["severity"], 1)
                topic_of.setdefault(f["code"], hw_id)
            else:
                hygiene[f["code"]] = hygiene.get(f["code"], 0) + 1

    growth = (student.portrait or {}).get("growth") or []
    if growth:
        # Портрет за курс написан моделью по дайджесту всех работ — он точнее
        # подсчёта по кодам. Ссылки всё равно фильтруем по каталогу.
        lines += ["🎯 <b>Что подтянуть в теории и практике</b>", ""]
        for i, g in enumerate(growth[:5], start=1):
            topic = g.get("topic", "")
            head = f"{i}. <b>{escape(g.get('title', ''))}</b>"
            if topic in course.rubrics:
                head += f" <i>({topic} · {escape(course.title(topic))})</i>"
            lines.append(head)
            if g.get("why"):
                lines.append(escape(g["why"]))
            for l in g.get("links") or []:
                if l.get("url") in course.known_links:
                    lines.append(f'📖 <a href="{l["url"]}">{escape(l.get("title") or "почитать")}</a>')
                    if (l.get("title") or "почитать", l["url"]) not in links:
                        links.append((l.get("title") or "почитать", l["url"]))
            lines.append("")
        top = []
    else:
        top = sorted(weight.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
    if top:
        lines += ["🎯 <b>Что подтянуть в теории и практике</b>", ""]
        for i, (code, _) in enumerate(top, start=1):
            art = course.article(code)
            icon = SEVERITY_ICON.get(art.severity, "•")
            lines.append(f"{i}. {icon} <b>{escape(art.title)}</b>")
            why = why_paragraph(art)
            if why:
                lines.append(to_html(why)[:500])
            link = best_link(course, art, topic_of[code])
            if link:
                lines.append(f'📖 <a href="{link[1]}">{escape(link[0])}</a>')
                if link not in links:
                    links.append(link)
            lines.append("")

    # Незачтённые темы — глава Хендбука по каждой, чтобы было с чего начать.
    chapters = []
    for hw_id, _ in gap:
        ranked = _prefer_handbook(course.reading(hw_id))
        if ranked and ranked[0] not in links and ranked[0] not in chapters:
            chapters.append(ranked[0])
    if chapters:
        lines += ["📚 <b>Пройти заново по незачтённым темам</b>"]
        lines += [f'• <a href="{u}">{escape(t)}</a>' for t, u in chapters[:5]]
        lines.append("")

    if student.portrait and student.portrait.get("next_steps"):
        lines += ["➡️ " + escape(student.portrait["next_steps"]), ""]

    if hygiene:
        titles = [course.article(c).title for c, _ in
                  sorted(hygiene.items(), key=lambda kv: -kv[1])[:3]]
        lines.append(f"<i>И ещё по дисциплине работы с ноутбуком: "
                     f"{escape('; '.join(t.lower() for t in titles))}. "
                     f"На зачёт это влияет только когда критично — такие случаи выше; "
                     f"остальное — в карточках тем.</i>")

    if not lines:
        lines = ["Замечаний по твоим работам нет — подтягивать нечего 🎉", "",
                 "Загляни в «🔎 Справочник ошибок»: там разобраны типовые грабли "
                 "всего потока, полезно и без своих ошибок."]
    return "\n".join(lines).strip(), links[:5]


def strengths_text(course: Course, student: Student) -> str:
    """Сильные стороны за весь курс — по каждой теме, где проверяющий их отметил.

    Временная замена портрету за курс: до него показываем всё, что уже есть,
    а не одну фразу по первой домашке.
    """
    pairs = student.strengths()
    if not pairs and not student.portrait:
        return ("💪 <b>Сильные стороны</b>\n\nПроверяющий пока ничего не отметил — "
                "загляни в разбор тем, там видно, чего не хватило.")
    lines = ["💪 <b>Сильные стороны за курс</b>"]
    if student.portrait:
        lines += [escape(student.portrait["portrait"]), ""]
    if pairs:
        lines += [f"<b>По темам</b> — отмечены в {len(pairs)} из {len(student.submitted())} сданных.", ""]
    for hw_id, text in pairs:
        hw = student.hw(hw_id) or {}
        icon = STATUS_ICON.get(hw.get("status", "missing"), "—")
        lines.append(f"{icon} <b>{hw_id} · {escape(course.title(hw_id))}</b>")
        lines.append(escape(text[:350]))
        lines.append("")
    return "\n".join(lines).strip()


def finding_text(course: Course, hw_id: str, f: dict, seen: int = 0,
                 hw: dict | None = None) -> str:
    icon = SEVERITY_ICON.get(f["severity"], "•")
    parts = [f"{icon} <b>{escape(f['title'])}</b>",
             f"<i>{hw_id} · {escape(course.title(hw_id))}</i>"]
    # Прямо говорим, стоило ли это замечание зачёта: список из тридцати
    # замечаний иначе читается как тридцать причин незачёта.
    if hw is not None and hw.get("status") == "failed":
        parts.append("🚫 <b>Из-за этого тема не зачтена</b>" if is_blocking(f)
                     else "На зачёт это не влияло — но пригодится")
    elif hw is not None:
        parts.append("На зачёт это не влияло")
    if f.get("detail"):
        parts += ["", f"<code>{escape(f['detail'][:400])}</code>"]
    if f.get("cells"):
        parts.append(f"Ячейки: {', '.join(map(str, f['cells'][:12]))}")
    if f.get("comment"):
        parts += ["", escape(f["comment"])]
    article = course.article(f["code"])
    if article:
        parts += ["", "———", "", to_html(article.body)]
    if seen >= 5:
        parts += ["", "<i>Ты изучил эту ошибку вдоль и поперёк. Уважаю.</i>"]
    return "\n".join(parts)


def article_text(course: Course, code: str) -> str | None:
    art = course.article(code)
    if art is None:
        return None
    icon = SEVERITY_ICON.get(art.severity, "•")
    return f"{icon} <b>{escape(art.title)}</b>\n\n" + to_html(art.body)


def external_links(f: dict) -> list[tuple[str, str]]:
    return [(t, u) for t, u in f.get("links", []) if u.startswith("http")]
