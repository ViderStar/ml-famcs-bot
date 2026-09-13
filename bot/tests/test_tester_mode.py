"""Admin tester mode and the throttling middleware.

Throttling: one fine day the menu buttons stopped answering. The inner
middleware wrapped every handler that fired rather than the event, and when
onboarding passed a button on through SkipHandler, the second handler was muted
as "too fast". Hence the check that throttling is outer only.
"""

from types import SimpleNamespace

import pytest

from mlbot.__main__ import ROUTERS, build_dispatcher
from mlbot.handlers import admin, deps, easter, start
from mlbot.handlers.admin import _TEST_PREFIX
from mlbot.handlers.admin import test_examples as examples  # otherwise pytest would collect it as a test
from mlbot.middlewares import Throttle
from mlbot.store import Store


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "t.sqlite3")
    await s.init()
    return s


# --- throttling ---------------------------------------------------------------------

def test_throttle_is_outer_only(cfg, course, store):
    dp = build_dispatcher(cfg, course, store)
    for observer in (dp.message, dp.callback_query):
        outer = [m for m in observer.outer_middleware if isinstance(m, Throttle)]
        inner = [m for m in observer.middleware if isinstance(m, Throttle)]
        assert outer, "throttling must be an outer middleware"
        assert not inner, ("внутренний троттлинг глушит обработчик, которому "
                           "событие передали через SkipHandler")


def test_router_order_is_start_first_easter_last():
    assert ROUTERS[0] is start and ROUTERS[-1] is easter


async def test_throttle_drops_second_call_for_the_same_user():
    """Documents why the inner middleware broke SkipHandler."""
    calls = []

    async def handler(event, data):
        calls.append(event)

    from aiogram.types import Message

    th = Throttle(interval=10)
    data = {"event_from_user": SimpleNamespace(id=7)}
    # The middleware only mutes real Message/CallbackQuery objects — pydantic can
    # build an empty one without validation.
    event = Message.model_construct()
    await th(handler, event, data)
    await th(handler, event, data)
    assert len(calls) == 1


# --- tester mode ----------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Тест Иванов Иван", "Иванов Иван"),
    ("тест: Иванов Иван", "Иванов Иван"),
    ("/test Иванов Иван", "Иванов Иван"),
    ("test Иванов", "Иванов"),
    ("Тест стоп", "стоп"),
    ("Тест", ""),
])
def test_prefix_parsing(text, expected):
    m = _TEST_PREFIX.match(text)
    assert m and m.group(1).strip() == expected


def test_prefix_does_not_catch_ordinary_words():
    # "Тестирование" and "тестовый" are not the command.
    assert _TEST_PREFIX.match("Тестирование модели") is None
    assert _TEST_PREFIX.match("протест") is None


def test_examples_are_one_with_and_one_without_certificate(course):
    cert, fail = examples(course)
    assert cert.certificate and cert.ok
    assert not fail.certificate and fail.ok and fail.passed > 0
    assert cert.key != fail.key
    # Deterministic: the hint in the greeting must not jump around.
    assert examples(course) == (cert, fail)


async def test_view_overrides_binding_and_survives_reload(course, store, tmp_path):
    cert, fail = examples(course)
    admin_id = 1

    assert await deps.student_of(admin_id, course, store) is None
    await store.set_test_view(admin_id, cert.key)
    assert (await deps.student_of(admin_id, course, store)).key == cert.key

    # Switching and reopening the database: the mode lives in SQLite.
    await store.set_test_view(admin_id, fail.key)
    reopened = Store(store.path)
    await reopened.init()
    assert (await deps.student_of(admin_id, course, reopened)).key == fail.key

    await store.clear_test_view(admin_id)
    assert await deps.student_of(admin_id, course, store) is None


async def test_view_does_not_block_the_real_student(course, store):
    """Tester mode does not occupy the record: the student can bind in parallel."""
    cert, _ = examples(course)
    await store.set_test_view(1, cert.key)
    await store.bind(555, cert.key, "student", "Студент")
    assert (await store.binding_of_student(cert.key)).tg_id == 555
    assert (await deps.student_of(555, course, store)).key == cert.key
    assert (await deps.student_of(1, course, store)).key == cert.key


