"""Загрузка рубрик: описание домашки, сигнатура для классификации, пункты проверки."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from .config import Config, load


@dataclass
class Check:
    id: str
    title: str
    required: bool
    kind: str                       # rule | llm
    any_regex: list[str] = field(default_factory=list)
    all_regex: list[str] = field(default_factory=list)
    none_regex: list[str] = field(default_factory=list)
    markdown_bullets_min: int | None = None

    @property
    def is_rule(self) -> bool:
        return self.kind == "rule"


@dataclass
class Signature:
    strong: list[str] = field(default_factory=list)
    weak: list[str] = field(default_factory=list)
    filename: list[str] = field(default_factory=list)


@dataclass
class Rubric:
    id: str
    title: str
    kind: str                       # template | free | mixed
    signature: Signature
    checks: list[Check]
    task_path: Path | None = None
    template_name: str | None = None
    leakage_exempt: tuple[str, ...] = ()
    # delta — по дописанному студентом (по умолчанию для заготовок),
    # full — по всему ноутбуку (для hw01 и hw07, розданных уже решёнными).
    check_scope: str = "delta"
    # False — тема показывается в отчёте, но в знаменателе сертификата не участвует
    # (по деревьям решений задания не выдавалось).
    graded: bool = True
    # Прочие раздатки по теме, не являющиеся основной заготовкой:
    # например, ноутбук практики с лекции.
    extra_templates: tuple[str, ...] = ()

    @property
    def all_templates(self) -> tuple[str, ...]:
        names = ([self.template_name] if self.template_name else []) \
            + list(self.extra_templates)
        return tuple(names)

    @property
    def required_checks(self) -> list[Check]:
        return [c for c in self.checks if c.required]

    @property
    def rule_checks(self) -> list[Check]:
        return [c for c in self.checks if c.is_rule]

    @property
    def llm_checks(self) -> list[Check]:
        return [c for c in self.checks if not c.is_rule]

    def task_text(self) -> str:
        return self.task_path.read_text(encoding="utf-8") if self.task_path else ""


def _load_one(path: Path) -> Rubric:
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    sig = d.get("signature") or {}
    checks = [
        Check(
            id=c["id"],
            title=c["title"],
            required=bool(c["required"]),
            kind=c["kind"],
            any_regex=c.get("any_regex") or [],
            all_regex=c.get("all_regex") or [],
            none_regex=c.get("none_regex") or [],
            markdown_bullets_min=c.get("markdown_bullets_min"),
        )
        for c in d["checks"]
    ]
    task = d.get("task")
    return Rubric(
        id=d["id"],
        title=d["title"],
        kind=d["kind"],
        signature=Signature(
            strong=sig.get("strong") or [],
            weak=sig.get("weak") or [],
            filename=sig.get("filename") or [],
        ),
        checks=checks,
        task_path=(path.parent / task) if task else None,
        template_name=d.get("template"),
        leakage_exempt=tuple(d.get("leakage_exempt") or ()),
        check_scope=d.get("check_scope", "delta"),
        graded=bool(d.get("graded", True)),
        extra_templates=tuple(d.get("extra_templates") or ()),
    )


@lru_cache(maxsize=1)
def load_all(cfg: Config | None = None) -> dict[str, Rubric]:
    cfg = cfg or load()
    return {r.id: r for r in (_load_one(p) for p in sorted(cfg.rubrics_dir.glob("hw*.yaml")))}


@lru_cache(maxsize=8)
def load_dir(path: Path) -> dict[str, Rubric]:
    """Рубрики из произвольного каталога — для тех, у кого своя раскладка файлов."""
    return {r.id: r for r in (_load_one(p) for p in sorted(Path(path).glob("hw*.yaml")))}


def compile_regex(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I | re.M)
