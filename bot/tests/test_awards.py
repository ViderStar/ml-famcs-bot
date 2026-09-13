"""Сертификаты и фотографии с вручения: сопоставление и выдача.

Цена ошибки здесь выше обычной: в PDF напечатано ФИО, и отправить студенту чужой
сертификат — это выдать чужие персональные данные. Поэтому проверяем не только
что файл нашёлся, но и что он именно того человека.
"""

import csv
import re
import unicodedata

import pytest
from mlcheck.awards import norm, word_set

from mlbot.keyboards import awards_buttons


@pytest.fixture(scope="module")
def awards(cfg):
    return list(csv.DictReader((cfg.out_dir / "awards.csv").open(encoding="utf-8")))


def test_every_graduate_has_a_certificate(course, awards):
    graduates = {s.fio for s in course.active if s.certificate}
    assert {a["fio"] for a in awards} == graduates
    assert all(a["certificate"] for a in awards), \
        [a["fio"] for a in awards if not a["certificate"]]


def test_no_certificate_file_is_used_twice(awards):
    files = [a["certificate"] for a in awards]
    assert len(files) == len(set(files))
    photos = [a["photo"] for a in awards if a["photo"]]
    assert len(photos) == len(set(photos))


def test_certificate_pdf_contains_that_students_name(course, awards):
    """Главная проверка: имя внутри PDF совпадает с тем, кому его отдадим.

    Работает только по настоящим сертификатам. В открытый репозиторий они не
    входят — в каждом напечатано ФИО, — и на синтетических заглушках проверка
    честно пропускается, а не делает вид, что прошла.
    """
    from mlcheck.awards import name_in_pdf

    first = course.certificate_file(awards[0]["key"]) if awards else None
    if first is None or not name_in_pdf(first):
        pytest.skip("настоящих сертификатов рядом нет — в них ФИО выпускников")

    checked = 0
    for a in awards:
        path = course.certificate_file(a["key"])
        assert path is not None, a["fio"]
        inside = name_in_pdf(path)
        assert inside, f"{a['fio']}: имя из PDF не прочиталось"
        assert norm(inside) == norm(a["fio"]), f"{a['fio']} ← {inside!r} в {path.name}"
        checked += 1
    assert checked == len(awards)


def test_photo_filename_matches_the_student(course, awards):
    for a in awards:
        if not a["photo"]:
            continue
        path = course.ceremony_photo(a["key"])
        assert path is not None, a["fio"]
        stem = unicodedata.normalize("NFC", path.stem)
        # Опечатка в одну букву допустима, порядок слов — тоже; чужое имя — нет.
        assert word_set(stem) == word_set(a["fio"]) or _one_letter_apart(stem, a["fio"]), \
            f"{a['fio']} ← {path.name}"


def _one_letter_apart(a: str, b: str) -> bool:
    x, y = norm(a), norm(b)
    return len(x) == len(y) and sum(p != q for p, q in zip(x, y)) <= 1


def test_only_graduates_get_files(course):
    """У непрошедших файлов нет — ни сертификата, ни фотографии."""
    for st in course.active:
        if st.certificate:
            continue
        assert course.certificate_file(st.key) is None
        assert course.ceremony_photo(st.key) is None


def test_buttons_appear_only_when_files_exist():
    assert awards_buttons(False, False) is None
    both = [b.callback_data for row in awards_buttons(True, True).inline_keyboard for b in row]
    assert both == ["cert:pdf", "cert:photo"]
    only = [b.callback_data for row in awards_buttons(True, False).inline_keyboard for b in row]
    assert only == ["cert:pdf"]


def test_button_callbacks_carry_no_student_key():
    for row in awards_buttons(True, True).inline_keyboard:
        for b in row:
            assert ":" in b.callback_data and len(b.callback_data.split(":")) == 2


# --- текст рассылки ---------------------------------------------------------------

def test_announcement_renders_for_every_graduate(course):
    from mlbot.announce import message_for

    for st in (s for s in course.active if s.certificate):
        text = message_for(course, st)
        assert st.fio in text and str(st.passed) in text
        assert "forms.gle" in text
        assert len(text) <= 4096
        for tag in ("b", "i"):
            assert text.count(f"<{tag}>") == text.count(f"</{tag}>")
        # Род студента неизвестен — окончаний вида «закрыл(а)» быть не должно.
        assert not re.search(r"\w+\((а|ла|ло)\)", text), text


def test_announcement_mentions_photo_only_when_there_is_one(course):
    from mlbot.announce import message_for

    with_photo = next(s for s in course.active
                      if s.certificate and course.ceremony_photo(s.key))
    without = next(s for s in course.active
                   if s.certificate and not course.ceremony_photo(s.key))
    assert "фотографию с вручения" in message_for(course, with_photo)
    assert "фотографию с вручения" not in message_for(course, without)
