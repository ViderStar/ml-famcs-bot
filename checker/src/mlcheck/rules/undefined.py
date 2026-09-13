"""Finding names that are used but defined nowhere.

Saved outputs mask the problem: the cell that created a variable is deleted while
its output remains, and the work looks like it runs. Started from scratch such a
notebook fails with a NameError — breaking the main requirement of every course
assignment.

The check is deliberately cautious: at any uncertainty (a cell will not parse,
there is a `from x import *`, exec/globals are used) it stays silent.
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
# Analysis is refused only where names can appear dynamically.
# Reading `if 'df' in locals()` is fine — writing through globals()[...] is not.
_BAIL = re.compile(
    r"\bimport\s+\*|\bexec\s*\(|\beval\s*\(|\b(?:globals|locals|vars)\s*\(\s*\)\s*\["
    r"|\bsetattr\s*\(|\b__import__\s*\(")


class _Scope(ast.NodeVisitor):
    """Collects names defined at module level and every name used."""

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
    """Names with no definition. None if the check cannot be performed."""
    scope = _Scope()
    for cell in nb.code_cells:
        src = _MAGIC.sub("", cell.source)
        if _BAIL.search(src):
            return None
        try:
            with warnings.catch_warnings():
        # Student code is full of strings like "\d+" without an r-prefix;
        # warnings about that must not clutter the pipeline output.
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(src)
        except SyntaxError:
            return None
        scope.visit(tree)
    # `locals()`/`globals()` when read create no names and do not block analysis.
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
