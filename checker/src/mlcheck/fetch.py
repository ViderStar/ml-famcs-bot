"""Fetching participants' repositories.

Cloned shallow (--depth 1) and without large blobs: only notebooks and small
text files are needed, while datasets and images in these repositories run to
gigabytes. A rerun does not refetch anything already there with the same
pushed_at.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .config import Config, load
from .roster import Student

# Blobs larger than this are skipped: the biggest course notebook is ~3.4 MB;
# anything heavier is datasets, archives and images.
BLOB_LIMIT = "8m"


@dataclass
class FetchResult:
    key: str
    slug: str
    status: str          # cloned | cached | failed | empty
    reason: str = ""
    path: str | None = None


def _stamp_path(dest: Path) -> Path:
    return dest.parent / f".{dest.name}.stamp"


def _clone(st: Student, dest: Path, timeout: int) -> FetchResult:
    url = f"https://github.com/{st.slug}.git"
    cmd = [
        "git", "clone", "--quiet",
        "--depth", "1",
        f"--filter=blob:limit={BLOB_LIMIT}",
        url, str(dest),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", "replace").strip().splitlines()
        return FetchResult(st.key, st.slug, "failed", err[-1] if err else "git clone failed")
    if not any(dest.rglob("*")):
        return FetchResult(st.key, st.slug, "empty", "репозиторий пуст", str(dest))
    return FetchResult(st.key, st.slug, "cloned", path=str(dest))


def _fetch_one(st: Student, root: Path, timeout: int, force: bool) -> FetchResult:
    dest = root / st.key
    stamp = _stamp_path(dest)

    if dest.exists() and not force:
        if stamp.exists() and stamp.read_text(encoding="utf-8").strip() == (st.pushed_at or ""):
            return FetchResult(st.key, st.slug, "cached", path=str(dest))
        shutil.rmtree(dest, ignore_errors=True)
    elif dest.exists():
        shutil.rmtree(dest, ignore_errors=True)

    try:
        res = _clone(st, dest, timeout)
    except subprocess.TimeoutExpired:
        shutil.rmtree(dest, ignore_errors=True)
        return FetchResult(st.key, st.slug, "failed", f"таймаут {timeout} c")

    if res.status in ("cloned", "empty"):
        stamp.write_text(st.pushed_at or "", encoding="utf-8")
    return res


def run(students: list[Student], cfg: Config | None = None, force: bool = False) -> list[FetchResult]:
    cfg = cfg or load()
    root = cfg.paths.raw
    root.mkdir(parents=True, exist_ok=True)
    timeout = cfg.fetch["timeout_sec"]
    targets = [s for s in students if s.ok]

    results: list[FetchResult] = []
    with ThreadPoolExecutor(max_workers=cfg.fetch["concurrency"]) as pool:
        futures = {pool.submit(_fetch_one, s, root, timeout, force): s for s in targets}
        for fut in as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda r: r.key)
    (cfg.paths.out / "fetch.json").write_text(
        json.dumps([r.__dict__ for r in results], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return results


def load_roster(cfg: Config | None = None) -> list[Student]:
    cfg = cfg or load()
    data = json.loads((cfg.paths.out / "roster.json").read_text(encoding="utf-8"))
    return [Student(**d) for d in data]
