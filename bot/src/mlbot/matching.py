"""Поиск студента по ссылке на репозиторий и по ФИО.

Проверка двойная: ссылка и ФИО должны сойтись на одной строке формы. По одной
фамилии однокурсника чужой разбор не откроешь, а ссылку на чужой репозиторий
без фамилии владельца тоже недостаточно знать.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mlcheck.roster import normalize_url
from rapidfuzz import fuzz, process

from .data import Course, Student

# Порог совпадения ФИО. Ниже — просим уточнить, выше — считаем подтверждением.
FIO_THRESHOLD = 82
# Порог, ниже которого подсказки по ФИО вообще не показываем.
SUGGEST_THRESHOLD = 60

_SPACE = re.compile(r"\s+")


def normalize_fio(text: str) -> str:
    """ФИО без регистра, лишних пробелов и разницы е/ё."""
    return _SPACE.sub(" ", (text or "").strip().lower().replace("ё", "е"))


def _repo_index(course: Course) -> dict[str, str]:
    index: dict[str, str] = {}
    for st in course.students.values():
        if st.repo:
            index[normalize_url(st.repo).lower()] = st.key
    return index


def find_by_repo(course: Course, text: str) -> Student | None:
    """Студент по ссылке на репозиторий. Принимает и полный URL, и owner/repo."""
    slug = normalize_url(text).lower()
    if not slug:
        return None
    index = _repo_index(course)
    if slug in index:
        return course.students[index[slug]]
    # Прислали ссылку на профиль или на файл внутри репозитория — берём owner/repo.
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
    """Кандидаты по ФИО, по убыванию похожести."""
    query = normalize_fio(text)
    if len(query) < 4:
        return []
    choices = {st.key: normalize_fio(st.fio) for st in course.students.values()}
    found = process.extract(
        query, choices, scorer=fuzz.WRatio, limit=limit, score_cutoff=SUGGEST_THRESHOLD
    )
    return [FioMatch(course.students[key], score) for _, score, key in found]


def fio_matches(student: Student, text: str) -> bool:
    """Подтверждает ли введённое ФИО этого конкретного студента."""
    return fuzz.WRatio(normalize_fio(student.fio), normalize_fio(text)) >= FIO_THRESHOLD


def find_by_username(course: Course, username: str | None) -> Student | None:
    """Студент по telegram-username из формы регистрации.

    Username принадлежит аккаунту, который пишет боту, — это фактор посильнее
    знания чужой ссылки. Но освободившийся username может занять кто угодно,
    поэтому связка не привязывает молча, а показывает ФИО на подтверждение.
    """
    if not username:
        return None
    key = course.usernames.get(username.strip().lstrip("@").lower())
    return course.students.get(key) if key else None


def looks_like_repo(text: str) -> bool:
    low = (text or "").strip().lower()
    return "github.com" in low or bool(re.fullmatch(r"[\w.-]+/[\w.-]+", low))
