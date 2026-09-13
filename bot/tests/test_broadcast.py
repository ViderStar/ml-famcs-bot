"""Рассылки: заморозка списка, возобновление, двойной клик, замок песочницы.

Ни одна проверка не отправляет ничего наружу: стенд перехватывает вызовы на
уровне сессии телеграма, а предохранитель в боевом режиме выключается только
переменной окружения.
"""

import dataclasses

import pytest

from harness import Bench
from mlbot.broadcast import audiences, sender
from mlbot.menu import core
from mlbot.store import Store

ADMIN_ID, ADMIN_NAME = 1, "chief"


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "cast.sqlite3")
    await s.init()
    return s


@pytest.fixture
def live(cfg):
    """Тот же конфиг с выключенным предохранителем — боевой режим."""
    return dataclasses.replace(cfg, safe_mode=False)


@pytest.fixture
async def flock(course, store):
    """Десять привязанных студентов, четверо с сертификатом."""
    keys = [s.key for s in list(course.active)[:10]]
    for i, key in enumerate(keys, start=100):
        await store.bind(i, key, None, None)
    return keys


# --- аудитории --------------------------------------------------------------------

async def test_the_certificate_audience_matches_the_standalone_script(live, course, store,
                                                                      flock):
    """Одна выборка, а не две расходящиеся: скрипт `announce` берёт её отсюда же."""
    from mlbot.announce import recipients

    bound = {b.student_key: b.tg_id for b in await store.all_bindings()}
    expected = [tg for _, tg in recipients(course, bound)]
    targets, _ = await audiences.resolve("cert", live, course, store)
    assert [tg for tg, _ in targets] == expected


async def test_the_sandbox_hides_every_real_audience(cfg, live):
    """Второй замок: даже при дырке в предохранителе списка студентов не достать."""
    assert cfg.safe_mode
    assert {a.id for a in audiences.available(cfg)} == {"me", "demo"}
    assert {"all", "cert", "nocert"} <= {a.id for a in audiences.available(live)}


async def test_unreachable_people_are_counted_not_hidden(live, course, store, flock):
    targets, unreachable = await audiences.resolve("all", live, course, store)
    assert len(targets) == 10
    assert len(unreachable) == len(course.active) - 10


# --- отправка ---------------------------------------------------------------------

async def test_the_list_is_frozen_at_confirmation(live, course, store, flock):
    """Привязавшийся после подтверждения не должен попасть в добавку.

    Иначе отчёт «отправлено 10 из 10» соврал бы, а человек получил бы письмо,
    которого преподаватель не подтверждал.
    """
    targets, _ = await audiences.resolve("all", live, course, store)
    cast_id = await store.create_broadcast(
        created_by=ADMIN_ID, audience="all", kind="text", body="привет",
        targets=targets, sandbox=False)

    latecomer = next(s for s in course.active if s.key not in flock)
    await store.bind(999, latecomer.key, None, None)

    frozen = {t["tg_id"] for t in await store.pending_targets(cast_id)}
    assert 999 not in frozen and len(frozen) == 10


async def test_resume_sends_exactly_the_remainder(live, course, store, flock):
    targets, _ = await audiences.resolve("all", live, course, store)
    cast_id = await store.create_broadcast(
        created_by=ADMIN_ID, audience="all", kind="text", body="привет",
        targets=targets, sandbox=False)
    for tg_id, _ in targets[:4]:
        await store.mark_target(cast_id, tg_id, "sent")

    sent = []

    class FakeBot:
        async def send_message(self, chat_id, text, **kw):
            sent.append(chat_id)

    await store.start_broadcast(cast_id)
    stats = await sender.run(FakeBot(), store, cast_id)
    assert len(sent) == 6, "возобновление обязано дослать ровно остаток"
    assert stats["sent"] == 10
    assert not set(sent) & {tg for tg, _ in targets[:4]}


async def test_a_second_click_starts_nothing(live, course, store, flock):
    targets, _ = await audiences.resolve("all", live, course, store)
    cast_id = await store.create_broadcast(
        created_by=ADMIN_ID, audience="all", kind="text", body="привет",
        targets=targets, sandbox=False)
    assert await store.start_broadcast(cast_id) is True
    assert await store.start_broadcast(cast_id) is False


