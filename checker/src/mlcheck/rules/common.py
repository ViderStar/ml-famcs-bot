"""Checks common to every homework: does the work run and is it filled in."""

from __future__ import annotations

import re

from ..nbio import Notebook
from .base import Finding, Severity

_SEED = re.compile(r"random_state|np\.random\.seed|default_rng\s*\(\s*\d|set_seed|random\.seed")
# Demanding a seed makes sense only where randomness exists: pure EDA with no
# split and no training has nothing to fix.
_STOCHASTIC = re.compile(
    r"train_test_split|KFold|ShuffleSplit|cross_val|\.sample\s*\(|np\.random|"
    r"random\.|RandomForest|GradientBoosting|XGB|LGBM|CatBoost|KMeans|DBSCAN|TSNE|"
    r"umap|SGD|MLP|bootstrap|shuffle\s*="
)
_BULLET = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+\S", re.M)


def markdown_bullets(nb: Notebook) -> int:
    return len(_BULLET.findall(nb.markdown_text))


def own_markdown(nb: Notebook, template_md: frozenset[str]) -> str:
    """The student's prose: template cells are subtracted from the markdown."""
    return "\n".join(
        c.source for c in nb.markdown_cells
        if re.sub(r"\s+", " ", c.source).strip() not in template_md
    )


def check(nb: Notebook, hw: str, template_md: frozenset[str] = frozenset()) -> list[Finding]:
    out: list[Finding] = []

    if not nb.ok:
        out.append(Finding(
            code="common.notebook_unreadable", hw=hw, severity=Severity.CRITICAL,
            title="Ноутбук не открывается", detail=nb.error or "",
        ))
        return out

    code = nb.code_cells
    nonempty = nb.nonempty_code_cells
    if not nonempty:
        out.append(Finding(
            code="common.nothing_done", hw=hw, severity=Severity.CRITICAL,
            title="В ноутбуке нет заполненного кода",
            detail=f"ячеек кода {len(code)}, все пустые или только с комментариями",
        ))
        return out

    # Unfilled template cells.
    blanks = [c.index for c in code if c.is_empty and c.has_marker]
    if blanks:
        share = len(blanks) / max(len(code), 1)
        out.append(Finding(
            code="common.blank_template_cells", hw=hw,
            severity=Severity.CRITICAL if share >= 0.30 else Severity.MAJOR,
            title="Остались незаполненные ячейки задания",
            detail=f"{len(blanks)} из {len(code)} ячеек кода не заполнены",
            cells=blanks,
        ))

    # Execution.
    executed = [c for c in nonempty if c.executed]
    if not executed:
        out.append(Finding(
            code="common.not_executed", hw=hw, severity=Severity.CRITICAL,
            title="Ноутбук сохранён без запуска",
            detail="ни у одной ячейки нет номера выполнения — выводов в работе нет",
        ))
    elif len(executed) < len(nonempty):
        missing = [c.index for c in nonempty if not c.executed]
        share = len(missing) / len(nonempty)
        out.append(Finding(
            code="common.partially_executed", hw=hw,
            severity=Severity.CRITICAL if share >= 0.5 else Severity.MAJOR,
            title="Часть ячеек не выполнена",
            detail=f"{len(missing)} из {len(nonempty)} заполненных ячеек без вывода",
            cells=missing,
        ))

    # Errors in the saved outputs.
    err_cells = nb.error_cells
    if err_cells:
        names = []
        for c in err_cells:
            for e in c.errors:
                names.append(f"{e.get('ename')}: {str(e.get('evalue'))[:60]}")
        out.append(Finding(
            code="common.error_output", hw=hw, severity=Severity.CRITICAL,
            title="Ноутбук падает с ошибкой",
            detail="; ".join(dict.fromkeys(names))[:300],
            cells=[c.index for c in err_cells],
        ))

    # Execution order: a sign that "Restart & Run All" was never done.
    breaks = nb.execution_order_breaks()
    if breaks and executed:
        out.append(Finding(
            code="common.execution_out_of_order", hw=hw, severity=Severity.MAJOR,
            title="Ноутбук не выполняется сверху вниз",
            detail=f"номера выполнения идут не по порядку в {len(breaks)} ячейках",
            cells=[c for c, _ in breaks],
        ))

    # Prose conclusions. In template-based work all the markdown may be handout,
    # so what the student wrote is counted separately.
    md_chars = len(nb.markdown_text.strip())
    own_chars = len(own_markdown(nb, template_md).strip())
    if md_chars < 200:
        out.append(Finding(
            code="common.no_conclusions", hw=hw, severity=Severity.MAJOR,
            title="Нет текстовых выводов",
            detail=f"markdown в работе всего {md_chars} символов",
        ))
    elif template_md and own_chars < 200:
        out.append(Finding(
            code="common.no_own_conclusions", hw=hw, severity=Severity.MAJOR,
            title="Весь текст в работе — из шаблона",
            detail=f"собственного markdown {own_chars} символов из {md_chars}",
        ))

    if _STOCHASTIC.search(nb.source_text) and not _SEED.search(nb.source_text):
        out.append(Finding(
            code="common.no_seed", hw=hw, severity=Severity.MINOR,
            title="Не зафиксирован seed",
            detail="результат не воспроизводится при повторном запуске",
        ))

    return out


# --- checks discovered by the exploratory pass over real submissions --------------

_CYRILLIC = re.compile(r"[а-яё]", re.I)
_ABS_PATH = re.compile(
    r"""read_(?:csv|excel|parquet|json)\s*\(\s*["'](/(?!content/)[^"']+|[A-Za-z]:[\\/][^"']+)["']""")
