"""Entry point: assembles the bot and starts long polling."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from . import commands, config, sinks, texts
from .safety import SafeMode
from .data import Course
from .handlers import admin, common, easter, season3, start, support
from .menu import router as menu
from .middlewares import DemoCourse, Identity, Throttle
from .store import Store


# Order matters. start goes first: its handlers are bound to onboarding states
# and stay silent outside them, but inside they must beat the menu buttons.
# menu comes before support: otherwise pressing a button in the middle of a
# support question would reach the teacher as the question text. easter is last:
# that is where the unknown-command fallback lives.
ROUTERS = (start, common, admin, menu, season3, support, easter)


def load_demo(cfg) -> Course | None:
    """Fictional students, if the directory is there. Their absence is not an error."""
    if not cfg.demo_findings.exists():
        return None
    return Course.load(cfg, findings_dir=cfg.demo_findings, season="demo")


def build_dispatcher(cfg, course: Course, store: Store,
                     demo: Course | None = None) -> Dispatcher:
    dp = Dispatcher(storage=MemoryStorage())
    dp["cfg"] = cfg
    dp["course"] = course
    dp["store"] = store
    dp["demo"] = demo

    # Throttling as an outer middleware only. An inner one wraps every handler
    # that fires, not the event: when onboarding passes a menu button on through
    # SkipHandler, the next handler is wrapped a second time for the same message
    # and muted as "too fast". An outer one fires once per event, before a
    # handler is chosen.
    dp.message.outer_middleware(Throttle())
    dp.callback_query.outer_middleware(Throttle(0.25))
    # Account memory after throttling: a muted press tells us nothing about the
    # person, so there is no reason to write to the database for it.
    dp.message.outer_middleware(Identity())
    dp.callback_query.outer_middleware(Identity())
    if demo is not None:
        dp.message.outer_middleware(DemoCourse(demo))
        dp.callback_query.outer_middleware(DemoCourse(demo))

    # Order matters — see the ROUTERS comment above.
    for module in ROUTERS:
        dp.include_router(module.router)
    return dp


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("mlbot")

    cfg = config.load()
    course = Course.load(cfg)
    store = Store(cfg.db_path)
    await store.init()
    log.info("loaded: %d students, %d catalog articles, %d topics",
             len(course.students), len(course.catalog), len(course.rubrics))
    if not cfg.admin_ids:
        log.warning("ADMIN_IDS is empty — the admin panel is reachable by nobody")

    bot = Bot(cfg.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # The safety catch goes on before anything else: from this point no Telegram
    # API call can reach a foreign chat past it.
    safe = SafeMode(cfg)
    bot.session.middleware(safe)
    if cfg.safe_mode:
        log.info("SAFE_MODE on: messages reach admins and the sandbox only")
    else:
        log.warning("SAFE_MODE OFF: messages will reach real students")
    demo = load_demo(cfg)
    if demo is not None:
        log.info("fictional students loaded: %d", len(demo.students))
    dp = build_dispatcher(cfg, course, store, demo)

    # A broadcast caught by a restart would read "sending" forever. Mark such
    # ones interrupted and say so out loud: they resume with a button, and nobody
    # gets anything twice — the recipient list is frozen.
    stalled = await store.stall_running()
    if stalled:
        log.warning("interrupted broadcasts: %s", ", ".join(f"#{i}" for i in stalled))

    # One background consumer drains the queue into the file and Notion: one
    # means no races and no locking.
    asyncio.create_task(sinks.worker.run(cfg, store))
    if not cfg.notion_ready:
        log.info("Notion not configured — applications queue up and arrive later")

    await bot.delete_webhook(drop_pending_updates=True)
    await commands.setup(bot, cfg.admin_ids)
    for admin_id in cfg.admin_ids if stalled else ():
        try:
            await bot.send_message(admin_id, texts.CAST_STALLED.format(
                ids=", ".join(f"#{i}" for i in stalled)))
        except Exception:
            continue
    log.info("bot started")
    await dp.start_polling(bot)


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
