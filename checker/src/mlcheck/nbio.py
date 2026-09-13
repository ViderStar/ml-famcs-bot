"""Reading and normalising notebooks.

Two things this module exists for:

1. Students do not delete `# YOUR CODE HERE`; they write code under it. So "not
   done" is decided by an empty cell body after comments and markers are
   subtracted, not by the presence of a marker.
2. The median course notebook is almost entirely base64 images in its outputs.
   They are stripped before the model sees it, or the run costs an order of
   magnitude more.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# Directories that hold no student work.
SKIP_DIRS = {
    ".git", ".ipynb_checkpoints", ".venv", "venv", "env", "site-packages",
    "node_modules", "__pycache__", ".idea", ".vscode", "catboost_info",
}

_MARKERS = (
    "your code here",
    "ваш код здесь",
    "todo",
    "# ...",
)
_COMMENT = re.compile(r"^\s*#.*$", re.M)
_MAGIC = re.compile(r"^\s*[%!].*$", re.M)


@dataclass
class Cell:
    index: int
    kind: str                       # code | markdown | raw
    source: str
    execution_count: int | None = None
    outputs: list[dict] = field(default_factory=list)

    @property
    def is_code(self) -> bool:
        return self.kind == "code"

    @property
    def body(self) -> str:
        """Code without comments, magics or template markers."""
        if not self.is_code:
            return self.source.strip()
        text = _COMMENT.sub("", self.source)
        text = _MAGIC.sub("", text)
        return text.strip()

    @property
    def is_empty(self) -> bool:
        """The cell is unfilled: only comments, a marker or pass remain."""
        body = self.body
        if not body:
            return True
        return body in {"pass", "...", "None"}

    @property
    def has_marker(self) -> bool:
        low = self.source.lower()
        return any(m in low for m in _MARKERS)

    @property
    def executed(self) -> bool:
        return self.is_code and self.execution_count is not None

    @property
    def errors(self) -> list[dict]:
        return [o for o in self.outputs if o.get("output_type") == "error"]

    @property
    def has_image_output(self) -> bool:
        for o in self.outputs:
            data = o.get("data") or {}
            if any(k.startswith("image/") for k in data):
                return True
        return False


@dataclass
class Notebook:
    path: Path
    rel: str
    cells: list[Cell] = field(default_factory=list)
    error: str | None = None
    nbformat_version: int | None = None

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def code_cells(self) -> list[Cell]:
        return [c for c in self.cells if c.is_code]

    @property
    def markdown_cells(self) -> list[Cell]:
        return [c for c in self.cells if c.kind == "markdown"]

    @property
    def source_text(self) -> str:
        """All the code as one string — for grepping and AST parsing."""
        return "\n".join(c.source for c in self.code_cells)

    @property
    def markdown_text(self) -> str:
        return "\n".join(c.source for c in self.markdown_cells)

    @property
    def nonempty_code_cells(self) -> list[Cell]:
        return [c for c in self.code_cells if not c.is_empty]

    @property
    def error_cells(self) -> list[Cell]:
        return [c for c in self.cells if c.errors]

    def execution_order_breaks(self) -> list[tuple[int, int]]:
        """Pairs of (cell index, execution_count) that break top-to-bottom order.

        An empty history or strictly increasing numbers mean the notebook was
        rerun from the top. Gaps are a sign that "Restart & Run All" was never
        done.
        """
        seen: list[tuple[int, int]] = []
        breaks: list[tuple[int, int]] = []
        prev = 0
        for c in self.code_cells:
            if c.execution_count is None:
                continue
            seen.append((c.index, c.execution_count))
            if c.execution_count <= prev:
                breaks.append((c.index, c.execution_count))
            prev = c.execution_count
        return breaks


def _coerce_source(src) -> str:
    if isinstance(src, list):
        return "".join(src)
    return src or ""


def load(path: Path, rel: str | None = None) -> Notebook:
    nb = Notebook(path=path, rel=rel or path.name)
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:  # broken JSON — common after merge conflicts
        nb.error = f"не разбирается как JSON: {type(exc).__name__}"
        return nb

    if not isinstance(raw, dict) or "cells" not in raw:
        # nbformat 3 kept cells inside worksheets
        sheets = raw.get("worksheets") if isinstance(raw, dict) else None
        if sheets:
            raw = {"cells": sheets[0].get("cells", []), "nbformat": raw.get("nbformat")}
        else:
            nb.error = "нет списка ячеек"
            return nb

    nb.nbformat_version = raw.get("nbformat")
    for i, c in enumerate(raw.get("cells") or []):
        if not isinstance(c, dict):
            continue
        kind = c.get("cell_type", "raw")
        # In nbformat 3 the code lived in input, not source.
        source = _coerce_source(c.get("source") if "source" in c else c.get("input"))
        nb.cells.append(
            Cell(
                index=i,
                kind=kind,
                source=source,
                execution_count=c.get("execution_count") or c.get("prompt_number"),
                outputs=[o for o in (c.get("outputs") or []) if isinstance(o, dict)],
            )
        )
    if not nb.cells:
        nb.error = "ноутбук пуст"
    return nb


def iter_notebooks(root: Path):
    """Every notebook in the repository except service directories."""
    for p in sorted(root.rglob("*.ipynb")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        yield p


# --- Preparing the text for the model ---------------------------------------------

    # Long tabular output is trimmed harder: metrics and table headers fit,
    # while hundreds of rows only bloat the review.
_MAX_OUTPUT_CHARS = 700


def _render_output(o: dict) -> str:
    kind = o.get("output_type")
    if kind == "error":
        # Tracebacks are kept whole: the most valuable signal for a review.
        tb = "\n".join(o.get("traceback") or [])
        tb = re.sub(r"\x1b\[[0-9;]*m", "", tb)  # ANSI colouring
        return f"[ОШИБКА] {o.get('ename')}: {o.get('evalue')}\n{tb}"
    if kind == "stream":
        return _clip(_coerce_source(o.get("text")))
    data = o.get("data") or {}
    if any(k.startswith("image/") for k in data):
        return "[график]"
    for key in ("text/plain",):
        if key in data:
            return _clip(_coerce_source(data[key]))
    return ""


def _clip(text: str, limit: int = _MAX_OUTPUT_CHARS) -> str:
    text = text.rstrip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… (обрезано, всего {len(text)} символов)"


def to_llm_text(nb: Notebook, max_chars: int) -> tuple[str, bool]:
    """A compact representation of a notebook. Returns the text and a truncation flag."""
    parts: list[str] = []
    for c in nb.cells:
        if c.kind == "markdown":
            parts.append(f"### [ячейка {c.index}] markdown\n{c.source.strip()}")
        elif c.is_code:
            head = f"### [ячейка {c.index}] код (execution_count={c.execution_count})"
            chunk = [head, c.source.rstrip()]
            rendered = [r for r in (_render_output(o) for o in c.outputs) if r]
            if rendered:
                chunk.append("--- вывод ---")
                chunk.append("\n".join(rendered))
            parts.append("\n".join(chunk))
    text = "\n\n".join(parts)
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n\n… НОУТБУК ОБРЕЗАН ПО ЛИМИТУ ДЛИНЫ …", True
