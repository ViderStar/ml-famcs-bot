"""Объяснение вердикта: почему домашка не зачтена.

Смысл этих тестов — чтобы бот и проверка никогда не расходились. Студенту
показывается не «список замечаний», а именно те причины, по которым тема не
зачтена: критичные замечания и недобор обязательных пунктов. Замечания уровня
«серьёзное» и «мелкое» на зачёт не влияют, и если бот начнёт намекать на
обратное, человек будет чинить не то.
"""

import pytest

from mlbot.views import (blockers, failed_topics, finding_text, hw_card_text,
                         is_blocking, points_needed, results_text, verdict_block)


def test_pass_ratio_matches_the_checker(course):
    import tomllib

    conf = tomllib.loads((course.cfg.checker_dir / "config.toml").read_text(encoding="utf-8"))
    assert course.hw_pass_ratio == conf["verdict"]["hw_pass_ratio"]


def test_points_needed_matches_the_ratio_comparison(course):
    """Граница в пунктах должна совпадать со сравнением доли в проверке."""
    ratio = course.hw_pass_ratio
    for total in range(1, 40):
        need = points_needed(course, {"required_total": total})
        assert need / total >= ratio, f"{need}/{total} проверку бы не прошло"
        if need:
            assert (need - 1) / total < ratio, f"{need - 1}/{total} тоже прошло бы"


def test_verdict_explanation_agrees_with_the_recorded_status(course):
    """Ключевой тест: причины находятся ровно у незачтённых работ.

    Прогоняется по всем работам потока. Если у незачтённой темы причин нет,
    студент увидит «не зачтено» без объяснения — ровно то, на что жаловались.
    """
    checked = 0
    for student in course.active:
        for hw_id, hw in student.homeworks.items():
            if hw["status"] == "missing":
                continue
            reasons = blockers(course, hw)
            checked += 1
            if hw["status"] == "failed":
                assert reasons, f"{student.key} {hw_id}: не зачтено без причины"
            else:
                assert not reasons, f"{student.key} {hw_id}: зачтено, но причины есть"
    assert checked > 3 * len(course.active)


def test_only_criticals_and_points_block(course):
    for student in course.active:
        for hw in student.homeworks.values():
            for r in blockers(course, hw):
                assert r["kind"] in ("points", "critical")
            for f in hw.get("findings", []):
                if f["severity"] != "critical":
                    assert not is_blocking(f)


def test_failed_topics_lists_only_graded_topics(course):
    for student in course.active:
        for hw_id, _ in failed_topics(course, student):
            assert hw_id in course.graded_ids
            assert student.hw(hw_id)["status"] == "failed"


def test_failed_count_matches_the_progress_bar(course):
    """«Не зачтено работ: N» не должно противоречить «зачтено M из 12»."""
    for student in course.active:
        submitted_graded = [h for hw_id, h in student.homeworks.items()
                            if hw_id in course.graded_ids and h["status"] != "missing"]
        assert len(failed_topics(course, student)) + student.passed == len(submitted_graded)


def test_card_of_failed_homework_explains_why(course):
    victim = next(s for s in course.active
                  if any(h["status"] == "failed" for h in s.homeworks.values()))
    hw_id = next(k for k, h in victim.homeworks.items() if h["status"] == "failed")
    card = hw_card_text(course, victim, hw_id, "не сдано")
    assert "Почему не зачтено" in card
    assert "не зачтено" in card


def test_passed_homework_says_remarks_did_not_matter(course):
    student = next(s for s in course.active
                   if any(h["status"] == "passed" and h.get("findings")
                          for h in s.homeworks.values()))
    hw_id = next(k for k, h in student.homeworks.items()
                 if h["status"] == "passed" and h.get("findings"))
    card = hw_card_text(course, student, hw_id, "не сдано")
    assert "на зачёт они не влияли" in card
    assert "Почему не зачтено" not in card


def test_every_verdict_block_renders_for_the_whole_cohort(course):
    """Ни одна карточка не должна падать и ломать разметку."""
    for student in course.active:
        for hw_id, hw in student.homeworks.items():
            text = "\n".join(verdict_block(course, hw))
            assert text.count("<b>") == text.count("</b>")
            assert text.count("<code>") == text.count("</code>")
            hw_card_text(course, student, hw_id, "не сдано")


def test_finding_card_says_whether_it_cost_the_verdict(course):
    student = next(s for s in course.active
                   if any(h["status"] == "failed" and
                          any(f["severity"] == "critical" for f in h["findings"])
                          for h in s.homeworks.values()))
    hw_id, hw = next((k, h) for k, h in student.homeworks.items()
                     if h["status"] == "failed"
                     and any(f["severity"] == "critical" for f in h["findings"]))
    crit = next(f for f in hw["findings"] if f["severity"] == "critical")
    assert "Из-за этого тема не зачтена" in finding_text(course, hw_id, crit, 0, hw)

    other = next((f for f in hw["findings"] if f["severity"] != "critical"), None)
    if other:
        assert "не влияло" in finding_text(course, hw_id, other, 0, hw)

    # Без данных по теме отметки нет — старый вызов не должен врать.
    assert "не зачтена" not in finding_text(course, hw_id, crit, 0)


def test_results_screen_explains_the_gap(course):
    """«Сдал 12, зачтено 6» без объяснения — исходная жалоба студентов."""
    student = next(s for s in course.active if failed_topics(course, s))
    text = results_text(course, student)
    assert f"зачтено {student.passed}" in text
    assert "Не зачтено работ" in text

    clean = next((s for s in course.active if not failed_topics(course, s)), None)
    if clean:
        assert "Не зачтено работ" not in results_text(course, clean)


def test_leakage_no_longer_costs_the_verdict(course):
    """Случай, ради которого утечку понизили до серьёзного замечания.

    Была работа, где все пункты закрыты, а `fit_before_split` закрывал зачёт —
    и таких набралось на два десятка незачётов. Теперь замечание остаётся в
    разборе, но вердикт не меняет. Свойство ищется по потоку, а не по
    конкретному человеку: имён студентов в тестах нет — репозиторий открытый.
    """
    checked = 0
    for st in course.active:
        for hw_id, hw in st.homeworks.items():
            leak = [f for f in hw["findings"] if f["code"] == "common.fit_before_split"]
            if not leak:
                continue
            checked += 1
            assert all(f["severity"] != "critical" for f in leak), f"{st.key} {hw_id}"
            if hw["status"] == "passed":
                reasons = dict(failed_topics(course, st))
                assert hw_id not in reasons, f"{st.key} {hw_id}: зачтено, но в причинах"
    assert checked, "в потоке не нашлось ни одной работы с утечкой"