async def test_a_restart_marks_a_running_broadcast_as_interrupted(live, course, store, flock):
    targets, _ = await audiences.resolve("all", live, course, store)
    cast_id = await store.create_broadcast(
        created_by=ADMIN_ID, audience="all", kind="text", body="привет",
        targets=targets, sandbox=False)
    await store.start_broadcast(cast_id)
    assert await store.stall_running() == [cast_id]
    assert (await store.broadcast(cast_id))["status"] == "stalled"
    # …и её можно продолжить, а не только посмотреть.
    assert await store.start_broadcast(cast_id) is True


async def test_blocking_the_bot_does_not_stall_the_whole_broadcast(live, course, store,
                                                                   flock):
    from aiogram.exceptions import TelegramForbiddenError

    targets, _ = await audiences.resolve("all", live, course, store)
    cast_id = await store.create_broadcast(
        created_by=ADMIN_ID, audience="all", kind="text", body="привет",
        targets=targets, sandbox=False)

    class FakeBot:
        async def send_message(self, chat_id, text, **kw):
            if chat_id == targets[0][0]:
                raise TelegramForbiddenError(method=None, message="bot was blocked")

    await store.start_broadcast(cast_id)
    stats = await sender.run(FakeBot(), store, cast_id)
    assert stats["sent"] == 9 and stats["blocked"] == 1
    # Заблокировавший не остаётся «в ожидании»: повторять бессмысленно.
    assert not await store.pending_targets(cast_id)


# --- через интерфейс ---------------------------------------------------------------

async def test_formatting_survives_the_trip_through_the_bot(live, course, store, flock):
    """`message.text` терял жирный и ссылки — писать надо `html_text`."""
    bench = Bench(live, course, store, user_id=ADMIN_ID, username=ADMIN_NAME)
    await bench.press(core.cb("a.cast.to", "all"))
    from aiogram.types import MessageEntity
    msg = await bench.send("важное")
    assert msg  # черновик создан
    cast = (await store.recent_broadcasts(1))[0]
    assert cast["audience"] == "all" and cast["status"] == "draft"

    # Разметку подкладываем так же, как её кладёт телеграм: entities поверх текста.
    bench2 = Bench(live, course, store, user_id=ADMIN_ID, username=ADMIN_NAME)
    await bench2.press(core.cb("a.cast.to", "all"))
    out = await bench2.send("важное слово",
                            [MessageEntity(type="bold", offset=0, length=6)])
    assert out
    latest = (await store.recent_broadcasts(1))[0]
    assert "<b>важное</b>" in latest["body"], latest["body"]


async def test_in_the_sandbox_the_wizard_refuses_a_real_audience(cfg, course, store, flock):
    bench = Bench(cfg, course, store, user_id=ADMIN_ID, username=ADMIN_NAME)
    out = await bench.press(core.cb("a.cast.to", "all"))
    assert not [s for s in out if s.api.startswith("Send")], (
        "в песочнице настоящая аудитория не должна открываться даже по прямой ссылке")
    assert await store.recent_broadcasts(1) == []


async def test_a_sandbox_broadcast_reaches_the_teacher_and_nobody_else(cfg, course, store):
    """Сквозная проверка требования «пока никому ничего не отправлять».

    Вымышленный аккаунт — не админ, поэтому письмо к нему обязано развернуться
    на преподавателя с пометкой, а не уйти по адресу.
    """
    from mlbot.safety import BADGE

    await store.bind(4242, "demo-star", None, None, demo=True)
    bench = Bench(cfg, course, store, user_id=ADMIN_ID, username=ADMIN_NAME, safe=True)

    targets, _ = await audiences.resolve("demo", cfg, course, store)
    assert [tg for tg, _ in targets] == [4242]

    cast_id = await store.create_broadcast(
        created_by=ADMIN_ID, audience="demo", kind="text", body="проверка связи",
        targets=targets, sandbox=True)
    await store.start_broadcast(cast_id)
    await sender.run(bench.bot, store, cast_id)

    letters = [s for s in bench.session.calls
               if s.api == "SendMessage" and "проверка связи" in s.text]
    assert letters, "письмо не отправилось вовсе"
    for letter in letters:
        assert letter.chat_id == ADMIN_ID, "в песочнице письмо ушло постороннему"
        assert BADGE in letter.text and "4242" in letter.text
    assert (await store.broadcast(cast_id))["sandbox"] == 1
