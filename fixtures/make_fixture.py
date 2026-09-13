#!/usr/bin/env python3
"""A synthetic stream: invented students, reports, awards.

Why. The tests run over the whole stream — every student, every homework, every
finding. The real corpus is not part of the public repository: it holds names,
links to private repositories and reviews. Without it half the tests check
nothing, and the green half manufactures false confidence.

So a stream of the same shape is generated here, entirely invented. Names are
assembled from two lists and belong to nobody; finding codes come from the real
catalog — that is teaching material, not personal data, and the tests must see
real codes.

Generation is deterministic: the same seed gives the same stream, so a test
failure reproduces.

    python fixtures/make_fixture.py            # rebuild fixtures/out
"""

from __future__ import annotations

import csv
import json
import random
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CHECKER = ROOT.parent / "checker"
sys.path.insert(0, str(CHECKER / "src"))

SEED = 20260302
STUDENTS = 60

SURNAMES = (
    "Астахов Белкин Вербицкий Гаврилов Дубровин Ерошкин Жданов Зиновьев "
    "Игнатов Кораблёв Лапшин Мухин Нестеров Орешкин Пчёлкин Рощин Соловьёв "
    "Тимошин Ушаков Фадеев Хлебников Цветков Черёмухин Шилов Щеглов Юдин "
    "Яковлев Ангелов Бирюков Вьюгин"
).split()
NAMES_M = "Артём Борис Вадим Глеб Денис Егор Иван Кирилл Лев Марк Никита Олег Пётр Роман Семён".split()
NAMES_F = "Алина Вера Галина Дарья Ева Жанна Злата Инна Ксения Лада Мила Нина Ольга Полина Рита".split()

STRENGTHS = (
    "Ты аккуратно разделяешь выборки и не подглядываешь в тест — это видно по порядку ячеек.",
    "Графики подписаны и читаются без пояснений: оси, единицы, легенда на месте.",
    "Выводы сформулированы своими словами, а не пересказом вывода библиотеки.",
    "Ты проверяешь гипотезу, а не подгоняешь результат: видно сравнение с бейзлайном.",
    "Код разбит на функции, повторы вынесены — ноутбук читается как текст.",
)
SUMMARIES = (
    "Задание выполнено, разбор корректный. Следующий шаг — сравнить с бейзлайном.",
    "Основное сделано, но выводов не хватает: допиши, что именно показал результат.",
    "Есть смысловая ошибка в валидации — посмотри разбор ниже и переделай этот шаг.",
    "Работа полная и аккуратная. Попробуй тот же приём на другом наборе данных.",
)
PORTRAITS = (
    "Ты идёшь ровно и закрываешь темы подряд — база собрана, дальше стоит углубляться.",
    "Сильная сторона — аккуратность с данными; слабее пока с обоснованием выбора модели.",
    "Видно, что практика даётся легче теории: формулы стоит проговорить ещё раз.",
)
NEXT_STEPS = (
    "Возьми соревнование на Kaggle и доведи решение до сабмита.",
    "Перечитай главу Хендбука про валидацию и переделай последнюю домашку.",
    "Собери небольшой pet-проект на своих данных — это лучше любого учебного датасета.",
)


def load_catalog():
    from mlcheck.catalog import load_dir
    return load_dir(CHECKER / "catalog")


def load_rubrics():
    from mlcheck.rubric import load_dir
    return load_dir(CHECKER / "rubrics")


def fake_people(rnd: random.Random) -> list[tuple[str, str]]:
    """Key and name. Surname and given name are paired without repeats."""
    pairs = [(s, n) for s in SURNAMES for n in (NAMES_M + NAMES_F)]
    rnd.shuffle(pairs)
    out, used = [], set()
    translit = str.maketrans(
        {"а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
         "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
         "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
         "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
         "ы": "y", "ь": "", "ъ": "", "э": "e", "ю": "yu", "я": "ya"})
    for surname, name in pairs:
        if len(out) >= STUDENTS:
            break
        key = f"{surname.lower().translate(translit)}-{name.lower().translate(translit)}"
        if key in used:
            continue
        used.add(key)
        out.append((key, f"{surname} {name}"))
    return out


