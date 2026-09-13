"""Защита записи, за которой закреплён username из формы регистрации.

Живой инцидент первой недели: посторонний аккаунт привязался к чужой записи,
введя ФИО студентки и ссылку на её репозиторий. И то и другое известно
однокурсникам, так что двух «факторов» тут не было — был один.
Теперь запись с проверенным username отдаётся только владельцу этого username,
остальные попадают в заявки на ручную проверку.
"""

from types import SimpleNamespace

import pytest

from mlbot.data import Course
from mlbot.handlers import start
from mlbot.store import Store


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "c.sqlite3")
    await s.init()
    return s


class Msg(SimpleNamespace):
    async def answer(self, text, **kw):
        self.sent.append(text)


def _msg(sent, user):
    return Msg(sent=sent, from_user=user, bot=SimpleNamespace(
        send_message=_noop, __name__="bot"))


async def _noop(*a, **kw):
    return None


class FakeState:
    def __init__(self):
        self.cleared = False

    async def clear(self):
        self.cleared = True

    async def set_state(self, *a):
        pass

    async def update_data(self, **kw):
        pass

    async def get_data(self):
        return {}


def _protected(course: Course):
    """Студент, за записью которого закреплён живой username."""
    key = next(k for k in course.expected_usernames if k in course.students)
    return course.students[key], course.expected_usernames[key]


# --- карта ------------------------------------------------------------------------

def test_expected_usernames_are_only_verified_links(cfg, course):
    from mlcheck.telegram import read_map

    links = {lk.key: lk for lk in read_map(cfg.out_dir / "telegram_map.csv")}
    for key, name in course.expected_usernames.items():
        assert links[key].usable and links[key].exists != "no", key
        assert links[key].username.lower() == name.lower()
    # Записи с мёртвым username в защиту не попадают: их владельцы сменили телеграм.
    dead = [lk.key for lk in links.values() if lk.exists == "no"]
    assert dead and all(k not in course.expected_usernames for k in dead)


def test_a_verified_record_keeps_its_owner(course):
    """Запись с подтверждённым телеграмом закреплена за ним, а не за первым пришедшим.

    Это та самая защита, которой не было: посторонний аккаунт открыл чужой
    разбор по ФИО и ссылке — и то и другое известно однокурсникам. Проверяем
    свойство, не называя студентов: репозиторий открытый.
    """
    protected = {k: u for k, u in course.expected_usernames.items() if u}
    assert protected, "в потоке нет ни одной записи с подтверждённым телеграмом"
    for key, username in protected.items():
        assert course.expected_username(key) == username
        assert key in course.students


# --- привязка ---------------------------------------------------------------------

async def test_stranger_gets_a_claim_instead_of_access(cfg, course, store):
    st, owner = _protected(course)
    sent, state = [], FakeState()
    stranger = SimpleNamespace(id=999, username="someone_else", full_name="Чужой")

    await start._finish(_msg(sent, stranger), state, store, cfg, course, st)

    assert await store.binding(999) is None, "чужой аккаунт не должен привязаться"
    assert await store.binding_of_student(st.key) is None
    claims = await store.pending_claims()
    assert [(c["tg_id"], c["student_key"], c["expected"]) for c in claims] == \
           [(999, st.key, owner)]
    assert "закреплён другой телеграм" in sent[0]


async def test_owner_binds_without_a_claim(cfg, course, store):
    st, owner = _protected(course)
    sent = []
    user = SimpleNamespace(id=1, username=owner.upper(), full_name="Владелец")

    await start._finish(_msg(sent, user), FakeState(), store, cfg, course, st)

    assert (await store.binding_of_student(st.key)).tg_id == 1
    assert await store.pending_claims() == []


async def test_record_without_username_also_waits_for_the_admin(cfg, course, store):
    """У 47 записей telegram в форме нет вовсе — сверять не с чем, решает человек.

    Прежде здесь работало «первый подтвердивший — владелец», и это была та же
    дыра: фамилию и ссылку знает любой однокурсник.
    """
    st = next(s for s in course.active if course.expected_username(s.key) is None)
    sent = []
    user = SimpleNamespace(id=2, username="whoever", full_name="Первый")

    await start._finish(_msg(sent, user), FakeState(), store, cfg, course, st)

    assert await store.binding_of_student(st.key) is None
    claims = await store.pending_claims()
    assert [(c["tg_id"], c["student_key"], c["expected"]) for c in claims] == \
           [(2, st.key, None)]
    assert "телеграма нет" in sent[0]


async def test_two_people_can_claim_the_same_unverifiable_record(cfg, course, store):
    """Обе заявки видны админу — именно тот случай, когда решать должен человек."""
    st = next(s for s in course.active if course.expected_username(s.key) is None)
    for tg, name in ((10, "first"), (11, "second")):
        await start._finish(_msg([], SimpleNamespace(id=tg, username=name, full_name=name)),
                            FakeState(), store, cfg, course, st)
    assert {c["tg_id"] for c in await store.pending_claims()} == {10, 11}
    assert await store.binding_of_student(st.key) is None


async def test_username_owner_binds_instantly_even_by_fio_and_link(cfg, course, store):
    """Ждать заставляем не «ручной путь», а недоказанное владение.

    Если username совпадает с закреплённым за записью, человек — владелец,
    и неважно, нажал он кнопку подтверждения или прислал ссылку.
    """
    st, owner = _protected(course)
    user = SimpleNamespace(id=3, username=owner, full_name="Владелец")
    await start._finish(_msg([], user), FakeState(), store, cfg, course, st)
    assert (await store.binding_of_student(st.key)).tg_id == 3
    assert await store.pending_claims() == []


async def test_repeated_attempt_does_not_duplicate_the_claim(cfg, course, store):
    st, _ = _protected(course)
    user = SimpleNamespace(id=999, username="someone_else", full_name="Чужой")
    for _ in range(3):
        await start._finish(_msg([], user), FakeState(), store, cfg, course, st)
    assert len(await store.pending_claims()) == 1


# --- разбор заявок ----------------------------------------------------------------

async def test_approving_a_claim_binds_and_closes_it(store):
    cid = await store.add_claim(999, "key1", "new_name", "Кто-то", "old_name")
    assert (await store.claim(cid))["status"] == "pending"
    await store.bind(999, "key1", "new_name", "Кто-то")
    await store.resolve_claim(cid, "approved")
    assert (await store.claim(cid))["status"] == "approved"
    assert await store.pending_claims() == []
    assert (await store.binding_of_student("key1")).tg_id == 999


async def test_rejected_claim_leaves_no_access(store):
    cid = await store.add_claim(999, "key1", "new_name", "Кто-то", "old_name")
    await store.resolve_claim(cid, "rejected")
    assert await store.binding(999) is None
    assert await store.pending_claims() == []


def test_claim_callbacks_carry_no_student_key():
    from mlbot.keyboards import claim_card

    for row in claim_card(42).inline_keyboard:
        for b in row:
            assert b.callback_data in ("adm:claim:ok:42", "adm:claim:no:42")
