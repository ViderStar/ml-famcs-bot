"""The engine for declarative rubric checks, plus common rules and leakage."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

import dataclasses
import re as _re

from ..nbio import Notebook
from ..rubric import Check, Rubric
from ..templates import template_cell_bodies, template_lines, template_markdown
from . import common, leakage, undefined
from .base import Finding, Severity


@lru_cache(maxsize=512)
def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I | re.M)


def student_delta(nb: Notebook, template_name: str | None) -> Notebook:
    """The notebook without cells that match the handout template verbatim.

    Rubric items must be checked against this: otherwise the template scaffolding
    (`def sigmoid`, `class MyLogisticRegressionGD`, lecture code) closes almost
    every requirement without the student's involvement.
    """
    tpl = template_cell_bodies(template_name)
    if not tpl:
        return nb
    kept = [c for c in nb.cells if _re.sub(r"\s+", "", c.source) not in tpl]
    return dataclasses.replace(nb, cells=kept)


def _check_passes(check: Check, nb: Notebook) -> bool:
    """A rubric item is looked for in both code and prose: some requirements are verbal."""
    haystack = nb.source_text + "\n" + nb.markdown_text

    if check.markdown_bullets_min is not None:
        return common.markdown_bullets(nb) >= check.markdown_bullets_min
    if check.any_regex and not any(_rx(p).search(haystack) for p in check.any_regex):
        return False
    if check.all_regex and not all(_rx(p).search(haystack) for p in check.all_regex):
        return False
    if check.none_regex and any(_rx(p).search(haystack) for p in check.none_regex):
        return False
    return True


@dataclass
class HwResult:
    hw: str
    findings: list[Finding] = field(default_factory=list)
    passed_required: int = 0
    total_required: int = 0
    passed_optional: int = 0
    total_optional: int = 0
    llm_pending: list[str] = field(default_factory=list)

    @property
    def required_ratio(self) -> float:
        # Items delegated to the model count as done until it rules, otherwise the
        # static pass would penalise them twice.
        return self.passed_required / self.total_required if self.total_required else 1.0

    @property
    def has_critical(self) -> bool:
        return any(f.severity == Severity.CRITICAL for f in self.findings)


def run_all(nb: Notebook, rubric: Rubric) -> HwResult:
    res = HwResult(hw=rubric.id)
    res.findings.extend(
        common.check(nb, rubric.id, template_markdown(rubric.template_name))
    )
    if nb.ok and nb.nonempty_code_cells:
        res.findings.extend(common.check_extra(nb, rubric.id))
        res.findings.extend(undefined.check(nb, rubric.id))

    if not nb.ok or not nb.nonempty_code_cells:
        # There is no point checking rubric items in empty or broken work.
        res.total_required = len(rubric.required_checks)
        return res

    # Mistakes inherited from the handout template are not the student's fault.
    res.findings.extend(
        leakage.check(nb, rubric.id, template_lines(rubric.template_name), rubric.leakage_exempt)
    )

    # For template-based homework, items are checked against the student's additions only.
    target = nb if rubric.check_scope == "full" else student_delta(nb, rubric.template_name)

    for check in rubric.checks:
        if not check.is_rule:
            if check.required:
                res.total_required += 1
                res.passed_required += 1   # the model decides, see required_ratio
            res.llm_pending.append(check.id)
            continue

        ok = _check_passes(check, target)
        if check.required:
            res.total_required += 1
            res.passed_required += int(ok)
        else:
            res.total_optional += 1
            res.passed_optional += int(ok)

        if not ok:
            res.findings.append(Finding(
                code=f"{rubric.id}.{check.id}",
                hw=rubric.id,
                severity=Severity.MAJOR if check.required else Severity.MINOR,
                title=check.title,
                detail="пункт задания не найден в работе",
            ))
    return res
