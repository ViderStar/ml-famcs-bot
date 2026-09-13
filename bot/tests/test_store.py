"""Bot state: bindings are unique, events get written."""

import pytest

from mlbot.store import Store


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.sqlite3")
    await s.init()
    return s


async def test_bind_and_read_back(store):
    await store.bind(100, "student-one", "tester", "Тест")
    b = await store.binding(100)
    assert b.student_key == "student-one" and b.username == "tester"


async def test_one_student_one_account(store):
    await store.bind(100, "student-one", None, None)
    assert (await store.binding_of_student("student-one")).tg_id == 100
    # A handler must reject a second account for the same record, but the
    # database must not quietly allow a duplicate either.
    with pytest.raises(Exception):
        await store.bind(101, "student-one", None, None)


async def test_rebinding_same_account_replaces(store):
    await store.bind(100, "student-one", None, None)
    await store.bind(100, "student-two", None, None)
    assert (await store.binding(100)).student_key == "student-two"


async def test_events_and_counters(store):
    for _ in range(6):
        await store.log(100, "finding", {"code": "common.no_seed"})
    await store.log(100, "finding", {"code": "common.not_executed"})
    assert await store.count_event(100, "finding", "common.no_seed") == 6
    top = await store.top_events("finding")
    assert top[0][1] == 6
    assert (await store.event_totals())["finding"] == 7


async def test_support_ticket(store):
    ticket = await store.add_support(100, "dasha", "не согласна с оценкой")
    assert ticket > 0
    rows = await store.open_support()
    assert rows and rows[0]["text"] == "не согласна с оценкой"


async def test_binding_number_is_the_order_of_arrival(store):
    await store.bind(1, "a", None, None)
    await store.bind(2, "b", None, None)
    assert await store.binding_number(2) >= await store.binding_number(1)
