"""Поиск утечек данных.

Утечкой считается только то, что действительно выучивает статистику по данным
и потому обязано видеть лишь обучающую выборку: масштабирование, заполнение
пропусков, PCA, отбор признаков, векторизация текста, target encoding.

Сознательно НЕ считаем утечкой:
* `LabelEncoder`/`OneHotEncoder`/`OrdinalEncoder` без целевой переменной —
  они лишь перечисляют категории, никакой статистики от таргета не берут;
* t-SNE и UMAP — они трансдуктивны, у них нет `transform`, и `fit_transform`
  на любых данных является единственным способом применения;
* строки, унаследованные из раздаточной заготовки, — за них отвечает не студент.

Работаем по строкам в порядке ячеек, а не через AST: во многих работах есть
магии и незакрытые конструкции, на которых разбор AST падает.
"""

from __future__ import annotations

import re

from ..nbio import Notebook
from ..templates import normalize_line
from .base import Finding, Severity

# Преобразования, выучивающие статистику по данным.
_STAT = (
    r"(?:\w*(?:scaler|imputer|pca|normalizer|discretizer|selector|vectorizer|"
    r"svd|kbins|quantiletransformer|powertransformer))"
)
_STAT_CLASS = (
    r"(?:StandardScaler|MinMaxScaler|RobustScaler|MaxAbsScaler|Normalizer|SimpleImputer|"
    r"KNNImputer|IterativeImputer|PCA|TruncatedSVD|KBinsDiscretizer|QuantileTransformer|"
    r"PowerTransformer|TfidfVectorizer|CountVectorizer|SelectKBest|SelectFromModel)"
)
# Target encoding — настоящая утечка: значения берутся из таргета.
_TARGET_ENC = (
    r"(?:TargetEncoder|CatBoostEncoder|WOEEncoder|LeaveOneOutEncoder|JamesSteinEncoder|"
    r"MEstimateEncoder)"
)

_FIT_STAT = re.compile(rf"\b{_STAT}\s*\.\s*fit(?:_transform)?\s*\(", re.I)
# Заполнение пропусков посчитанной по всем данным статистикой — та же утечка,
# только без объекта-преобразователя: df.fillna(df.median()) до train_test_split.
_FILLNA_STAT = re.compile(
    r"\.fillna\s*\([^()]*\.\s*(?:mean|median|mode|quantile)\s*\(", re.I)
_FIT_STAT_INLINE = re.compile(rf"\b{_STAT_CLASS}\s*\([^()]*\)\s*\.\s*fit(?:_transform)?\s*\(", re.I)
# Упоминание класса без вызова .fit — это импорт, а не утечка.
_FIT_TARGET_ENC = re.compile(rf"\b{_TARGET_ENC}\b(?=.*\.\s*fit)", re.I)
# encoder.fit_transform(X, y) — второй аргумент выдаёт target encoding.
_FIT_WITH_Y = re.compile(
    r"\b\w*encoder\s*\.\s*fit(?:_transform)?\s*\([^()]*,\s*[\w\[\]'\"\.]*\s*\)", re.I
)

_SPLIT = re.compile(r"\b(?:train_test_split|StratifiedShuffleSplit|TimeSeriesSplit)\s*\(")
# Pipeline внутри кросс-валидации — правильный способ, утечки нет.
_PIPELINE = re.compile(r"\b(?:make_pipeline|Pipeline)\s*\(")

# Обучение на обучающей выборке — норма. Подчёркивание словесное, поэтому
# «\btrain\b» не сработало бы внутри «X_train»: границу слова слева не ставим.
_ON_TRAIN = re.compile(r"\.\s*fit(?:_transform)?\s*\(\s*[^()]*train", re.I)
_TRANSDUCTIVE = re.compile(r"\b(?:tsne|t_sne|umap|manifold)\w*\s*\.", re.I)
_ON_TEST = re.compile(r"\.\s*fit(?:_transform)?\s*\(\s*(?:X_?test|x_?test|test_X|df_test)\b", re.I)


def _numbered_lines(nb: Notebook) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for cell in nb.code_cells:
        for line in cell.source.splitlines():
            stripped = line.split("#", 1)[0]
            if stripped.strip():
                out.append((cell.index, stripped))
    return out


def _is_statistical_fit(line: str) -> bool:
    if _FILLNA_STAT.search(line):
        return True
    if ".fit" not in line.replace(" ", ""):
        return False
    if _FIT_TARGET_ENC.search(line) or _FIT_WITH_Y.search(line):
        return True
    return bool(_FIT_STAT.search(line) or _FIT_STAT_INLINE.search(line))


def _skip(line: str, template_lines: frozenset[str], exempt: tuple[str, ...]) -> bool:
    low = line.lower()
    return (
        _ON_TRAIN.search(line) is not None
        or _TRANSDUCTIVE.search(line) is not None
        or any(e in low for e in exempt)
        or normalize_line(line) in template_lines
    )


def check(
    nb: Notebook,
    hw: str,
    template_lines: frozenset[str] = frozenset(),
    exempt: tuple[str, ...] = (),
) -> list[Finding]:
    findings: list[Finding] = []
    lines = _numbered_lines(nb)
    if not lines:
        return findings

    split_at = next((i for i, (_, ln) in enumerate(lines) if _SPLIT.search(ln)), None)
    uses_pipeline = any(_PIPELINE.search(ln) for _, ln in lines)

    if split_at is not None and not uses_pipeline:
        before = [
            (cell, ln) for i, (cell, ln) in enumerate(lines)
            if i < split_at
            and _is_statistical_fit(ln)
            and not _skip(ln, template_lines, exempt)
        ]
        if before:
            # Серьёзное, а не критичное: ошибка настоящая, но одна и та же во
            # всех работах — скопирована из общего шаблона, — и на потоке она
            # одна закрывала двадцать зачётов при полностью выполненных заданиях.
            # Обучение на самом тесте (ниже) остаётся критичным.
            findings.append(Finding(
                code="common.fit_before_split",
                hw=hw,
                severity=Severity.MAJOR,
                title="Преобразование обучено до разделения выборки",
                detail="; ".join(ln.strip()[:90] for _, ln in before[:3]),
                cells=sorted({c for c, _ in before}),
            ))

    on_test = [
        (cell, ln) for cell, ln in lines
        if _ON_TEST.search(ln)
        and _is_statistical_fit(ln)
        and not _skip(ln, template_lines, exempt)
    ]
    if on_test:
        findings.append(Finding(
            code="common.fit_on_test",
            hw=hw,
            severity=Severity.CRITICAL,
            title="Преобразование обучено на тестовой выборке",
            detail="; ".join(ln.strip()[:90] for _, ln in on_test[:3]),
            cells=sorted({c for c, _ in on_test}),
        ))
    return findings
