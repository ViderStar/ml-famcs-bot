"""Invented students for walking the screens without a single real message.

Four records cover every branch: a graduate with a certificate and a portrait,
someone who fell short with critical findings, an excluded student (unreachable
repository), and a bound one who submitted nothing.

Finding codes come from the real `checker/catalog`, otherwise a demo student's
review renders empty and the walkthrough shows nothing. That the codes exist is
pinned by `test_demo.py`.

Run:  uv run python demo/make_demo.py
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = pathlib.Path(__file__).resolve().parent / "findings"

HW = {
    "hw01": "Настройка окружения, NumPy и Pandas",
    "hw02": "Разведочный анализ данных (EDA)",
    "hw03": "KNN — метод k ближайших соседей",
    "hw04": "Линейная регрессия",
    "hw05": "Логистическая регрессия с нуля",
    "hw06": "Наивный Байес с нуля",
    "hw07": "Деревья решений",
    "hw08": "SVM — метод опорных векторов",
    "hw09": "Случайный лес",
    "hw10": "Градиентный бустинг",
    "hw11": "Подбор гиперпараметров и интерпретируемость",
    "hw12": "Кластеризация II — DBSCAN",
    "hw13": "Снижение размерности — PCA, t-SNE, UMAP",
}


def finding(code, severity, title, detail="", comment="", links=()):
    return {"code": code, "severity": severity, "title": title, "detail": detail,
            "comment": comment, "source": "llm" if comment else "rule",
            "cells": [], "links": list(links), "article": None}


def hw(hw_id, status, passed=0, total=0, findings=(), strengths="", summary="",
       notebook=None):
    return {"title": HW[hw_id], "status": status,
            "notebook": notebook or (f"{hw_id}/solution.ipynb" if status != "missing" else None),
            "required_passed": passed, "required_total": total,
            "reviewed_by_model": bool(summary), "strengths": strengths,
            "summary": summary, "findings": list(findings)}


LEAK = finding(
    "common.fit_before_split", "major", "Преобразование обучено до разделения выборки",
    detail="X[num] = imputer.fit_transform(X[num])",
    links=[["Кросс-валидация", "https://education.yandex.ru/handbook/ml/article/kross-validaciya"]])
NOT_RUN = finding("common.not_executed", "critical", "Ноутбук сохранён без запуска",
                  detail="ни у одной ячейки нет номера выполнения")
NO_TEXT = finding("common.no_conclusions", "major", "Нет текстовых выводов",
                  detail="markdown в работе всего 84 символа")


def graduate():
    """A graduate: certificate, photo, portrait, every screen filled."""
    hws = {}
    for i, hw_id in enumerate(HW):
        if hw_id == "hw07":
            hws[hw_id] = hw(hw_id, "passed", 0, 0, strengths="Разобрался с обрезкой дерева.")
            continue
        hws[hw_id] = hw(
            hw_id, "passed", 9, 9,
            findings=[LEAK] if i % 4 == 0 else [],
            strengths="Умеешь проверять гипотезу до того, как поверить в метрику.",
            summary="Работа сделана целиком, выводы честные. Следующий шаг — собрать "
                    "препроцессинг в Pipeline, чтобы утечка стала невозможной.")
    return {
        "key": "demo-star", "fio": "Демидова Вера (демо)",
        "repo": "https://github.com/demo-star/ml-course-homeworks",
        "status": "ok", "reason": "", "certificate": True,
        "passed_hw": 12, "total_hw": 12, "homeworks": hws, "similarity": [],
        "portrait": {
            "portrait": "За курс видно главное умение: ты не веришь метрике, пока не "
                        "проверишь её на бейзлайне. Свои реализации KNN и логрегрессии "
                        "сходятся со sklearn, а выводы опираются на числа из работы.",
            "growth": [{"topic": "hw04", "title": "Утечка при препроцессинге",
                        "why": "Импьютер обучался до разбиения в трёх работах.",
                        "codes": ["common.fit_before_split"],
                        "links": [{"title": "Кросс-валидация",
                                   "url": "https://education.yandex.ru/handbook/ml/article/kross-validaciya"}]}],
            "next_steps": "Собери препроцессинг в Pipeline и прогони кросс-валидацию.",
        },
    }


def borderline():
    """Fell short: some topics passed, critical findings and too few items."""
    hws = {}
    for i, hw_id in enumerate(HW):
        if i < 5:
            hws[hw_id] = hw(hw_id, "passed", 8, 9, strengths="Аккуратная работа с признаками.")
        elif hw_id == "hw07":
            hws[hw_id] = hw(hw_id, "missing")
        elif i < 9:
            hws[hw_id] = hw(hw_id, "failed", 4, 9, findings=[NOT_RUN, NO_TEXT],
                            summary="Ноутбук не запускался — выводов в работе нет. "
                                    "Прогони Restart & Run All и перезалей.")
        else:
            hws[hw_id] = hw(hw_id, "missing")
    return {
        "key": "demo-almost", "fio": "Почтивсёв Пётр (демо)",
        "repo": "https://github.com/demo-almost/ml",
        "status": "ok", "reason": "", "certificate": False,
        "passed_hw": 5, "total_hw": 12, "homeworks": hws, "similarity": [],
        "portrait": None,
    }


def excluded():
    """Unreachable repository: the EXCLUDED screen."""
    return {
        "key": "demo-lost", "fio": "Приватов Игнат (демо)",
        "repo": "https://github.com/demo-lost/hidden",
        "status": "excluded", "reason": "репозиторий недоступен (404)",
        "certificate": False, "passed_hw": 0, "total_hw": 12,
        "homeworks": {k: hw(k, "missing") for k in HW}, "similarity": [],
        "portrait": None,
    }


def empty():
    """Bound but submitted nothing: the empty state of every screen."""
    return {
        "key": "demo-quiet", "fio": "Тихонов Савва (демо)",
        "repo": "https://github.com/demo-quiet/ml-course",
        "status": "ok", "reason": "", "certificate": False,
        "passed_hw": 0, "total_hw": 12,
        "homeworks": {k: hw(k, "missing") for k in HW}, "similarity": [],
        "portrait": None,
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    for build in (graduate, borderline, excluded, empty):
        rec = build()
        (OUT / f"{rec['key']}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  {rec['key']:14} {rec['fio']:24} зачтено {rec['passed_hw']}/12"
              f" сертификат {'да' if rec['certificate'] else 'нет'}")
    print(f"\nкаталог: {OUT}")


if __name__ == "__main__":
    main()
