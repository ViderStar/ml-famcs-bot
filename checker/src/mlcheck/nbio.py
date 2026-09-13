"""Чтение и нормализация ноутбуков.

Две вещи, ради которых модуль существует:

1. `# YOUR CODE HERE` студенты не удаляют, а пишут код под ним. Поэтому
   «не выполнено» определяется по пустому телу ячейки после вычитания
   комментариев и маркеров, а не по наличию маркера.
2. Медианный ноутбук курса почти целиком состоит из base64-картинок в выводах.
   Перед отправкой в модель они вырезаются, иначе прогон дорожает на порядок.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# Каталоги, которые не содержат студенческих работ.
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
        """Код без комментариев, магий и маркеров-заготовок."""
        if not self.is_code:
            return self.source.strip()
        text = _COMMENT.sub("", self.source)
        text = _MAGIC.sub("", text)
        return text.strip()

    @property
    def is_empty(self) -> bool:
        """Ячейка не заполнена: остались только комментарии, маркер или pass."""
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
        """Весь код одной строкой — для грепа и AST-разбора."""
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
        """Пары (индекс ячейки, execution_count), нарушающие порядок сверху вниз.

        Пустая история или строго возрастающие номера означают, что ноутбук
        прогнали заново сверху вниз. Разрывы — признак, что «Restart & Run All»
        не делали.
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
    except Exception as exc:  # битый JSON — частый случай при конфликтах слияния
        nb.error = f"не разбирается как JSON: {type(exc).__name__}"
        return nb

    if not isinstance(raw, dict) or "cells" not in raw:
        # nbformat 3 хранил ячейки внутри worksheets
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
        # В nbformat 3 код лежал в input, а не в source.
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
    """Все ноутбуки репозитория, кроме служебных каталогов."""
    for p in sorted(root.rglob("*.ipynb")):
        if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        yield p


# --- Подготовка текста для модели -------------------------------------------------

# Длинные табличные выводы режем сильнее: метрики и заголовки таблиц
# помещаются, а простыни из сотен строк только раздувают разбор.
_MAX_OUTPUT_CHARS = 700


def _render_output(o: dict) -> str:
    kind = o.get("output_type")
    if kind == "error":
        # Трейсбеки сохраняем целиком: это самый ценный сигнал для рецензии.
        tb = "\n".join(o.get("traceback") or [])
        tb = re.sub(r"\x1b\[[0-9;]*m", "", tb)  # ANSI-раскраска
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
    """Компактное представление ноутбука. Возвращает текст и флаг обрезки."""
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
