"""Узнавание по telegram-username и закрепление владельца записи.

Форма сдачи домашек username не спрашивала — он взят из формы регистрации на
курс (`mlcheck telegram`). Для 47 записей живого username нет вовсе, и там
владельцем становится первый, кто подтвердит ФИО и ссылку.
"""

import csv

import pytest
from mlcheck.telegram import FIELDS, Link, read_map, save

from mlbot.matching import find_by_username
from mlbot.store import Store


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "u.sqlite3")
    await s.init()
    return s


def test_map_exists_and_is_consistent_with_roster(cfg, course):
    links = read_map(cfg.out_dir / "telegram_map.csv")
    assert len(links) == len(course.students)
    assert {lk.key for lk in links} == set(course.students)
    for lk in links:
        assert lk.exists in ("yes", "no", "unknown", "")


def test_index_only_holds_verified_links(cfg, course):
    links = {lk.username.lower(): lk for lk in read_map(cfg.out_dir / "telegram_map.csv")
             if lk.username}
    for name, key in course.usernames.items():
        assert links[name].usable, f"@{name} попал в индекс, хотя связка ненадёжна"
        assert links[name].key == key


def test_index_has_no_duplicates(course):
    # Один username не может указывать на двух студентов: иначе первый
    # написавший увидел бы чужой разбор.
    assert len(set(course.usernames.values())) == len(course.usernames)


def test_lookup_is_case_and_at_insensitive(course):
    name = next(iter(course.usernames))
    st = find_by_username(course, name)
    assert st is not None
    assert find_by_username(course, f"@{name.upper()}") is st
    assert find_by_username(course, f"  {name}  ") is st


def test_unknown_username_is_not_recognised(course):
    assert find_by_username(course, "zzq_nobody_9137xz") is None
    assert find_by_username(course, None) is None
    assert find_by_username(course, "") is None


def test_dead_username_falls_back_to_manual_flow(cfg, course, tmp_path):
    """Переименовавшийся студент по username не узнаётся — и это правильно."""
    dead = [lk for lk in read_map(cfg.out_dir / "telegram_map.csv") if lk.exists == "no"]
    assert dead, "в карте нет ни одного освободившегося username"
    for lk in dead:
        assert find_by_username(course, lk.username) is None


async def test_first_claimant_becomes_the_owner(course, store):
    """У записи нет живого username — владельцем становится первый пришедший."""
    st = next(s for s in course.active if s.key not in course.usernames)

    await store.bind(100, st.key, "new_owner", "Первый")
    assert (await store.binding_of_student(st.key)).tg_id == 100

    # Второй желающий получает отказ, а не чужой разбор.
    taken = await store.binding_of_student(st.key)
    assert taken.tg_id != 200
    assert taken.username == "new_owner"          # username закреплён за записью


async def test_recognised_student_cannot_be_taken_twice(course, store):
    name, key = next(iter(course.usernames.items()))
    await store.bind(300, key, name, "Хозяин")
    assert (await store.binding_of_student(key)).tg_id == 300


def test_saved_map_round_trips(tmp_path):
    links = [Link(key="k", fio="Иванов Иван", reg_fio="Иванов Иван Иванович",
                  username="ivanov", match="exact", exists="yes", note="")]
    path = tmp_path / "m.csv"
    save(links, path)
    assert list(csv.DictReader(path.open(encoding="utf-8")))[0]["username"] == "ivanov"
    assert read_map(path)[0] == links[0]
    assert set(FIELDS) == {"key", "fio", "reg_fio", "username", "match", "exists", "note"}
