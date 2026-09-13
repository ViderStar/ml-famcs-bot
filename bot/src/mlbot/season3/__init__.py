"""Третий сезон: направления, анкета, домашки."""

from __future__ import annotations

from pathlib import Path

from .tracks import Season, Track, load_tracks

_SEASON: Season | None = None


def current_season(path: Path | None = None) -> Season:
    """Направления, прочитанные один раз.

    Кэш, а не глобальная константа: путь к файлу задаёт окружение, а тесты
    подменяют сезон целиком через `set_season`.
    """
    global _SEASON
    if _SEASON is None or path is not None:
        _SEASON = load_tracks(path)
    return _SEASON


def set_season(season: Season | None) -> None:
    global _SEASON
    _SEASON = season


__all__ = ["Season", "Track", "current_season", "load_tracks", "set_season"]
