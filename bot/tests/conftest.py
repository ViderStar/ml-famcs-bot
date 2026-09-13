from pathlib import Path

import pytest

from harness import detach_routers
from mlbot.config import Config
from mlbot.data import Course

ROOT = Path(__file__).resolve().parents[2]

# Настоящий корпус отчётов в открытый репозиторий не входит: там ФИО, ссылки на
# личные репозитории и рецензии. Если он рядом — прогоняемся по нему, иначе по
# синтетическому потоку (`python fixtures/make_fixture.py`).
REAL_OUT = ROOT / "out" / "findings"
OUT_ROOT = None if REAL_OUT.exists() else ROOT / "fixtures" / "out"


@pytest.fixture(scope="session")
def cfg(tmp_path_factory) -> Config:
    return Config(
        token="test",
        admin_ids=frozenset({1}),
        admin_usernames=frozenset({"chief"}),
        support_username="swanovich",
        data_root=ROOT,
        db_path=tmp_path_factory.mktemp("db") / "mlbot.sqlite3",
        out_root=OUT_ROOT,
    )


@pytest.fixture(scope="session")
def course(cfg) -> Course:
    return Course.load(cfg)


@pytest.fixture(autouse=True)
def detached_routers():
    """Диспетчер собирается заново во многих тестах — см. `harness.detach_routers`."""
    detach_routers()


@pytest.fixture(scope="session")
def somebody(course):
    """Любой студент со сдачами.

    Тесты не называют студентов по имени: репозиторий открытый, а корпус
    отчётов в него не входит. Выбор по свойствам ещё и честнее — он проверяет
    поведение на произвольной записи, а не на одной заученной.
    """
    return next(s for s in course.active if s.submitted() and s.repo)
