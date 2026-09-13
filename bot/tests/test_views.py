"""Экраны рендерятся для всех 205 студентов, без падений и без превышения лимита."""

import re

from mlbot.render import LIMIT, split
from mlbot.views import (article_text, external_links, finding_text,
                         hw_card_text, results_text, sorted_findings)

PAIRED = ("b", "i", "code", "pre")


def _tags_balanced(text: str) -> bool:
    for tag in PAIRED:
        if text.count(f"<{tag}>") != text.count(f"</{tag}>"):
            return False
    return text.count("<a href=") == text.count("</a>")


def test_every_student_screen_renders(course):
    checked = 0
    for student in course.students.values():
        if not student.ok:
            continue
        for chunk in split(results_text(course, student)):
            assert len(chunk) <= LIMIT
            assert _tags_balanced(chunk), student.key
        checked += 1
    assert checked == len(course.active)


def test_every_homework_card_renders(course):
    for student in course.active:
        for hw_id in course.rubrics:
            text = hw_card_text(course, student, hw_id, "не сдано")
            for chunk in split(text):
                assert len(chunk) <= LIMIT
                assert _tags_balanced(chunk), f"{student.key}/{hw_id}"


def test_every_finding_renders(course):
    total = 0
    for student in course.active:
        for hw_id, hw in student.homeworks.items():
            for f in sorted_findings(hw):
                total += 1
                for chunk in split(finding_text(course, hw_id, f)):
                    assert len(chunk) <= LIMIT
                    assert _tags_balanced(chunk), f"{student.key}/{hw_id}/{f['code']}"
    # Порог — проверка, что данные вообще на месте, а не точная цифра: он
    # считается от размера потока, поэтому переживает и перепрогон рецензий,
    # и подмену корпуса на синтетический.
    assert total > 3 * len(course.active), "замечаний подозрительно мало"


def test_every_catalog_article_renders(course):
    for code in course.catalog:
        text = article_text(course, code)
        assert text
        for chunk in split(text):
            assert len(chunk) <= LIMIT
            assert _tags_balanced(chunk), code


def test_every_finding_offers_something_to_read(course):
    """У каждой находки должна быть внешняя ссылка — либо своя, либо из статьи."""
    without = set()
    for student in course.active:
        for hw in student.homeworks.values():
            for f in hw.get("findings", []):
                art = course.article(f["code"])
                links = external_links(f) or (
                    [(t, u) for t, u in art.links if u.startswith("http")] if art else [])
                if not links:
                    without.add(f["code"])
    assert without <= {"hw01.other", "hw02.other", "hw03.other", "hw04.other",
                       "hw05.other", "hw06.other", "hw07.other", "hw08.other",
                       "hw09.other", "hw10.other", "hw11.other", "hw12.other",
                       "hw13.other"}, sorted(without)


def test_notebook_link_points_into_the_students_own_repo(course):
    student = next(s for s in course.active
                   if s.repo and (s.hw("hw05") or {}).get("status") != "missing")
    text = hw_card_text(course, student, "hw05", "нет")
    urls = re.findall(r'href="([^"]+)"', text)
    assert any(u.startswith(student.repo) for u in urls)
