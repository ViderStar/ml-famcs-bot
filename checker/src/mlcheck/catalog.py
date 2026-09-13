"""The catalog of common mistakes: one article per finding code.

This is what the Telegram bot reads, so every finding must have an article and
every article an existing code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .config import Config, load

_FRONT = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.S)


KINDS = frozenset({"methodology", "hygiene"})


@dataclass
class Article:
    code: str
    hw: str
    title: str
    severity: str
    detector: str
    body: str
    path: Path
    # methodology — a mistake in ML methodology or theory (leakage, validation, metrics);
    # hygiene — notebook discipline (not executed, no conclusions, warnings).
    # The bot needs this so "what to improve" advises theory, not "run the cells".
    kind: str = "methodology"

    @property
    def links(self) -> list[tuple[str, str]]:
        return re.findall(r"^- \[(.+?)\]\((.+?)\)$", self.body, re.M)


def _parse(path: Path) -> Article:
    text = path.read_text(encoding="utf-8")
    m = _FRONT.match(text)
    if not m:
        raise ValueError(f"{path}: нет frontmatter")
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    kind = meta.get("kind") or ("hygiene" if meta["hw"] == "common" else "methodology")
    if kind not in KINDS:
        raise ValueError(f"{path}: kind должен быть одним из {sorted(KINDS)}, а не {kind!r}")
    return Article(
        code=meta["code"], hw=meta["hw"], title=meta["title"],
        severity=meta["severity"], detector=meta["detector"],
        body=m.group(2).strip(), path=path, kind=kind,
    )


@lru_cache(maxsize=1)
def load_all(cfg: Config | None = None) -> dict[str, Article]:
    cfg = cfg or load()
    out: dict[str, Article] = {}
    for p in sorted(cfg.catalog_dir.rglob("*.md")):
        art = _parse(p)
        if art.code in out:
            raise ValueError(f"дубль кода {art.code}: {p} и {out[art.code].path}")
        out[art.code] = art
    return out


@lru_cache(maxsize=8)
def load_dir(path: Path) -> dict[str, Article]:
    """The catalog from an arbitrary directory — for anyone with a different layout."""
    out: dict[str, Article] = {}
    for p in sorted(Path(path).rglob("*.md")):
        art = _parse(p)
        if art.code in out:
            raise ValueError(f"дубль кода {art.code}: {p} и {out[art.code].path}")
        out[art.code] = art
    return out


def known_codes(cfg: Config | None = None) -> set[str]:
    return set(load_all(cfg))


def expected_codes(cfg: Config | None = None) -> set[str]:
    """Every code the pipeline can emit."""
    from .rubric import load_all as load_rubrics

    codes = {
        "common.notebook_unreadable", "common.nothing_done", "common.not_executed",
        "common.partially_executed", "common.error_output", "common.blank_template_cells",
        "common.execution_out_of_order", "common.no_conclusions", "common.no_own_conclusions",
        "common.no_seed",
        "common.fit_before_split", "common.fit_on_test",
        "common.conclusions_in_code_comments", "common.absolute_path",
        "common.warnings_suppressed", "common.no_effect_call",
        "common.split_without_seed", "common.undefined_name", "common.show_without_call",
        "common.text_contradicts_output", "common.prompt_injection_attempt",
        "common.secret_in_repo",
    }
    for rubric in load_rubrics(cfg).values():
        for check in rubric.checks:
            codes.add(f"{rubric.id}.{check.id}")
    return codes


def coverage(cfg: Config | None = None) -> tuple[set[str], set[str]]:
    """Returns (codes with no article, articles with no code)."""
    have, need = known_codes(cfg), expected_codes(cfg)
    return need - have, have - need
