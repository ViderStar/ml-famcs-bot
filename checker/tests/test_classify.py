"""Классификация тем по содержимому.

Имя папки на курсе ненадёжно: встречается `hw04 (LOG REGRESSION)` с линейной
регрессией внутри, сдвинутая на единицу нумерация и папки, поголовно названные
`setup_tools`. Поэтому решает содержимое.
"""

import pytest

from mlcheck import classify, nbio
from mlcheck.rubric import load_all


@pytest.fixture(scope="module")
def rubrics():
    return load_all()


def _classify(write_nb, cells, name):
    p = write_nb(cells, name=name)
    return {m.hw for m in classify.classify(nbio.load(p, rel=name), load_all())}


def test_content_wins_over_wrong_folder_name(write_nb):
    """Случай из потока: папка «LOG REGRESSION», а внутри линейная регрессия."""
    cells = [("code",
              "from sklearn.linear_model import LinearRegression\n"
              "df = pd.read_csv('ToyotaCorolla.csv')\n"
              "m = LinearRegression().fit(X_train, y_train)\n"
              "print(r2_score(y_test, m.predict(X_test)))\n", 1)]
    got = _classify(write_nb, cells, "hw04 (LOG REGRESSION)/toyota_regression.ipynb")
    assert "hw04" in got
    assert "hw05" not in got


def test_shifted_numbering_is_resolved_by_content(write_nb):
    """Случай из потока: логистическая регрессия лежит в папке hw06_."""
    cells = [("code",
              "class MyLogisticRegressionGD:\n    pass\n"
              "def sigmoid(z): return 1/(1+np.exp(-z))\n"
              "def compute_log_loss(y, p): pass\n"
              "def forward_backward(X, y, w, b): pass\n", 1)]
    got = _classify(write_nb, cells, "hw06_.ipynb")
    assert "hw05" in got


def test_ipynb_extension_does_not_grant_filename_confidence(write_nb):
    """Подсказка «nb» не должна ловиться на расширении .ipynb у каждого файла."""
    cells = [("code", "x = 1\n", 1)]
    assert _classify(write_nb, cells, "random_scratch.ipynb") == set()


def test_hyphen_and_underscore_are_equivalent_in_names(write_nb):
    cells = [("code", "def sigmoid(z): return 1/(1+np.exp(-z))\n"
                      "from sklearn.linear_model import LogisticRegression\n", 1)]
    assert "hw05" in _classify(write_nb, cells, "hw5_logreg/log-reg.ipynb")


def test_eda_inside_another_homework_is_not_credited_as_eda(write_nb):
    """EDA есть почти в каждой домашке — сама по себе она не домашка по EDA."""
    cells = [("code",
              "df.info()\ndf.describe()\ndf.isnull().sum()\n"
              "sns.heatmap(df.corr())\ndf['x'].fillna(df['x'].median())\n"
              "from sklearn.linear_model import LinearRegression\n"
              "df = pd.read_csv('ToyotaCorolla.csv')\n", 1)]
    got = _classify(write_nb, cells, "hw04_linreg/hw04.ipynb")
    assert "hw04" in got
    assert "hw02" not in got


def test_full_eda_checklist_is_credited_as_eda(write_nb):
    cells = [("code",
              "df.describe(include='object')\nprint(df.skew(), df.kurt())\n"
              "pd.get_dummies(df)\nimport plotly.express as px\n"
              "df.isnull().sum()\ndf.duplicated().sum()\ndf.quantile([.05,.95])\n", 1)]
    assert "hw02" in _classify(write_nb, cells, "hw02_eda/eda.ipynb")


def test_notebook_may_cover_two_topics(write_nb):
    """Задание по лесу просит дополнить ноутбук из домашки по линейной регрессии."""
    cells = [("code",
              "from sklearn.linear_model import LinearRegression\n"
              "from sklearn.ensemble import RandomForestRegressor\n"
              "df = pd.read_csv('ToyotaCorolla.csv')\n"
              "rf = RandomForestRegressor(max_depth=7, oob_score=True)\n"
              "r2_score(y_test, rf.predict(X_test))\n", 1)]
    got = _classify(write_nb, cells, "hw09_forest/hw09.ipynb")
    assert {"hw04", "hw09"} <= got


