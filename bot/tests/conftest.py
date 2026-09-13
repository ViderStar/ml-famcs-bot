from pathlib import Path

import pytest

from harness import detach_routers
from mlbot.config import Config
from mlbot.data import Course

ROOT = Path(__file__).resolve().parents[2]

# The real report corpus is not part of the public repository: it holds names,
# links to private repositories and reviews. If it is there, run against it;
# otherwise against the synthetic stream (`python fixtures/make_fixture.py`).
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
    """Many tests rebuild the dispatcher — see `harness.detach_routers`."""
    detach_routers()


@pytest.fixture(scope="session")
def somebody(course):
    """Any student with submissions.

    Tests never name students: the repository is public and the report corpus is
    not part of it. Selecting by properties is also more honest — it checks the
    behaviour on an arbitrary record rather than one memorised case.
    """
    return next(s for s in course.active if s.submitted() and s.repo)
