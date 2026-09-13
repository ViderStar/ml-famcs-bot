"""Поиск заимствований.

Ключевой риск: заготовки идентичны у всех по построению, и наивное сравнение
файлов обвинило бы в списывании десятки честных студентов. Сравнивается только
дельта поверх раздатки.
"""

from mlcheck import nbio, similarity

TEMPLATE = [
    ("markdown", "## Шаг 1. Разделение данных"),
    ("code", "import numpy as np\nimport pandas as pd\nfrom sklearn.model_selection import train_test_split"),
    ("code", "# YOUR CODE HERE\n"),
    ("markdown", "## Шаг 2. Реализуем сигмоиду"),
    ("code", "def sigmoid(z):\n    # YOUR CODE HERE\n    pass\n"),
]


def _work(write_nb, key, cells, boiler=frozenset(), name=None):
    nb = nbio.load(write_nb(cells, name=name or f"{key}.ipynb"), rel="hw05/nb.ipynb")
    return similarity.build_work(key, key, "hw05", nb, None, 5, boiler)


def test_untouched_template_copies_produce_no_pairs(write_nb):
    """Десять нетронутых копий одной заготовки не должны дать ни одной пары."""
    students = {f"s{i}": [c[1] for c in TEMPLATE] for i in range(10)}
    boiler = similarity.corpus_boilerplate(
        {k: [similarity._WS.sub("", c) for c in v] for k, v in students.items()},
        min_students=5,
    )
    works = [_work(write_nb, f"s{i}", TEMPLATE, boiler) for i in range(10)]
    assert similarity.find_pairs(works, 0.8, min_tokens=0) == []


def test_known_template_is_subtracted_even_without_corpus(write_nb):
    nb = nbio.load(write_nb(TEMPLATE), rel="hw05/nb.ipynb")
    assert similarity.delta_cells(nb, None) != []
    tpl_bodies = {similarity._WS.sub("", c[1]) for c in TEMPLATE}
    kept = [
        src for body, src in similarity.cell_bodies(nb) if body not in tpl_bodies
    ]
    assert kept == []


def test_identical_own_work_is_detected(write_nb):
    own = TEMPLATE + [("code",
        "def my_metric(y_true, y_pred):\n"
        "    tp = ((y_true == 1) & (y_pred == 1)).sum()\n"
        "    fp = ((y_true == 0) & (y_pred == 1)).sum()\n"
        "    fn = ((y_true == 1) & (y_pred == 0)).sum()\n"
        "    return tp / (tp + 0.5 * (fp + fn))\n")]
    works = [_work(write_nb, "alice", own), _work(write_nb, "bob", own)]
    pairs = similarity.find_pairs(works, 0.8, min_tokens=0)
    assert len(pairs) == 1 and pairs[0].kind == "exact"


def test_renamed_variables_still_look_similar(write_nb):
    a = TEMPLATE + [("code", "alpha = 0.1\nbeta = alpha * 2\nresult = beta + alpha\nprint(result)\n")]
    b = TEMPLATE + [("code", "gamma = 0.1\ndelta = gamma * 2\noutput = delta + gamma\nprint(output)\n")]
    wa, wb = _work(write_nb, "a", a), _work(write_nb, "b", b, name="b2.ipynb")
    assert wa.fingerprint != wb.fingerprint, "точного совпадения нет — имена разные"
    assert similarity.jaccard(wa.shingles, wb.shingles) > 0.9, "но структура та же"


def test_short_delta_never_forms_a_near_pair(write_nb):
    """Правильную сигмоиду все пишут одинаково — на паре строк это не улика."""
    tiny = [("code", "def sigmoid(z):\n    return 1 / (1 + np.exp(-z))\n")]
    works = [_work(write_nb, "a", tiny), _work(write_nb, "b", tiny, name="b2.ipynb")]
    assert similarity.find_pairs(works, 0.8, min_tokens=300) == []


def test_corpus_boilerplate_needs_enough_students(write_nb):
    """Ячейка, встреченная у двоих, — это ещё не раздатка, а возможная копия."""
    cells = {"a": ["X" * 50], "b": ["X" * 50]}
    assert similarity.corpus_boilerplate(cells, min_students=5) == frozenset()
    assert similarity.corpus_boilerplate(cells, min_students=2) == frozenset({"X" * 50})


def test_tokenizer_survives_broken_code(write_nb):
    """В ноутбуках попадаются магии и оборванный код — падать нельзя."""
    tokens = similarity.normalize_tokens("%%time\nfor i in range(:\n    print(")
    assert tokens


def test_boilerplate_threshold_scales_with_cohort():
    """Пятеро списавших на потоке в полсотни человек — это не раздатка."""
    cheaters = {f"c{i}": ["ОБЩАЯ ЯЧЕЙКА" * 5] for i in range(5)}
    others = {f"s{i}": [f"своя работа {i}" * 5] for i in range(45)}
    cells = {**cheaters, **others}

    # Абсолютного порога в 5 хватило бы, чтобы стереть эту группу.
    assert similarity.corpus_boilerplate(cells, 5, min_share=0.0) != frozenset()
    # Долевой порог (15% от 50 = 8) её сохраняет.
    assert similarity.corpus_boilerplate(cells, 5, min_share=0.15) == frozenset()


def test_widely_distributed_cell_is_still_boilerplate():
    handout = {f"s{i}": ["РАЗДАТОЧНАЯ ЯЧЕЙКА" * 5] for i in range(20)}
    own = {f"o{i}": [f"своё {i}" * 5] for i in range(30)}
    cells = {**handout, **own}
    assert similarity.corpus_boilerplate(cells, 5, min_share=0.15) != frozenset()
