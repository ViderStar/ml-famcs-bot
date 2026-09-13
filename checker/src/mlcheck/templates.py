"""Reference handout notebooks from materials/.

Needed to tell the student's work from what they were given. For example,
`pca_practice_student.ipynb` scales the whole dataset before the train/test
split — that is leakage, but it lives in the handout and cannot be charged to
the student.
"""

from __future__ import annotations

import re
from functools import lru_cache

from . import nbio
from .config import Config, load
from .nbio import Notebook


def normalize_line(line: str) -> str:
    line = line.split("#", 1)[0]
    return re.sub(r"\s+", "", line)


@lru_cache(maxsize=32)
def load_template(name: str, cfg: Config | None = None) -> Notebook | None:
    cfg = cfg or load()
    for base in (cfg.paths.materials, cfg.rubrics_dir / "templates"):
        path = base / name
        if path.exists():
            return nbio.load(path, rel=name)
    return None


@lru_cache(maxsize=32)
def template_lines(name: str | None) -> frozenset[str]:
    """Normalised template code lines — to subtract from the student's work."""
    if not name:
        return frozenset()
    nb = load_template(name)
    if nb is None or not nb.ok:
        return frozenset()
    out = set()
    for cell in nb.code_cells:
        for line in cell.source.splitlines():
            norm = normalize_line(line)
            if norm:
                out.add(norm)
    return frozenset(out)


@lru_cache(maxsize=32)
def template_cell_bodies(name: str | None) -> frozenset[str]:
    """Template cell bodies — to subtract when looking for copied work."""
    if not name:
        return frozenset()
    nb = load_template(name)
    if nb is None or not nb.ok:
        return frozenset()
    return frozenset(
        re.sub(r"\s+", "", c.source) for c in nb.cells if re.sub(r"\s+", "", c.source)
    )


@lru_cache(maxsize=32)
def template_markdown(name: str | None) -> frozenset[str]:
    """Normalised template markdown cells.

    Needed to tell the student's own conclusions from the template prose:
    otherwise work without a single word of their own looks well documented.
    """
    if not name:
        return frozenset()
    nb = load_template(name)
    if nb is None or not nb.ok:
        return frozenset()
    return frozenset(
        re.sub(r"\s+", " ", c.source).strip()
        for c in nb.markdown_cells
        if c.source.strip()
    )


@lru_cache(maxsize=32)
def union_cell_bodies(names: tuple[str, ...]) -> frozenset[str]:
    """Cells from every handout notebook of a topic at once."""
    out: set[str] = set()
    for name in names:
        out |= template_cell_bodies(name)
    return frozenset(out)
