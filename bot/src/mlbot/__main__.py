"""Точка входа: собирает бота и запускает long polling."""

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


# Порядок значим. start — первым: его обработчики привязаны к состояниям
# онбординга и вне их молчат, зато внутри должны выигрывать у кнопок меню.
# menu идёт до support: иначе нажатие кнопки посреди вопроса в поддержку
# уехало бы преподавателю как текст вопроса. easter — последним: там
# заглушка на неизвестную команду.
ROUTERS = (start, common, admin, menu, season3, support, easter)


def load_demo(cfg) -> Course | None:
    """Вымышленные студенты, если каталог на месте. Их отсутствие не ошибка."""
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

    # Троттлинг — только внешней мидлварью. Внутренняя оборачивает каждый
    # сработавший обработчик, а не событие: когда онбординг отдаёт кнопку меню
    # дальше через SkipHandler, следующий обработчик оборачивается второй раз
    # для того же сообщения и глушится как «слишком быстро». Внешняя
    # срабатывает один раз на событие, до выбора обработчика.
    dp.message.outer_middleware(Throttle())
    dp.callback_query.outer_middleware(Throttle(0.25))
    # Память об аккаунте — после троттлинга: заглушённое нажатие ничего не
    # сообщает о человеке, писать из-за него в базу незачем.
    dp.message.outer_middleware(Identity())
    dp.callback_query.outer_middleware(Identity())
    if demo is not None:
        dp.message.outer_middleware(DemoCourse(demo))
        dp.callback_query.outer_middleware(DemoCourse(demo))

    # Порядок важен. start идёт первым: его обработчики привязаны к состояниям
    # онбординга и вне их не срабатывают, зато внутри должны выигрывать у
    # пасхалок и кнопок меню. easter — последним: там заглушка на неизвестную
    # команду.
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
    log.info("загружено: студентов %d, статей каталога %d, тем %d",
             len(course.students), len(course.catalog), len(course.rubrics))
    if not cfg.admin_ids:
        log.warning("ADMIN_IDS пуст — админка недоступна никому")

    bot = Bot(cfg.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # Предохранитель ставится до всего остального: с этого момента ни один вызов
    # Telegram API не может уйти постороннему чату мимо него.
    safe = SafeMode(cfg)
    bot.session.middleware(safe)
    if cfg.safe_mode:
        log.info("SAFE_MODE включён: сообщения уходят только админам и песочнице")
    else:
        log.warning("SAFE_MODE ВЫКЛЮЧЕН: сообщения уйдут живым студентам")
    demo = load_demo(cfg)
    if demo is not None:
        log.info("демо-студентов загружено: %d", len(demo.students))
    dp = build_dispatcher(cfg, course, store, demo)

    # Рассылка, застигнутая перезапуском, числилась бы «отправляется» вечно.
    # Помечаем такие оборванными и говорим об этом вслух: продолжить их можно
    # кнопкой, и дважды никто ничего не получит — список адресатов заморожен.
    stalled = await store.stall_running()
    if stalled:
        log.warning("оборванные рассылки: %s", ", ".join(f"#{i}" for i in stalled))

    # Очередь в файл и Notion разгребает один фоновой потребитель: один —
    # значит без гонок и без блокировок.
    asyncio.create_task(sinks.worker.run(cfg, store))
    if not cfg.notion_ready:
        log.info("Notion не настроен — анкеты копятся в очереди и дойдут позже")

    await bot.delete_webhook(drop_pending_updates=True)
    await commands.setup(bot, cfg.admin_ids)
    for admin_id in cfg.admin_ids if stalled else ():
        try:
            await bot.send_message(admin_id, texts.CAST_STALLED.format(
                ids=", ".join(f"#{i}" for i in stalled)))
        except Exception:
            continue
    log.info("бот запущен")
    await dp.start_polling(bot)


def run() -> None:
    asyncio.run(main())


if __name__ == "__main__":
    run()
