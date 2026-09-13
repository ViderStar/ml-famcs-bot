"""Вердикт: когда домашка засчитана и когда выдаётся сертификат."""

from conftest import text_output

import pytest

from mlcheck import nbio, report
from mlcheck.catalog import load_all as load_catalog
from mlcheck.classify import Submission
from mlcheck.config import load
from mlcheck.pipeline import StudentWork
from mlcheck.roster import Student
from mlcheck.rubric import load_all as load_rubrics

GOOD_HW01 = (
    "import sys, numpy as np, pandas as pd, sklearn\n"
    "import seaborn as sns\n"
    "print(sys.version, np.__version__, pd.__version__, sklearn.__version__)\n"
    "rng = np.random.default_rng(42)\n"
    "X = rng.random((100, 5))\n"
    "print(X.mean(axis=0), X.std(axis=0))\n"
    "w = np.ones(5); y = X @ w\n"
    "df = pd.DataFrame(X, columns=[f'f{i}' for i in range(5)])\n"
    "df['target'] = y\n"
    "df.head(); df.describe(); df.isnull().sum()\n"
    "df.groupby('f0').mean()\n"
    "df['target'].hist()\n"
    "sns.heatmap(df.corr())\n"
)


def _work(write_nb, cells, hw="hw01", fio="Тестов Тест"):
    nb = nbio.load(write_nb(cells), rel=f"{hw}/nb.ipynb")
    st = Student(fio=fio, submitted_at="", raw_url="", slug="a/b",
                 owner="a", repo="b", key="tester", status="ok")
    return StudentWork(
        student=st,
        submissions={hw: Submission(hw=hw, notebook=nb, score=3.0, strong_hits=[])},
        notebook_count=1,
    )


def _build(work):
    cfg = load()
    return report.build_student(work, load_rubrics(cfg), load_catalog(cfg), {}, cfg), cfg


def test_complete_executed_homework_is_passed(write_nb):
    rep, cfg = _build(_work(write_nb, [
        ("markdown", "## Выводы\n\n" + "Разобрал данные. " * 30),
        ("code", GOOD_HW01, 1, [text_output()]),
    ]))
    assert rep.homeworks["hw01"].status == report.PASSED


def test_error_output_fails_the_homework(write_nb):
    from conftest import error_output
    rep, _ = _build(_work(write_nb, [
        ("markdown", "## Выводы\n\n" + "Текст. " * 40),
        ("code", GOOD_HW01, 1, [error_output()]),
    ]))
    hw = rep.homeworks["hw01"]
    assert hw.status == report.FAILED
    assert any(f["severity"] == "critical" for f in hw.findings)


def test_unexecuted_homework_fails(write_nb):
    rep, _ = _build(_work(write_nb, [("code", GOOD_HW01, None)]))
    assert rep.homeworks["hw01"].status == report.FAILED


def test_missing_homework_is_marked_missing(write_nb):
    rep, _ = _build(_work(write_nb, [("code", GOOD_HW01, 1, [text_output()])]))
    assert rep.homeworks["hw05"].status == report.MISSING


def test_too_few_rubric_points_fails(write_nb):
    """Ноутбук запускается, но закрывает меньше 70% обязательных пунктов."""
    rep, _ = _build(_work(write_nb, [
        ("markdown", "## Выводы\n\n" + "Текст. " * 40),
        ("code", "import pandas as pd\ndf = pd.read_csv('a.csv')\n"
                 "df.head()\ndf.info()\ndf.describe()\n", 1, [text_output()]),
    ], hw="hw02"))
    hw = rep.homeworks["hw02"]
    assert hw.status == report.FAILED
    assert hw.ratio < 0.7


def test_homework_without_required_points_passes_when_it_runs(write_nb):
    """hw01 и hw07 роздали уже решёнными: требовать в них нечего,
    и зачёт держится только на том, что ноутбук запускается."""
    rep, _ = _build(_work(write_nb, [
        ("code", "print('ok')", 1, [text_output()]),
    ], hw="hw07"))
    assert rep.homeworks["hw07"].required_total == 0
    assert rep.homeworks["hw07"].status == report.PASSED


