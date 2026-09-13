"""Сборка вердикта и отчётов.

`out/findings/<key>.json` — контракт для телеграм-бота: по каждой домашке
статус, список находок с кодами и персональными комментариями, итог по
сертификату. Пояснительные тексты бот берёт из `catalog/` по коду находки,
чтобы правки в каталоге не требовали пересборки отчётов.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field

from . import llm as llm_mod
from . import pipeline
from .catalog import Article
from .catalog import load_all as load_catalog
from .config import Config, load
from .pipeline import StudentWork
from .rubric import Rubric
from .rules import Finding, Severity, run_all
from .rules.engine import HwResult

MISSING = "missing"
PASSED = "passed"
FAILED = "failed"


@dataclass
class HwReport:
    hw: str
    title: str
    status: str
    notebook: str | None = None
    required_passed: int = 0
    required_total: int = 0
    findings: list[dict] = field(default_factory=list)
    strengths: str = ""
    summary: str = ""
    llm_used: bool = False

    @property
    def ratio(self) -> float:
        return self.required_passed / self.required_total if self.required_total else 0.0


@dataclass
class StudentReport:
    key: str
    fio: str
    slug: str | None
    status: str                       # ok | excluded
    reason: str = ""
    homeworks: dict[str, HwReport] = field(default_factory=dict)
    similarity: list[dict] = field(default_factory=list)
    portrait: dict | None = None      # портрет за курс, режим llm student

    graded_ids: frozenset[str] = frozenset()

    @property
    def passed_count(self) -> int:
        """Засчитанные темы, учитываемые в сертификате."""
        return sum(
            1 for hw, h in self.homeworks.items()
            if h.status == PASSED and (not self.graded_ids or hw in self.graded_ids)
        )


def _finding_dict(f: Finding, catalog: dict[str, Article], comment: str = "") -> dict:
    art = catalog.get(f.code)
    return {
        "code": f.code,
        "severity": str(f.severity),
        "title": art.title if art else f.title,
        "detail": f.detail,
        "comment": comment,
        "source": f.source,
        "cells": f.cells,
        "links": art.links if art else [],
        "article": str(art.path.relative_to(art.path.parents[2])) if art else None,
    }


def _apply_llm(res: HwResult, rubric: Rubric, payload: dict,
               catalog: dict[str, Article]) -> tuple[list[dict], str, str]:
    """Учитывает вердикт модели по смысловым пунктам и её находки."""
    extra: list[dict] = []
    by_id = {c["id"]: c for c in payload.get("checks", [])}

    for check in rubric.llm_checks:
        verdict = by_id.get(check.id)
        if verdict is None or verdict.get("passed", True):
            continue
        if check.required:
            res.passed_required -= 1        # статика считала пункт закрытым авансом
        code = f"{rubric.id}.{check.id}"
        art = catalog.get(code)
        extra.append({
            "code": code,
            "severity": art.severity if art else "major",
            "title": art.title if art else check.title,
            "detail": "",
            "comment": verdict.get("comment", ""),
            "source": "llm",
            "cells": [],
            "links": art.links if art else [],
            "article": str(art.path.relative_to(art.path.parents[2])) if art else None,
        })

    seen = {f["code"] for f in extra}
    for item in payload.get("findings", []):
        code = llm_mod.normalize_code(item.get("code", ""), rubric.id, catalog) or "other"
        if code in seen:
            continue
        seen.add(code)
        art = catalog.get(code)
        if art is None:
            # Код `other` — модель нашла что-то за пределами каталога.
            extra.append({
                "code": f"{rubric.id}.other", "severity": "minor",
                "title": "Замечание вне каталога", "detail": "",
                "comment": item.get("comment", ""), "source": "llm",
                "cells": [], "links": [], "article": None,
            })
            continue
        severity, comment = art.severity, item.get("comment", "")
        if art.detector == "rule" and severity == "critical":
            # Коды с детерминированным детектором («падает с ошибкой», «имя не
            # определено», «обучено на тесте») правило уже проверило и не нашло.
            # Модель видит только дописанное студентом и без раздатки ошибается:
            # в перепрогоне v2 такие находки стоили одиннадцати незачётов и одного
            # сертификата, и оба проверенных вручную случая оказались ложными.
            # Оставляем как серьёзное замечание, но зачёт им не закрываем.
            severity = "major"
            comment = "(по мнению проверяющей модели; автоматическое правило этого " \
                      "не подтвердило) " + comment
        extra.append({
            "code": code, "severity": severity, "title": art.title,
            "detail": "", "comment": comment, "source": "llm",
            "cells": [], "links": art.links, "article":
                str(art.path.relative_to(art.path.parents[2])),
        })
    return extra, payload.get("strengths", ""), payload.get("summary", "")


def build_student(work: StudentWork, rubrics: dict[str, Rubric],
                  catalog: dict[str, Article], llm_results: dict[str, dict],
                  cfg: Config) -> StudentReport:
    rep = StudentReport(key=work.student.key, fio=work.student.fio,
                        slug=work.student.slug, status="ok",
                        graded_ids=frozenset(r.id for r in rubrics.values() if r.graded))
    threshold = cfg.verdict["hw_pass_ratio"]

    for hw_id, rubric in sorted(rubrics.items()):
        sub = work.submissions.get(hw_id)
        if sub is None:
            rep.homeworks[hw_id] = HwReport(hw=hw_id, title=rubric.title, status=MISSING)
            continue

        res = run_all(sub.notebook, rubric)
        findings = [_finding_dict(f, catalog) for f in res.findings]
        strengths = summary = ""
        llm_used = False

        payload = llm_results.get(f"{work.student.key}|{hw_id}")
        if payload:
            llm_used = True
            extra, strengths, summary = _apply_llm(res, rubric, payload, catalog)
            known = {f["code"] for f in findings}
            findings.extend(f for f in extra if f["code"] not in known)

        has_critical = any(f["severity"] == str(Severity.CRITICAL) for f in findings)
        # Нет обязательных пунктов — заваливать не за что (так у hw01 и hw07,
        # где раздаточный ноутбук был уже решён).
        ratio = res.passed_required / res.total_required if res.total_required else 1.0
        status = PASSED if (not has_critical and ratio >= threshold) else FAILED

        order = {"critical": 0, "major": 1, "minor": 2}
        findings.sort(key=lambda f: (order.get(f["severity"], 3), f["code"]))

        rep.homeworks[hw_id] = HwReport(
            hw=hw_id, title=rubric.title, status=status, notebook=sub.notebook.rel,
            required_passed=max(res.passed_required, 0), required_total=res.total_required,
            findings=findings, strengths=strengths, summary=summary, llm_used=llm_used,
        )
    return rep


def load_similarity(cfg: Config) -> dict[str, list[dict]]:
    path = cfg.paths.out / "similarity.csv"
    if not path.exists():
        return {}
    out: dict[str, list[dict]] = {}
    with path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row["тип"] != "exact":
                continue
            for me, other in ((row["студент A"], row["студент B"]),
                              (row["студент B"], row["студент A"])):
                out.setdefault(me, []).append({
                    "тема": row["тема"], "с кем": other,
                    "кто раньше": row["кто раньше"],
                })
    return out


def required_passed_for(ratio: float, total_hw: int) -> int:
    """Сколько домашек нужно при заданной доле.

    Округляем вниз — в пользу студентов. При пороге 66% от 12 тем выходит 7.92,
    и требовать восемь было бы натяжкой: разница между «двумя третями» и «ровно
    восемью из двенадцати» — это десять живых человек.

    Вынесено отдельной чистой функцией, потому что ту же цифру показывает бот.
    """
    import math

    return max(1, math.floor(ratio * total_hw))


def points_needed_for(ratio: float, total: int) -> int:
    """Сколько пунктов задания нужно закрыть при данной доле.

    Проверка сравнивает долю с порогом; это та же граница в пунктах. Поправка
    1e-9 — страховка от двоичного округления на ровной границе (0.28 × 25 даёт
    7.000000000000001). Ту же цифру показывает бот — формула одна.
    """
    import math

    return math.ceil(ratio * total - 1e-9) if total else 0


def required_passed(total_hw: int, cfg: Config) -> int:
    return required_passed_for(cfg.verdict["certificate_ratio"], total_hw)


def certificate(rep: StudentReport, total_hw: int, cfg: Config) -> bool:
    return rep.passed_count >= required_passed(total_hw, cfg)


# --- вывод ------------------------------------------------------------------------

def to_json(rep: StudentReport, total_hw: int, cfg: Config) -> dict:
    return {
        "key": rep.key,
        "fio": rep.fio,
        "repo": f"https://github.com/{rep.slug}" if rep.slug else None,
        "status": rep.status,
        "reason": rep.reason,
        "certificate": certificate(rep, total_hw, cfg) if rep.status == "ok" else False,
        "passed_hw": rep.passed_count,
        "total_hw": total_hw,
        "homeworks": {
            hw: {
                "title": h.title, "status": h.status, "notebook": h.notebook,
                "required_passed": h.required_passed, "required_total": h.required_total,
                "reviewed_by_model": h.llm_used,
                "strengths": h.strengths, "summary": h.summary,
                "findings": h.findings,
            }
            for hw, h in rep.homeworks.items()
        },
        "similarity": rep.similarity,
        "portrait": rep.portrait,
    }


_ICON = {PASSED: "✅", FAILED: "❌", MISSING: "—"}
_SEV = {"critical": "🔴", "major": "🟠", "minor": "🔵"}


def to_markdown(rep: StudentReport, total_hw: int, cfg: Config) -> str:
    ok = certificate(rep, total_hw, cfg)
    lines = [f"# {rep.fio}", ""]
    if rep.status != "ok":
        lines += [f"**Статус:** {rep.reason}", "", "Работа не проверялась."]
        return "\n".join(lines) + "\n"

    lines += [
        f"Репозиторий: {rep.slug}",
        "",
        f"**Засчитано домашек: {rep.passed_count} из {total_hw}.** "
        + ("Сертификат: да ✅" if ok else "Сертификат: нет ❌"),
        "",
    ]
    if rep.portrait:
        # Портрет за курс — то же, что видит студент в боте: чтобы преподаватель
        # читал ровно тот текст, который получил человек.
        lines += ["## Портрет за курс", "", rep.portrait["portrait"], ""]
        if rep.portrait.get("growth"):
            lines += ["**Что подтянуть:**", ""]
            for g in rep.portrait["growth"]:
                links = ", ".join(f"[{l['title']}]({l['url']})" for l in g.get("links") or [])
                topic = f" ({g['topic']})" if g.get("topic") else ""
                lines.append(f"* **{g.get('title', '')}**{topic} — {g.get('why', '')}"
                             + (f" Почитать: {links}" if links else ""))
            lines.append("")
        if rep.portrait.get("next_steps"):
            lines += [f"**Следующий шаг.** {rep.portrait['next_steps']}", ""]
    lines += [
        "| | Домашка | Пункты | Замечаний |",
        "|---|---|---|---|",
    ]
    for hw, h in rep.homeworks.items():
        pts = f"{h.required_passed}/{h.required_total}" if h.status != MISSING else "—"
        cnt = len(h.findings) if h.status != MISSING else "—"
        lines.append(f"| {_ICON[h.status]} | {hw} {h.title} | {pts} | {cnt} |")

    for hw, h in rep.homeworks.items():
        if h.status == MISSING:
            continue
        lines += ["", f"## {hw} — {h.title}", "", f"Файл: `{h.notebook}`"]
        if h.summary:
            lines += ["", h.summary]
        if h.strengths:
            lines += ["", f"**Что хорошо.** {h.strengths}"]
        if not h.findings:
            lines += ["", "Замечаний нет."]
        for f in h.findings:
            lines += ["", f"### {_SEV.get(f['severity'], '')} {f['title']}"]
            if f["detail"]:
                lines.append(f"`{f['detail']}`")
            if f["comment"]:
                lines.append(f["comment"])
            # Локальные пути к заданиям студенту не откроются — только внешние ссылки.
            external = [(t, u) for t, u in f["links"] if u.startswith("http")]
            if external:
                lines.append("Почитать: " + ", ".join(f"[{t}]({u})" for t, u in external))

    missing = [hw for hw, h in rep.homeworks.items() if h.status == MISSING]
    if missing:
        lines += ["", "## Не найдено работ по темам", "",
                  ", ".join(missing)]
    if rep.similarity:
        lines += ["", "## Совпадения с чужими работами", ""]
        for s in rep.similarity:
            lines.append(f"- {s['тема']}: полное совпадение с «{s['с кем']}», "
                         f"раньше сдал: {s['кто раньше']}")
    return "\n".join(lines) + "\n"


def build_all(cfg: Config | None = None) -> list[StudentReport]:
    from .rubric import load_all as load_rubrics

    cfg = cfg or load()
    rubrics = load_rubrics(cfg)
    catalog = load_catalog(cfg)
    llm_results = llm_mod.load_results(cfg, "grading")
    portraits = llm_mod.load_results(cfg, "student")
    allowed = llm_mod.allowed_urls(catalog)
    sim = load_similarity(cfg)
    total_hw = sum(1 for r in rubrics.values() if r.graded)

    reports: list[StudentReport] = []
    for st in pipeline.load_roster(cfg):
        if not st.ok:
            rep = StudentReport(key=st.key, fio=st.fio, slug=st.slug,
                                status="excluded", reason=st.reason,
                                graded_ids=frozenset(r.id for r in rubrics.values() if r.graded))
        else:
            work = pipeline.read_student(st, cfg, rubrics)
            rep = build_student(work, rubrics, catalog, llm_results, cfg)
            rep.similarity = sim.get(st.fio, [])
            if st.key in portraits:
                rep.portrait = llm_mod.sanitize_student(portraits[st.key], rubrics, catalog, allowed)
        reports.append(rep)

    _write(reports, total_hw, cfg)
    return reports


def _typical_errors(reports: list[StudentReport], cfg: Config) -> str:
    """Свод типовых ошибок по потоку — что разбирать на занятии в первую очередь."""
    from collections import Counter

    from .rubric import load_all as load_rubrics

    rubrics = load_rubrics(cfg)
    catalog = load_catalog(cfg)
    submitted: Counter = Counter()
    per_hw: dict[str, Counter] = {}
    for rep in reports:
        for hw, h in rep.homeworks.items():
            if h.status == MISSING:
                continue
            submitted[hw] += 1
            c = per_hw.setdefault(hw, Counter())
            for f in h.findings:
                c[f["code"]] += 1

    lines = ["# Типовые ошибки потока", "",
             "Сводка по реально проверенным работам. Доля считается от числа сдач "
             "по этой теме.", ""]
    for hw in sorted(rubrics):
        n = submitted.get(hw, 0)
        if not n:
            continue
        lines += [f"## {hw} — {rubrics[hw].title}", "",
                  f"Сдач: {n}.", "",
                  "| Доля | Ошибка | Код |", "|---|---|---|"]
        for code, cnt in per_hw[hw].most_common(12):
            art = catalog.get(code)
            if art:
                title = art.title
            elif code.endswith(".other"):
                title = "Замечание вне каталога (разбор модели)"
            else:
                title = code
            lines.append(f"| {cnt / n:.0%} ({cnt}) | {title} | `{code}` |")
        lines.append("")
    return "\n".join(lines) + "\n"


def _write_certificates(reports: list[StudentReport], total_hw: int, cfg: Config) -> None:
    """Список прошедших курс — для вручения.

    Собирается вместе с отчётами, а не руками: цифра меняется после каждой
    перепроверки, и отдельный файл успел бы устареть.
    """
    need = required_passed(total_hw, cfg)
    passed = sorted((r for r in reports if r.status == "ok" and certificate(r, total_hw, cfg)),
                    key=lambda r: r.fio.casefold())

    lines = [
        "# Прошли курс ML FAMCS", "",
        f"Курс закрыли **{len(passed)} человек** из {sum(1 for r in reports if r.status == 'ok')} "
        f"проверенных.", "",
        f"Условие: не меньше {need} засчитанных домашек из {total_hw}. Домашка "
        f"засчитана, если в ней нет критичных замечаний и закрыто не меньше "
        f"{cfg.verdict['hw_pass_ratio']:.0%} обязательных пунктов задания.", "",
        "| № | ФИО | Засчитано |", "|---:|---|---:|",
    ]
    lines += [f"| {i} | {r.fio} | {r.passed_count} из {total_hw} |"
              for i, r in enumerate(passed, start=1)]

    by_count: dict[int, int] = {}
    for r in passed:
        by_count[r.passed_count] = by_count.get(r.passed_count, 0) + 1
    lines += ["", "## Сколько тем закрыли", "", "| Тем | Человек |", "|---:|---:|"]
    lines += [f"| {n} | {by_count[n]} |" for n in sorted(by_count, reverse=True)]
    (cfg.paths.out / "certificates.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    with (cfg.paths.out / "certificates.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["№", "ФИО", "засчитано", "из", "репозиторий"])
        for i, r in enumerate(passed, start=1):
            w.writerow([i, r.fio, r.passed_count, total_hw,
                        f"https://github.com/{r.slug}" if r.slug else ""])


def _write(reports: list[StudentReport], total_hw: int, cfg: Config) -> None:
    fdir, rdir = cfg.paths.findings, cfg.paths.reports
    fdir.mkdir(parents=True, exist_ok=True)
    rdir.mkdir(parents=True, exist_ok=True)

    for rep in reports:
        (fdir / f"{rep.key}.json").write_text(
            json.dumps(to_json(rep, total_hw, cfg), ensure_ascii=False, indent=2),
            encoding="utf-8")
        (rdir / f"{rep.key}.md").write_text(
            to_markdown(rep, total_hw, cfg), encoding="utf-8")

    (cfg.paths.out / "typical_errors.md").write_text(
        _typical_errors(reports, cfg), encoding="utf-8")

    _write_certificates(reports, total_hw, cfg)

    hw_ids = sorted({hw for r in reports for hw in r.homeworks})
    with (cfg.paths.out / "summary.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ФИО", "репозиторий", "статус", "сертификат", "засчитано"]
                   + hw_ids + ["совпадения"])
        for rep in sorted(reports, key=lambda r: (-r.passed_count, r.fio)):
            if rep.status != "ok":
                w.writerow([rep.fio, rep.slug or "", "исключён", "нет", 0]
                           + [""] * len(hw_ids) + [""])
                continue
            cells = []
            for hw in hw_ids:
                h = rep.homeworks.get(hw)
                cells.append({PASSED: "зачтено", FAILED: "не зачтено",
                              MISSING: "нет"}[h.status] if h else "нет")
            w.writerow([rep.fio, rep.slug, "проверен",
                        "да" if certificate(rep, total_hw, cfg) else "нет",
                        rep.passed_count] + cells
                       + [len(rep.similarity) or ""])
