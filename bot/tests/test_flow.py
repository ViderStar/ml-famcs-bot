"""Сквозной путь студента по логике бота, без телеграма."""

import pytest

from mlbot.matching import find_by_repo, fio_matches
from mlbot.store import Store
from mlbot.views import finding_text, hw_card_text, results_text, sorted_findings
from mlbot.handlers.deps import student_of


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "flow.sqlite3")
    await s.init()
    return s


async def test_student_journey(course, store, somebody):
    # 1. Прислал ссылку — нашли кандидата.
    candidate = find_by_repo(course, somebody.repo)
    assert candidate is not None

    # 2. Подтвердил фамилией — привязались.
    assert fio_matches(candidate, somebody.fio)
    await store.bind(555, candidate.key, "tester", "Тест")

    # 3. Дальше студент достаётся только из привязки.
    me = await student_of(555, course, store)
    assert me is not None and me.key == candidate.key

    # 4. Экраны собираются.
    assert str(me.passed) in results_text(course, me)
    hw_id = me.submitted()[0]
    card = hw_card_text(course, me, hw_id, "не сдано")
    assert hw_id in card
    findings = sorted_findings(me.hw(hw_id))
    if findings:
        assert findings[0]["title"] in finding_text(course, hw_id, findings[0])


async def test_wrong_surname_does_not_open_someone_elses_report(course, somebody):
    victim = find_by_repo(course, somebody.repo)
    assert not fio_matches(victim, "Иванов Иван")


async def test_unbound_account_gets_nothing(course, store):
    assert await student_of(999, course, store) is None


async def test_findings_are_sorted_by_severity(course):
    order = {"critical": 0, "major": 1, "minor": 2}
    for student in list(course.active)[:40]:
        for hw in student.homeworks.values():
            ranks = [order[f["severity"]] for f in sorted_findings(hw)]
            assert ranks == sorted(ranks)


def test_router_order_puts_onboarding_first():
    """Состояния онбординга должны выигрывать у пасхалок и кнопок меню."""
    from mlbot.__main__ import ROUTERS
    from mlbot.handlers import easter, start

    assert ROUTERS[0] is start
    assert ROUTERS.index(start) < ROUTERS.index(easter)
