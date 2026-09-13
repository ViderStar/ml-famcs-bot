"""Protecting a record that carries a username from the registration form.

A real incident in the first week: an outsider bound to someone else's record by
typing the student's name and her repository link. Classmates know both, so
there were not two "factors" here — there was one. Now a record with a verified
username is given only to the owner of that username; everyone else becomes a
manual-review claim.
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
    """A student whose record carries a live username."""
    key = next(k for k in course.expected_usernames if k in course.students)
    return course.students[key], course.expected_usernames[key]


# --- the map -------------------------------------------------------------------------

def test_expected_usernames_are_only_verified_links(cfg, course):
    from mlcheck.telegram import read_map

    links = {lk.key: lk for lk in read_map(cfg.out_dir / "telegram_map.csv")}
    for key, name in course.expected_usernames.items():
        assert links[key].usable and links[key].exists != "no", key
        assert links[key].username.lower() == name.lower()
    # Records with a dead username are not protected: their owners changed telegram.
    dead = [lk.key for lk in links.values() if lk.exists == "no"]
    assert dead and all(k not in course.expected_usernames for k in dead)


def test_a_verified_record_keeps_its_owner(course):
    """A record with a confirmed telegram belongs to it, not to whoever came first.

    This is the protection that was missing: an outsider opened someone else's
    review using a name and a link, both known to classmates. The property is
    checked without naming students: the repository is public.
    """
    protected = {k: u for k, u in course.expected_usernames.items() if u}
    assert protected, "no record in the stream has a confirmed telegram"
    for key, username in protected.items():
        assert course.expected_username(key) == username
        assert key in course.students


# --- binding --------------------------------------------------------------------------

async def test_stranger_gets_a_claim_instead_of_access(cfg, course, store):
    st, owner = _protected(course)
    sent, state = [], FakeState()
    stranger = SimpleNamespace(id=999, username="someone_else", full_name="Чужой")

    await start._finish(_msg(sent, stranger), state, store, cfg, course, st)

    assert await store.binding(999) is None, "a foreign account must not bind"
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
    """47 records have no telegram in the form at all — nothing to compare, a human decides.

    The old rule here was "first to confirm owns it", which was the same hole:
    any classmate knows a surname and a link.
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
    """Both claims are visible to the admin — exactly the case a human should decide."""
    st = next(s for s in course.active if course.expected_username(s.key) is None)
    for tg, name in ((10, "first"), (11, "second")):
        await start._finish(_msg([], SimpleNamespace(id=tg, username=name, full_name=name)),
                            FakeState(), store, cfg, course, st)
    assert {c["tg_id"] for c in await store.pending_claims()} == {10, 11}
    assert await store.binding_of_student(st.key) is None


async def test_username_owner_binds_instantly_even_by_fio_and_link(cfg, course, store):
    """What waits is unproven ownership, not "the manual route".

    If the username matches the one recorded for the record, the person is the
    owner — whether they pressed confirm or sent a link.
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


# --- resolving claims -----------------------------------------------------------------

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
