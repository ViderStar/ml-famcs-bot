"""Кому писать. Реестр — по той же причине, что и реестр меню: чтобы новую
аудиторию можно было добавить одной строкой, а тест мог обойти все.

Непривязанным бот написать не может: Bot API не даёт писать первым. Поэтому у
каждой аудитории есть ещё и «недостижимые» — их видно на экране, и их можно
выгрузить, чтобы позвать людей каналом.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

Target = tuple[int, str]          # чат и подпись для отчёта
Picked = tuple[list[Target], list[str]]   # кому пишем, кого не достаём


@dataclass(frozen=True)
class Audience:
    id: str
    title: str
    pick: Callable[..., Awaitable[Picked]]
    sandbox_safe: bool = False    # можно ли выбирать при включённом предохранителе


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
    """Та же выборка, что у скрипта рассылки сертификатов, — и это закреплено тестом."""
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
    """Аккаунты, помеченные тестовыми: они и есть адресаты проверочной рассылки."""
    everyone_ = await store.all_bindings(include_demo=True)
    real = {b.tg_id for b in await store.all_bindings()}
    return [(b.tg_id, b.tg_name or str(b.tg_id))
            for b in everyone_ if b.tg_id not in real], []


@audience("me", "Только себе", sandbox_safe=True)
async def just_me(cfg, course, store, who: int | None = None) -> Picked:
    return ([(who, "ты")] if who else []), []


def available(cfg) -> list[Audience]:
    """В песочнице — только безопасные.

    Второй замок к предохранителю: даже если тот пропустит сообщение, список
    настоящих студентов рассылке просто неоткуда взять.
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
