"""A check finding and its weight in the verdict."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    CRITICAL = "critical"   # the homework does not pass
    MAJOR = "major"         # passes with findings
    MINOR = "minor"         # advice for next time


@dataclass
class Finding:
    code: str                       # article key in the error catalog
    hw: str
    severity: Severity
    title: str
    detail: str = ""                # specifics for this submission
    source: str = "rule"            # rule | llm
    cells: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["severity"] = str(self.severity)
        return d
