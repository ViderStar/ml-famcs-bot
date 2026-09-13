"""Поиск имён, которые используются, но нигде не определены.

Сохранённые выводы маскируют проблему: ячейка, где переменная создавалась,
удалена, а её вывод остался, и работа выглядит рабочей. При запуске с нуля
такой ноутбук падает с NameError — то есть нарушает главное требование всех
заданий курса.

Проверка сознательно осторожная: при любой неуверенности (ячейка не разбирается,
есть `from x import *`, используется exec/globals) она молчит.
"""

from __future__ import annotations

import ast
import builtins
import re
import warnings

from ..nbio import Notebook
from .base import Finding, Severity

_MAGIC = re.compile(r"^\s*[%!].*$", re.M)
_BUILTINS = set(dir(builtins)) | {
    "__file__", "__name__", "display", "get_ipython", "In", "Out", "exit", "quit",
}
# Отказываемся анализировать только там, где имена могут появляться динамически.
# Чтение `if 'df' in locals()` этому не мешает — а вот запись через globals()[...] мешает.
_BAIL = re.compile(
    r"\bimport\s+\*|\bexec\s*\(|\beval\s*\(|\b(?:globals|locals|vars)\s*\(\s*\)\s*\["
    r"|\bsetattr\s*\(|\b__import__\s*\(")


class _Scope(ast.NodeVisitor):
    """Собирает имена, определённые на уровне модуля, и все использованные."""

    def __init__(self) -> None:
        self.defined: set[str] = set()
        self.used: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.defined.add(node.id)
        else:
            self.used.add(node.id)
        self.generic_visit(node)

    def _function(self, node) -> None:
        self.defined.add(node.name)
        args = node.args
        for a in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            self.defined.add(a.arg)
        if args.vararg:
            self.defined.add(args.vararg.arg)
        if args.kwarg:
            self.defined.add(args.kwarg.arg)
        self.generic_visit(node)

    visit_FunctionDef = _function
    visit_AsyncFunctionDef = _function

    def visit_Lambda(self, node: ast.Lambda) -> None:
        args = node.args
        for a in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            self.defined.add(a.arg)
        if args.vararg:
            self.defined.add(args.vararg.arg)
        if args.kwarg:
            self.defined.add(args.kwarg.arg)
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.defined.add(node.name)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            self.defined.add((a.asname or a.name).split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for a in node.names:
            self.defined.add(a.asname or a.name)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.defined.add(node.name)
        self.generic_visit(node)

    def visit_Global(self, node: ast.Global) -> None:
        self.defined.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.defined.update(node.names)


def undefined_names(nb: Notebook) -> set[str] | None:
    """Имена без определения. None — если проверку провести нельзя."""
    scope = _Scope()
    for cell in nb.code_cells:
        src = _MAGIC.sub("", cell.source)
        if _BAIL.search(src):
            return None
        try:
            with warnings.catch_warnings():
                # В студенческом коде хватает строк вроде "\d+" без r-префикса;
                # предупреждения об этом не должны засорять вывод конвейера.
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(src)
        except SyntaxError:
            return None
        scope.visit(tree)
    # `locals()`/`globals()` при чтении не создают имён, но и не мешают анализу.
    return {n for n in scope.used - scope.defined - _BUILTINS if not n.startswith("_")}


def check(nb: Notebook, hw: str) -> list[Finding]:
    missing = undefined_names(nb)
    if not missing:
        return []
    return [Finding(
        code="common.undefined_name",
        hw=hw,
        severity=Severity.CRITICAL,
        title="Ноутбук не запустится с нуля: имя нигде не определено",
        detail=", ".join(sorted(missing)[:6]),
    )]
