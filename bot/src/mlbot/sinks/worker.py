"""Один потребитель очереди `sync_outbox`.

Потребитель ровно один, поэтому гонок между приёмниками нет и блокировок не
нужно. Устаревшие задания пропускаются по `synced_rev`: серия правок анкеты
схлопывается до последней — в Notion не полетит десять запросов подряд.

После нескольких неудач задание становится `diverged` и поднимает флаг
администратору. Это единственная альтернатива тихой потере.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("sync")

SINKS = {}
IDLE = 5.0          # пауза, когда очередь пуста
BACKOFF = 30.0      # пауза после неудачи: сеть чинится не мгновенно


def _sinks():
    if not SINKS:
        from . import csv_file, notion
        SINKS.update({"csv": csv_file.sync, "notion": notion.sync})
    return SINKS


async def once(cfg, store) -> int:
    """Разгрести пачку. Возвращает, сколько заданий закрыто."""
    done = 0
    for task in await store.outbox_batch():
        handler = _sinks().get(task["sink"])
        if handler is None:
            await store.outbox_failed(task, f"неизвестный приёмник {task['sink']!r}")
            continue
        # Более свежая ревизия уже доехала — это задание просто устарело.
        if await store.synced_rev(task["sink"], task["entity"], task["key"]) >= task["rev"]:
            await store.outbox_skip(task["id"])
            done += 1
            continue
        if task["sink"] == "notion" and not cfg.notion_ready:
            # Токена нет — не ошибка, а «ещё не настроено». Задание ждёт в
            # очереди; анкета при этом уже сохранена и никуда не денется.
            continue
        try:
            remote = await handler(cfg, store, task)
        except Exception as exc:
            status = await store.outbox_failed(task, f"{type(exc).__name__}: {exc}")
            log.warning("приёмник %s, ключ %s: %s (%s)",
                        task["sink"], task["key"], exc, status)
            continue
        await store.mark_synced(task, remote if isinstance(remote, str) else None)
        done += 1
    return done


async def run(cfg, store, stop: asyncio.Event | None = None) -> None:
    """Фоновый цикл. Живёт столько же, сколько бот."""
    while stop is None or not stop.is_set():
        try:
            done = await once(cfg, store)
        except Exception:
            log.exception("сбой в разгребателе очереди")
            done = 0
        await asyncio.sleep(IDLE if done else BACKOFF)
