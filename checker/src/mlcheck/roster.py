"""Parsing the submission form: normalising links, resolving profiles, checking access.

Produces out/roster.json (people in the analysis) and out/excluded.csv (those
left out). By the teacher's decision an unreachable repository is terminal: such
a student is out of the analysis and gets no certificate.
"""

from __future__ import annotations

import csv
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import gh
from .config import Config, load

# Student links arrive in every shape: with no scheme, with .git, with
# /tree/main, with a trailing slash, sometimes pointing at a profile.
_SCHEME = re.compile(r"^https?://", re.I)
_HOST = re.compile(r"^(www\.)?github\.com/", re.I)
_TREE = re.compile(r"/(tree|blob)/.*$")

# How much the repository name looks like "this course's repository".
_NAME_HINTS = (
    ("ml-course-homework", 100),
    ("ml_course_homework", 100),
    ("ml-course", 80),
    ("ml_course", 80),
    ("mlcourse", 80),
    ("famcs", 70),
    ("bsu", 50),
    ("fpmi", 50),
    ("homework", 40),
    ("hw", 25),
    ("ml", 20),
)


@dataclass
class Student:
    fio: str
    submitted_at: str
    raw_url: str
    slug: str | None = None          # owner/repo
    owner: str | None = None
    repo: str | None = None
    key: str | None = None           # key used for report files
    status: str = "unknown"          # ok | missing_repo | no_url | owner_missing
    reason: str = ""
    pushed_at: str | None = None
    size_kb: int | None = None
    default_branch: str | None = None
    resolved_from_profile: bool = False
    owner_repos: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def normalize_url(url: str) -> str:
    """Normalises a link to owner/repo, or owner if a profile was given."""
    u = (url or "").strip()
    u = _SCHEME.sub("", u)
    u = _HOST.sub("", u)
    u = _TREE.sub("", u)
    u = re.sub(r"\.git$", "", u)
    u = re.sub(r"[?#].*$", "", u)
    return u.strip("/ ")


def _score_repo_name(name: str) -> int:
    low = name.lower()
    return max((score for hint, score in _NAME_HINTS if hint in low), default=0)


def _list_owner_repos(owner: str) -> list[dict]:
    data = gh.try_api(f"users/{owner}/repos?per_page=100&sort=pushed")
    return data or []


def _resolve_profile(st: Student) -> None:
    """The student gave a profile link — look for a suitable repository among theirs."""
    repos = _list_owner_repos(st.owner)
    st.owner_repos = [r["name"] for r in repos]
    if not repos:
        st.status = "missing_repo"
        st.reason = "дана ссылка на профиль, публичных репозиториев нет"
        return
    best = max(repos, key=lambda r: _score_repo_name(r["name"]))
    if _score_repo_name(best["name"]) == 0:
        st.status = "missing_repo"
        st.reason = (
            "дана ссылка на профиль, среди репозиториев нет похожего на курсовой: "
            + ", ".join(st.owner_repos[:10])
        )
        return
    st.repo = best["name"]
    st.slug = f"{st.owner}/{st.repo}"
    st.resolved_from_profile = True


def _probe(st: Student) -> Student:
    """Checks the repository is reachable; on failure collects context about the owner."""
    if not st.slug and not st.owner:
        st.status = "no_url"
        st.reason = "в форме нет ссылки"
        return st

    if st.slug is None:  # a profile link
        _resolve_profile(st)
        if st.status == "missing_repo":
            return st

    meta = gh.try_api(f"repos/{st.slug}")
    if meta is None:
        st.status = "missing_repo"
        st.reason = "репозиторий удалён, приватен или переименован"
        # The owner's repository list — so a rename can be spotted by eye.
        if not st.owner_repos:
            owner_meta = gh.try_api(f"users/{st.owner}")
            if owner_meta is None:
                st.status = "owner_missing"
                st.reason = "пользователя GitHub не существует"
            else:
                st.owner_repos = [r["name"] for r in _list_owner_repos(st.owner)]
        return st

    st.status = "ok"
    st.owner = meta["owner"]["login"]  # the canonical case of the login
    st.repo = meta["name"]
    st.slug = meta["full_name"]
    st.pushed_at = meta.get("pushed_at")
    st.size_kb = meta.get("size")
    st.default_branch = meta.get("default_branch")
    return st


def read_csv(path: Path) -> list[Student]:
    students: list[Student] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            # Headers in the form export arrive with trailing spaces.
            row = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            fio = row.get("Фамилия Имя", "")
            url = row.get("URL", "")
            st = Student(fio=fio, submitted_at=row.get("Timestamp", ""), raw_url=url)
            norm = normalize_url(url)
            if not norm:
                st.status = "no_url"
                st.reason = "в форме нет ссылки"
            elif "/" in norm:
                st.owner, st.repo = norm.split("/", 1)
                st.repo = st.repo.split("/")[0]
                st.slug = f"{st.owner}/{st.repo}"
            else:
                st.owner = norm  # a profile link; the repository is found later
            students.append(st)
    return students


def _assign_keys(students: list[Student]) -> None:
    """Report file key: the login, extended with the repository name on collision."""
    seen: dict[str, int] = {}
    for st in students:
        base = (st.owner or re.sub(r"\W+", "_", st.fio) or "unknown").lower()
        seen[base] = seen.get(base, 0) + 1
    used: dict[str, int] = {}
    for st in students:
        base = (st.owner or re.sub(r"\W+", "_", st.fio) or "unknown").lower()
        if seen[base] > 1:
            suffix = (st.repo or str(used.get(base, 0))).lower()
            suffix = re.sub(r"\W+", "-", suffix)
            st.key = f"{base}__{suffix}"
            used[base] = used.get(base, 0) + 1
        else:
            st.key = base


def build(cfg: Config | None = None) -> list[Student]:
    cfg = cfg or load()
    gh.check_auth()
    students = read_csv(cfg.paths.roster_csv)
    with ThreadPoolExecutor(max_workers=cfg.fetch["concurrency"]) as pool:
        students = list(pool.map(_probe, students))
    _assign_keys(students)
    return students


def save(students: list[Student], cfg: Config | None = None) -> None:
    cfg = cfg or load()
    out = cfg.paths.out
    out.mkdir(parents=True, exist_ok=True)

    (out / "roster.json").write_text(
        json.dumps([asdict(s) for s in students], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    excluded = [s for s in students if not s.ok]
    with (out / "excluded.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["ФИО", "ссылка из формы", "статус", "причина", "репозитории владельца"])
        for s in excluded:
            w.writerow([s.fio, s.raw_url, s.status, s.reason, ", ".join(s.owner_repos)])
