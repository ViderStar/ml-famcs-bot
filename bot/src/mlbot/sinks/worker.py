"""A single consumer of the `sync_outbox` queue.

There is exactly one consumer, so there are no races between sinks and no locks
are needed. Stale tasks are skipped by `synced_rev`: a run of form edits
collapses to the last one — Notion does not get ten requests in a row.

After several failures a task becomes `diverged` and raises a flag for the
admin. That is the only alternative to losing it silently.
"""

from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("sync")

SINKS = {}
IDLE = 5.0          # pause when the queue is empty
BACKOFF = 30.0      # pause after a failure: the network does not heal instantly


def _sinks():
    if not SINKS:
        from . import csv_file, notion
        SINKS.update({"csv": csv_file.sync, "notion": notion.sync})
    return SINKS


async def once(cfg, store) -> int:
    """Drain a batch. Returns how many tasks were closed."""
    done = 0
    for task in await store.outbox_batch():
        handler = _sinks().get(task["sink"])
        if handler is None:
            await store.outbox_failed(task, f"неизвестный приёмник {task['sink']!r}")
            continue
        # A newer revision already arrived — this task is simply stale.
        if await store.synced_rev(task["sink"], task["entity"], task["key"]) >= task["rev"]:
            await store.outbox_skip(task["id"])
            done += 1
            continue
        if task["sink"] == "notion" and not cfg.notion_ready:
            # No token is not an error but "not configured yet". The task waits
            # in the queue; the form is already saved and is going nowhere.
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
    """The background loop. Lives as long as the bot does."""
    while stop is None or not stop.is_set():
        try:
            done = await once(cfg, store)
        except Exception:
            log.exception("сбой в разгребателе очереди")
            done = 0
        await asyncio.sleep(IDLE if done else BACKOFF)
