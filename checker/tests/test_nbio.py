"""Поведение парсера ноутбуков.

Главный инвариант курса: `# YOUR CODE HERE` студенты не удаляют, а дописывают код
под ним. На корпусе таких ячеек 3744 против 23 действительно пустых, поэтому
трактовка маркера как «не выполнено» завалила бы почти весь поток.
"""

from conftest import error_output, image_output, text_output

from mlcheck import nbio


def test_marker_with_code_under_it_is_not_empty(write_nb):
    p = write_nb([("code", "# YOUR CODE HERE\nX_train, X_test = split(X)\n", 1)])
    nb = nbio.load(p)
    cell = nb.code_cells[0]
    assert cell.has_marker
    assert not cell.is_empty, "ячейка с кодом под маркером не должна считаться пустой"


def test_marker_alone_is_empty(write_nb):
    p = write_nb([("code", "# YOUR CODE HERE\n", None)])
    assert nbio.load(p).code_cells[0].is_empty


def test_only_comments_or_pass_is_empty(write_nb):
    p = write_nb([("code", "# просто мысли вслух\n\npass\n", 3)])
    assert nbio.load(p).code_cells[0].is_empty


def test_magics_alone_do_not_count_as_code(write_nb):
    p = write_nb([("code", "%matplotlib inline\n!pip install seaborn\n", 1)])
    assert nbio.load(p).code_cells[0].is_empty


def test_execution_order_breaks_detected(write_nb):
    ok = write_nb([("code", "a=1", 1), ("code", "b=2", 2), ("code", "c=3", 3)])
    assert nbio.load(ok).execution_order_breaks() == []

    broken = write_nb([("code", "a=1", 5), ("code", "b=2", 2), ("code", "c=3", 9)])
    assert nbio.load(broken).execution_order_breaks() == [(1, 2)]


def test_error_output_detected(write_nb):
    p = write_nb([("code", "1/0", 1, [error_output("ZeroDivisionError", "division by zero")])])
    nb = nbio.load(p)
    assert len(nb.error_cells) == 1
    assert nb.error_cells[0].errors[0]["ename"] == "ZeroDivisionError"


def test_zero_byte_file_reports_error(tmp_path):
    p = tmp_path / "empty.ipynb"
    p.write_bytes(b"")
    nb = nbio.load(p)
    assert not nb.ok and "JSON" in nb.error


def test_markdown_saved_as_ipynb_reports_error(tmp_path):
    """Реальный случай: студент переименовал README.md в .ipynb."""
    p = tmp_path / "hw01.ipynb"
    p.write_text("# HW01 — Настройка окружения\n\nтекст задания\n", encoding="utf-8")
    assert not nbio.load(p).ok


def test_notebook_without_cells_reports_empty(tmp_path):
    p = tmp_path / "n.ipynb"
    p.write_text('{"cells": [], "metadata": {}, "nbformat": 4}', encoding="utf-8")
    nb = nbio.load(p)
    assert not nb.ok and nb.error == "ноутбук пуст"


def test_nbformat3_worksheets_are_read(tmp_path):
    p = tmp_path / "old.ipynb"
    p.write_text(
        '{"nbformat": 3, "worksheets": [{"cells": ['
        '{"cell_type": "code", "input": ["x = 1"], "prompt_number": 4, "outputs": []}]}]}',
        encoding="utf-8",
    )
    nb = nbio.load(p)
    assert nb.ok and nb.code_cells[0].source == "x = 1"
    assert nb.code_cells[0].execution_count == 4


def test_llm_text_strips_images_but_keeps_tracebacks(write_nb):
    p = write_nb([
        ("markdown", "## Шаг 1"),
        ("code", "plt.plot(x)", 1, [image_output()]),
        ("code", "1/0", 2, [error_output()]),
        ("code", "print('ok')", 3, [text_output("ok")]),
    ])
    text, truncated = nbio.to_llm_text(nbio.load(p), max_chars=100_000)
    assert not truncated
    assert "iVBORw0KGgo" not in text, "base64 картинки обязаны вырезаться"
    assert "[график]" in text
    assert "ValueError: boom" in text, "трейсбек — самый ценный сигнал, он остаётся"
    assert "\x1b[" not in text, "ANSI-раскраска должна быть снята"


def test_llm_text_truncates_and_flags(write_nb):
    p = write_nb([("code", "x = 1\n" * 5000, 1)])
    text, truncated = nbio.to_llm_text(nbio.load(p), max_chars=500)
    assert truncated and "ОБРЕЗАН" in text


def test_iter_notebooks_skips_service_dirs(tmp_path):
    (tmp_path / ".ipynb_checkpoints").mkdir()
    (tmp_path / ".ipynb_checkpoints" / "a-checkpoint.ipynb").write_text("{}")
    (tmp_path / ".venv" / "lib").mkdir(parents=True)
    (tmp_path / ".venv" / "lib" / "b.ipynb").write_text("{}")
    (tmp_path / "hw01").mkdir()
    (tmp_path / "hw01" / "real.ipynb").write_text("{}")
    found = [p.name for p in nbio.iter_notebooks(tmp_path)]
    assert found == ["real.ipynb"]
