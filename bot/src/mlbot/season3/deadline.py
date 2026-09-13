"""Сроки сдачи: разбор минского времени и показ его же.

Храним в UTC, показываем минским и с явной пометкой. Иначе при переносе сервера
в другой часовой пояс срок сместился бы у всех разом — и молча.

Беларусь часы не переводит, смещение постоянное +3, поэтому обходимся без
базы часовых поясов.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

MINSK = timezone(timedelta(hours=3))

_LINE = re.compile(
    r"^\s*срок\s*:\s*(\d{1,2})\.(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?\s*$", re.I)


def parse(line: str, now: datetime | None = None) -> str | None:
    """«срок: 14.03 23:59» минского времени → момент в UTC, либо None."""
    m = _LINE.match(line or "")
    if not m:
        return None
    now = now or datetime.now(MINSK)
    day, month = int(m.group(1)), int(m.group(2))
    hour = int(m.group(3)) if m.group(3) else 23
    minute = int(m.group(4)) if m.group(4) else 59
    # Месяц уже прошёл — значит имелся в виду следующий год.
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
