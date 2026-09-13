"""Находка проверки и её вес в вердикте."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    CRITICAL = "critical"   # домашка не засчитывается
    MAJOR = "major"         # засчитана с замечаниями
    MINOR = "minor"         # совет на будущее


@dataclass
class Finding:
    code: str                       # ключ статьи в каталоге ошибок
    hw: str
    severity: Severity
    title: str
    detail: str = ""                # конкретика по этой работе
    source: str = "rule"            # rule | llm
    cells: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = str(self.severity)
        return d
