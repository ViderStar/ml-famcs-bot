"""Versioned database schema.

`init()` used to just run `executescript(SCHEMA)` with `CREATE TABLE IF NOT
EXISTS`. New tables appear that way, new **columns** in existing ones do not:
the script silently does nothing, and the code starts reading a field the
database lacks. On a live database with 74 bindings that surfaces at runtime.

The version lives in `PRAGMA user_version` — an integer in the database file
header. No extra table is needed, and the version physically cannot drift from
the file it describes.

Rule: **migrations are append-only**. A released one is never edited — on a live
database it was applied long ago and the edit will never arrive. Inside, nothing
but `CREATE` and `ALTER TABLE ADD COLUMN`; nothing that loses data (pinned by
`test_migrations.py`).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import aiosqlite

# --- 1. Initial schema ---------------------------------------------------------
# State the bot itself produces. Grades and reviews are not kept here — they are
# read from disk.
_V1_BASE = """
CREATE TABLE IF NOT EXISTS bindings (
    tg_id       INTEGER PRIMARY KEY,
    student_key TEXT NOT NULL UNIQUE,
    username    TEXT,
    tg_name     TEXT,
    bound_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id    INTEGER NOT NULL,
    kind     TEXT NOT NULL,
    payload  TEXT,
    at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS events_kind ON events(kind);
CREATE INDEX IF NOT EXISTS events_tg ON events(tg_id);
-- Admin tester mode: whose eyes they are currently looking through.
-- Only admin handlers write here, so an ordinary account never has a row.
CREATE TABLE IF NOT EXISTS test_views (
    tg_id       INTEGER PRIMARY KEY,
    student_key TEXT NOT NULL,
    since       TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Claims for a record already tied to another telegram username.
-- Added after an outsider bound to a student's record using her name and
-- repository link: classmates know both.
CREATE TABLE IF NOT EXISTS claims (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id       INTEGER NOT NULL,
    student_key TEXT NOT NULL,
    username    TEXT,
    tg_name     TEXT,
    expected    TEXT,
    at          TEXT NOT NULL DEFAULT (datetime('now')),
    status      TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS claims_status ON claims(status);
CREATE TABLE IF NOT EXISTS support (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id    INTEGER NOT NULL,
    username TEXT,
    text     TEXT NOT NULL,
    at       TEXT NOT NULL DEFAULT (datetime('now')),
    answered INTEGER NOT NULL DEFAULT 0
);
"""

# --- 2. Fictional test entities ------------------------------------------------
# While an admin looks through a demo student's eyes, every press is written to
# `events` under the admin's own tg_id. Without this flag, invented visits land
# in "what people read" and in the summary — walking the bot would change its stats.
_V2_DEMO = """
ALTER TABLE bindings ADD COLUMN demo INTEGER NOT NULL DEFAULT 0;
ALTER TABLE events   ADD COLUMN demo INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS events_demo ON events(demo);
"""

# --- 3. Broadcasts from the interface -------------------------------------------
# The composite primary key on `broadcast_targets` makes a duplicate physically
# impossible: even a double launch will not send anyone two letters.
#
# The recipient list is frozen at confirmation, in one transaction with creating
# the broadcast. Resuming reads that list and **never re-decides the audience** —
# otherwise people who bound between the start and the crash would be swept in,
# and the report would lie about how many were sent.
_V3_BROADCASTS = """
CREATE TABLE IF NOT EXISTS broadcasts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_by   INTEGER NOT NULL,
    audience     TEXT NOT NULL,
    audience_arg TEXT,
    kind         TEXT NOT NULL DEFAULT 'text',   -- text | copy
    body         TEXT,
    src_chat     INTEGER,
    src_msg      INTEGER,
    status       TEXT NOT NULL DEFAULT 'draft',  -- draft|sending|stalled|done|cancelled
    sandbox      INTEGER NOT NULL DEFAULT 1,
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at  TEXT
);
CREATE TABLE IF NOT EXISTS broadcast_targets (
    broadcast_id INTEGER NOT NULL,
    tg_id        INTEGER NOT NULL,
    label        TEXT,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending|sent|blocked|failed
    error        TEXT,
    at           TEXT,
    PRIMARY KEY (broadcast_id, tg_id)
);
CREATE INDEX IF NOT EXISTS broadcast_targets_pending
    ON broadcast_targets(broadcast_id, status);
"""

# --- 4. Season 3 -----------------------------------------------------------------
# The key simplification: registration goes through the bot, so `tg_id` is known
# from the first message and cannot be forged. The whole class of problems that
# produced `claims` and `telegram_map.csv` simply does not arise in season 3.
#
# `username` is always stored but is **never a key** — only an attribute and a
# log: it gets released and goes to someone else, and that is exactly how an
# outsider opened another student's review in season 2.
_V4_SEASON3 = """
CREATE TABLE IF NOT EXISTS people (
    tg_id      INTEGER PRIMARY KEY,
    username   TEXT,
    tg_name    TEXT,
    fio        TEXT,
    email      TEXT,
    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen  TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Username change log: it changes, and lists used to be built on it.
CREATE TABLE IF NOT EXISTS identity_history (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_id    INTEGER NOT NULL,
    username TEXT,
    tg_name  TEXT,
    at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS identity_history_tg ON identity_history(tg_id);

CREATE TABLE IF NOT EXISTS s3_tracks (
    id       TEXT PRIMARY KEY,
    title    TEXT NOT NULL,
    emoji    TEXT,
    teacher  TEXT,
    lessons  INTEGER,
    about    TEXT,
    is_open  INTEGER NOT NULL DEFAULT 1,
    ord      INTEGER NOT NULL DEFAULT 0
);

-- Application. The draft lives here, not in FSM: MemoryStorage does not survive
-- a container restart, and a twelve-step form is not filled in a minute.
CREATE TABLE IF NOT EXISTS s3_applications (
    tg_id      INTEGER PRIMARY KEY,
    status     TEXT NOT NULL DEFAULT 'draft',   -- draft | submitted
    step       TEXT,
    answers    TEXT NOT NULL DEFAULT '{}',      -- JSON: answers by step
    rev        INTEGER NOT NULL DEFAULT 0,      -- grows on every edit
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    submitted_at TEXT
);
CREATE TABLE IF NOT EXISTS s3_enrollments (
    tg_id    INTEGER NOT NULL,
    track_id TEXT NOT NULL,
    at       TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (tg_id, track_id)
);

CREATE TABLE IF NOT EXISTS s3_repos (
    tg_id    INTEGER PRIMARY KEY,
    url      TEXT NOT NULL,
    owner    TEXT,
    repo     TEXT,
    at       TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Existence check result, timestamped so it can be cached.
CREATE TABLE IF NOT EXISTS s3_repo_checks (
    url     TEXT PRIMARY KEY,
    exists_ INTEGER,
    code    INTEGER,
    at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS s3_homeworks (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    num       INTEGER,
    title     TEXT NOT NULL,
    body      TEXT NOT NULL,
    deadline  TEXT,                             -- UTC; Minsk time is what we show
    materials TEXT,
    status    TEXT NOT NULL DEFAULT 'draft',    -- draft | published
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    published_at TEXT
);
CREATE TABLE IF NOT EXISTS s3_homework_tracks (
    homework_id INTEGER NOT NULL,
    track_id    TEXT NOT NULL,
    PRIMARY KEY (homework_id, track_id)
);
-- Homework delivery. Primary key on (homework, person): a student on both CV
-- and DL gets **one** message, not two.
CREATE TABLE IF NOT EXISTS s3_deliveries (
    homework_id INTEGER NOT NULL,
    tg_id       INTEGER NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    error       TEXT,
    at          TEXT,
    PRIMARY KEY (homework_id, tg_id)
);

CREATE TABLE IF NOT EXISTS s3_flags (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    kind    TEXT NOT NULL,
    payload TEXT,
    at      TEXT NOT NULL DEFAULT (datetime('now')),
    seen    INTEGER NOT NULL DEFAULT 0
);

-- Sync queue. Saving the application and enqueueing the task happen in **one
-- transaction**: there is no window between "form saved" and "task created" to
-- crash in, so "do not lose the form" holds by construction rather than by hope
-- placed in a try/except.
CREATE TABLE IF NOT EXISTS sync_outbox (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    sink     TEXT NOT NULL,                     -- csv | notion
    entity   TEXT NOT NULL,                     -- application
    key      TEXT NOT NULL,
    rev      INTEGER NOT NULL DEFAULT 0,
    tries    INTEGER NOT NULL DEFAULT 0,
    status   TEXT NOT NULL DEFAULT 'pending',   -- pending | done | diverged
    error    TEXT,
    at       TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS sync_outbox_pending ON sync_outbox(status, id);
-- What already arrived: a run of edits collapses to the last revision.
CREATE TABLE IF NOT EXISTS sync_state (
    sink        TEXT NOT NULL,
    entity      TEXT NOT NULL,
    key         TEXT NOT NULL,
    remote_id   TEXT,
    synced_rev  INTEGER NOT NULL DEFAULT -1,
    at          TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (sink, entity, key)
);
"""

MIGRATIONS: tuple[str, ...] = (_V1_BASE, _V2_DEMO, _V3_BROADCASTS, _V4_SEASON3)
LATEST = len(MIGRATIONS)


async def version(db: aiosqlite.Connection) -> int:
    async with db.execute("PRAGMA user_version") as cur:
        row = await cur.fetchone()
    return int(row[0]) if row else 0


def backup(path: Path, at_version: int) -> Path | None:
    """A copy of the database beside it, before the version goes up.

    The first copy is never overwritten: if a migration turned out to be broken
    and the bot restarted several times, the earliest one is the valuable one.
    """
    dst = path.with_name(f"{path.name}.v{at_version}.bak")
    if dst.exists():
        return dst
    shutil.copy2(path, dst)
    return dst


async def apply(db: aiosqlite.Connection) -> int:
    """Brings the schema up to `LATEST`. Returns the version it stopped at."""
    have = await version(db)
    for i in range(have, LATEST):
        await db.executescript(MIGRATIONS[i])
        # PRAGMA takes no bound parameters; `i` is a tuple index, not input.
        await db.execute(f"PRAGMA user_version = {i + 1}")
    await db.commit()
    return LATEST