def build(rnd: random.Random, out: Path) -> None:
    catalog = load_catalog()
    rubrics = load_rubrics()
    hw_ids = sorted(rubrics)
    graded = [h for h in hw_ids if rubrics[h].graded]
    need = round(len(graded) * 0.66)

    by_hw: dict[str, list] = {}
    for art in catalog.values():
        by_hw.setdefault(art.hw, []).append(art)

    findings_dir = out / "findings"
    shutil.rmtree(findings_dir, ignore_errors=True)
    findings_dir.mkdir(parents=True)

    people = fake_people(rnd)
    telegram_rows, award_rows, excluded_rows = [], [], []

    for i, (key, fio) in enumerate(people):
        # Every tenth has an unreachable repository: the bot must explain that too.
        excluded = i % 10 == 9
        depth = rnd.choice([0, 1, 3, 5, 7, 9, 11, 12, 13])
        homeworks, passed = {}, 0

        for n, hw in enumerate(hw_ids):
            title = rubrics[hw].title
            if excluded or n >= depth:
                homeworks[hw] = {
                    "title": title, "status": "missing", "notebook": None,
                    "required_passed": 0, "required_total": 0,
                    "reviewed_by_model": False, "strengths": "", "summary": "",
                    "findings": [],
                }
                continue

            pool = by_hw.get(hw, []) + by_hw.get("common", [])
            picked = rnd.sample(pool, min(len(pool), rnd.choice([0, 1, 2, 3, 4])))
            critical = [a for a in picked if a.severity == "critical"]
            total = max(3, len(rubrics[hw].checks))
            done = total if not critical else rnd.randint(0, total - 1)
            status = "passed" if not critical and done / total >= 0.7 else "failed"
            if status == "passed" and rubrics[hw].graded:
                passed += 1

            homeworks[hw] = {
                "title": title, "status": status,
                "notebook": f"{hw}/{hw}_solution.ipynb",
                "required_passed": done, "required_total": total,
                "reviewed_by_model": True,
                "strengths": rnd.choice(STRENGTHS),
                "summary": rnd.choice(SUMMARIES),
                "findings": [
                    {
                        "code": a.code, "severity": a.severity, "title": a.title,
                        "detail": "", "comment": f"{a.title}. Подробности — в разборе.",
                        "source": rnd.choice(["rule", "llm"]), "cells": [],
                        "links": [[t, u] for t, u in a.links][:3],
                        "article": f"catalog/{a.hw}/{a.code.split('.', 1)[1]}.md",
                    }
                    for a in picked
                ],
            }

        certificate = (not excluded) and passed >= need
        report = {
            "key": key, "fio": fio,
            "repo": f"https://github.com/{key}/ml-course-homeworks",
            "status": "excluded" if excluded else "ok",
            "reason": "репозиторий удалён, приватен или переименован" if excluded else "",
            "certificate": certificate,
            "passed_hw": passed, "total_hw": len(graded),
            "homeworks": homeworks, "similarity": [],
            "portrait": {
                "portrait": rnd.choice(PORTRAITS),
                "growth": [
                    {
                        "topic": hw, "title": f"{rubrics[hw].title}: стоит вернуться",
                        "why": "Тема закрыта не полностью — она понадобится дальше.",
                        "codes": [],
                        "links": [{"title": t, "url": u}
                                  for t, u in (by_hw.get(hw) or by_hw["common"])[0].links[:1]],
                    }
                    for hw in rnd.sample(graded, 2)
                ],
                "next_steps": rnd.choice(NEXT_STEPS),
            } if not excluded else {},
        }
        (findings_dir / f"{key}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

        # The telegram map: some are recognised by username, some are not.
        surname, name = fio.split()
        if i % 4 == 3:
            telegram_rows.append([key, fio, "", "", "none", "", "регистрационную форму не заполнял"])
        else:
            telegram_rows.append([
                key, fio, f"{surname} {name} Сергеевич",
                f"{key.replace('-', '_')}", "exact",
                "no" if i % 7 == 6 else "yes", ""])

        if certificate:
            # File and photo are per person: the bot must hand over exactly the
            # document belonging to them, and a test checks that.
            award_rows.append([
                key, fio,
                f"fixtures/certificates/pdf/{key}.pdf",
                f"fixtures/certificates/photos/{fio}.jpg" if i % 3 else "", ""])
        if excluded:
            excluded_rows.append([fio, report["repo"], "missing_repo",
                                  "репозиторий удалён, приватен или переименован", ""])

    def write(name: str, header: list[str], rows: list[list[str]]) -> None:
        with (out / name).open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(header)
            w.writerows(rows)

    write("telegram_map.csv",
          ["key", "fio", "reg_fio", "username", "match", "exists", "note"], telegram_rows)
    write("awards.csv", ["key", "fio", "certificate", "photo", "note"], award_rows)
    write("excluded.csv",
          ["ФИО", "ссылка из формы", "статус", "причина", "репозитории владельца"],
          excluded_rows)

    (out / "attention.md").write_text(
        "# Требует решения\n\n"
        "Файл собирается проверкой и перечисляет спорные случаи: совпадения работ,\n"
        "найденные секреты, попытки подсказать модели оценку.\n\n"
        "В этом синтетическом потоке спорных случаев нет.\n", encoding="utf-8")

    certs = ROOT / "certificates"
    shutil.rmtree(certs, ignore_errors=True)
    (certs / "pdf").mkdir(parents=True)
    (certs / "photos").mkdir(parents=True)
    # Stubs, not real documents. The check that the PDF carries this student's
    # name skips honestly on them — see tests/test_awards.py.
    for row in award_rows:
        (ROOT.parent / row[2]).write_bytes(
            b"%PDF-1.4\n% synthetic fixture, not a real certificate\n%%EOF\n")
        if row[3]:
            (ROOT.parent / row[3]).write_bytes(
                bytes.fromhex("ffd8ffe000104a46494600010100000100010000ffd9"))

    print(f"студентов: {len(people)}, с сертификатом: {len(award_rows)}, "
          f"исключённых: {len(excluded_rows)}")
    print(f"записано в {out}")


if __name__ == "__main__":
    build(random.Random(SEED), ROOT / "out")
