"""Deadlines: parsing Minsk time and displaying it.

Stored in UTC, shown in Minsk time with an explicit label. Otherwise moving the
server to another timezone would shift everyone's deadline at once — silently.

Belarus does not change its clocks; the offset is a constant +3, so no timezone
database is needed.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

MINSK = timezone(timedelta(hours=3))

_LINE = re.compile(
    r"^\s*срок\s*:\s*(\d{1,2})\.(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?\s*$", re.I)


def parse(line: str, now: datetime | None = None) -> str | None:
    """"срок: 14.03 23:59" in Minsk time → a moment in UTC, or None."""
    m = _LINE.match(line or "")
    if not m:
        return None
    now = now or datetime.now(MINSK)
    day, month = int(m.group(1)), int(m.group(2))
    hour = int(m.group(3)) if m.group(3) else 23
    minute = int(m.group(4)) if m.group(4) else 59
    # The month has already passed, so next year was meant.
    year = now.year + (1 if month < now.month else 0)
    try:
        local = datetime(year, month, day, hour, minute, tzinfo=MINSK)
    except ValueError:
        return None
    return local.astimezone(timezone.utc).isoformat(timespec="minutes")


def show(iso: str | None) -> str:
    if not iso:
        return "без срока"
    try:
        moment = datetime.fromisoformat(iso).astimezone(MINSK)
    except ValueError:
        return iso
    return moment.strftime("%d.%m %H:%M") + " по Минску"
