"""Detecting data leakage.

Only things that genuinely learn statistics from the data — and therefore must
see the training split alone — count as leakage: scaling, imputation, PCA,
feature selection, text vectorisation, target encoding.

Deliberately NOT counted as leakage:
* `LabelEncoder`/`OneHotEncoder`/`OrdinalEncoder` without a target — they only
  enumerate categories and take no statistics from the target;
* t-SNE and UMAP — they are transductive, have no `transform`, and
  `fit_transform` on whatever data is the only way to use them;
* lines inherited from the handout template — the student is not responsible.

The analysis works line by line in cell order rather than through an AST: many
submissions contain magics and unclosed constructs that break AST parsing.
"""

from __future__ import annotations

import re

from ..nbio import Notebook
from ..templates import normalize_line
from .base import Finding, Severity

# Transforms that learn statistics from the data.
_STAT = (
    r"(?:\w*(?:scaler|imputer|pca|normalizer|discretizer|selector|vectorizer|"
    r"svd|kbins|quantiletransformer|powertransformer))"
)
_STAT_CLASS = (
    r"(?:StandardScaler|MinMaxScaler|RobustScaler|MaxAbsScaler|Normalizer|SimpleImputer|"
    r"KNNImputer|IterativeImputer|PCA|TruncatedSVD|KBinsDiscretizer|QuantileTransformer|"
    r"PowerTransformer|TfidfVectorizer|CountVectorizer|SelectKBest|SelectFromModel)"
)
# Target encoding is real leakage: the values come from the target.
_TARGET_ENC = (
    r"(?:TargetEncoder|CatBoostEncoder|WOEEncoder|LeaveOneOutEncoder|JamesSteinEncoder|"
    r"MEstimateEncoder)"
)

_FIT_STAT = re.compile(rf"\b{_STAT}\s*\.\s*fit(?:_transform)?\s*\(", re.I)
# Imputing with a statistic computed over all the data is the same leakage,
# just without a transformer object: df.fillna(df.median()) before the split.
_FILLNA_STAT = re.compile(
    r"\.fillna\s*\([^()]*\.\s*(?:mean|median|mode|quantile)\s*\(", re.I)
_FIT_STAT_INLINE = re.compile(rf"\b{_STAT_CLASS}\s*\([^()]*\)\s*\.\s*fit(?:_transform)?\s*\(", re.I)
# Mentioning the class without calling .fit is an import, not leakage.
_FIT_TARGET_ENC = re.compile(rf"\b{_TARGET_ENC}\b(?=.*\.\s*fit)", re.I)
# encoder.fit_transform(X, y) — the second argument gives away target encoding.
_FIT_WITH_Y = re.compile(
    r"\b\w*encoder\s*\.\s*fit(?:_transform)?\s*\([^()]*,\s*[\w\[\]'\"\.]*\s*\)", re.I
)

_SPLIT = re.compile(r"\b(?:train_test_split|StratifiedShuffleSplit|TimeSeriesSplit)\s*\(")
# A Pipeline inside cross-validation is the correct way; no leakage.
_PIPELINE = re.compile(r"\b(?:make_pipeline|Pipeline)\s*\(")

    # Fitting on the training split is normal. The underscore is part of the
    # word, so "\btrain\b" would not match inside "X_train".
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
            # Major rather than critical: the mistake is real but identical
            # across submissions — copied from a shared template — and on its own
            # it failed twenty otherwise complete assignments. Fitting on the test
            # set itself (below) stays critical.
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
