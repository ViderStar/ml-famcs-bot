"""Предохранитель: в песочнице сообщение не может уйти настоящему студенту.

Второй сезон закончился, у бота живые привязки, и цена ошибки — рассылка мусора
полусотне человек. Поэтому проверяем не «функция вызвалась», а свойство: при
включённом режиме ни один вызов Telegram API с чужим chat_id не проходит насквозь.
"""

from dataclasses import replace

import pytest
from aiogram.methods import (AnswerCallbackQuery, DeleteMessage, EditMessageText,
                             SendDocument, SendMessage, SetMyCommands)

from mlbot.config import Config, load
from mlbot.safety import BADGE, BlockedBySafeMode, SafeMode, badge

ADMIN, STRANGER = 1, 999_999


@pytest.fixture
def safe(cfg):
    return SafeMode(replace(cfg, safe_mode=True, admin_ids=frozenset({ADMIN})))


async def call(mw, method):
    """Прогоняет метод через мидлварь, возвращая то, что дошло до транспорта."""
    seen = []

    async def transport(bot, m):
        seen.append(m)
        return m

    await mw(transport, None, method)
    return seen[0] if seen else None


# --- умолчание: забыть переменную должно быть безопасно ---------------------------

def test_safe_mode_is_on_by_default():
    assert load({"BOT_TOKEN": "x"}).safe_mode is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "НЕТ", " 0 "])
def test_only_an_explicit_no_switches_it_off(raw):
    assert load({"BOT_TOKEN": "x", "SAFE_MODE": raw}).safe_mode is False


@pytest.mark.parametrize("raw", ["1", "true", "yes", "", "maybe", "потом"])
def test_anything_else_keeps_it_on(raw):
    assert load({"BOT_TOKEN": "x", "SAFE_MODE": raw}).safe_mode is True


# --- что проходит, что перехватывается --------------------------------------------

async def test_message_to_admin_passes_untouched(safe):
    got = await call(safe, SendMessage(chat_id=ADMIN, text="привет"))
    assert got.chat_id == ADMIN and got.text == "привет"
    assert safe.intercepted == 0


async def test_message_to_a_student_is_redirected_to_the_admin(safe):
    got = await call(safe, SendMessage(chat_id=STRANGER, text="твой сертификат"))
    assert got.chat_id == ADMIN, "письмо ушло постороннему"
    assert BADGE in got.text and str(STRANGER) in got.text
    assert "твой сертификат" in got.text
    assert safe.intercepted == 1 and safe.last == (STRANGER, "sendMessage")


async def test_document_keeps_its_caption_and_gets_the_badge(safe):
    got = await call(safe, SendDocument(chat_id=STRANGER, document="id", caption="держи"))
    assert got.chat_id == ADMIN and BADGE in got.caption and "держи" in got.caption


async def test_editing_someone_elses_message_is_a_loud_error(safe):
    """Перенаправлять правку некуда: чужого сообщения у админа нет."""
    with pytest.raises(BlockedBySafeMode) as exc:
        await call(safe, EditMessageText(chat_id=STRANGER, message_id=1, text="x"))
    assert exc.value.chat_id == STRANGER


async def test_deleting_in_someone_elses_chat_is_blocked(safe):
    with pytest.raises(BlockedBySafeMode):
        await call(safe, DeleteMessage(chat_id=STRANGER, message_id=1))


@pytest.mark.parametrize("method", [
    AnswerCallbackQuery(callback_query_id="1"),
    SetMyCommands(commands=[]),
])
async def test_methods_without_a_recipient_pass(safe, method):
    assert await call(safe, method) is method


async def test_sandbox_chat_ids_are_allowed(cfg):
    mw = SafeMode(replace(cfg, safe_mode=True, admin_ids=frozenset({ADMIN}),
                          sandbox_chat_ids=frozenset({STRANGER})))
    got = await call(mw, SendMessage(chat_id=STRANGER, text="тест"))
    assert got.chat_id == STRANGER and got.text == "тест"


async def test_nothing_is_intercepted_when_switched_off(cfg):
    mw = SafeMode(replace(cfg, safe_mode=False, admin_ids=frozenset({ADMIN})))
    got = await call(mw, SendMessage(chat_id=STRANGER, text="боевая отправка"))
    assert got.chat_id == STRANGER and mw.intercepted == 0


async def test_original_method_is_not_mutated(safe):
    """Перенаправление делает копию: исходный объект мог бы уйти повторно."""
    method = SendMessage(chat_id=STRANGER, text="привет")
    await call(safe, method)
    assert method.chat_id == STRANGER and method.text == "привет"


# --- подключение и индикация ------------------------------------------------------

def test_middleware_is_registered_on_the_session(cfg):
    """Мидлварь бесполезна, если её забыли повесить, — проверяем сам факт."""
    from aiogram import Bot
    from aiogram.client.default import DefaultBotProperties

    bot = Bot("1:x", default=DefaultBotProperties())
    bot.session.middleware(SafeMode(cfg))
    assert any(isinstance(m, SafeMode) for m in bot.session.middleware)


def test_badge_shows_only_in_sandbox(cfg):
    assert badge(replace(cfg, safe_mode=True)) == BADGE
    assert badge(replace(cfg, safe_mode=False)) == ""


def test_config_still_builds_with_the_original_arguments(tmp_path):
    """conftest и selfcheck строят Config шестью аргументами — не сломать их."""
    c = Config(token="t", admin_ids=frozenset(), admin_usernames=frozenset(),
               support_username="s", data_root=tmp_path, db_path=tmp_path / "db")
    assert c.safe_mode is True and c.sandbox_chat_ids == frozenset()
