"""Finding a student by repository link and by name.

The check has two factors: link and name must land on the same form row. A
classmate's surname alone will not open their review, and knowing someone
else's repository link without the owner's name is not enough either.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mlcheck.roster import normalize_url
from rapidfuzz import fuzz, process

from .data import Course, Student

# Name-match threshold. Below it we ask to clarify, above it we take it as confirmation.
FIO_THRESHOLD = 82
# Threshold below which no name suggestions are shown at all.
SUGGEST_THRESHOLD = 60

_SPACE = re.compile(r"\s+")


def normalize_fio(text: str) -> str:
    """A name without case, extra spaces or the е/ё distinction."""
    return _SPACE.sub(" ", (text or "").strip().lower().replace("ё", "е"))


def _repo_index(course: Course) -> dict[str, str]:
    index: dict[str, str] = {}
    for st in course.students.values():
        if st.repo:
            index[normalize_url(st.repo).lower()] = st.key
    return index


def find_by_repo(course: Course, text: str) -> Student | None:
    """A student by repository link. Accepts a full URL or owner/repo."""
    slug = normalize_url(text).lower()
    if not slug:
        return None
    index = _repo_index(course)
    if slug in index:
        return course.students[index[slug]]
    # They sent a profile link or a link to a file inside — take owner/repo.
    parts = slug.split("/")
    if len(parts) >= 2:
        short = "/".join(parts[:2])
        if short in index:
            return course.students[index[short]]
    return None


@dataclass
class FioMatch:
    student: Student
    score: float

    @property
    def confident(self) -> bool:
        return self.score >= FIO_THRESHOLD


def find_by_fio(course: Course, text: str, limit: int = 5) -> list[FioMatch]:
    """Candidates by name, most similar first."""
    query = normalize_fio(text)
    if len(query) < 4:
        return []
    choices = {st.key: normalize_fio(st.fio) for st in course.students.values()}
    found = process.extract(
        query, choices, scorer=fuzz.WRatio, limit=limit, score_cutoff=SUGGEST_THRESHOLD
    )
    return [FioMatch(course.students[key], score) for _, score, key in found]


def fio_matches(student: Student, text: str) -> bool:
    """Whether the entered name confirms this particular student."""
    return fuzz.WRatio(normalize_fio(student.fio), normalize_fio(text)) >= FIO_THRESHOLD


def find_by_username(course: Course, username: str | None) -> Student | None:
    """A student by telegram username from the registration form.

    The username belongs to the account writing to the bot — a stronger factor
    than knowing someone's link. But a released username can be claimed by
    anyone, so this never binds silently: it shows the name for confirmation.
    """
    if not username:
        return None
    key = course.usernames.get(username.strip().lstrip("@").lower())
    return course.students.get(key) if key else None


def looks_like_repo(text: str) -> bool:
    low = (text or "").strip().lower()
    return "github.com" in low or bool(re.fullmatch(r"[\w.-]+/[\w.-]+", low))
