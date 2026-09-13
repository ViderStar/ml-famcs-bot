"""Поиск заимствований.

Главная тонкость: заготовки идентичны у всех по построению. Студент, не тронувший
`svm_practice_student.ipynb`, побайтово совпадёт с полусотней других. Поэтому
сравнивается не файл, а **дельта поверх эталона** — только то, что дописал студент.

Два уровня:
* точное совпадение дельты — повод посмотреть даты и решить, кто у кого;
* близкое сходство по шинглам токенов — просто цифра для сводной таблицы.
"""

from __future__ import annotations

import hashlib
import io
import re
import subprocess
import token as token_mod
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

from .nbio import Notebook
from .templates import template_cell_bodies

_WS = re.compile(r"\s+")

# Имена, по которым нормализация не проходит: это API, а не выбор студента.
_KEEP = {
    "fit", "predict", "transform", "fit_transform", "score", "self", "np", "pd", "plt",
    "sns", "px", "sklearn", "train_test_split", "DataFrame", "print", "range", "len",
    "import", "from", "as", "def", "class", "return", "for", "in", "if", "else", "None",
    "True", "False", "and", "or", "not", "lambda", "with", "try", "except", "while",
}


def cell_bodies(nb: Notebook) -> list[tuple[str, str]]:
    """Пары (нормализованное тело, исходный текст) по всем ячейкам."""
    out = []
    for c in nb.cells:
        body = _WS.sub("", c.source)
        if body:
            out.append((body, _WS.sub(" ", c.source).strip()))
    return out


def corpus_boilerplate(
    cells_by_student: dict[str, list[str]],
    min_students: int,
    min_share: float = 0.15,
) -> frozenset[str]:
    """Ячейки, дословно повторяющиеся у многих, — это раздатка, а не работа студента.

    Нужно потому, что не все заготовки сохранились в materials: например,
    `lin_reg_practice.ipynb` раздавали на лекции, и без этой поправки полтора
    десятка студентов выглядели бы копиями друг друга.

    Порог одновременно абсолютный и долевой: группа из пяти списавших на потоке
    в полсотни человек — это ещё не раздатка, и стирать её нельзя.
    """
    counts: dict[str, int] = {}
    for bodies in cells_by_student.values():
        for body in set(bodies):
            counts[body] = counts.get(body, 0) + 1
    threshold = max(min_students, round(min_share * len(cells_by_student)))
    return frozenset(b for b, n in counts.items() if n >= threshold)


def delta_cells(
    nb: Notebook, template_name: str | None, boilerplate: frozenset[str] = frozenset()
) -> list[str]:
    """Ячейки, которых нет ни в эталоне, ни в общей для потока раздатке."""
    tpl = template_cell_bodies(template_name)
    return [src for body, src in cell_bodies(nb) if body not in tpl and body not in boilerplate]


def delta_fingerprint(
    nb: Notebook, template_name: str | None, boilerplate: frozenset[str] = frozenset()
) -> str | None:
    """Хэш дописанного студентом. None, если он не тронул заготовку."""
    cells = delta_cells(nb, template_name, boilerplate)
    if not cells:
        return None
    blob = "\n".join(sorted(_WS.sub("", c) for c in cells))
    if len(blob) < 120:      # слишком мало, чтобы говорить о совпадении
        return None
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def normalize_tokens(code: str) -> list[str]:
    """Токены с обезличенными именами, числами и строками.

    Переименование переменных перестаёт скрывать копию.
    """
    out: list[str] = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(code).readline):
            if tok.type in (token_mod.COMMENT, token_mod.NL, token_mod.NEWLINE,
                            token_mod.INDENT, token_mod.DEDENT, token_mod.ENDMARKER):
                continue
            if tok.type == token_mod.NAME:
                out.append(tok.string if tok.string in _KEEP else "V")
            elif tok.type == token_mod.NUMBER:
                out.append("N")
            elif tok.type == token_mod.STRING:
                out.append("S")
            else:
                out.append(tok.string)
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # В ноутбуках попадаются магии и оборванный код — падать нельзя.
        out = [w if w in _KEEP else "V" for w in re.findall(r"\w+|\S", code)]
    return out


