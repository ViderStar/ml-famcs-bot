"""Course data in memory: student reports, the error catalog, materials.

About six megabytes in total, so it is read whole at startup. An admin command
rereads it on a running bot — files on disk can change after another grading
pass.
"""

from __future__ import annotations

import csv
import json
import statistics
from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from mlcheck.catalog import Article
from mlcheck.catalog import load_dir as load_catalog_dir
from mlcheck.rubric import Rubric
from mlcheck.rubric import load_dir as load_rubrics_dir

from .config import Config

# Lecture slides and notes by topic. File names in materials/ are inconsistent,
# so the mapping is spelled out rather than guessed.
MATERIALS: dict[str, tuple[tuple[str, str], ...]] = {
    "hw03": (("Слайды лекции по KNN", "KNN_final.pptx"),),
    "hw04": (("Лекция: линейная регрессия", "Лекция 4_ Линейная_регрессия.pdf"),),
    "hw07": (("Лекция: деревья решений", "Машинное_обучение_дерево_решений_лекция.pdf"),),
    "hw08": (("Слайды лекции по SVM", "svm_slides.pdf"),),
    "hw09": (("Лекция: ансамбли", "lecture_9_ansambles.pdf"),),
    "hw10": (("Практика: градиентный бустинг", "GB_practice.pdf"),
             ("Лекция: ансамбли и бустинг", "lecture_9_10_ansambles.pdf")),
    "hw11": (("Слайды: гиперпараметры и интерпретируемость", "lecture_hp_interp_slides.pdf"),
             ("Конспект: гиперпараметры и интерпретируемость", "lecture_hp_interp_notes.pdf")),
    "hw12": (("Слайды: DBSCAN", "clustering2_slides.pdf"),
             ("Конспект: DBSCAN", "clustering2_notes.pdf"),
             ("Лекция: кластеризация", "Лекция_Кластеризация.pdf")),
    "hw13": (("Слайды: снижение размерности", "pca_slides.pdf"),
             ("Конспект: снижение размерности", "pca_notes.pdf")),
}

SEVERITY_ORDER = {"critical": 0, "major": 1, "minor": 2}
SEVERITY_ICON = {"critical": "🔴", "major": "🟠", "minor": "🔵"}
STATUS_ICON = {"passed": "✅", "failed": "❌", "missing": "—"}


@dataclass
class Student:
    """One student's report, as it lies in out/findings/<key>.json."""

    raw: dict

    @property
    def key(self) -> str:
        return self.raw["key"]

    @property
    def fio(self) -> str:
        return self.raw["fio"]

    @property
    def repo(self) -> str | None:
        return self.raw.get("repo")

    @property
    def ok(self) -> bool:
        return self.raw.get("status") == "ok"

    @property
    def reason(self) -> str:
        return self.raw.get("reason", "")

    @property
    def certificate(self) -> bool:
        return bool(self.raw.get("certificate"))

    @property
    def passed(self) -> int:
        return int(self.raw.get("passed_hw", 0))

    @property
    def total(self) -> int:
        return int(self.raw.get("total_hw", 12))

    @property
    def homeworks(self) -> dict[str, dict]:
        return self.raw.get("homeworks", {})

    @property
    def similarity(self) -> list[dict]:
        return self.raw.get("similarity", [])

    def hw(self, hw_id: str) -> dict | None:
        return self.homeworks.get(hw_id)

    def submitted(self) -> list[str]:
        return [k for k, v in self.homeworks.items() if v["status"] != "missing"]

    def findings(self) -> list[dict]:
        return [f for h in self.homeworks.values() for f in h.get("findings", [])]

    def severity_counts(self) -> Counter:
        return Counter(f["severity"] for f in self.findings())

    @property
    def portrait(self) -> dict | None:
        """Course portrait from llm student mode; None until that pass is done."""
        p = self.raw.get("portrait")
        return p if isinstance(p, dict) and p.get("portrait") else None

    def strengths(self) -> list[tuple[str, str]]:
        """Pairs of (topic, what went well) — non-empty ones only."""
        return [(hw, h["strengths"]) for hw, h in sorted(self.homeworks.items())
                if h.get("strengths")]


