"""Данные курса в памяти: отчёты студентов, каталог ошибок, материалы.

Всего около шести мегабайт, поэтому читаем целиком при старте. Перечитать
на живом боте можно командой администратора — файлы на диске могут обновиться
после повторного прогона проверки.
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

# Слайды и конспекты лекций по темам. Имена файлов в materials/ разнородные,
# поэтому сопоставление задано явно, а не угадывается.
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
    """Отчёт одного студента, как он лежит в out/findings/<key>.json."""

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
        """Портрет за курс из режима llm student; None, пока прогон не сделан."""
        p = self.raw.get("portrait")
        return p if isinstance(p, dict) and p.get("portrait") else None

    def strengths(self) -> list[tuple[str, str]]:
        """Пары (тема, что получилось хорошо) — только непустые."""
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

    # --- загрузка ---------------------------------------------------------------

    @classmethod
    def load(cls, cfg: Config, findings_dir: Path | None = None,
             season: str = "s2") -> "Course":
        """Курс с диска.

        `findings_dir` нужен для вымышленных студентов: демо-курс грузится из
        отдельного каталога, а не подмешивается к настоящим. Иначе демо поехало
        бы в медиану, перцентиль и число сертификатов, и заметить это было бы
        нечем — цифры просто тихо съехали бы.
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
        """Перечитывает данные с диска в этот же объект.

        Обработчики получают Course по ссылке, поэтому подменять объект нельзя —
        обновляем содержимое на месте и сбрасываем закэшированные агрегаты.
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

    # --- справочники ------------------------------------------------------------

    @property
    def graded_ids(self) -> list[str]:
        return [r.id for r in self.rubrics.values() if r.graded]

    @property
    def total_graded(self) -> int:
        return len(self.graded_ids)

    @cached_property
    def certificate_ratio(self) -> float:
        """Порог из конфига проверки — чтобы бот и отчёты говорили одно и то же."""
        import tomllib

        path = self.cfg.checker_dir / "config.toml"
        try:
            conf = tomllib.loads(path.read_text(encoding="utf-8"))
            return float(conf["verdict"]["certificate_ratio"])
        except Exception:
            return 0.66

    @cached_property
    def hw_pass_ratio(self) -> float:
        """Доля обязательных пунктов, при которой домашка зачтена."""
        import tomllib

        path = self.cfg.checker_dir / "config.toml"
        try:
            conf = tomllib.loads(path.read_text(encoding="utf-8"))
            return float(conf["verdict"]["hw_pass_ratio"])
        except Exception:
            return 0.70

    @cached_property
    def required_passed(self) -> int:
        """Сколько домашек нужно для сертификата, той же формулой, что в checker."""
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
        """Внешние ссылки по теме — объединение ссылок из её статей каталога."""
        seen: dict[str, str] = {}
        for code, art in self.catalog.items():
            if not code.startswith(f"{hw_id}."):
                continue
            for title, url in art.links:
                if url.startswith("http") and url not in seen:
                    seen[url] = title
        return [(t, u) for u, t in seen.items()]

    # --- агрегаты по потоку -----------------------------------------------------

    @cached_property
    def awards(self) -> dict:
        """Реестр наград: чей сертификат и чья фотография с вручения.

        Собирается командой `mlcheck awards`: имена читаются из самих PDF, потому
        что файлы называются `sertificate_original-N.pdf`, а отправить студенту
        чужой сертификат нельзя — там его ФИО.
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
        """Все внешние ссылки каталога — третий фильтр для ссылок из портрета."""
        from mlcheck.llm import allowed_urls

        return allowed_urls(self.catalog)

    @cached_property
    def expected_usernames(self) -> dict[str, str]:
        """Ключ студента → username, закреплённый за записью формой регистрации.

        Только проверенные связки: за такой записью стоит живой аккаунт, и
        привязать её к другому телеграму без ведома преподавателя нельзя.
        """
        from mlcheck.telegram import read_map

        return {lk.key: lk.username
                for lk in read_map(self.cfg.out_dir / "telegram_map.csv")
                if lk.usable and lk.key in self.students}

    def expected_username(self, key: str) -> str | None:
        return self.expected_usernames.get(key)

    @cached_property
    def usernames(self) -> dict[str, str]:
        """username в нижнем регистре → ключ студента.

        Сшито из формы регистрации на курс (`mlcheck telegram`). Берём только
        связки, которые модуль счёл надёжными и username которых существует:
        остальные проходят обычную привязку по ФИО и ссылке.
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
        """Доля потока, у которой закрыто не больше, чем у этого студента."""
        if not self.active:
            return 0
        below = sum(1 for s in self.active if s.passed <= student.passed)
        return round(100 * below / len(self.active))

    @cached_property
    def hw_stats(self) -> dict[str, dict]:
        """По каждой теме: сдач, зачётов, топ ошибок."""
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