def shingles(tokens: list[str], size: int) -> set[str]:
    if len(tokens) < size:
        return set()
    return {" ".join(tokens[i:i + size]) for i in range(len(tokens) - size + 1)}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class Work:
    key: str            # ключ студента
    fio: str
    hw: str
    rel: str            # путь ноутбука в репозитории
    fingerprint: str | None
    shingles: set[str] = field(default_factory=set)
    n_tokens: int = 0          # объём дописанного: на коротких дельтах сходство пусто
    added_at: str | None = None


@dataclass
class Pair:
    hw: str
    a: Work
    b: Work
    kind: str           # exact | near
    similarity: float

    @property
    def earlier(self) -> Work | None:
        if not (self.a.added_at and self.b.added_at) or self.a.added_at == self.b.added_at:
            return None
        return self.a if self.a.added_at < self.b.added_at else self.b


def build_work(key: str, fio: str, hw: str, nb: Notebook, template_name: str | None,
               shingle_size: int, boilerplate: frozenset[str] = frozenset()) -> Work:
    cells = delta_cells(nb, template_name, boilerplate)
    code = "\n".join(cells)
    tokens = normalize_tokens(code)
    return Work(
        key=key, fio=fio, hw=hw, rel=nb.rel,
        fingerprint=delta_fingerprint(nb, template_name, boilerplate),
        shingles=shingles(tokens, shingle_size),
        n_tokens=len(tokens),
    )


def find_pairs(works: list[Work], threshold: float, min_tokens: int = 0) -> list[Pair]:
    """Пары внутри одной темы: сначала точные совпадения, затем близкие."""
    pairs: list[Pair] = []
    by_hw: dict[str, list[Work]] = {}
    for w in works:
        by_hw.setdefault(w.hw, []).append(w)

    for hw, group in by_hw.items():
        exact: dict[str, list[Work]] = {}
        for w in group:
            if w.fingerprint:
                exact.setdefault(w.fingerprint, []).append(w)

        exact_keys: set[tuple[str, str]] = set()
        for same in exact.values():
            if len(same) < 2:
                continue
            for i in range(len(same)):
                for j in range(i + 1, len(same)):
                    pairs.append(Pair(hw, same[i], same[j], "exact", 1.0))
                    exact_keys.add((same[i].key, same[j].key))

        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if (a.key, b.key) in exact_keys or (b.key, a.key) in exact_keys:
                    continue
                if min(a.n_tokens, b.n_tokens) < min_tokens:
                    # Совпадение на десятке токенов ничего не доказывает:
                    # правильную сигмоиду все пишут одинаково.
                    continue
                sim = jaccard(a.shingles, b.shingles)
                if sim >= threshold:
                    pairs.append(Pair(hw, a, b, "near", round(sim, 3)))
    return sorted(pairs, key=lambda p: (-p.similarity, p.hw))


def first_commit_date(repo: Path, rel: str) -> str | None:
    """Дата коммита, которым файл появился. Требует полной истории."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "log", "--diff-filter=A", "--follow",
         "--format=%aI", "--", rel],
        capture_output=True,
    )
    if proc.returncode != 0:
        return None
    dates = proc.stdout.decode("utf-8", "replace").split()
    return dates[-1] if dates else None


def unshallow(repo: Path) -> bool:
    """Дотягивает историю: клонировали поверхностно, а для дат нужны коммиты."""
    if not (repo / ".git" / "shallow").exists():
        return True
    proc = subprocess.run(
        ["git", "-C", str(repo), "fetch", "--unshallow", "--quiet"], capture_output=True
    )
    return proc.returncode == 0
