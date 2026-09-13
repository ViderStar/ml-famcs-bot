"""Диагностика: видит ли бот данные курса.

Запускается без токена — полезно сразу после сборки образа, чтобы проверить,
что монтирования на месте:

    docker run --rm -v ...:/data:ro -e DATA_ROOT=/data bot-mlbot \
        uv run --no-dev python -m mlbot.selfcheck
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .config import Config
from .data import Course


def main() -> int:
    root = Path(os.environ.get("DATA_ROOT", ".")).resolve()
    cfg = Config(
        token="selfcheck",
        admin_ids=frozenset(),
        admin_usernames=frozenset(),
        support_username=os.environ.get("SUPPORT_USERNAME", "").lstrip("@").strip(),
        data_root=root,
        db_path=Path(os.environ.get("DB_PATH", "/tmp/selfcheck.sqlite3")),
        safe_mode=os.environ.get("SAFE_MODE", "1").strip().lower()
        not in {"0", "false", "no", "off", "нет"},
        demo_root=Path(os.environ.get("DEMO_ROOT", Path(__file__).resolve().parents[2] / "demo")),
        export_dir=Path(os.environ.get("EXPORT_DIR", "/state/export")),
    )

    problems: list[str] = []
    for label, path in (
        ("отчёты", cfg.findings_dir),
        ("каталог ошибок", cfg.checker_dir / "catalog"),
        ("рубрики", cfg.checker_dir / "rubrics"),
        ("материалы лекций", cfg.materials_dir),
    ):
        if not path.exists():
            problems.append(f"нет каталога {label}: {path}")

    print(f"DATA_ROOT = {root}")
    if problems:
        for p in problems:
            print(f"  ✗ {p}")
        print("\nПроверьте монтирования в compose.yaml.")
        return 1

    course = Course.load(cfg)
    print(f"  ✓ студентов: {len(course.students)}, проверено {len(course.active)}")
    print(f"  ✓ статей каталога: {len(course.catalog)}")
    print(f"  ✓ тем: {len(course.rubrics)}, зачётных {course.total_graded}")
    print(f"  ✓ порог {course.certificate_ratio:.0%} → нужно "
          f"{course.required_passed} из {course.total_graded}")
    print(f"  ✓ сертификатов: {course.certificates}")

    known = len(course.usernames)
    print(f"  {'✓' if known else '·'} узнаётся по telegram-username: {known} "
          f"из {len(course.students)} (остальные — по ФИО и ссылке)")

    tasks = sum(1 for hw in course.rubrics if course.task_text(hw))
    materials = sum(len(course.materials(hw)) for hw in course.rubrics)
    print(f"  ✓ текстов заданий: {tasks}, файлов лекций: {materials}")
    print(f"  {'✓' if course.attention else '·'} attention.md: "
          f"{'есть' if course.attention else 'нет (не критично)'}")

    # --- то, от чего зависит безопасность проверки ---------------------------------
    print()
    if cfg.support_username:
        print(f"  ✓ поддержка: @{cfg.support_username}")
    else:
        problems.append("SUPPORT_USERNAME не задан — кнопки «написать преподавателю» не будет")
        print("  ✗ SUPPORT_USERNAME не задан: кнопка «написать преподавателю» не появится")

    if cfg.safe_mode:
        print("  ✓ SAFE_MODE включён: письма студентам разворачиваются на админа")
    else:
        print("  ⚠ SAFE_MODE ВЫКЛЮЧЕН: сообщения уйдут живым людям")

    if cfg.demo_findings.exists():
        demo = Course.load(cfg, findings_dir=cfg.demo_findings, season="demo")
        print(f"  ✓ вымышленных студентов: {len(demo.students)} "
              f"({cfg.demo_findings})")
    else:
        problems.append(f"нет каталога с демо-записями: {cfg.demo_findings}")
        print(f"  ✗ демо-записей нет: {cfg.demo_findings}")

    # out/ монтируется только на чтение — выгрузкам нужно своё записываемое место.
    try:
        cfg.export_dir.mkdir(parents=True, exist_ok=True)
        probe = cfg.export_dir / ".selfcheck"
        probe.write_text("ok")
        probe.unlink()
        print(f"  ✓ каталог выгрузок пишется: {cfg.export_dir}")
    except OSError as exc:
        problems.append(f"в {cfg.export_dir} не пишется: {exc}")
        print(f"  ✗ в {cfg.export_dir} не пишется: {exc}")

    from .menu import core as menu
    print(f"  ✓ узлов меню: {len(menu.NODES)}")

    if not course.students:
        print("\nОтчётов нет — сначала прогоните проверку: uv run mlcheck report")
        return 1
    if problems:
        print("\nНе всё на месте:")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print("\nВсё на месте. Осталось задать BOT_TOKEN и запустить бота.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
