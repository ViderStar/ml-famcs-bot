"""Версионированная схема базы.

Раньше `init()` просто прогонял `executescript(SCHEMA)` с `CREATE TABLE IF NOT
EXISTS`. Новые таблицы так появляются, а новые **колонки** в уже существующих —
нет: скрипт молча ничего не делает, и код начинает читать поле, которого в базе
нет. На живой базе с 74 привязками это выяснилось бы в рантайме.

Версия лежит в `PRAGMA user_version` — целое число в заголовке файла базы.
Отдельная таблица не нужна, и версия физически не может разойтись с файлом,
который описывает.

Правило: **миграции только дописываются в конец**. Уже выпущенную не
редактируют — на живой базе она давно применена, и правка туда не доедет.
Внутри — только `CREATE` и `ALTER TABLE ADD COLUMN`; ничего, что теряет данные
(закреплено тестом `test_migrations.py`).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import aiosqlite

# --- 1. Исходная схема ---------------------------------------------------------
# Состояние, которое порождает сам бот. Оценки и разборы здесь не хранятся —
# они читаются с диска.
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
-- Тестер-режим администратора: чьими глазами он сейчас смотрит на бота.
-- Пишут сюда только админские обработчики, поэтому у обычного аккаунта записи
-- здесь не бывает.
CREATE TABLE IF NOT EXISTS test_views (
    tg_id       INTEGER PRIMARY KEY,
    student_key TEXT NOT NULL,
    since       TEXT NOT NULL DEFAULT (datetime('now'))
);
-- Заявки на доступ к записи, за которой уже закреплён другой telegram-username.
-- Появились после случая, когда посторонний аккаунт привязался к записи студентки
-- по её ФИО и ссылке на репозиторий: и то и другое известно однокурсникам.
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

# --- 2. Вымышленные тестовые сущности ------------------------------------------
# Пока админ смотрит глазами демо-студента, каждое его нажатие пишется в
# `events` под его же tg_id. Без этой пометки выдуманные визиты попадут в
# «Что читают» и в сводку — то есть проверка бота будет менять его статистику.
_V2_DEMO = """
ALTER TABLE bindings ADD COLUMN demo INTEGER NOT NULL DEFAULT 0;
ALTER TABLE events   ADD COLUMN demo INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS events_demo ON events(demo);
"""

# --- 3. Рассылки через интерфейс -----------------------------------------------
# Составной первичный ключ в `broadcast_targets` делает дубль физически
# невозможным: даже двойной запуск не отправит человеку два письма.
#
# Список адресатов замораживается в момент подтверждения, одной транзакцией с
# созданием рассылки. Возобновление читает этот список и **никогда не
# перерешивает аудиторию** — иначе в добавку попали бы привязавшиеся между
# началом и обрывом, а отчёт соврал бы про число отправленных.
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

# --- 4. Третий сезон -----------------------------------------------------------
# Ключевое упрощение: регистрация идёт через бота, значит `tg_id` известен с
# первого сообщения и подделать его нельзя. Весь класс проблем, породивший
# `claims` и `telegram_map.csv`, в третьем сезоне просто не возникает.
#
# `username` хранится всегда, но **никогда не ключ** — только атрибут и журнал:
# он освобождается и достаётся другому человеку, и именно на этом во втором
# сезоне посторонний аккаунт открыл чужой разбор.
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
-- Журнал смены username: он меняется, а списки составлялись по нему.
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

-- Анкета. Черновик живёт здесь, а не в FSM: MemoryStorage не переживает
-- перезапуск контейнера, а анкету на двенадцать шагов заполняют не за минуту.
CREATE TABLE IF NOT EXISTS s3_applications (
    tg_id      INTEGER PRIMARY KEY,
    status     TEXT NOT NULL DEFAULT 'draft',   -- draft | submitted
    step       TEXT,
    answers    TEXT NOT NULL DEFAULT '{}',      -- JSON: ответы по шагам
    rev        INTEGER NOT NULL DEFAULT 0,      -- растёт на каждой правке
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
-- Результат проверки существования — с временем, чтобы кэшировать.
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
    deadline  TEXT,                             -- UTC; минское время показываем
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
-- Выдача домашки. Первичный ключ по (домашка, человек): студент на CV и на DL
-- получает **одно** сообщение, а не два.
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

-- Очередь синхронизации. Запись анкеты и постановка задания идут **одной
-- транзакцией**: между «анкета сохранена» и «задание создано» нет окна, в
-- которое можно упасть, поэтому «не потерять анкету» выполняется
-- конструктивно, а не надеждой на try/except.
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
-- Что уже доехало: серия правок схлопывается до последней ревизии.
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
    """Копия базы рядом, перед повышением версии.

    Первая копия не перезаписывается: если миграция оказалась кривой и бот
    перезапустился несколько раз, ценна именно самая ранняя.
    """
    dst = path.with_name(f"{path.name}.v{at_version}.bak")
    if dst.exists():
        return dst
    shutil.copy2(path, dst)
    return dst


async def apply(db: aiosqlite.Connection) -> int:
    """Догоняет схему до `LATEST`. Возвращает версию, на которой остановились."""
    have = await version(db)
    for i in range(have, LATEST):
        await db.executescript(MIGRATIONS[i])
        # PRAGMA не принимает параметры подстановки; `i` — индекс кортежа, не ввод.
        await db.execute(f"PRAGMA user_version = {i + 1}")
    await db.commit()
    return LATEST