@dataclass
class Course:
    cfg: Config
    season: str = "s2"
    students: dict[str, Student] = field(default_factory=dict)
    catalog: dict[str, Article] = field(default_factory=dict)
    rubrics: dict[str, Rubric] = field(default_factory=dict)
    tasks: dict[str, str] = field(default_factory=dict)
    attention: str = ""

    # --- loading ------------------------------------------------------------------

    @classmethod
    def load(cls, cfg: Config, findings_dir: Path | None = None,
             season: str = "s2") -> "Course":
        """The course from disk.

        `findings_dir` exists for the fictional students: the demo course loads
        from its own directory instead of being mixed into the real one.
        Otherwise demo would seep into the median, the percentile and the
        certificate count, with nothing to notice it by — the numbers would just
        quietly shift.
        """
        students = {}
        for p in sorted((findings_dir or cfg.findings_dir).glob("*.json")):
            st = Student(json.loads(p.read_text(encoding="utf-8")))
            students[st.key] = st

        tasks = {}
        tasks_dir = cfg.checker_dir / "rubrics" / "tasks"
        if tasks_dir.exists():
            for p in sorted(tasks_dir.glob("hw*.md")):
                tasks[p.stem] = p.read_text(encoding="utf-8")

        attention_path = cfg.out_dir / "attention.md"
        return cls(
            season=season,
            cfg=cfg,
            students=students,
            catalog=dict(load_catalog_dir(cfg.checker_dir / "catalog")),
            rubrics=dict(load_rubrics_dir(cfg.checker_dir / "rubrics")),
            tasks=tasks,
            attention=attention_path.read_text(encoding="utf-8") if attention_path.exists() else "",
        )

    def refresh(self) -> None:
        """Rereads data from disk into this same object.

        Handlers hold Course by reference, so the object cannot be swapped —
        the contents are refreshed in place and cached aggregates are dropped.
        """
        load_catalog_dir.cache_clear()
        load_rubrics_dir.cache_clear()
        fresh = Course.load(self.cfg)
        self.students = fresh.students
        self.catalog = fresh.catalog
        self.rubrics = fresh.rubrics
        self.tasks = fresh.tasks
        self.attention = fresh.attention
        for name in ("active", "excluded", "passed_distribution", "certificates",
                     "hw_stats", "median_passed", "certificate_ratio", "required_passed",
                     "hw_pass_ratio", "usernames", "known_links", "expected_usernames",
                     "awards"):
            self.__dict__.pop(name, None)

    # --- reference data ---------------------------------------------------------

    @property
    def graded_ids(self) -> list[str]:
        return [r.id for r in self.rubrics.values() if r.graded]

    @property
    def total_graded(self) -> int:
        return len(self.graded_ids)

    @cached_property
    def certificate_ratio(self) -> float:
        """The threshold from the grader config — so bot and reports say the same thing."""
        import tomllib

        path = self.cfg.checker_dir / "config.toml"
        try:
            conf = tomllib.loads(path.read_text(encoding="utf-8"))
            return float(conf["verdict"]["certificate_ratio"])
        except Exception:
            return 0.66

    @cached_property
    def hw_pass_ratio(self) -> float:
        """Share of required items at which a homework passes."""
        import tomllib

        path = self.cfg.checker_dir / "config.toml"
        try:
            conf = tomllib.loads(path.read_text(encoding="utf-8"))
            return float(conf["verdict"]["hw_pass_ratio"])
        except Exception:
            return 0.70

    @cached_property
    def required_passed(self) -> int:
        """How many homework a certificate needs, by the same formula as checker."""
        from mlcheck.report import required_passed_for

        return required_passed_for(self.certificate_ratio, self.total_graded)

    def title(self, hw_id: str) -> str:
        r = self.rubrics.get(hw_id)
        return r.title if r else hw_id

    def article(self, code: str) -> Article | None:
        return self.catalog.get(code)

    def materials(self, hw_id: str) -> list[tuple[str, Path]]:
        out = []
        for label, name in MATERIALS.get(hw_id, ()):
            path = self.cfg.materials_dir / name
            if path.exists():
                out.append((label, path))
        return out

    def task_text(self, hw_id: str) -> str | None:
        return self.tasks.get(hw_id)

    def reading(self, hw_id: str) -> list[tuple[str, str]]:
        """External links for a topic — the union of links from its catalog articles."""
        seen: dict[str, str] = {}
        for code, art in self.catalog.items():
            if not code.startswith(f"{hw_id}."):
                continue
            for title, url in art.links:
                if url.startswith("http") and url not in seen:
                    seen[url] = title
        return [(t, u) for u, t in seen.items()]

    # --- stream aggregates ------------------------------------------------------

    @cached_property
    def awards(self) -> dict:
        """Award registry: whose certificate and whose ceremony photo.

        Built by `mlcheck awards`: names are read from the PDFs themselves,
        because the files are called `sertificate_original-N.pdf` and sending a
        student someone else's certificate is not an option — it carries a name.
        """
        from mlcheck.awards import load_awards

        return load_awards(self.cfg.out_dir / "awards.csv")

    def certificate_file(self, key: str) -> Path | None:
        a = self.awards.get(key)
        if not a or not a.certificate:
            return None
        p = self.cfg.data_root / a.certificate
        return p if p.exists() else None

    def ceremony_photo(self, key: str) -> Path | None:
        a = self.awards.get(key)
        if not a or not a.photo:
            return None
        p = self.cfg.data_root / a.photo
        return p if p.exists() else None

    @cached_property
    def known_links(self) -> set[str]:
        """All external catalog links — the third filter for links from a portrait."""
        from mlcheck.llm import allowed_urls

        return allowed_urls(self.catalog)

    @cached_property
    def expected_usernames(self) -> dict[str, str]:
        """Student key → the username recorded for that record by the registration form.

        Verified links only: behind such a record stands a live account, and it
        cannot be tied to another telegram without the teacher knowing.
        """
        from mlcheck.telegram import read_map

        return {lk.key: lk.username
                for lk in read_map(self.cfg.out_dir / "telegram_map.csv")
                if lk.usable and lk.key in self.students}

    def expected_username(self, key: str) -> str | None:
        return self.expected_usernames.get(key)

    @cached_property
    def usernames(self) -> dict[str, str]:
        """Lowercase username → student key.

        Stitched from the course registration form (`mlcheck telegram`). Only
        links the module judged reliable and whose username exists: the rest go
        through the usual binding by name and repository link.
        """
        from mlcheck.telegram import read_map

        index: dict[str, str] = {}
        for link in read_map(self.cfg.out_dir / "telegram_map.csv"):
            if link.usable and link.key in self.students:
                index[link.username.lower()] = link.key
        return index

    @cached_property
    def active(self) -> list[Student]:
        return [s for s in self.students.values() if s.ok]

    @cached_property
    def excluded(self) -> list[Student]:
        return [s for s in self.students.values() if not s.ok]

    @cached_property
    def passed_distribution(self) -> Counter:
        return Counter(s.passed for s in self.active)

    @cached_property
    def certificates(self) -> int:
        return sum(1 for s in self.active if s.certificate)

    def percentile(self, student: Student) -> int:
        """Share of the stream that has closed no more topics than this student."""
        if not self.active:
            return 0
        below = sum(1 for s in self.active if s.passed <= student.passed)
        return round(100 * below / len(self.active))

    @cached_property
    def hw_stats(self) -> dict[str, dict]:
        """Per topic: submissions, passes, top findings."""
        stats: dict[str, dict] = {}
        for hw_id in sorted(self.rubrics):
            subs = passed = 0
            codes: Counter = Counter()
            for s in self.active:
                h = s.hw(hw_id)
                if not h or h["status"] == "missing":
                    continue
                subs += 1
                passed += int(h["status"] == "passed")
                codes.update(f["code"] for f in h.get("findings", []))
            stats[hw_id] = {"submitted": subs, "passed": passed, "codes": codes}
        return stats

    @cached_property
    def median_passed(self) -> float:
        return statistics.median([s.passed for s in self.active]) if self.active else 0.0

    def excluded_rows(self) -> list[dict]:
        path = self.cfg.out_dir / "excluded.csv"
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
