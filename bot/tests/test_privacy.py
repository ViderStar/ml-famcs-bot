"""Чужие данные недоступны ни через кнопки, ни подменой callback.

Раньше эти три проверки были грепом по исходникам: «в `keyboards.py` нет
callback_data со словом key», «в `admin.py` у каждой функции есть `_is_admin(cfg`».
Такая проверка охраняет не бота, а расположение файлов. Стоит вынести половину
обработчиков в другой модуль — и она продолжит проходить, разглядывая опустевший
файл. Молча проходящий тест хуже отсутствующего: он создаёт уверенность.

Здесь всё проверяется поведением. Стенд гоняет настоящие апдейты через настоящий
диспетчер, обходит бота по кнопкам — так же, как это делает человек, — и смотрит,
что получил чужой. Где именно лежит код, тесту неизвестно и безразлично.

Каждая проверка начинается с того, что обход вообще что-то нашёл: иначе «утечек
не обнаружено» означало бы «ничего не смотрели».
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
    """Привязанный студент, чей разбор пытаются добыть."""
    st = next(s for s in course.active if s.submitted())
    await store.bind(VICTIM_ID, st.key, None, None)
    return st


def _leaks(sent) -> list:
    """Что бот реально показал: `answer()` на колбэк ничего не раскрывает."""
    return [s for s in sent if s.api.startswith(("Send", "Edit", "Copy", "Forward"))]


async def test_callback_data_never_carries_a_student_key(cfg, course, store, victim):
    """Идентификатор студента берётся только из привязки в базе.

    Попади ключ в callback_data — и любой подставил бы чужой: кнопки живут в
    истории чата, их содержимое видно и подделывается.
    """
    seen = set()
    for bench, start in (
        (Bench(cfg, course, store, user_id=VICTIM_ID), "/start"),
        (Bench(cfg, course, store, user_id=ADMIN_ID, username=ADMIN_NAME), "/start"),
    ):
        seen |= (await crawl(bench, start, limit=150)).payloads

    assert len(seen) > 50, "обход почти ничего не нашёл — проверять нечего"
    keys = {s.key for s in course.students.values() if len(s.key) >= 4}
    for data in seen:
        hit = next((k for k in keys if k in data), None)
        assert hit is None, f"ключ студента {hit!r} уехал в кнопку {data!r}"


async def test_an_unbound_account_cannot_reach_someone_elses_report(
        cfg, course, store, victim):
    """Посторонний жмёт все кнопки студента и не получает ни строчки чужого."""
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
            assert secret not in shown, f"{data!r} показал постороннему {secret!r}"


async def test_a_stranger_gets_nothing_from_the_admin_buttons(cfg, course, store):
    """Каждая кнопка админки проверяется правами — включая те, что появятся потом.

    Проверка не знает имён обработчиков и не читает исходники: она нажимает
    ровно то, что бот показал администратору.
    """
    admin = Bench(cfg, course, store, user_id=ADMIN_ID, username=ADMIN_NAME)
    seen_by_admin = (await crawl(admin, limit=200)).payloads
    guest = Bench(cfg, course, store, user_id=STRANGER_ID)
    seen_by_guest = (await crawl(guest, limit=200)).payloads
    # Админское — то, чего гостю не показали. Определяется поведением, а не
    # префиксом callback_data: префикс переживёт не всякую перестройку.
    admin_only = sorted(seen_by_admin - seen_by_guest)
    assert len(admin_only) >= 10, "админских кнопок не найдено — проверять нечего"

    for data in admin_only:
        assert not _leaks(await guest.press(data)), f"{data!r} ответил постороннему"


async def test_a_stranger_cannot_switch_into_tester_mode(cfg, course, store):
    """Тестер-режим подменяет студента для всех экранов — это ключ от всех записей."""
    stranger = Bench(cfg, course, store, user_id=STRANGER_ID)
    cert = next(s for s in course.active if s.passed)
    for text in ("/test", f"Тест {cert.fio}", "/admin", "🛠 Админка"):
        await stranger.send(text)
    assert await store.test_view(STRANGER_ID) is None


def test_the_student_is_resolved_only_through_a_binding():
    """Страховка на случай нового модуля: прямой доступ к `course.students`.

    Глоб по всему пакету, а не по одной папке: рендереры экранов переезжают,
    и проверка, привязанная к `handlers/*.py`, перестала бы их видеть.
    """
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "mlbot"
    # Кому можно: админка (ищет по ФИО), онбординг (ещё нет привязки), deps
    # (сам и есть привязка), data и matching (владеют каталогом), announce и
    # selfcheck (скрипты без пользователя), __main__ (считает записи в лог).
    allowed = {"admin.py", "start.py", "deps.py", "data.py", "matching.py",
               "announce.py", "selfcheck.py", "__main__.py",
               # Подписывает адресатов рассылки: ключ приходит из привязки,
               # а не из нажатия — по сути это и есть «через привязку».
               "audiences.py"}
    checked = 0
    for path in sorted(src.rglob("*.py")):
        if path.name in allowed:
            continue
        checked += 1
        assert "course.students" not in path.read_text(encoding="utf-8"), path.name
    assert checked >= 10, "глоб ничего не нашёл — проверка выродилась"
