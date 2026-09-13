"""Вымышленные студенты: экраны на них работают, а статистику они не портят.

Требование преподавателя — проверять бота, никого не тревожа. Значит демо должно
покрывать все ветки экранов и при этом быть отделено от настоящих 205 не
дисциплиной, а конструкцией: отдельный каталог и отдельный объект `Course`.
"""

import pytest

from mlbot.__main__ import load_demo
from mlbot.data import Course
from mlbot.views import (finding_text, hw_card_text, plan_text, results_text,
                         sorted_findings, strengths_text)
from mlbot.render import LIMIT


@pytest.fixture(scope="module")
def demo(cfg):
    d = load_demo(cfg)
    assert d is not None, "каталог demo/findings не найден — запусти demo/make_demo.py"
    return d


def _balanced(text: str) -> None:
    for tag in ("b", "i", "a", "code", "pre"):
        assert text.count(f"<{tag}") == text.count(f"</{tag}>"), tag


# --- отделённость ------------------------------------------------------------------

def test_demo_does_not_touch_the_real_statistics(cfg, course, demo):
    """Главное свойство: настоящие цифры одинаковы при наличии демо и без него."""
    again = Course.load(cfg)
    assert (course.certificates, len(course.active), course.median_passed) == \
           (again.certificates, len(again.active), again.median_passed)
    assert set(course.students) & set(demo.students) == set()


def test_demo_students_are_marked_in_their_name(demo):
    """Чтобы никто не принял демо за живого человека, если оно всплывёт в списке."""
    for st in demo.students.values():
        assert "(демо)" in st.fio and st.key.startswith("demo-")


def test_demo_covers_every_branch_of_the_screens(demo):
    kinds = {
        "выпускник": [s for s in demo.students.values() if s.certificate],
        "недобравший": [s for s in demo.students.values()
                        if s.ok and not s.certificate and s.passed],
        "исключённый": [s for s in demo.students.values() if not s.ok],
        "пустой": [s for s in demo.students.values()
                   if s.ok and not s.submitted()],
    }
    for name, found in kinds.items():
        assert found, f"нет демо-сущности «{name}» — ветка экрана не проверяется"


def test_finding_codes_exist_in_the_real_catalog(course, demo):
    """Выдуманный код отрисовался бы пустым разбором, и проверка ничего не показала бы."""
    for st in demo.students.values():
        for f in st.findings():
            assert course.article(f["code"]) is not None, f"{st.key}: {f['code']}"


# --- экраны -------------------------------------------------------------------------

def test_every_screen_renders_for_every_demo_student(course, demo):
    for st in demo.students.values():
        for text in (results_text(demo, st), strengths_text(demo, st)):
            _balanced(text)
            assert len(text) <= LIMIT
        plan, links = plan_text(demo, st)
        _balanced(plan)
        assert all(u.startswith("http") for _, u in links)
        for hw_id in demo.rubrics:
            card = hw_card_text(demo, st, hw_id, "не сдано")
            _balanced(card)
            assert len(card) <= LIMIT
            for f in sorted_findings(st.hw(hw_id)):
                _balanced(finding_text(demo, hw_id, f, 0, st.hw(hw_id)))


def test_graduate_sees_a_portrait_and_the_rest_survive_without_one(demo):
    star = demo.students["demo-star"]
    assert star.portrait and "Сильные стороны за курс" in results_text(demo, star)
    for key in ("demo-almost", "demo-quiet"):
        st = demo.students[key]
        assert st.portrait is None
        assert results_text(demo, st)          # не падает без портрета


def test_excluded_student_reaches_the_excluded_screen(demo):
    st = demo.students["demo-lost"]
    assert not st.ok and st.reason
