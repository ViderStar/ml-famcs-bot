"""Application sinks: a file beside the bot and a Notion table.

Our own database is primary and always right. The other two receive a projection
through the `sync_outbox` queue, and there is no reverse import: two writers into
one model lose data silently.
"""

from . import csv_file, notion, worker  # noqa: F401

__all__ = ["csv_file", "notion", "worker"]
