"""Состояние бота в SQLite: привязки, события, обращения в поддержку.

Оценки и разборы здесь не хранятся — они читаются с диска. В базе только то,
что порождает сам бот.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from . import migrations
from .config import DEMO_PREFIX


@dataclass
class Binding:
    tg_id: int
    student_key: str
    username: str | None
    tg_name: str | None
    bound_at: str
    demo: int = 0  # вымышленный аккаунт для проверки бота


class Store:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    async def init(self) -> None:
        """Догоняет схему до последней версии, сохранив копию непустой базы."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Размер смотрим до подключения: aiosqlite создаёт файл сама, и после
        # этого «была ли база» уже не отличить от «только что завели».
        existed = self.path.exists() and self.path.stat().st_size > 0
        async with aiosqlite.connect(self.path) as db:
            have = await migrations.version(db)
            if existed and have < migrations.LATEST:
                migrations.backup(self.path, have)
            await migrations.apply(db)

    async def sent_awards(self) -> list[dict]:
        """Кому уже ушла рассылка с сертификатом — чтобы не отправить дважды."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT DISTINCT tg_id FROM events WHERE kind = 'awards_sent'"
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # --- заявки на доступ -------------------------------------------------------

    async def add_claim(self, tg_id: int, student_key: str, username: str | None,
                        tg_name: str | None, expected: str | None) -> int:
        """Заявка на ручную проверку. Повторная от того же аккаунта не дублируется."""
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id FROM claims WHERE tg_id = ? AND student_key = ? AND status = 'pending'",
                (tg_id, student_key),
            ) as cur:
                row = await cur.fetchone()
            if row:
                return int(row[0])
            cur = await db.execute(
                "INSERT INTO claims (tg_id, student_key, username, tg_name, expected) "
                "VALUES (?, ?, ?, ?, ?)",
                (tg_id, student_key, username, tg_name, expected),
            )
            await db.commit()
            return int(cur.lastrowid)

    async def pending_claims(self, limit: int = 30) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM claims WHERE status = 'pending' ORDER BY at LIMIT ?", (limit,)
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def claim(self, claim_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM claims WHERE id = ?", (claim_id,)) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

    async def resolve_claim(self, claim_id: int, status: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE claims SET status = ? WHERE id = ?", (status, claim_id))
            await db.commit()

    # --- тестер-режим -----------------------------------------------------------

    async def set_test_view(self, tg_id: int, student_key: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO test_views(tg_id, student_key) VALUES (?, ?) "
                "ON CONFLICT(tg_id) DO UPDATE SET student_key = excluded.student_key, "
                "since = datetime('now')",
                (tg_id, student_key),
            )
            await db.commit()

    async def test_view(self, tg_id: int) -> str | None:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT student_key FROM test_views WHERE tg_id = ?", (tg_id,)
            ) as cur:
                row = await cur.fetchone()
        return row[0] if row else None

    async def clear_test_view(self, tg_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM test_views WHERE tg_id = ?", (tg_id,))
            await db.commit()

    # --- привязки ---------------------------------------------------------------

    async def bind(self, tg_id: int, student_key: str, username: str | None,
                   tg_name: str | None, demo: bool = False) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO bindings (tg_id, student_key, username, tg_name, demo) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(tg_id) DO UPDATE SET student_key=excluded.student_key, "
                "username=excluded.username, tg_name=excluded.tg_name",
                (tg_id, student_key, username, tg_name, int(demo)),
            )
            await db.commit()

    async def mark_demo(self, tg_id: int, demo: bool = True) -> None:
        """Пометить аккаунт вымышленным: он исчезает из сводок и рассылок «всем»."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE bindings SET demo = ? WHERE tg_id = ?", (int(demo), tg_id))
            await db.commit()

    async def binding(self, tg_id: int) -> Binding | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM bindings WHERE tg_id = ?", (tg_id,)) as cur:
                row = await cur.fetchone()
        return Binding(**dict(row)) if row else None

    async def binding_of_student(self, student_key: str) -> Binding | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM bindings WHERE student_key = ?", (student_key,)
            ) as cur:
                row = await cur.fetchone()
        return Binding(**dict(row)) if row else None

    async def unbind(self, tg_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM bindings WHERE tg_id = ?", (tg_id,))
            await db.commit()

    async def all_bindings(self, include_demo: bool = False) -> list[Binding]:
        """Настоящие привязки. Демо приходится исключать по умолчанию: иначе
        вымышленный аккаунт попадёт и в «Кто привязался», и в адресаты рассылки."""
        where = "" if include_demo else " WHERE demo = 0"
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(f"SELECT * FROM bindings{where} ORDER BY bound_at") as cur:
                rows = await cur.fetchall()
        return [Binding(**dict(r)) for r in rows]

    async def binding_number(self, tg_id: int) -> int:
        """Порядковый номер привязки — для пасхалки «ты N-й»."""
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM bindings WHERE demo = 0 AND bound_at <= "
                "(SELECT bound_at FROM bindings WHERE tg_id = ?)", (tg_id,)
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else 0

    # --- события ----------------------------------------------------------------

    async def log(self, tg_id: int, kind: str, payload: dict | None = None) -> None:
        """Событие. Признак «демо» вычисляется тут же подзапросом.

        Иначе его пришлось бы прокидывать через полсотни вызовов `log` в
        обработчиках — и достаточно забыть один, чтобы выдуманные нажатия
        просочились в статистику.
        """
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO events (tg_id, kind, payload, demo) VALUES (?, ?, ?, "
                "  EXISTS(SELECT 1 FROM test_views"
                f"         WHERE tg_id = ? AND student_key LIKE '{DEMO_PREFIX}%'))",
                (tg_id, kind, json.dumps(payload, ensure_ascii=False) if payload else None, tg_id),
            )
            await db.commit()

    async def count_event(self, tg_id: int, kind: str, payload_like: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM events WHERE tg_id = ? AND kind = ? AND payload LIKE ?",
                (tg_id, kind, f"%{payload_like}%"),
            ) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else 0

    async def top_events(self, kind: str, limit: int = 15) -> list[tuple[str, int]]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT payload, COUNT(*) c FROM events "
                "WHERE kind = ? AND payload IS NOT NULL AND demo = 0 "
                "GROUP BY payload ORDER BY c DESC LIMIT ?", (kind, limit),
            ) as cur:
                rows = await cur.fetchall()
        return [(r[0], r[1]) for r in rows]

    async def event_totals(self) -> dict[str, int]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT kind, COUNT(*) FROM events WHERE demo = 0 "
                "GROUP BY kind ORDER BY 2 DESC"
            ) as cur:
                rows = await cur.fetchall()
        return {r[0]: r[1] for r in rows}

    # --- поддержка --------------------------------------------------------------

    async def add_support(self, tg_id: int, username: str | None, text: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO support (tg_id, username, text) VALUES (?, ?, ?)",
                (tg_id, username, text),
            )
            await db.commit()
            return int(cur.lastrowid)

    async def answer_support(self, ticket_id: int) -> dict | None:
        """Пометить отвеченным. Раньше `answered` только читалось — снять флаг
        было нечем, и список открытых обращений рос вечно."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM support WHERE id = ?", (ticket_id,)) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            await db.execute("UPDATE support SET answered = 1 WHERE id = ?", (ticket_id,))
            await db.commit()
        return dict(row)

    async def open_support(self, limit: int = 20) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM support WHERE answered = 0 ORDER BY at DESC LIMIT ?", (limit,)
            ) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # --- рассылки ---------------------------------------------------------------

    async def create_broadcast(self, created_by: int, audience: str, kind: str,
                               body: str | None, targets: list[tuple[int, str]],
                               sandbox: bool, audience_arg: str | None = None,
                               src: tuple[int, int] | None = None) -> int:
        """Черновик и список адресатов — одной транзакцией.

        Список замораживается здесь и больше не пересчитывается: возобновление
        обязано дослать ровно остаток, а не тех, кто привязался за это время.
        """
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO broadcasts (created_by, audience, audience_arg, kind, body, "
                "src_chat, src_msg, sandbox) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (created_by, audience, audience_arg, kind, body,
                 src[0] if src else None, src[1] if src else None, int(sandbox)),
            )
            cast_id = int(cur.lastrowid)
            await db.executemany(
                "INSERT OR IGNORE INTO broadcast_targets (broadcast_id, tg_id, label) "
                "VALUES (?, ?, ?)",
                [(cast_id, tg_id, label) for tg_id, label in targets],
            )
            await db.commit()
        return cast_id

    async def broadcast(self, cast_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM broadcasts WHERE id = ?", (cast_id,)) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

    async def start_broadcast(self, cast_id: int) -> bool:
        """Перевод в «отправляется» — атомарный.

        Поэтому двойное нажатие кнопки безвредно: второе просто не находит, что
        переводить, и возвращает False.
        """
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "UPDATE broadcasts SET status = 'sending' "
                "WHERE id = ? AND status IN ('draft', 'stalled')", (cast_id,))
            await db.commit()
            return cur.rowcount > 0

    async def cancel_broadcast(self, cast_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "UPDATE broadcasts SET status = 'cancelled', finished_at = datetime('now') "
                "WHERE id = ? AND status IN ('draft', 'stalled')", (cast_id,))
            await db.commit()
            return cur.rowcount > 0

    async def finish_broadcast(self, cast_id: int, status: str = "done") -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE broadcasts SET status = ?, finished_at = datetime('now') "
                "WHERE id = ?", (status, cast_id))
            await db.commit()

    async def stall_running(self) -> list[int]:
        """При старте: то, что «отправлялось», на деле оборвалось вместе с ботом."""
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id FROM broadcasts WHERE status = 'sending'") as cur:
                ids = [int(r[0]) for r in await cur.fetchall()]
            if ids:
                await db.execute(
                    "UPDATE broadcasts SET status = 'stalled' WHERE status = 'sending'")
                await db.commit()
        return ids

    async def pending_targets(self, cast_id: int, limit: int = 500) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM broadcast_targets WHERE broadcast_id = ? "
                "AND status = 'pending' ORDER BY tg_id LIMIT ?", (cast_id, limit)) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def mark_target(self, cast_id: int, tg_id: int, status: str,
                          error: str | None = None) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE broadcast_targets SET status = ?, error = ?, at = datetime('now') "
                "WHERE broadcast_id = ? AND tg_id = ?", (status, error, cast_id, tg_id))
            await db.commit()

    async def broadcast_stats(self, cast_id: int) -> dict[str, int]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT status, COUNT(*) FROM broadcast_targets WHERE broadcast_id = ? "
                "GROUP BY status", (cast_id,)) as cur:
                rows = await cur.fetchall()
        return {r[0]: r[1] for r in rows}

    async def recent_broadcasts(self, limit: int = 15) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM broadcasts ORDER BY id DESC LIMIT ?", (limit,)) as cur:
                rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # --- что бот знает о человеке -----------------------------------------------

    async def about(self, tg_id: int) -> dict:
        """Всё, что в базе связано с этим аккаунтом. Для экрана «Мои данные»."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            out: dict = {"tg_id": tg_id}
            async with db.execute("SELECT * FROM bindings WHERE tg_id = ?", (tg_id,)) as cur:
                row = await cur.fetchone()
            out["binding"] = dict(row) if row else None
            async with db.execute(
                "SELECT kind, COUNT(*) c, MIN(at) first, MAX(at) last FROM events "
                "WHERE tg_id = ? GROUP BY kind ORDER BY c DESC", (tg_id,)) as cur:
                out["events"] = [dict(r) for r in await cur.fetchall()]
            async with db.execute(
                "SELECT id, text, at, answered FROM support WHERE tg_id = ? ORDER BY at",
                (tg_id,)) as cur:
                out["support"] = [dict(r) for r in await cur.fetchall()]
            async with db.execute(
                "SELECT id, student_key, status, at FROM claims WHERE tg_id = ? ORDER BY at",
                (tg_id,)) as cur:
                out["claims"] = [dict(r) for r in await cur.fetchall()]
        return out

    async def forget(self, tg_id: int) -> dict[str, int]:
        """Удалить привязку, историю нажатий, заявки и тестер-режим.

        Обращения в поддержку остаются: это переписка с живым человеком, и
        стереть её в одностороннем порядке нельзя. Экран говорит об этом прямо.
        """
        removed: dict[str, int] = {}
        async with aiosqlite.connect(self.path) as db:
            for table in ("bindings", "events", "claims", "test_views"):
                cur = await db.execute(f"DELETE FROM {table} WHERE tg_id = ?", (tg_id,))
                removed[table] = cur.rowcount
            await db.commit()
        return removed

    # --- люди: username хранится, но ключом не бывает ------------------------------

    async def touch_person(self, tg_id: int, username: str | None,
                           tg_name: str | None) -> bool:
        """Запомнить аккаунт и записать смену username в журнал.

        Username освобождается и достаётся другому человеку — во втором сезоне
        ровно на этом посторонний аккаунт открыл чужой разбор. Поэтому он здесь
        атрибут и история, а связывает всё `tg_id`.
        """
        changed = False
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT username FROM people WHERE tg_id = ?", (tg_id,)) as cur:
                row = await cur.fetchone()
            if row is None:
                await db.execute(
                    "INSERT INTO people (tg_id, username, tg_name) VALUES (?, ?, ?)",
                    (tg_id, username, tg_name))
                changed = True
            else:
                changed = (row[0] or "") != (username or "")
                await db.execute(
                    "UPDATE people SET username = ?, tg_name = ?, last_seen = datetime('now') "
                    "WHERE tg_id = ?", (username, tg_name, tg_id))
            if changed:
                await db.execute(
                    "INSERT INTO identity_history (tg_id, username, tg_name) "
                    "VALUES (?, ?, ?)", (tg_id, username, tg_name))
            await db.commit()
        return changed

    async def identity_trail(self, tg_id: int) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM identity_history WHERE tg_id = ? ORDER BY at", (tg_id,)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    # --- анкета третьего сезона ----------------------------------------------------

    async def application(self, tg_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM s3_applications WHERE tg_id = ?", (tg_id,)) as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        out = dict(row)
        out["answers"] = json.loads(out["answers"] or "{}")
        return out

    async def save_answer(self, tg_id: int, step_id: str | None, value,
                          next_step: str | None = None) -> dict:
        """Записать ответ в черновик. Черновик в SQLite, а не в FSM.

        `MemoryStorage` не переживает перезапуск контейнера, а анкету на
        двенадцать шагов заполняют не за минуту — потерять её на середине
        значит потерять человека.
        """
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT answers, rev FROM s3_applications WHERE tg_id = ?", (tg_id,)) as cur:
                row = await cur.fetchone()
            answers = json.loads(row["answers"]) if row else {}
            rev = (row["rev"] if row else 0) + 1
            if step_id is not None:
                answers[step_id] = value
            payload = json.dumps(answers, ensure_ascii=False)
            await db.execute(
                "INSERT INTO s3_applications (tg_id, step, answers, rev) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(tg_id) DO UPDATE SET step = excluded.step, "
                "answers = excluded.answers, rev = excluded.rev, "
                "updated_at = datetime('now')",
                (tg_id, next_step, payload, rev))
            await db.commit()
        return answers

    async def submit_application(self, tg_id: int, tracks: list[str],
                                 sinks: tuple[str, ...] = ("csv", "notion")) -> bool:
        """Анкета и задания приёмникам — одной транзакцией.

        Между «анкета сохранена» и «задание создано» нет окна, в которое можно
        упасть: «не потерять анкету» выполняется устройством, а не надеждой на
        try/except вокруг сетевого вызова.
        """
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT status, rev, answers FROM s3_applications WHERE tg_id = ?",
                (tg_id,)) as cur:
                row = await cur.fetchone()
            if row is None:
                return False
            fio = json.loads(row["answers"] or "{}").get("fio")
            email = json.loads(row["answers"] or "{}").get("email")
            await db.execute(
                "UPDATE s3_applications SET status = 'submitted', step = NULL, "
                "submitted_at = datetime('now') WHERE tg_id = ?", (tg_id,))
            await db.execute("DELETE FROM s3_enrollments WHERE tg_id = ?", (tg_id,))
            await db.executemany(
                "INSERT OR IGNORE INTO s3_enrollments (tg_id, track_id) VALUES (?, ?)",
                [(tg_id, t) for t in tracks])
            await db.execute(
                "UPDATE people SET fio = ?, email = ? WHERE tg_id = ?", (fio, email, tg_id))
            await db.executemany(
                "INSERT INTO sync_outbox (sink, entity, key, rev) VALUES (?, 'application', ?, ?)",
                [(sink, str(tg_id), row["rev"]) for sink in sinks])
            await db.commit()
        return True

    async def applications(self, status: str = "submitted") -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT a.*, p.username, p.tg_name FROM s3_applications a "
                "LEFT JOIN people p ON p.tg_id = a.tg_id "
                "WHERE a.status = ? ORDER BY a.submitted_at", (status,)) as cur:
                rows = [dict(r) for r in await cur.fetchall()]
            for r in rows:
                r["answers"] = json.loads(r["answers"] or "{}")
                async with db.execute(
                    "SELECT track_id FROM s3_enrollments WHERE tg_id = ? ORDER BY track_id",
                    (r["tg_id"],)) as cur:
                    r["tracks"] = [t[0] for t in await cur.fetchall()]
        return rows

    async def track_counts(self) -> dict[str, int]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT track_id, COUNT(*) FROM s3_enrollments GROUP BY track_id") as cur:
                return {r[0]: r[1] for r in await cur.fetchall()}

    # --- очередь синхронизации -----------------------------------------------------

    async def outbox_batch(self, limit: int = 20) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM sync_outbox WHERE status = 'pending' ORDER BY id LIMIT ?",
                (limit,)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def synced_rev(self, sink: str, entity: str, key: str) -> int:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT synced_rev FROM sync_state WHERE sink = ? AND entity = ? AND key = ?",
                (sink, entity, key)) as cur:
                row = await cur.fetchone()
        return int(row[0]) if row else -1

    async def remote_id(self, sink: str, entity: str, key: str) -> str | None:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT remote_id FROM sync_state WHERE sink = ? AND entity = ? AND key = ?",
                (sink, entity, key)) as cur:
                row = await cur.fetchone()
        return row[0] if row else None

    async def mark_synced(self, task: dict, remote_id: str | None = None) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO sync_state (sink, entity, key, remote_id, synced_rev) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(sink, entity, key) DO UPDATE SET "
                "remote_id = COALESCE(excluded.remote_id, sync_state.remote_id), "
                "synced_rev = MAX(sync_state.synced_rev, excluded.synced_rev), "
                "at = datetime('now')",
                (task["sink"], task["entity"], task["key"], remote_id, task["rev"]))
            await db.execute("UPDATE sync_outbox SET status = 'done' WHERE id = ?",
                             (task["id"],))
            await db.commit()

    async def outbox_failed(self, task: dict, error: str, limit: int = 8) -> str:
        """Неудача. После `limit` попыток — «разошлось» и флаг админу, а не тишина."""
        tries = int(task["tries"]) + 1
        status = "diverged" if tries >= limit else "pending"
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE sync_outbox SET tries = ?, status = ?, error = ? WHERE id = ?",
                (tries, status, error[:400], task["id"]))
            if status == "diverged":
                await db.execute(
                    "INSERT INTO s3_flags (kind, payload) VALUES ('sync_diverged', ?)",
                    (json.dumps({"sink": task["sink"], "key": task["key"],
                                 "error": error[:200]}, ensure_ascii=False),))
            await db.commit()
        return status

    async def outbox_skip(self, task_id: int) -> None:
        """Задание устарело: эту запись уже доставили более свежей ревизией."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE sync_outbox SET status = 'done' WHERE id = ?",
                             (task_id,))
            await db.commit()

    async def outbox_health(self) -> dict[str, int]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT status, COUNT(*) FROM sync_outbox GROUP BY status") as cur:
                return {r[0]: r[1] for r in await cur.fetchall()}

    async def open_flags(self, limit: int = 20) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM s3_flags WHERE seen = 0 ORDER BY at DESC LIMIT ?",
                (limit,)) as cur:
                return [dict(r) for r in await cur.fetchall()]

    # --- репозитории третьего сезона ------------------------------------------------

    async def repo_check(self, url: str, ttl_hours: int = 6) -> dict | None:
        """Свежий результат проверки, если он есть.

        Кэш нужен не для скорости: без токена GitHub даёт 60 запросов в час, и
        поток в двести человек выбирает лимит в день старта.
        """
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT exists_, code, at FROM s3_repo_checks WHERE url = ? "
                "AND at > datetime('now', ?)", (url, f"-{int(ttl_hours)} hours")) as cur:
                row = await cur.fetchone()
        if row is None:
            return None
        return {"exists": None if row["exists_"] is None else bool(row["exists_"]),
                "code": row["code"], "at": row["at"]}

    async def save_repo_check(self, url: str, found: bool | None, code: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO s3_repo_checks (url, exists_, code) VALUES (?, ?, ?) "
                "ON CONFLICT(url) DO UPDATE SET exists_ = excluded.exists_, "
                "code = excluded.code, at = datetime('now')",
                (url, None if found is None else int(found), code))
            await db.commit()

    async def bind_repo(self, tg_id: int, url: str, owner: str, repo: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO s3_repos (tg_id, url, owner, repo) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(tg_id) DO UPDATE SET url = excluded.url, "
                "owner = excluded.owner, repo = excluded.repo, at = datetime('now')",
                (tg_id, url, owner, repo))
            await db.commit()

    async def repo_of(self, tg_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM s3_repos WHERE tg_id = ?", (tg_id,)) as cur:
                row = await cur.fetchone()
        return dict(row) if row else None

    # --- домашки третьего сезона ------------------------------------------------------

    async def recipients_for_tracks(self, tracks: list[str]) -> list[tuple[int, str]]:
        """Кому уйдёт домашка. Дедупликация по `tg_id` — не по паре с направлением.

        Студент на CV и на DL получает **одно** сообщение, а не два: иначе
        подписка на второе направление наказывала бы дублями.
        """
        if not tracks:
            return []
        marks = ",".join("?" * len(tracks))
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                f"SELECT DISTINCT e.tg_id, COALESCE(p.fio, p.username, e.tg_id) "
                f"FROM s3_enrollments e LEFT JOIN people p ON p.tg_id = e.tg_id "
                f"WHERE e.track_id IN ({marks}) ORDER BY e.tg_id", tracks) as cur:
                return [(int(r[0]), str(r[1])) for r in await cur.fetchall()]

    async def create_homework(self, title: str, body: str, tracks: list[str],
                              created_by: int, num: int | None = None,
                              deadline: str | None = None,
                              materials: str | None = None) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO s3_homeworks (num, title, body, deadline, materials, "
                "created_by) VALUES (?, ?, ?, ?, ?, ?)",
                (num, title, body, deadline, materials, created_by))
            hw_id = int(cur.lastrowid)
            await db.executemany(
                "INSERT OR IGNORE INTO s3_homework_tracks (homework_id, track_id) "
                "VALUES (?, ?)", [(hw_id, t) for t in tracks])
            await db.commit()
        return hw_id

    async def homework(self, hw_id: int) -> dict | None:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM s3_homeworks WHERE id = ?", (hw_id,)) as cur:
                row = await cur.fetchone()
            if row is None:
                return None
            out = dict(row)
            async with db.execute(
                "SELECT track_id FROM s3_homework_tracks WHERE homework_id = ? "
                "ORDER BY track_id", (hw_id,)) as cur:
                out["tracks"] = [t[0] for t in await cur.fetchall()]
        return out

    async def homeworks(self, status: str | None = None) -> list[dict]:
        where, args = ("WHERE status = ?", (status,)) if status else ("", ())
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM s3_homeworks {where} ORDER BY id DESC", args) as cur:
                return [dict(r) for r in await cur.fetchall()]

    async def publish_homework(self, hw_id: int,
                               recipients: list[tuple[int, str]]) -> bool:
        """Заморозить список получателей и пометить домашку опубликованной."""
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "UPDATE s3_homeworks SET status = 'published', "
                "published_at = datetime('now') WHERE id = ? AND status = 'draft'",
                (hw_id,))
            if cur.rowcount == 0:
                return False
            await db.executemany(
                "INSERT OR IGNORE INTO s3_deliveries (homework_id, tg_id) VALUES (?, ?)",
                [(hw_id, tg) for tg, _ in recipients])
            await db.commit()
        return True

    async def pending_deliveries(self, hw_id: int, limit: int = 500) -> list[int]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT tg_id FROM s3_deliveries WHERE homework_id = ? "
                "AND status = 'pending' ORDER BY tg_id LIMIT ?", (hw_id, limit)) as cur:
                return [int(r[0]) for r in await cur.fetchall()]

    async def mark_delivery(self, hw_id: int, tg_id: int, status: str,
                            error: str | None = None) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE s3_deliveries SET status = ?, error = ?, at = datetime('now') "
                "WHERE homework_id = ? AND tg_id = ?", (status, error, hw_id, tg_id))
            await db.commit()

    async def delivery_stats(self, hw_id: int) -> dict[str, int]:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT status, COUNT(*) FROM s3_deliveries WHERE homework_id = ? "
                "GROUP BY status", (hw_id,)) as cur:
                return {r[0]: r[1] for r in await cur.fetchall()}

    async def homeworks_for(self, tg_id: int) -> list[dict]:
        """Опубликованные домашки по направлениям этого человека."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT DISTINCT h.* FROM s3_homeworks h "
                "JOIN s3_homework_tracks ht ON ht.homework_id = h.id "
                "JOIN s3_enrollments e ON e.track_id = ht.track_id "
                "WHERE e.tg_id = ? AND h.status = 'published' "
                "ORDER BY h.num, h.id", (tg_id,)) as cur:
                return [dict(r) for r in await cur.fetchall()]
