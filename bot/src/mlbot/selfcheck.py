"""Diagnostics: can the bot see the course data.

Runs without a token — useful right after building the image, to check the
mounts are in place:

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
        ("reports", cfg.findings_dir),
        ("error catalog", cfg.checker_dir / "catalog"),
        ("rubrics", cfg.checker_dir / "rubrics"),
        ("lecture materials", cfg.materials_dir),
    ):
        if not path.exists():
            problems.append(f"no {label} directory: {path}")

    print(f"DATA_ROOT = {root}")
    if problems:
        for p in problems:
            print(f"  ✗ {p}")
        print("\nCheck the mounts in compose.yaml.")
        return 1

    course = Course.load(cfg)
    print(f"  ✓ students: {len(course.students)}, graded {len(course.active)}")
    print(f"  ✓ catalog articles: {len(course.catalog)}")
    print(f"  ✓ topics: {len(course.rubrics)}, graded {course.total_graded}")
    print(f"  ✓ threshold {course.certificate_ratio:.0%} → need "
          f"{course.required_passed} of {course.total_graded}")
    print(f"  ✓ certificates: {course.certificates}")

    known = len(course.usernames)
    print(f"  {'✓' if known else '·'} recognised by telegram username: {known} "
          f"of {len(course.students)} (the rest by name and link)")

    tasks = sum(1 for hw in course.rubrics if course.task_text(hw))
    materials = sum(len(course.materials(hw)) for hw in course.rubrics)
    print(f"  ✓ assignment texts: {tasks}, lecture files: {materials}")
    print(f"  {'✓' if course.attention else '·'} attention.md: "
          f"{'present' if course.attention else 'absent (not critical)'}")

    # --- what the safety of walking the bot depends on -----------------------------
    print()
    if cfg.support_username:
        print(f"  ✓ support contact: @{cfg.support_username}")
    else:
        problems.append("SUPPORT_USERNAME unset — there will be no 'write to the teacher' button")
        print("  ✗ SUPPORT_USERNAME unset: the 'write to the teacher' button will not appear")

    if cfg.safe_mode:
        print("  ✓ SAFE_MODE on: letters to students are redirected to the admin")
    else:
        print("  ⚠ SAFE_MODE OFF: messages will reach real people")

    if cfg.demo_findings.exists():
        demo = Course.load(cfg, findings_dir=cfg.demo_findings, season="demo")
        print(f"  ✓ fictional students: {len(demo.students)} "
              f"({cfg.demo_findings})")
    else:
        problems.append(f"no fictional-records directory: {cfg.demo_findings}")
        print(f"  ✗ no fictional records: {cfg.demo_findings}")

    # out/ is mounted read-only — exports need a writable place of their own.
    try:
        cfg.export_dir.mkdir(parents=True, exist_ok=True)
        probe = cfg.export_dir / ".selfcheck"
        probe.write_text("ok")
        probe.unlink()
        print(f"  ✓ export directory is writable: {cfg.export_dir}")
    except OSError as exc:
        problems.append(f"{cfg.export_dir} is not writable: {exc}")
        print(f"  ✗ {cfg.export_dir} is not writable: {exc}")

    from .menu import core as menu
    print(f"  ✓ menu nodes: {len(menu.NODES)}")

    if not course.students:
        print("\nNo reports — run the grader first: uv run mlcheck report")
        return 1
    if problems:
        print("\nSomething is missing:")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print("\nAll set. Just add BOT_TOKEN and start the bot.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
