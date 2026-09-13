"""Маршрутизация команд и кнопок.

Дырка, которую здесь ловим: обработчик состояния онбординга был привязан к
`F.text` и съедал команды вместе с обычным текстом. Из-за этого администратор,
не привязанный к записи студента, не мог попасть в админку вообще никак —
`/admin` уходил в поиск по ФИО.
"""

from types import SimpleNamespace

import pytest
from aiogram.filters import Command
from aiogram.fsm.state import State

from mlbot import commands
from mlbot.__main__ import ROUTERS as MODULES
from mlbot.handlers import easter, start
from mlbot.menu import core as menu


def registered_commands() -> set[str]:
    out: set[str] = set()
    for module in MODULES:
        for handler in module.router.message.handlers:
            for flt in handler.filters or ():
                if isinstance(flt.callback, Command):
                    out |= {str(c) for c in flt.callback.commands}
    return out


def test_every_menu_command_has_a_handler():
    """Команда в кнопке «Меню» без обработчика — это кнопка, которая молчит."""
    listed = {c for c, _ in commands.STUDENT + commands.ADMIN}
    assert listed <= registered_commands(), listed - registered_commands()


def test_menu_descriptions_fit_telegram_limits():
    for cmd, desc in commands.STUDENT + commands.ADMIN:
        assert 1 <= len(cmd) <= 32 and cmd.islower()
        assert 3 <= len(desc) <= 256


def test_menu_has_no_duplicates():
    listed = [c for c, _ in commands.STUDENT + commands.ADMIN]
    assert len(listed) == len(set(listed))


def _state_text_handlers():
    """Обработчики, привязанные к состоянию и к тексту."""
    out = []
    for module in MODULES:
        for handler in module.router.message.handlers:
            has_state = any(isinstance(getattr(f.callback, "state", None), (State, str))
                            or type(f.callback).__name__ == "StateFilter"
                            for f in handler.filters or ())
            if has_state:
                out.append((module.__name__, handler))
    return out


class FakeMessage(SimpleNamespace):
    """Достаточно для magic-фильтров: они читают только атрибуты."""


def _magic_filters(handler):
    from aiogram.utils.magic_filter import MagicFilter
    return [f.callback.__self__ for f in handler.filters or ()
            if isinstance(getattr(f.callback, "__self__", None), MagicFilter)]


@pytest.mark.parametrize("command", ["/admin", "/help", "/id", "/cancel"])
def test_onboarding_states_do_not_swallow_commands(command):
    """В состоянии онбординга команды должны доходить до своих обработчиков.

    Проверяем сам фильтр: он обязан отказаться от текста, начинающегося со
    слэша, иначе обработчик состояния ответит на команду поиском по ФИО.
    """
    checked = 0
    for name, handler in _state_text_handlers():
        if not name.endswith("start"):
            continue
        for magic in _magic_filters(handler):
            checked += 1
            assert not magic.resolve(FakeMessage(text=command)), (
                f"{handler.callback.__name__} ловит {command}"
            )
            assert magic.resolve(FakeMessage(text="Иванов Иван")), (
                f"{handler.callback.__name__} перестал ловить обычный текст"
            )
    assert checked >= 4, "обработчики состояний онбординга не найдены"


def test_guest_keyboards_only_offer_what_works_without_binding(cfg):
    """Каждая кнопка гостя обязана вести в узел, работающий без привязки.

    Раньше здесь стоял жёсткий список подписей. Он проверял не свойство, а
    текущий текст кнопок, и любое переименование требовало править тест —
    не задумываясь, стало ли меню правильнее.
    """
    guest = SimpleNamespace(id=999, username=None)
    for label in (n.button for n in menu.roots(menu.Ctx(cfg=cfg, user=guest))):
        node = menu.by_label(label)
        assert node is not None, label
        assert not node.needs_student, f"гостю показана кнопка {label!r}, требующая привязки"

    # У администратора записи студента тоже нет — ему нужна панель.
    admin = SimpleNamespace(id=1, username="chief")
    labels = [n.button for n in menu.roots(menu.Ctx(cfg=cfg, user=admin))]
    assert "🛠 Админка" in labels
    assert menu.by_label("🛠 Админка") not in [menu.by_label(x) for x in
                                               (n.button for n in
                                                menu.roots(menu.Ctx(cfg=cfg, user=guest)))]


def test_help_lists_only_existing_commands():
    import re

    from mlbot import texts
    mentioned = set(re.findall(r"^/(\w+)", texts.HELP + "\n" + texts.HELP_ADMIN, re.M))
    assert mentioned <= registered_commands(), mentioned - registered_commands()


def test_unknown_command_fallback_is_last():
    """Заглушка на неизвестную команду не должна перехватывать чужие команды."""
    handlers = easter.router.message.handlers
    assert handlers[-1].callback.__name__ == "unknown_command"
    assert MODULES[-1] is easter


async def test_menu_button_in_onboarding_is_passed_along(course):
    """Кнопку меню онбординг обязан отдать дальше, а не отвечать на неё сам.

    Иначе администратор, ещё не привязанный к записи студента, жмёт «Админку»
    и получает просьбу прислать ссылку на репозиторий.
    """
    from aiogram.dispatcher.event.bases import SkipHandler

    sent: list[str] = []

    class Msg(SimpleNamespace):
        async def answer(self, text, **kw):
            sent.append(text)

    assert len(menu.root_labels()) >= 3, "корневых кнопок не нашлось"
    for label in menu.root_labels():
        with pytest.raises(SkipHandler):
            await start.got_identifier(
                Msg(text=label, from_user=SimpleNamespace(id=1, username=None)),
                None, course, None, None,
            )
    assert not sent, "онбординг ответил на кнопку меню вместо передачи дальше"
