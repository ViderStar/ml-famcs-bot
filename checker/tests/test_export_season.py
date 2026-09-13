"""Building the season materials branch.

The branch is built by command rather than by hand, so it can be rebuilt after
editing the rubrics. Hence the requirement: a rebuild must produce the same
thing, and every file in materials/ must land somewhere or be named as withheld.
"""

import unicodedata
from pathlib import Path

import pytest

from mlcheck import export_season
from mlcheck.config import load

MATERIALS = Path(__file__).resolve().parents[2] / "materials"

# Slides and handout notebooks are not part of this repository: they live in the
# course repository. Without them there is nothing to build — skip the file.
pytestmark = pytest.mark.skipif(
    not MATERIALS.exists(), reason="нет каталога materials — он живёт в репозитории курса")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    out = tmp_path_factory.mktemp("season")
    report = export_season.build(load(), out)
    return out, report


def test_every_lesson_becomes_a_folder_with_a_readme(built):
    out, _ = built
    for lesson in export_season.LESSONS:
        folder = out / lesson.folder
        assert folder.is_dir(), lesson.folder
        assert (folder / "README.md").exists()


def test_no_file_disappears_without_a_reason(built):
    """A silently lost file is the worst outcome: nobody notices it is missing."""
    out, report = built
    accounted = set()
    for path in out.rglob("*"):
        if path.is_file():
            accounted.add(unicodedata.normalize("NFC", path.name))
    accounted |= {n for n, _ in report.skipped_dupes}
    accounted |= {n for n, _ in report.withheld}

    missing = []
    for src in MATERIALS.iterdir():
        if src.is_file() and unicodedata.normalize("NFC", src.name) not in accounted:
            missing.append(src.name)
    assert not missing, f"vanished without explanation: {missing}"
    assert not report.leftovers, report.leftovers


def test_operational_data_is_never_published(built):
    """The repository is public, and the scooter service data belongs to someone else."""
    out, report = built
    withheld = {n for n, _ in report.withheld}
    assert "ml_dataset_20k.csv" in withheld
    assert "scooter_alerts.ipynb" in withheld
    assert not list(out.rglob("ml_dataset_20k.csv"))
    assert not list(out.rglob("scooter_alerts.ipynb"))


def test_every_homework_gets_a_page(built):
    out, report = built
    assert len(report.homeworks) >= 13
    pages = list((out / export_season.HOMEWORK_DIR).glob("*/README.md"))
    assert len(pages) == len(report.homeworks)
    # A topic with no separate assignment still gets a page explaining what was checked.
    hw05 = next(p for p in pages if "Логистическая" in p.parent.name)
    body = hw05.read_text(encoding="utf-8")
    assert "условие лежало прямо" in body and "Что проверялось" in body


def test_the_ungraded_topic_says_so(built):
    out, _ = built
    page = next(p for p in (out / export_season.HOMEWORK_DIR).glob("*/README.md")
                if "Деревья" in p.parent.name)
    assert "Вне зачёта" in page.read_text(encoding="utf-8")


def test_mistakes_section_carries_the_whole_catalog(built):
    out, report = built
    articles = list((out / export_season.MISTAKES_DIR).rglob("*.md"))
    assert len(articles) == report.articles + 1      # plus the section README


def test_root_readme_links_resolve(built):
    """A table link leading nowhere is the usual way to break a README."""
    out, _ = built
    import re

    body = (out / "README.md").read_text(encoding="utf-8")
    links = re.findall(r"\]\(([^)#:]+)\)", body)
    assert len(links) > 20
    for link in links:
        target = out / link
        assert target.exists(), link


def test_a_rebuild_changes_nothing(tmp_path):
    cfg = load()
    out = tmp_path / "twice"
    export_season.build(cfg, out)
    first = {p.relative_to(out): p.stat().st_size for p in out.rglob("*") if p.is_file()}
    export_season.build(cfg, out)
    second = {p.relative_to(out): p.stat().st_size for p in out.rglob("*") if p.is_file()}
    assert first == second


def test_folder_names_are_safe_for_git():
    for lesson in export_season.LESSONS:
        name = lesson.folder
        assert not set(name) & set(' /\\:*?"<>|'), name
        assert len(name) < 100, name