async def test_non_admin_cannot_enter_test_mode(cfg, course, store):
    sent = []

    class Msg(SimpleNamespace):
        async def answer(self, text, **kw):
            sent.append(text)

    msg = Msg(text="Тест Иванов Иван", from_user=SimpleNamespace(id=999, username=None))
    await admin.test_mode(msg, cfg, course, store)
    assert not sent
    assert await store.test_view(999) is None


async def test_admin_enters_and_leaves_test_mode(cfg, course, store):
    sent = []

    class Msg(SimpleNamespace):
        async def answer(self, text, **kw):
            sent.append((text, kw.get("reply_markup")))

    cert, fail = examples(course)
    admin_id = next(iter(cfg.admin_ids))
    who = lambda: SimpleNamespace(id=admin_id, username="adm")

    await admin.test_mode(Msg(text=f"Тест {fail.fio}", from_user=who()), cfg, course, store)
    assert await store.test_view(admin_id) == fail.key
    assert "без сертификата" in sent[-1][0]
    labels = [b.text for row in sent[-1][1].keyboard for b in row]
    assert "🎓 Второй сезон" in labels and "🛠 Админка" in labels

    await admin.test_mode(Msg(text="Тест стоп", from_user=who()), cfg, course, store)
    assert await store.test_view(admin_id) is None

    await admin.test_mode(Msg(text="Тест Зюзюкин Абракадабра", from_user=who()),
                          cfg, course, store)
    assert "не нашёл" in sent[-1][0].lower()
    assert await store.test_view(admin_id) is None


# --- rights by username ----------------------------------------------------------------

def test_admin_by_username(cfg):
    from dataclasses import replace

    c = replace(cfg, admin_ids=frozenset({1}), admin_usernames=frozenset({"teacher_one"}))
    assert c.is_admin(1)                              # by id, as before
    assert c.is_admin(777, "Teacher_One")                # case does not matter
    assert c.is_admin(777, "@teacher_one")               # with an @ too
    assert not c.is_admin(777, "someone_else")
    assert not c.is_admin(777, None)
    assert not c.is_admin(777)


def test_admin_usernames_parsing():
    from mlbot.config import load

    c = load({"BOT_TOKEN": "x", "ADMIN_IDS": "1, 2",
              "ADMIN_USERNAMES": "@Teacher_One, teacher_two , @@ , "})
    assert c.admin_ids == {1, 2}
    assert c.admin_usernames == {"teacher_one", "teacher_two"}


async def test_admin_by_username_reaches_test_mode(cfg, course, store):
    from dataclasses import replace

    sent = []

    class Msg(SimpleNamespace):
        async def answer(self, text, **kw):
            sent.append(text)

    c = replace(cfg, admin_ids=frozenset(), admin_usernames=frozenset({"teacher_one"}))
    cert, _ = examples(course)
    await admin.test_mode(
        Msg(text=f"Тест {cert.fio}", from_user=SimpleNamespace(id=42, username="Teacher_One")),
        c, course, store)
    assert await store.test_view(42) == cert.key

    # But an outsider with a similar name does not.
    await admin.test_mode(
        Msg(text=f"Тест {cert.fio}", from_user=SimpleNamespace(id=43, username="teacher_one2")),
        c, course, store)
    assert await store.test_view(43) is None


def test_admin_menu_offers_the_tester_button():
    from mlbot.keyboards import admin_menu

    data = [b.callback_data for row in admin_menu().inline_keyboard for b in row]
    labels = [b.text for row in admin_menu().inline_keyboard for b in row]
    assert "adm:test" in data
    assert any("Глазами студента" in x for x in labels)


def test_certificate_rule_does_not_explain_why_hw07_is_ungraded(course):
    """The student-facing text no longer claims no decision-tree assignment was issued."""
    from mlbot import texts

    rule = texts.CERT_RULE.format(total=course.total_graded, need=course.required_passed)
    assert "не выдавалось" not in rule
    assert "Деревья решений" not in rule
