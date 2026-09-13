"""Определение темы домашки по содержимому ноутбука.

Имя папки ненадёжно: встречается `hw04 (LOG REGRESSION)` с линейной регрессией
внутри и `hwXX_` без темы вообще. Поэтому решает содержимое, а путь — лишь
слабая подсказка.

Классификация многометочная: задание по случайному лесу прямо просит дополнить
ноутбук из домашки про линейную регрессию, так что один файл закрывает две темы.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .nbio import Notebook
from .rubric import Rubric

# Веса подобраны так, чтобы одного сильного маркера хватало для уверенного
# попадания, а совпадения только по имени файла — нет.
W_STRONG = 2.0
W_WEAK = 1.0
W_FILENAME = 0.6
# Путь — заявка студента о теме, поэтому для совпавших по имени порог ниже.
# Для остальных нужен и сильный маркер, и заметно более высокий балл: иначе
# EDA-часть чужой домашки засчитывалась бы как отдельная домашка по EDA.
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
    # Расширение отбрасываем: иначе подсказка вроде «nb» совпадала бы с «.ipynb»
    # у каждого файла и раздавала ложную уверенность.
    # Разделители приводим к одному виду: «log-reg» и «log_reg» — одно и то же.
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
    """Все темы, которым ноутбук соответствует, по убыванию уверенности."""
    if not nb.ok:
        return []
    matches = [score_notebook(nb, r) for r in rubrics.values()]
    hits = [m for m in matches if m.accepted]
    return sorted(hits, key=lambda m: -m.score)


def _own_cells(nb: Notebook, template_name: str | None) -> int:
    """Сколько ячеек написал сам студент (без раздаточной заготовки)."""
    from .templates import template_cell_bodies

    tpl = template_cell_bodies(template_name)
    if not tpl:
        return len(nb.cells)
    return sum(1 for c in nb.cells if re.sub(r"\s+", "", c.source) not in tpl)


def _completeness(nb: Notebook) -> tuple[int, int, int]:
    """Чем полнее работа, тем выше приоритет при выборе среди дублей."""
    executed = sum(1 for c in nb.code_cells if c.executed)
    nonempty = len(nb.nonempty_code_cells)
    return (nonempty, executed, len(nb.markdown_text))


@dataclass
class Submission:
    hw: str
    notebook: Notebook
    score: float
    strong_hits: list[str]
    alternatives: list[str] = None   # прочие ноутбуки, подошедшие под ту же тему
    by_folder: bool = False          # принят только по номеру папки, см. folder_topic


# Номер темы в имени КАТАЛОГА: «hw02/», «hw_03 (KNN)/», «HW07_tree/». Имя файла
# не смотрим: «hw04 (LOG REGRESSION)» совпадал бы и с hw04, и с hw05 по подсказкам,
# а номер каталога однозначен.
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
    """Среди нескольких кандидатов на тему выигрывает тот, где больше своей работы.

    Иначе раздаточный ноутбук лекции (в нём ячеек больше, но они не студента)
    вытесняет настоящую домашку, лежащую в той же папке.
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
        # Если студент положил работу в папку с названием темы — это его прямая
        # заявка, и она важнее того, что чужой ноутбук содержит больше кода.
        template = rubrics[hw].template_name

        def rank(pr):
            nb = pr[1]
            own = _own_cells(nb, template)
            share = own / max(len(nb.cells), 1)
            # Ноутбук, который больше чем наполовину состоит из раздатки, —
            # это копия заготовки с лекции, а не сданная домашка.
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

    # Второй проход — по папке. Ноутбук, который по содержимому ни на что не
    # похож, но лежит в «hw02/», а другой сдачи по hw02 у студента нет, — это
    # его заявка на тему: пустая или брошенная на середине, но заявка. Без этого
    # такая работа числилась «не сдано», хотя файл есть. Содержательные сдачи
    # правило не трогает: заполняются только пустые темы, порог `accepted` не
    # меняется, поэтому вердикт хуже стать не может.
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
