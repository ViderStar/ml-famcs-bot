"""Deciding a homework's topic from the notebook's content.

A folder name is unreliable: there is an `hw04 (LOG REGRESSION)` holding linear
regression, and `hwXX_` with no topic at all. So content decides and the path is
only a weak hint.

Classification is multi-label: the random-forest assignment explicitly asks
students to extend their linear-regression notebook, so one file closes two
topics.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .nbio import Notebook
from .rubric import Rubric

# Weights are chosen so one strong marker is enough for a confident match, while
# a filename match alone is not.
W_STRONG = 2.0
W_WEAK = 1.0
W_FILENAME = 0.6
# The path is the student's own claim about the topic, so the threshold is lower
# for filename matches. The rest need both a strong marker and a noticeably
# higher score: otherwise the EDA part of another homework would count as a
# separate EDA submission.
MIN_SCORE_NAMED = 0.9
MIN_SCORE_UNNAMED = 1.6


@dataclass
class Match:
    hw: str
    score: float
    strong_hits: list[str]
    weak_hits: list[str]
    filename_hit: bool

    @property
    def accepted(self) -> bool:
        if self.filename_hit:
            return self.score >= MIN_SCORE_NAMED
        return bool(self.strong_hits) and self.score >= MIN_SCORE_UNNAMED


def score_notebook(nb: Notebook, rubric: Rubric) -> Match:
    haystack = nb.source_text
    # The extension is dropped: otherwise a hint like "nb" would match ".ipynb"
    # on every file and hand out false confidence.
    # Separators are normalised: "log-reg" and "log_reg" are the same thing.
    lowpath = re.sub(r"\.ipynb$", "", nb.rel.lower())
    lowpath = re.sub(r"[\s\-.]+", "_", lowpath)
    sig = rubric.signature

    strong = [m for m in sig.strong if m in haystack]
    weak = [m for m in sig.weak if m in haystack]
    fname = any(re.sub(r"[\s\-.]+", "_", h.lower()) in lowpath for h in sig.filename)

    score = 0.0
    if sig.strong:
        score += W_STRONG * len(strong) / len(sig.strong)
    if sig.weak:
        score += W_WEAK * len(weak) / len(sig.weak)
    if fname:
        score += W_FILENAME
    return Match(rubric.id, round(score, 3), strong, weak, fname)


def classify(nb: Notebook, rubrics: dict[str, Rubric]) -> list[Match]:
    """Every topic the notebook matches, most confident first."""
    if not nb.ok:
        return []
    matches = [score_notebook(nb, r) for r in rubrics.values()]
    hits = [m for m in matches if m.accepted]
    return sorted(hits, key=lambda m: -m.score)


def _own_cells(nb: Notebook, template_name: str | None) -> int:
    """How many cells the student wrote themselves (excluding the handout template)."""
    from .templates import template_cell_bodies

    tpl = template_cell_bodies(template_name)
    if not tpl:
        return len(nb.cells)
    return sum(1 for c in nb.cells if re.sub(r"\s+", "", c.source) not in tpl)


def _completeness(nb: Notebook) -> tuple[int, int, int]:
    """The fuller the work, the higher its priority when choosing among duplicates."""
    executed = sum(1 for c in nb.code_cells if c.executed)
    nonempty = len(nb.nonempty_code_cells)
    return (nonempty, executed, len(nb.markdown_text))


@dataclass
class Submission:
    hw: str
    notebook: Notebook
    score: float
    strong_hits: list[str]
    alternatives: list[str] = None   # other notebooks that matched the same topic
    by_folder: bool = False          # accepted by folder number alone, see folder_topic


# The topic number in the DIRECTORY name: "hw02/", "hw_03 (KNN)/", "HW07_tree/".
# The file name is ignored: "hw04 (LOG REGRESSION)" would match both hw04 and
# hw05 by hints, while the directory number is unambiguous.
_HW_DIR = re.compile(r"(?:^|/)hw[_\s-]?0?(\d{1,2})[^/]*/", re.I)


def folder_topic(rel: str, rubrics: dict[str, Rubric]) -> str | None:
    m = _HW_DIR.search(rel.lower())
    if not m:
        return None
    hw = f"hw{int(m.group(1)):02d}"
    return hw if hw in rubrics else None


def pick_submissions(
    notebooks: list[Notebook], rubrics: dict[str, Rubric]
) -> tuple[dict[str, Submission], list[Notebook]]:
    """Among several candidates for a topic, the one with more own work wins.

    Otherwise the lecture handout notebook (more cells, but not the student's)
    displaces the real homework sitting in the same folder.
    """
    """По одной лучшей работе на тему. Возвращает также неопознанные ноутбуки."""
    by_hw: dict[str, list[tuple[Match, Notebook]]] = {}
    unmatched: list[Notebook] = []

    for nb in notebooks:
        matches = classify(nb, rubrics)
        if not matches:
            unmatched.append(nb)
            continue
        for m in matches:
            by_hw.setdefault(m.hw, []).append((m, nb))

    chosen: dict[str, Submission] = {}
    for hw, pairs in by_hw.items():
        # If the student put the work in a folder named after the topic, that is
        # their direct claim, and it outweighs another notebook having more code.
        template = rubrics[hw].template_name

        def rank(pr):
            nb = pr[1]
            own = _own_cells(nb, template)
            share = own / max(len(nb.cells), 1)
            # A notebook more than half of which is handout material is a copy of
            # the lecture template, not submitted homework.
            return (pr[0].filename_hit, share >= 0.5, own, _completeness(nb), pr[0].score)

        pairs.sort(key=rank, reverse=True)
        best_match, best_nb = pairs[0]
        chosen[hw] = Submission(
            hw=hw,
            notebook=best_nb,
            score=best_match.score,
            strong_hits=best_match.strong_hits,
            alternatives=[nb.rel for _, nb in pairs[1:]],
        )

    # Second pass, by folder. A notebook that matches nothing by content but sits
    # in "hw02/" while the student has no other hw02 submission is their claim on
    # that topic: empty or abandoned halfway, but a claim. Without this such work
    # counted as "not submitted" although the file exists. Substantive submissions
    # are untouched: only empty topics are filled, the `accepted` threshold does
    # not move, so no verdict can get worse.
    by_folder: dict[str, list[Notebook]] = {}
    for nb in unmatched:
        hw = folder_topic(nb.rel, rubrics)
        if hw and hw not in chosen:
            by_folder.setdefault(hw, []).append(nb)
    for hw, cands in by_folder.items():
        template = rubrics[hw].template_name
        cands.sort(key=lambda nb: (_own_cells(nb, template), _completeness(nb)), reverse=True)
        best = cands[0]
        chosen[hw] = Submission(
            hw=hw, notebook=best, score=W_FILENAME, strong_hits=[],
            alternatives=[nb.rel for nb in cands[1:]], by_folder=True,
        )
        unmatched = [nb for nb in unmatched if nb is not best]
    return chosen, unmatched
