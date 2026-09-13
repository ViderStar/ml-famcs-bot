"""Comparing two report builds: what changed from run to run.

Needed after rerunning the reviews: how many certificates there were and are,
whose passed-topic count moved, which per-topic verdicts flipped and why.
The "passed → failed" flips are the main thing a teacher must look at by eye:
behind each is a real person who may already have seen the old verdict.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Flip:
    key: str
    fio: str
    hw: str
    before: str
    after: str
    reason: str


@dataclass
class Diff:
    students: int = 0
    cert_before: int = 0
    cert_after: int = 0
    cert_gained: list[str] = field(default_factory=list)
    cert_lost: list[str] = field(default_factory=list)
    passed_delta: dict[int, int] = field(default_factory=dict)   # change → people
    flips: list[Flip] = field(default_factory=list)
    hw_pass_before: dict[str, int] = field(default_factory=dict)
    hw_pass_after: dict[str, int] = field(default_factory=dict)


def _load(dir_: Path) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(dir_.glob("*.json"))}


def _why(hw: dict) -> str:
    crit = [f["title"] for f in hw.get("findings", []) if f["severity"] == "critical"]
    parts = []
    if hw.get("required_total"):
        parts.append(f"пунктов {hw['required_passed']}/{hw['required_total']}")
    if crit:
        parts.append("критично: " + "; ".join(crit[:2]))
    return ", ".join(parts) or "—"


def compare(before_dir: Path, after_dir: Path) -> Diff:
    before, after = _load(before_dir), _load(after_dir)
    d = Diff()
    for key, b in before.items():
        a = after.get(key)
        if a is None or b.get("status") != "ok" or a.get("status") != "ok":
            continue
        d.students += 1
        d.cert_before += bool(b.get("certificate"))
        d.cert_after += bool(a.get("certificate"))
        if a.get("certificate") and not b.get("certificate"):
            d.cert_gained.append(a["fio"])
        if b.get("certificate") and not a.get("certificate"):
            d.cert_lost.append(a["fio"])
        delta = a.get("passed_hw", 0) - b.get("passed_hw", 0)
        d.passed_delta[delta] = d.passed_delta.get(delta, 0) + 1
        for hw_id, hb in b["homeworks"].items():
            ha = a["homeworks"].get(hw_id)
            if ha is None:
                continue
            d.hw_pass_before[hw_id] = d.hw_pass_before.get(hw_id, 0) + (hb["status"] == "passed")
            d.hw_pass_after[hw_id] = d.hw_pass_after.get(hw_id, 0) + (ha["status"] == "passed")
            if hb["status"] != ha["status"]:
                d.flips.append(Flip(key, a["fio"], hw_id, hb["status"], ha["status"], _why(ha)))
    return d


_WORD = {"passed": "зачтено", "failed": "не зачтено", "missing": "не сдано"}


def render(d: Diff, before_label: str, after_label: str) -> str:
    lines = [f"# Сравнение сборок: {before_label} → {after_label}", "",
             f"Студентов проверено: {d.students}.", "",
             "## Сертификаты", "",
             f"| | {before_label} | {after_label} |", "|---|---|---|",
             f"| сертификатов | {d.cert_before} | {d.cert_after} |", ""]
    if d.cert_gained:
        lines += [f"**Получили ({len(d.cert_gained)}):** " + ", ".join(sorted(d.cert_gained)), ""]
    if d.cert_lost:
        lines += [f"**Потеряли ({len(d.cert_lost)}):** " + ", ".join(sorted(d.cert_lost)), ""]
    lines += ["## Изменение числа зачтённых тем", "", "| изменение | людей |", "|---|---|"]
    for delta in sorted(d.passed_delta):
        lines.append(f"| {delta:+d} | {d.passed_delta[delta]} |")
    lines += ["", "## Зачтено по темам", "", f"| тема | {before_label} | {after_label} |", "|---|---|---|"]
    for hw_id in sorted(d.hw_pass_before):
        lines.append(f"| {hw_id} | {d.hw_pass_before[hw_id]} | {d.hw_pass_after.get(hw_id, 0)} |")
    down = [f for f in d.flips if f.before == "passed"]
    up = [f for f in d.flips if f.after == "passed"]
    other = [f for f in d.flips if f not in down and f not in up]
    lines += ["", f"## Вердикты перевернулись: {len(d.flips)}", ""]
    for title, group in (("Было зачтено — стало не зачтено (смотреть обязательно)", down),
                         ("Стало зачтено", up), ("Прочее (не сдано ↔ не зачтено)", other)):
        if not group:
            continue
        lines += [f"### {title}: {len(group)}", "", "| студент | тема | было | стало | почему |",
                  "|---|---|---|---|---|"]
        for f in sorted(group, key=lambda f: (f.hw, f.fio)):
            lines.append(f"| {f.fio} | {f.hw} | {_WORD[f.before]} | {_WORD[f.after]} | {f.reason} |")
        lines.append("")
    return "\n".join(lines) + "\n"
