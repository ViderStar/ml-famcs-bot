"""Wiring the steps: who takes part, which notebooks they have, what belongs to which topic."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import classify, nbio
from .config import Config, load
from .nbio import Notebook
from .roster import Student
from .rubric import Rubric, load_all


@dataclass
class StudentWork:
    student: Student
    submissions: dict[str, classify.Submission] = field(default_factory=dict)
    unmatched: list[Notebook] = field(default_factory=list)
    broken: list[Notebook] = field(default_factory=list)   # unparseable or empty
    notebook_count: int = 0

    @property
    def repo_dir_empty(self) -> bool:
        return self.notebook_count == 0


def load_roster(cfg: Config | None = None) -> list[Student]:
    cfg = cfg or load()
    data = json.loads((cfg.paths.out / "roster.json").read_text(encoding="utf-8"))
    return [Student(**d) for d in data]


def read_student(st: Student, cfg: Config, rubrics: dict[str, Rubric]) -> StudentWork:
    repo = cfg.paths.raw / st.key
    work = StudentWork(student=st)
    if not repo.exists():
        return work
    all_nbs = [nbio.load(p, rel=str(p.relative_to(repo))) for p in nbio.iter_notebooks(repo)]
    work.notebook_count = len(all_nbs)
    work.broken = [n for n in all_nbs if not n.ok]
    good = [n for n in all_nbs if n.ok]
    work.submissions, work.unmatched = classify.pick_submissions(good, rubrics)
    return work


def iter_work(cfg: Config | None = None):
    cfg = cfg or load()
    rubrics = load_all()
    for st in load_roster(cfg):
        if not st.ok:
            continue
        yield read_student(st, cfg, rubrics)


def save_submissions(works: list[StudentWork], cfg: Config | None = None) -> Path:
    cfg = cfg or load()
    out = {}
    for w in works:
        out[w.student.key] = {
            "fio": w.student.fio,
            "slug": w.student.slug,
            "notebook_count": w.notebook_count,
            "submissions": {
                hw: {
                    "notebook": s.notebook.rel,
                    "score": s.score,
                    "strong_hits": s.strong_hits,
                    "alternatives": s.alternatives or [],
                    "by_folder": s.by_folder,
                }
                for hw, s in sorted(w.submissions.items())
            },
            "unmatched": [n.rel for n in w.unmatched],
            "broken": [{"notebook": n.rel, "error": n.error} for n in w.broken],
        }
    path = cfg.paths.out / "submissions.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
