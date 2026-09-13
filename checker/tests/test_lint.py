"""Статическая страховка: неопределённые имена и неиспользуемые импорты.

Появилась после того, как обработчик карточки темы падал с NameError на имени,
которое скопировали из другого модуля без импорта. Тесты проверяли модуль
`views`, а обработчик — нет, и падение дошло до студентов. ruff находит такое
за секунду по всему пакету. При отсутствии ruff тест падает, а не пропускается:
страховка, которая пропускается, — не страховка.
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
