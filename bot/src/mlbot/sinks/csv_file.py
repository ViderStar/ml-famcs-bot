"""Файл с анкетами.

Не дописываем построчно, а **перегенерируем проекцию целиком** из SQLite:
дописывание при повторе задания дало бы дубль, а при правке анкеты — вторую
строку на того же человека. Запись идёт во временный файл и `os.replace`,
поэтому читающий никогда не увидит половину таблицы.

Каталог берётся из `EXPORT_DIR`, а не из `out/`: тот смонтирован только на
чтение, и первая же анкета упёрлась бы в «Read-only file system».
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
    """Строка таблицы. По умолчанию — подписями, а не кодами.

    Таблицу читает человек: `basic` и `derivative` в ней не значат ничего, а
    «Базовый» и «Производная» — значат.
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
    """Перегенерировать файл. Задание одно на любую правку — файл всегда целиком."""
    apps = await store.applications("submitted")
    path = Path(cfg.export_dir) / "s3_applications.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    tmp.write_text(render(apps), encoding="utf-8-sig")
    os.replace(tmp, path)
    return str(path)


def human(value_id: str, step_id: str, answers: dict | None = None) -> str:
    """Подпись варианта — чтобы в таблице стояло «Базовый», а не `basic`."""
    step = wizard.step(step_id)
    if step is None or not value_id:
        return value_id
    return dict(step.choices(answers or {})).get(value_id, value_id)