def test_certificate_threshold(write_nb):
    """Порог берётся из конфига, тест не должен ломаться при его смене."""
    cfg = load()
    total = 12
    need = report.required_passed(total, cfg)

    def report_with(passed: int) -> report.StudentReport:
        rep = report.StudentReport(key="k", fio="Ф", slug="a/b", status="ok")
        for i in range(1, total + 1):
            rep.homeworks[f"hw{i:02d}"] = report.HwReport(
                hw=f"hw{i:02d}", title="",
                status=report.PASSED if i <= passed else report.MISSING)
        return rep

    assert not report.certificate(report_with(need - 1), total, cfg)
    assert report.certificate(report_with(need), total, cfg)


def test_required_passed_rounds_down_in_favour_of_students():
    """66% от 12 тем — это 7.92; требовать восемь было бы натяжкой."""
    assert report.required_passed_for(0.66, 12) == 7
    assert report.required_passed_for(0.50, 12) == 6
    assert report.required_passed_for(0.75, 12) == 9
    # Ровное деление не должно ничего сдвигать.
    assert report.required_passed_for(0.5, 10) == 5
    # И хотя бы одна домашка нужна всегда.
    assert report.required_passed_for(0.0, 12) == 1


def test_llm_verdict_can_fail_a_required_point(write_nb):
    cfg = load()
    rubrics, catalog = load_rubrics(cfg), load_catalog(cfg)
    work = _work(write_nb, [
        ("markdown", "## Выводы\n\n" + "Текст. " * 40),
        ("code", GOOD_HW01, 1, [text_output()]),
    ], hw="hw03")
    payload = {
        "checks": [
            {"id": "when_knn_good", "passed": False, "comment": "вывода нет"},
            {"id": "scaling_conclusion", "passed": True, "comment": "разобрано"},
        ],
        "findings": [{"code": "hw03.baselines", "comment": "нет бейзлайна"}],
        "strengths": "аккуратный код",
        "summary": "в целом неплохо",
    }
    rep = report.build_student(work, rubrics, catalog,
                               {"tester|hw03": payload}, cfg)
    hw = rep.homeworks["hw03"]
    codes = {f["code"] for f in hw.findings}
    assert "hw03.when_knn_good" in codes
    assert hw.summary == "в целом неплохо" and hw.strengths == "аккуратный код"
    assert hw.llm_used


def test_llm_other_code_is_kept_as_free_text(write_nb):
    cfg = load()
    work = _work(write_nb, [("code", GOOD_HW01, 1, [text_output()])], hw="hw01")
    payload = {"checks": [], "findings": [{"code": "other", "comment": "странный признак"}],
               "strengths": "", "summary": ""}
    rep = report.build_student(work, load_rubrics(cfg), load_catalog(cfg),
                               {"tester|hw01": payload}, cfg)
    other = [f for f in rep.homeworks["hw01"].findings if f["code"].endswith(".other")]
    assert other and other[0]["comment"] == "странный признак"


def test_every_finding_has_a_catalog_article():
    """Бот показывает пояснение по коду — статья обязана существовать."""
    from mlcheck.catalog import coverage
    missing, orphans = coverage()
    assert not missing, f"нет статей для: {sorted(missing)}"
    assert not orphans, f"статьи без кода: {sorted(orphans)}"


def test_llm_code_without_prefix_is_normalized(write_nb):
    """Проверяющий иногда теряет префикс — это форматная оплошность, не брак."""
    from mlcheck.catalog import load_all as load_catalog
    from mlcheck.llm import normalize_code

    catalog = load_catalog()
    assert normalize_code("conclusions_in_code_comments", "hw12", catalog) == (
        "common.conclusions_in_code_comments")
    assert normalize_code("baselines", "hw03", catalog) == "hw03.baselines"
    assert normalize_code("common.no_seed", "hw03", catalog) == "common.no_seed"
    assert normalize_code("other", "hw03", catalog) == "other"
    assert normalize_code("выдуманный_код", "hw03", catalog) is None


