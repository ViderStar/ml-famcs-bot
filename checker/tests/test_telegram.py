"""Сшивка формы регистрации с формой сдачи.

Главное требование — не склеить двух разных людей: ошибочная связка означает,
что чужой человек увидит чей-то разбор. Поэтому тесты на отказ важнее тестов
на успех.
"""

from mlcheck.telegram import Registration, clean_username, match


def reg(fio: str, username: str, row: int = 2) -> Registration:
    return Registration(fio=fio, username=clean_username(username),
                        raw_username=username, row=row)


def roster(*fios: str) -> list[dict]:
    return [{"key": f"k{i}", "fio": fio} for i, fio in enumerate(fios)]


class TestUsername:
    def test_strips_at_sign_and_spaces(self):
        assert clean_username("  @Vasya_99 ") == "Vasya_99"

    def test_accepts_link(self):
        assert clean_username("https://t.me/durov") == "durov"
        assert clean_username("t.me/s/durov") == "durov"

    def test_fixes_russian_layout(self):
        # «Сohanaia» набрано с кириллической С — в Telegram такого быть не может.
        assert clean_username("@Сohanaia") == "Cohanaia"

    def test_rejects_prose(self):
        assert clean_username("нет телеграма") == ""
        assert clean_username("") == ""

    def test_rejects_too_short(self):
        assert clean_username("@ab") == ""


class TestMatch:
    def test_exact_pair(self):
        links = match(roster("Иванов Иван"), [reg("Иванов Иван Иванович", "@ivanov")])
        assert (links[0].match, links[0].username) == ("exact", "ivanov")

    def test_reversed_order(self):
        links = match(roster("Иван Иванов"), [reg("Иванов Иван Петрович", "@ivanov")])
        assert links[0].match == "exact"

    def test_yo_and_mixed_alphabet_in_fio(self):
        # «Caфiя» набрано в двух алфавитах, «Артём» — с ё.
        links = match(roster("Caфiя Артёмова"),
                      [reg("Артемова Сафия Ивановна", "@safia_a")])
        assert links[0].username == "safia_a"

    def test_diminutive_name(self):
        links = match(roster("Соболева Лиза"),
                      [reg("Соболева Елизавета Владимировна", "@liza_s")])
        assert (links[0].match, links[0].username) == ("diminutive", "liza_s")

    def test_surname_only_when_unique(self):
        links = match(roster("Ковалёв"), [reg("Ковалёв Владимир Алексеевич", "@vova")])
        assert links[0].match == "surname"

    def test_surname_only_rejected_when_ambiguous(self):
        links = match(roster("Ковалёв"),
                      [reg("Ковалёв Владимир", "@vova"),
                       reg("Ковалёв Пётр", "@petr", row=3)])
        assert (links[0].match, links[0].username) == ("none", "")

    def test_duplicate_registration_is_one_person(self):
        # Форму отправили дважды с одним username — это не однофамильцы.
        links = match(roster("Тарасов Егор"),
                      [reg("Тарасов Егор Сергеевич", "@egor_t"),
                       reg("Тарасов Егор Сергеевич", "@egor_t", row=9)])
        assert links[0].username == "egor_t"

    def test_real_namesakes_are_not_guessed(self):
        links = match(roster("Тарасов Егор"),
                      [reg("Тарасов Егор Сергеевич", "@one"),
                       reg("Тарасов Егор Павлович", "@two", row=9)])
        assert links[0].match == "none"
        assert "однофамильц" in links[0].note

    def test_same_username_for_two_students_is_dropped(self):
        # Кто-то указал чужой или общий username — связка ненадёжна для обоих.
        links = match(roster("Иванов Иван", "Петров Пётр"),
                      [reg("Иванов Иван Иванович", "@shared"),
                       reg("Петров Пётр Петрович", "@shared", row=3)])
        assert [lk.match for lk in links] == ["none", "none"]
        assert all(not lk.usable for lk in links)

    def test_different_person_is_not_matched_by_first_name(self):
        # Совпадение только по имени — не совпадение.
        links = match(roster("Гончарова Дарья"), [reg("Зайцева Дарья Михайловна", "@d")])
        assert links[0].match == "none"

    def test_missing_from_registration(self):
        links = match(roster("Левченко Кирилл"), [reg("Исаков Кирилл Михайлович", "@k")])
        assert links[0].note == "регистрационную форму не заполнял"

    def test_unusable_without_username(self):
        links = match(roster("Иванов Иван"), [reg("Иванов Иван Иванович", "нет")])
        assert links[0].match == "exact" and not links[0].usable
        assert "не распознан" in links[0].note

    def test_dead_username_is_not_usable(self):
        links = match(roster("Иванов Иван"), [reg("Иванов Иван Иванович", "@ivanov")])
        links[0].exists = "no"
        assert not links[0].usable
