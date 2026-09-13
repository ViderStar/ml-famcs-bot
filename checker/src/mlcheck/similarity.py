"""Looking for copied work.

The key subtlety: handouts are identical for everyone by construction. A student
who never touched `svm_practice_student.ipynb` matches fifty others byte for
byte. So what is compared is not the file but the **diff over the template** —
only what the student added.

Two levels:
* an exact diff match — a reason to look at the dates and decide who copied whom;
* close similarity by token shingles — just a number for the summary table.
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

# Names exempt from normalisation: these are API, not the student's choice.
_KEEP = {
    "fit", "predict", "transform", "fit_transform", "score", "self", "np", "pd", "plt",
    "sns", "px", "sklearn", "train_test_split", "DataFrame", "print", "range", "len",
    "import", "from", "as", "def", "class", "return", "for", "in", "if", "else", "None",
    "True", "False", "and", "or", "not", "lambda", "with", "try", "except", "while",
}


def cell_bodies(nb: Notebook) -> list[tuple[str, str]]:
    """Pairs of (normalised body, original text) across all cells."""
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
    """Cells repeated verbatim by many people are handout, not the student's work.

    Needed because not every template survived in materials: some were handed out
    in the lecture, and without this correction a dozen students would look like
    copies of one another.

    The threshold is both absolute and proportional: five people copying in a
    stream of fifty is not handout, and must not be erased.
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
    """Cells present neither in the template nor in the stream-wide handout."""
    tpl = template_cell_bodies(template_name)
    return [src for body, src in cell_bodies(nb) if body not in tpl and body not in boilerplate]


def delta_fingerprint(
    nb: Notebook, template_name: str | None, boilerplate: frozenset[str] = frozenset()
) -> str | None:
    """A hash of what the student added. None if they never touched the template."""
    cells = delta_cells(nb, template_name, boilerplate)
    if not cells:
        return None
    blob = "\n".join(sorted(_WS.sub("", c) for c in cells))
    if len(blob) < 120:      # too little to call it a match
        return None
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def normalize_tokens(code: str) -> list[str]:
    """Tokens with names, numbers and strings anonymised.

    Renaming variables stops hiding a copy.
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
        # Notebooks contain magics and truncated code — crashing is not an option.
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
    key: str            # student key
    fio: str
    hw: str
    rel: str            # notebook path inside the repository
    fingerprint: str | None
    shingles: set[str] = field(default_factory=set)
    n_tokens: int = 0          # size of the addition: on short diffs similarity is meaningless
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
    """Pairs within one topic: exact matches first, then close ones."""
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
            # A match on a dozen tokens proves nothing: everyone writes the
            # correct sigmoid the same way.
                    continue
                sim = jaccard(a.shingles, b.shingles)
                if sim >= threshold:
                    pairs.append(Pair(hw, a, b, "near", round(sim, 3)))
    return sorted(pairs, key=lambda p: (-p.similarity, p.hw))


def first_commit_date(repo: Path, rel: str) -> str | None:
    """The date of the commit that introduced the file. Needs full history."""
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
    """Deepens the history: the clone was shallow, and dates need commits."""
    if not (repo / ".git" / "shallow").exists():
        return True
    proc = subprocess.run(
        ["git", "-C", str(repo), "fetch", "--unshallow", "--quiet"], capture_output=True
    )
    return proc.returncode == 0
