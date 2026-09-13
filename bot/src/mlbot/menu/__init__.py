"""The menu tree: node registry (`core`), screens, entry point (`router`).

The name `router` here is a module, not a Router object: the entry point is
`menu.router.router`, the same shape as the other handlers.
"""

from . import admin, core, router, screens, season3  # noqa: F401

__all__ = ["admin", "core", "router", "screens", "season3"]
