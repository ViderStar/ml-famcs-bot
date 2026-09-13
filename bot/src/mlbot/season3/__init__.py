"""Season 3: tracks, the application form, homework."""

from __future__ import annotations

from pathlib import Path

from .tracks import Season, Track, load_tracks

_SEASON: Season | None = None


def current_season(path: Path | None = None) -> Season:
    """Tracks, read once.

    A cache rather than a global constant: the environment sets the file path,
    and tests substitute the whole season through `set_season`.
    """
    global _SEASON
    if _SEASON is None or path is not None:
        _SEASON = load_tracks(path)
    return _SEASON


def set_season(season: Season | None) -> None:
    global _SEASON
    _SEASON = season


__all__ = ["Season", "Track", "current_season", "load_tracks", "set_season"]
