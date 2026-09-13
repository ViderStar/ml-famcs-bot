"""Дерево меню: реестр узлов (`core`), экраны, точка входа (`router`).

Имя `router` здесь — модуль, а не объект Router: точка входа собирается как
`menu.router.router`, так же как у остальных обработчиков.
"""

from . import admin, core, router, screens, season3  # noqa: F401

__all__ = ["admin", "core", "router", "screens", "season3"]
