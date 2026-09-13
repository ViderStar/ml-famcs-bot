"""Схема базы: версии, перенос живых данных, изоляция демо.

Главное здесь — третий тест. Живая база бота заведена ещё без `user_version`,
и повышение версии обязано не потерять привязки: именно они связывают telegram
с записью студента, и восстановить их неоткуда.
"""

import re
import sqlite3

import pytest

from mlbot import migrations
from mlbot.store import Store

# Схема первой версии — ровно в том виде, в каком её создавал прежний `init()`:
# `executescript(SCHEMA)` без всякой отметки о версии.
LEGACY = migrations.MIGRATIONS[0]


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.sqlite3")
    await s.init()
    return s


async def test_fresh_database_reaches_the_latest_version(store):
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == migrations.LATEST


async def test_second_start_changes_nothing(store):
    await store.bind(100, "student-one", "tester", "Тест")
    await store.init()
    await store.init()
    assert (await store.binding(100)).student_key == "student-one"
    with sqlite3.connect(store.path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == migrations.LATEST


async def test_old_database_keeps_its_bindings_and_leaves_a_copy(tmp_path):
    path = tmp_path / "live.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(LEGACY)
        for i in range(74):
            db.execute(
                "INSERT INTO bindings (tg_id, student_key) VALUES (?, ?)", (i + 1, f"s{i}")
            )
        db.commit()
        assert db.execute("PRAGMA user_version").fetchone()[0] == 0

    store = Store(path)
    await store.init()

    assert len(await store.all_bindings()) == 74
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == migrations.LATEST
    copy = path.with_name("live.sqlite3.v0.bak")
    assert copy.exists(), "перед повышением версии копия базы обязана лечь рядом"
    with sqlite3.connect(copy) as db:
        assert db.execute("SELECT COUNT(*) FROM bindings").fetchone()[0] == 74


async def test_the_first_copy_is_not_overwritten(tmp_path):
    path = tmp_path / "live.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript(LEGACY)
        db.commit()
    copy = path.with_name("live.sqlite3.v0.bak")
    copy.write_bytes("самая ранняя копия".encode())
    migrations.backup(path, 0)
    assert copy.read_bytes() == "самая ранняя копия".encode()


def test_migrations_only_add():
    """Ни одна миграция не теряет данные — это условие их безоглядного прогона.

    Бот применяет миграции на старте, без подтверждения. Единственное, что
    делает это безопасным, — запрет на разрушающие операции.
    """
    forbidden = re.compile(
        r"\b(DROP|DELETE|TRUNCATE|RENAME|UPDATE)\b|ALTER\s+TABLE\s+\w+\s+DROP", re.I
    )
    for i, sql in enumerate(migrations.MIGRATIONS, 1):
        assert not forbidden.search(sql), f"миграция {i} способна потерять данные"


# --- демо не смешивается с настоящим -------------------------------------------


async def test_demo_binding_is_invisible_to_the_admin_screens(store):
    await store.bind(100, "student-one", None, None)
    await store.bind(200, "tester", None, None, demo=True)
    assert [b.tg_id for b in await store.all_bindings()] == [100]
    assert len(await store.all_bindings(include_demo=True)) == 2


async def test_mark_demo_hides_an_account_after_the_fact(store):
    await store.bind(100, "student-one", None, None)
    await store.mark_demo(100)
    assert await store.all_bindings() == []


async def test_clicks_made_in_a_demo_skin_stay_out_of_the_statistics(store):
    await store.log(1, "article", {"code": "common.no_seed"})
    await store.set_test_view(1, "demo-star")
    for _ in range(9):
        await store.log(1, "article", {"code": "common.fit_before_split"})
    # Настоящий просмотр — один, выдуманных девять. В «Что читают» и в сводке
    # обязан остаться только настоящий.
    assert await store.event_totals() == {"article": 1}
    assert await store.top_events("article") == [('{"code": "common.no_seed"}', 1)]


async def test_the_skin_comes_off_and_events_count_again(store):
    await store.set_test_view(1, "demo-star")
    await store.log(1, "article", {"code": "a"})
    await store.clear_test_view(1)
    await store.log(1, "article", {"code": "a"})
    assert await store.event_totals() == {"article": 1}


async def test_watching_a_real_student_is_still_counted(store):
    """Тестер-режим на настоящей записи — не демо: админ смотрит живой экран."""
    await store.set_test_view(1, "student-one")
    await store.log(1, "article", {"code": "a"})
    assert await store.event_totals() == {"article": 1}