def test_unknown_llm_code_falls_back_to_other(write_nb):
    cfg = load()
    work = _work(write_nb, [("code", GOOD_HW01, 1, [text_output()])], hw="hw01")
    payload = {"checks": [], "strengths": "", "summary": "",
               "findings": [{"code": "нет_такого_кода", "comment": "что-то важное"}]}
    rep = report.build_student(work, load_rubrics(cfg), load_catalog(cfg),
                               {"tester|hw01": payload}, cfg)
    codes = [f["code"] for f in rep.homeworks["hw01"].findings if f["source"] == "llm"]
    assert codes == ["hw01.other"]



def test_llm_finding_on_rule_code_cannot_block_the_verdict():
    """Правило — авторитет по своим кодам; модель видит только дельту и ошибается.

    В перепрогоне v2 «ноутбук падает с ошибкой» от модели при пустом списке
    error-выводов в самом ноутбуке стоило студенту сертификата.
    """
    from mlcheck import report
    from mlcheck.catalog import load_all as load_catalog
    from mlcheck.rubric import load_all as load_rubrics
    from mlcheck.rules.engine import HwResult

    rubric = load_rubrics()["hw04"]
    catalog = load_catalog()
    res = HwResult(hw="hw04")
    res.passed_required, res.total_required = 9, 9
    payload = {"checks": [], "findings": [
        {"code": "common.error_output", "comment": "падает"},
        {"code": "common.undefined_name", "comment": "model не определена"},
    ], "strengths": "", "summary": ""}
    extra, _, _ = report._apply_llm(res, rubric, payload, catalog)
    by_code = {f["code"]: f for f in extra}
    assert by_code["common.error_output"]["severity"] == "major"
    assert by_code["common.undefined_name"]["severity"] == "major"
    assert "правило этого не подтвердило" in by_code["common.error_output"]["comment"]


def _needs_real_run(*names: str) -> None:
    """Пропустить, если рядом нет результатов настоящего прогона.

    В открытый репозиторий out/ не входит: там ФИО, ссылки на личные
    репозитории и рецензии. Лучше честный пропуск, чем тест, который на пустом
    каталоге ничего не проверяет и молча зеленеет.
    """
    from mlcheck.config import load

    cfg = load()
    missing = [n for n in names if not (cfg.paths.out / n).exists()]
    if missing:
        pytest.skip(f"нет результатов прогона: {', '.join(missing)}")


def test_certificate_list_matches_the_verdicts(tmp_path):
    _needs_real_run("certificates.csv", "findings")
    """Список прошедших не должен расходиться с вердиктами в отчётах.

    Файл собирается вместе с отчётами именно поэтому: цифра менялась дважды,
    и отдельный список успел бы устареть.
    """
    import csv as _csv
    import json as _json
    from pathlib import Path

    from mlcheck.config import load

    cfg = load()
    passed = set()
    for p in Path(cfg.paths.findings).glob("*.json"):
        d = _json.loads(p.read_text(encoding="utf-8"))
        if d["status"] == "ok" and d["certificate"]:
            passed.add(d["fio"])

    rows = list(_csv.DictReader((cfg.paths.out / "certificates.csv").open(encoding="utf-8")))
    assert {r["ФИО"] for r in rows} == passed
    assert [int(r["№"]) for r in rows] == list(range(1, len(rows) + 1))
    assert [r["ФИО"] for r in rows] == sorted((r["ФИО"] for r in rows), key=str.casefold)

    md = (cfg.paths.out / "certificates.md").read_text(encoding="utf-8")
    assert f"**{len(passed)} человек**" in md
    for fio in passed:
        assert fio in md
