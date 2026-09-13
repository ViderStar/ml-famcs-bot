"""Эталонные ноутбуки-заготовки из materials/.

Нужны, чтобы отличать работу студента от того, что ему раздали. Например,
`pca_practice_student.ipynb` сам масштабирует весь датасет до train/test split —
это утечка, но она в раздаточном материале, и студенту её вменять нельзя.
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
    """Нормализованные строки кода эталона — для вычитания из работы студента."""
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
    """Тела ячеек эталона — чтобы вычесть их при поиске заимствований."""
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
    """Нормализованные markdown-ячейки эталона.

    Нужны, чтобы отличить собственные выводы студента от текста заготовки:
    иначе работа без единого своего слова выглядит как хорошо документированная.
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
    """Ячейки всех раздаточных ноутбуков темы разом."""
    out: set[str] = set()
    for name in names:
        out |= template_cell_bodies(name)
    return frozenset(out)
