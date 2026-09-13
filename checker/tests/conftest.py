import json

import pytest


def make_nb(cells, nbformat=4):
    """Builds a notebook from a compact description [(kind, source, ec, outputs)]."""
    out = []
    for c in cells:
        kind, source = c[0], c[1]
        ec = c[2] if len(c) > 2 else None
        outputs = c[3] if len(c) > 3 else []
        cell = {"cell_type": kind, "source": source, "metadata": {}}
        if kind == "code":
            cell["execution_count"] = ec
            cell["outputs"] = outputs
        out.append(cell)
    return {"cells": out, "metadata": {}, "nbformat": nbformat, "nbformat_minor": 5}


@pytest.fixture
def write_nb(tmp_path):
    def _write(cells, name="nb.ipynb", nbformat=4):
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(make_nb(cells, nbformat)), encoding="utf-8")
        return p
    return _write


def error_output(ename="ValueError", evalue="boom"):
    return {
        "output_type": "error",
        "ename": ename,
        "evalue": evalue,
        "traceback": ["\x1b[0;31m---\x1b[0m", f"{ename}: {evalue}"],
    }


def image_output():
    return {"output_type": "display_data", "data": {"image/png": "iVBORw0KGgo=" * 200}, "metadata": {}}


def text_output(text="ok"):
    return {"output_type": "stream", "name": "stdout", "text": text}