_COLAB_PATH = re.compile(r"""read_\w+\s*\(\s*["']/content/[^"']+["']""")
_WARN_OFF = re.compile(r"warnings\.filterwarnings\s*\(\s*['\"]ignore")
# Secrets in plain text. The value itself never reaches the finding — only the fact.
_SECRETS = (
    ("ключ Kaggle API", re.compile(r"\bKGAT_[A-Za-z0-9]{20,}")),
    ("токен OpenAI", re.compile(r"\bsk-[A-Za-z0-9]{32,}")),
    ("токен GitHub", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}")),
    ("ключ AWS", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("kaggle.json с ключом", re.compile(r'"username"\s*:\s*"[^"]+"\s*,\s*"key"\s*:\s*"[a-f0-9]{32}"')),
)
# Text addressed to the grading system rather than to a reader.
_INJECTION = re.compile(
    r"(?:игн[оа]рируй|ингорируй|забудь)\s+(?:все\s+)?предыдущие\s+инструкц"
    r"|ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions"
    r"|disregard\s+(?:all\s+)?(?:previous|prior)\s+instructions",
    re.I)
# plt.show without parentheses: the function is not called, its repr lands in the output.
_SHOW_NO_CALL = re.compile(r"^\s*(?:plt|pyplot|fig)\.show\s*$", re.M)
# A call whose result goes nowhere and which does not modify the object in place.
_NO_EFFECT = re.compile(
    r"^\s*[\w\]\['\"\.]+\.(dropna|drop_duplicates|fillna|drop|rename|replace|"
    r"sort_values|reset_index|astype|set_index|drop_duplicates)\s*\([^=]*\)\s*$")


def _split_without_seed(src: str) -> bool:
    """train_test_split with no random_state: the split shifts on every run."""
    for m in re.finditer(r"train_test_split\s*\(", src):
        depth, i = 0, m.end() - 1
        while i < len(src):
            if src[i] == "(":
                depth += 1
            elif src[i] == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if "random_state" not in src[m.end():i]:
            return True
    return False


def check_extra(nb: Notebook, hw: str) -> list[Finding]:
    """Findings added after reviewing real course submissions."""
    out: list[Finding] = []

    # Conclusions written as comments inside empty code cells.
    comment_cells = [
        c.index for c in nb.code_cells
        if c.is_empty and len(_CYRILLIC.findall(c.source)) >= 20
    ]
    if comment_cells:
        out.append(Finding(
            code="common.conclusions_in_code_comments", hw=hw, severity=Severity.MAJOR,
            title="Выводы написаны комментариями в ячейке кода",
            detail=f"{len(comment_cells)} ячеек кода содержат только текст в комментариях",
            cells=comment_cells,
        ))

    src = nb.source_text
    if _ABS_PATH.search(src):
        out.append(Finding(
            code="common.absolute_path", hw=hw, severity=Severity.MAJOR,
            title="Абсолютный путь к данным",
            detail=(_ABS_PATH.search(src).group(0))[:90],
        ))
    elif _COLAB_PATH.search(src):
        out.append(Finding(
            code="common.absolute_path", hw=hw, severity=Severity.MINOR,
            title="Путь к данным привязан к Google Colab",
            detail=(_COLAB_PATH.search(src).group(0))[:90],
        ))

    whole = src + "\n" + nb.markdown_text
    if _INJECTION.search(whole):
        out.append(Finding(
            code="common.prompt_injection_attempt", hw=hw, severity=Severity.CRITICAL,
            title="Попытка обмануть автоматическую проверку",
            detail="в работе есть текст, адресованный проверяющей системе",
        ))

    leaked = sorted({name for name, rx in _SECRETS if rx.search(src)})
    if leaked:
        out.append(Finding(
            code="common.secret_in_repo", hw=hw, severity=Severity.CRITICAL,
            title="В репозитории лежит ключ доступа",
            detail=", ".join(leaked),   # the key value is deliberately not stored
        ))

    show_cells = [
        c.index for c in nb.code_cells
        if _SHOW_NO_CALL.search(c.source.replace("\r", ""))
    ]
    if show_cells:
        out.append(Finding(
            code="common.show_without_call", hw=hw, severity=Severity.MAJOR,
            title="plt.show написан без скобок",
            detail="функция не вызывается — в вывод попадает её описание вместо графика",
            cells=show_cells,
        ))

    if _WARN_OFF.search(src):
        out.append(Finding(
            code="common.warnings_suppressed", hw=hw, severity=Severity.MINOR,
            title="Предупреждения отключены глобально",
            detail="warnings.filterwarnings('ignore') прячет в том числе полезные сигналы",
        ))

    if _split_without_seed(src):
        out.append(Finding(
            code="common.split_without_seed", hw=hw, severity=Severity.MAJOR,
            title="Разбиение выборки не зафиксировано",
            detail="в train_test_split не указан random_state",
        ))

    dead = []
    for cell in nb.code_cells:
        for line in cell.source.splitlines():
            if "inplace" in line:
                continue
            if _NO_EFFECT.match(line.split("#", 1)[0]):
                dead.append((cell.index, line.strip()))
    if dead:
        out.append(Finding(
            code="common.no_effect_call", hw=hw, severity=Severity.MAJOR,
            title="Вызов не меняет данные и результат не сохраняется",
            detail="; ".join(ln for _, ln in dead[:3])[:200],
            cells=sorted({c for c, _ in dead}),
        ))
    return out
