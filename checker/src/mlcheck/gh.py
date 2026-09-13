"""A thin wrapper around the gh CLI.

The token comes from gh's existing authentication; it is in no code or config.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any


class GhError(RuntimeError):
    pass


def api(endpoint: str, *, jq: str | None = None, raw: bool = False) -> Any:
    """A GitHub API call. Returns parsed JSON, a string (jq) or bytes (raw)."""
    cmd = ["gh", "api", endpoint]
    if raw:
        cmd += ["-H", "Accept: application/vnd.github.raw"]
    if jq:
        cmd += ["--jq", jq]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise GhError(proc.stderr.decode("utf-8", "replace").strip() or f"gh api {endpoint} failed")
    if raw:
        return proc.stdout
    out = proc.stdout.decode("utf-8", "replace").strip()
    if not out:
        return None
    if jq:
        return out
    return json.loads(out)


def try_api(endpoint: str, **kw: Any) -> Any | None:
    """The same, but None instead of an exception — for existence checks."""
    try:
        return api(endpoint, **kw)
    except GhError:
        return None


def check_auth() -> None:
    proc = subprocess.run(["gh", "auth", "status"], capture_output=True)
    if proc.returncode != 0:
        raise GhError(
            "gh не авторизован. Выполните: gh auth login"
        )
