"""Other people's data is unreachable, by button or by forged callback.

These three checks used to grep the source: "`keyboards.py` has no callback_data
containing the word key", "every function in `admin.py` contains `_is_admin(cfg`".
Such a check guards the file layout, not the bot. Move half the handlers into
another module and it keeps passing, staring at an emptied file. A silently
passing test is worse than a missing one: it manufactures confidence.

Everything here is checked by behaviour. The bench feeds real updates through the
real dispatcher, walks the bot by its buttons the way a person does, and looks at
what a stranger received. Where the code lives is unknown and irrelevant to the
test.

Every check starts by asserting the traversal found anything at all: otherwise
"no leaks detected" would mean "nothing was looked at".
"""

import pytest

from harness import Bench, crawl
from mlbot.store import Store

ADMIN_ID, ADMIN_NAME = 1, "chief"
VICTIM_ID, STRANGER_ID = 555, 888


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "privacy.sqlite3")
    await s.init()
    return s


@pytest.fixture
async def victim(course, store):
    """A bound student whose review someone is trying to obtain."""
    st = next(s for s in course.active if s.submitted())
    await store.bind(VICTIM_ID, st.key, None, None)
    return st


def _leaks(sent) -> list:
    """What the bot actually showed: answering a callback reveals nothing."""
    return [s for s in sent if s.api.startswith(("Send", "Edit", "Copy", "Forward"))]


async def test_callback_data_never_carries_a_student_key(cfg, course, store, victim):
    """The student identifier comes only from the binding in the database.

    Should the key reach callback_data, anyone could substitute someone else's:
    buttons live in chat history, their contents are visible and forgeable.
    """
    seen = set()
    for bench, start in (
        (Bench(cfg, course, store, user_id=VICTIM_ID), "/start"),
        (Bench(cfg, course, store, user_id=ADMIN_ID, username=ADMIN_NAME), "/start"),
    ):
        seen |= (await crawl(bench, start, limit=150)).payloads

    assert len(seen) > 50, "the traversal found almost nothing — there is nothing to check"
    keys = {s.key for s in course.students.values() if len(s.key) >= 4}
    for data in seen:
        hit = next((k for k in keys if k in data), None)
        assert hit is None, f"student key {hit!r} leaked into button {data!r}"


async def test_an_unbound_account_cannot_reach_someone_elses_report(
        cfg, course, store, victim):
    """A stranger presses every student button and gets not one line of it."""
    owner = Bench(cfg, course, store, user_id=VICTIM_ID)
    payloads = sorted((await crawl(owner, limit=150)).payloads)
    assert len(payloads) > 50

    stranger = Bench(cfg, course, store, user_id=STRANGER_ID)
    secrets = [victim.fio, victim.repo or "\0"] + [
        part for part in victim.fio.split() if len(part) >= 5]
    for data in payloads:
        out = await stranger.press(data)
        shown = "\n".join(s.text for s in _leaks(out))
        for secret in secrets:
            assert secret not in shown, f"{data!r} showed an outsider {secret!r}"


async def test_a_stranger_gets_nothing_from_the_admin_buttons(cfg, course, store):
    """Every admin button is rights-checked — including ones added later.

    The check knows no handler names and reads no source: it presses exactly what
    the bot showed the admin.
    """
    admin = Bench(cfg, course, store, user_id=ADMIN_ID, username=ADMIN_NAME)
    seen_by_admin = (await crawl(admin, limit=200)).payloads
    guest = Bench(cfg, course, store, user_id=STRANGER_ID)
    seen_by_guest = (await crawl(guest, limit=200)).payloads
    # "Admin" means what a guest was not shown. Decided by behaviour, not by a
    # callback_data prefix: a prefix does not survive every restructuring.
    admin_only = sorted(seen_by_admin - seen_by_guest)
    assert len(admin_only) >= 10, "no admin buttons found — there is nothing to check"

    for data in admin_only:
        assert not _leaks(await guest.press(data)), f"{data!r} answered an outsider"


async def test_a_stranger_cannot_switch_into_tester_mode(cfg, course, store):
    """Tester mode substitutes the student on every screen — it is a key to every record."""
    stranger = Bench(cfg, course, store, user_id=STRANGER_ID)
    cert = next(s for s in course.active if s.passed)
    for text in ("/test", f"Тест {cert.fio}", "/admin", "🛠 Админка"):
        await stranger.send(text)
    assert await store.test_view(STRANGER_ID) is None


def test_the_student_is_resolved_only_through_a_binding():
    """A guard against a new module reaching into `course.students` directly.

    A glob over the whole package, not one folder: screen renderers move, and a
    check tied to `handlers/*.py` would stop seeing them.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "mlbot"
    # Who may: the admin panel (searches by name), onboarding (no binding yet),
    # deps (it is the binding), data and matching (they own the catalog),
    # announce and selfcheck (scripts with no user), __main__ (counts for a log).
    allowed = {"admin.py", "start.py", "deps.py", "data.py", "matching.py",
               "announce.py", "selfcheck.py", "__main__.py",
               # Labels broadcast recipients: the key comes from the binding, not
               # from a press — which is what "through the binding" means.
               "audiences.py"}
    checked = 0
    for path in sorted(src.rglob("*.py")):
        if path.name in allowed:
            continue
        checked += 1
        assert "course.students" not in path.read_text(encoding="utf-8"), path.name
    assert checked >= 10, "the glob found nothing — the check has degenerated"
