"""The applications file.

Not appended row by row but **regenerated whole** from SQLite: appending would
duplicate on a repeated task, and on an edited form it would add a second row
for the same person. The write goes to a temporary file plus `os.replace`, so a
reader never sees half a table.

The directory comes from `EXPORT_DIR`, not from `out/`: that one is mounted
read-only, and the very first application would hit "Read-only file system".
"""

from __future__ import annotations

import csv
import io
import os
from pathlib import Path

from ..season3 import wizard

FIELDS = ("tg_id", "username", "fio", "email", "university", "faculty", "year",
          "level", "python", "math", "ml", "knows", "tracks", "why", "submitted_at")


def row_of(app: dict, readable: bool = True) -> dict:
    """A table row. Labels rather than codes by default.

    A human reads this table: `basic` and `derivative` mean nothing in it, while
    the Russian labels do.
    """
    a = app["answers"]

    def one(step_id: str) -> str:
        value = a.get(step_id, "")
        return human(value, step_id, a) if readable else value

    def many(step_id: str, values) -> str:
        values = values or []
        return "; ".join(human(v, step_id, a) for v in values) if readable \
            else ";".join(values)

    return {
        "tg_id": app["tg_id"],
        "username": app.get("username") or "",
        "fio": a.get("fio", ""),
        "email": a.get("email", ""),
        "university": one("university"),
        "faculty": one("faculty"),
        "year": one("year"),
        "level": one("level"),
        "python": one("python"),
        "math": one("math"),
        "ml": one("ml"),
        "knows": many("knows", a.get("knows")),
        "tracks": many("tracks", app.get("tracks")),
        "why": (a.get("why", "") or "").replace("\n", " ").strip(),
        "submitted_at": app.get("submitted_at") or "",
    }


def render(apps: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS, extrasaction="ignore")
    w.writeheader()
    for app in apps:
        w.writerow(row_of(app))
    return buf.getvalue()


async def sync(cfg, store, task: dict) -> str | None:
    """Regenerate the file. One task per edit — the file is always written whole."""
    apps = await store.applications("submitted")
    path = Path(cfg.export_dir) / "s3_applications.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    tmp.write_text(render(apps), encoding="utf-8-sig")
    os.replace(tmp, path)
    return str(path)


def human(value_id: str, step_id: str, answers: dict | None = None) -> str:
    """The option label — so the table shows a readable word rather than `basic`."""
    step = wizard.step(step_id)
    if step is None or not value_id:
        return value_id
    return dict(step.choices(answers or {})).get(value_id, value_id)
