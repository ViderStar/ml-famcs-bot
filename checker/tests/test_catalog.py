"""The catalog: the kind flag — methodology or notebook hygiene."""

import re

from mlcheck.catalog import KINDS, load_all
from mlcheck.config import load

METHODOLOGY_COMMON = {
    "common.fit_before_split", "common.fit_on_test", "common.no_seed",
    "common.split_without_seed", "common.text_contradicts_output",
}


def test_every_common_article_declares_kind_explicitly():
    cfg = load()
    for p in (cfg.catalog_dir / "common").glob("*.md"):
        assert re.search(r"^kind:", p.read_text(encoding="utf-8"), re.M), p.name


def test_kind_values_are_valid_and_hw_articles_default_to_methodology():
    for code, art in load_all().items():
        assert art.kind in KINDS, code
        if not code.startswith("common."):
            assert art.kind == "methodology", code


def test_common_split_matches_the_teacher_decision():
    arts = load_all()
    for code, art in arts.items():
        if code.startswith("common."):
            expected = "methodology" if code in METHODOLOGY_COMMON else "hygiene"
            assert art.kind == expected, code
