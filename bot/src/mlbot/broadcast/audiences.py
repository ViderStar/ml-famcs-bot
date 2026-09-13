"""Who to write to. A registry, for the same reason the menu is one: a new
audience is one line, and a test can walk them all.

The bot cannot write to unbound people: the Bot API does not allow writing
first. So every audience also reports the "unreachable" — they are shown on the
screen and can be exported, to invite those people through the channel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

Target = tuple[int, str]          # chat and a label for the report
Picked = tuple[list[Target], list[str]]   # who we write to, who we cannot reach


@dataclass(frozen=True)
class Audience:
    id: str
    title: str
    pick: Callable[..., Awaitable[Picked]]
    sandbox_safe: bool = False    # may it be chosen while the safety catch is on


REGISTRY: dict[str, Audience] = {}


def audience(id: str, title: str, sandbox_safe: bool = False):
    def wrap(fn):
        REGISTRY[id] = Audience(id, title, fn, sandbox_safe)
        return fn
    return wrap


def _fio(course, key: str) -> str:
    st = course.students.get(key)
    return st.fio if st else key


@audience("all", "Всем привязанным")
async def everyone(cfg, course, store) -> Picked:
    bindings = await store.all_bindings()
    bound = {b.student_key for b in bindings}
    unreachable = [s.fio for s in course.active if s.key not in bound]
    return [(b.tg_id, _fio(course, b.student_key)) for b in bindings], unreachable


@audience("cert", "С сертификатом")
async def with_certificate(cfg, course, store) -> Picked:
    """The same query the certificate mailing script uses — pinned by a test."""
    bound = {b.student_key: b.tg_id for b in await store.all_bindings()}
    pairs = [(st, bound[st.key]) for st in course.active
             if st.certificate and st.key in bound]
    pairs.sort(key=lambda p: p[0].fio.casefold())
    unreachable = [s.fio for s in course.active if s.certificate and s.key not in bound]
    return [(tg, st.fio) for st, tg in pairs], unreachable


@audience("nocert", "Без сертификата")
async def without_certificate(cfg, course, store) -> Picked:
    bound = {b.student_key: b.tg_id for b in await store.all_bindings()}
    out = [(bound[st.key], st.fio) for st in course.active
           if not st.certificate and st.key in bound]
    unreachable = [s.fio for s in course.active
                   if not s.certificate and s.key not in bound]
    return out, unreachable


@audience("demo", "Вымышленные аккаунты", sandbox_safe=True)
async def demo(cfg, course, store) -> Picked:
    """Accounts marked as test ones: they are the recipients of a trial broadcast."""
    everyone_ = await store.all_bindings(include_demo=True)
    real = {b.tg_id for b in await store.all_bindings()}
    return [(b.tg_id, b.tg_name or str(b.tg_id))
            for b in everyone_ if b.tg_id not in real], []


@audience("me", "Только себе", sandbox_safe=True)
async def just_me(cfg, course, store, who: int | None = None) -> Picked:
    return ([(who, "ты")] if who else []), []


def available(cfg) -> list[Audience]:
    """In the sandbox, only the safe ones.

    The second lock behind the safety catch: even if it lets a message through,
    a broadcast has nowhere to get a list of real students.
    """
    items = sorted(REGISTRY.values(), key=lambda a: a.id)
    if cfg.safe_mode:
        return [a for a in items if a.sandbox_safe]
    return items


async def resolve(audience_id: str, cfg, course, store, who: int | None = None) -> Picked:
    aud = REGISTRY[audience_id]
    if audience_id == "me":
        return await aud.pick(cfg, course, store, who)
    return await aud.pick(cfg, course, store)
