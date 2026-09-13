"""A static guard: undefined names and unused imports.

Added after the topic-card handler crashed with a NameError on a name copied
from another module without its import. Tests covered the `views` module but not
the handler, and the crash reached students. ruff finds that across the package
in a second. Without ruff this test fails rather than skips: a guard that skips
is not a guard.
"""

import shutil
import subprocess
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def test_no_undefined_names_or_unused_imports():
    ruff = [shutil.which("ruff")] if shutil.which("ruff") else [sys.executable, "-m", "ruff"]
    result = subprocess.run(
        [*ruff, "check", "--select", "F821,F401,F811", "--no-cache", str(SRC)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout or result.stderr
