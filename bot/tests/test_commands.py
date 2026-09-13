"""Routing of commands and buttons.

The hole caught here: the onboarding state handler was bound to `F.text` and
swallowed commands along with plain text. Because of it an admin with no student
record could not reach the admin panel at all — `/admin` went into the name
search.
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
    """A command in the Menu button with no handler is a button that stays silent."""
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
    """Handlers bound to both a state and text."""
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
    """Enough for magic filters: they only read attributes."""


def _magic_filters(handler):
    from aiogram.utils.magic_filter import MagicFilter
    return [f.callback.__self__ for f in handler.filters or ()
            if isinstance(getattr(f.callback, "__self__", None), MagicFilter)]


@pytest.mark.parametrize("command", ["/admin", "/help", "/id", "/cancel"])
def test_onboarding_states_do_not_swallow_commands(command):
    """In an onboarding state, commands must reach their own handlers.

    The filter itself is checked: it must refuse text starting with a slash,
    otherwise the state handler answers a command with a name search.
    """
    checked = 0
    for name, handler in _state_text_handlers():
        if not name.endswith("start"):
            continue
        for magic in _magic_filters(handler):
            checked += 1
            assert not magic.resolve(FakeMessage(text=command)), (
                f"{handler.callback.__name__} catches {command}"
            )
            assert magic.resolve(FakeMessage(text="Иванов Иван")), (
                f"{handler.callback.__name__} перестал catchesь обычный текст"
            )
    assert checked >= 4, "no onboarding state handlers found"


def test_guest_keyboards_only_offer_what_works_without_binding(cfg):
    """Every guest button must lead to a node that works without a binding.

    There used to be a hardcoded list of captions here. It checked the current
    button text rather than a property, and any rename meant editing the test —
    without asking whether the menu had got better.
    """
    guest = SimpleNamespace(id=999, username=None)
    for label in (n.button for n in menu.roots(menu.Ctx(cfg=cfg, user=guest))):
        node = menu.by_label(label)
        assert node is not None, label
        assert not node.needs_student, f"guest was shown button {label!r}, which needs a binding"

    # An admin has no student record either — they need the panel.
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
    """The unknown-command fallback must not intercept other people's commands."""
    handlers = easter.router.message.handlers
    assert handlers[-1].callback.__name__ == "unknown_command"
    assert MODULES[-1] is easter


async def test_menu_button_in_onboarding_is_passed_along(course):
    """Onboarding must pass a menu button on rather than answering it itself.

    Otherwise an admin not yet bound to a student record presses Admin and is
    asked to send a repository link.
    """
    from aiogram.dispatcher.event.bases import SkipHandler

    sent: list[str] = []

    class Msg(SimpleNamespace):
        async def answer(self, text, **kw):
            sent.append(text)

    assert len(menu.root_labels()) >= 3, "no root buttons found"
    for label in menu.root_labels():
        with pytest.raises(SkipHandler):
            await start.got_identifier(
                Msg(text=label, from_user=SimpleNamespace(id=1, username=None)),
                None, course, None, None,
            )
    assert not sent, "onboarding answered a menu button instead of passing it on"