def test_path_named_submission_wins_over_richer_foreign_notebook(write_nb, tmp_path):
    """Работа в папке своей темы важнее чужого ноутбука, где кода больше."""
    real = nbio.load(write_nb(
        [("code", "df.describe(include='object')\ndf.skew()\ndf.kurt()\n"
                  "pd.get_dummies(df)\nimport plotly.express as px\n", 1)],
        name="a.ipynb"), rel="hw02_eda/eda.ipynb")
    foreign = nbio.load(write_nb(
        [("code", "df.describe(include='object')\ndf.skew()\ndf.kurt()\n"
                  "pd.get_dummies(df)\nimport plotly.express as px\n"
                  + "z = 1\n" * 200, 1)],
        name="b.ipynb"), rel="hw03_knn/hw.ipynb")
    chosen, _ = classify.pick_submissions([foreign, real], load_all())
    assert chosen["hw02"].notebook.rel == "hw02_eda/eda.ipynb"


def test_unparseable_notebook_is_not_classified(tmp_path):
    p = tmp_path / "x.ipynb"
    p.write_bytes(b"")
    assert classify.classify(nbio.load(p, rel="hw02_eda/x.ipynb"), load_all()) == []


def test_own_homework_wins_over_lecture_template_copy(write_nb):
    """В папке лежат и раздаточный ноутбук лекции, и своя домашка — выбрать надо свою."""
    import mlcheck.classify as cls

    template_cells = [("code", f"# ячейка лекции {i}\nprint({i})\n") for i in range(20)]
    lecture_copy = nbio.load(
        write_nb(template_cells + [("code", "my_note = 1\n")], name="a.ipynb"),
        rel="hw03/KNN_empty.ipynb")
    own = nbio.load(
        write_nb([("code", "from sklearn.neighbors import KNeighborsClassifier\n"
                           "knn = KNeighborsClassifier(n_neighbors=5)\nbest_k = 5\n")],
                 name="b.ipynb"),
        rel="hw03/03_homework.ipynb")

    tpl = frozenset("".join(c[1].split()) for c in template_cells)
    orig = cls._own_cells
    try:
        cls._own_cells = lambda nb, name: sum(
            1 for c in nb.cells if "".join(c.source.split()) not in tpl)
        chosen, _ = cls.pick_submissions([lecture_copy, own], load_all())
        assert chosen["hw03"].notebook.rel == "hw03/03_homework.ipynb"
    finally:
        cls._own_cells = orig


# --- fallback по папке ------------------------------------------------------------

def _nb(write_nb, cells, rel):
    return nbio.load(write_nb(cells, name=rel.replace("/", "__")), rel=rel)


def test_folder_fallback_credits_orphan_when_topic_is_empty(write_nb, rubrics):
    """Брошенная EDA в «hw02/»: по содержимому не опознаётся, но это заявка на тему."""
    orphan = _nb(write_nb, [("code", "df = pd.read_csv('x.csv')\ndf.isnull().sum()\n", 1)],
                 "hw02/analysis.ipynb")
    chosen, unmatched = classify.pick_submissions([orphan], rubrics)
    assert chosen["hw02"].notebook.rel == "hw02/analysis.ipynb"
    assert chosen["hw02"].by_folder
    assert unmatched == []


def test_folder_fallback_does_not_override_content_match(write_nb, rubrics):
    orphan = _nb(write_nb, [("code", "df.isnull().sum()\n", 1)], "hw02/stub.ipynb")
    real = _nb(write_nb, [("code", "df.describe(include='object')\ndf.skew()\ndf.kurt()\n"
                                   "pd.get_dummies(df)\nimport plotly.express as px\n", 1)],
               "eda/eda.ipynb")
    chosen, unmatched = classify.pick_submissions([orphan, real], rubrics)
    assert chosen["hw02"].notebook.rel == "eda/eda.ipynb"
    assert not chosen["hw02"].by_folder
    assert [nb.rel for nb in unmatched] == ["hw02/stub.ipynb"]


def test_folder_fallback_ignores_unknown_topic_numbers(write_nb, rubrics):
    orphan = _nb(write_nb, [("code", "x = 1\n", 1)], "hw14/whatever.ipynb")
    chosen, unmatched = classify.pick_submissions([orphan], rubrics)
    assert chosen == {}
    assert len(unmatched) == 1


def test_folder_fallback_looks_at_directory_not_filename(write_nb, rubrics):
    """Файл «hw_1.ipynb» в корне — не папка темы: под правило не попадает."""
    orphan = _nb(write_nb, [("code", "x = 1\n", 1)], "hw_1.ipynb")
    chosen, _ = classify.pick_submissions([orphan], rubrics)
    assert chosen == {}
    assert classify.folder_topic("hw_03 (KNN)/hw.ipynb", rubrics) == "hw03"
    assert classify.folder_topic("HW07_tree/flash_cards.ipynb", rubrics) == "hw07"
