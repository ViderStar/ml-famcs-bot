"""Поиск студента: обе половины проверки должны сходиться на одной строке."""

from mlbot.matching import (find_by_fio, find_by_repo, fio_matches,
                            looks_like_repo, normalize_fio)


def test_repo_found_by_full_url(course, somebody):
    st = find_by_repo(course, somebody.repo)
    assert st is not None and st.key == somebody.key


def test_repo_found_despite_git_suffix_and_tree_path(course, somebody):
    slug = somebody.repo.split("github.com/", 1)[1]
    for text in (f"{somebody.repo}.git",
                 f"github.com/{slug}/tree/main",
                 slug):
        assert find_by_repo(course, text).key == somebody.key, text


def test_unknown_repo_is_not_matched(course):
    assert find_by_repo(course, "https://github.com/octocat/hello-world") is None


def test_fio_tolerates_typo_and_case(course, somebody):
    matches = find_by_fio(course, somebody.fio.lower())
    assert matches and matches[0].student.key == somebody.key and matches[0].confident


def test_fio_confirmation_rejects_a_classmate(course, somebody):
    other = next(s for s in course.active if s.key != somebody.key)
    assert fio_matches(somebody, somebody.fio)
    assert not fio_matches(somebody, other.fio)


def test_excluded_student_is_still_findable(course):
    """Тем, у кого репозиторий недоступен, тоже нужно объяснение."""
    excluded = next(s for s in course.students.values() if not s.ok and s.repo)
    assert find_by_repo(course, excluded.repo).key == excluded.key


def test_looks_like_repo():
    assert looks_like_repo("https://github.com/a/b")
    assert looks_like_repo("a/b")
    assert not looks_like_repo("Иванов Иван")


def test_normalize_fio_handles_yo():
    assert normalize_fio("Артём  Лебедевич") == normalize_fio("артем лебедевич")
