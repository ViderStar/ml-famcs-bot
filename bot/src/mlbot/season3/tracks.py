"""Season 3 tracks from TOML.

A file rather than constants: teachers and session counts are confirmed right up
to the start, and an edit must not require rebuilding the image.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT = Path(__file__).with_name("tracks.toml")


@dataclass(frozen=True)
class Track:
    id: str
    title: str
    emoji: str
    lessons: int
    teacher: str
    about: str
    is_open: bool = True

    @property
    def button(self) -> str:
        return f"{self.emoji} {self.title}".strip()


@dataclass(frozen=True)
class Season:
    title: str
    starts: str
    about: str
    tracks: tuple[Track, ...]

    def get(self, track_id: str) -> Track | None:
        return next((t for t in self.tracks if t.id == track_id), None)

    @property
    def open(self) -> tuple[Track, ...]:
        return tuple(t for t in self.tracks if t.is_open)


def load_tracks(path: Path | None = None) -> Season:
    raw = tomllib.loads((path or DEFAULT).read_text(encoding="utf-8"))
    season = raw.get("season", {})
    tracks = tuple(
        Track(
            id=t["id"],
            title=t["title"],
            emoji=t.get("emoji", ""),
            lessons=int(t.get("lessons", 0)),
            teacher=t.get("teacher", ""),
            about=t.get("about", "").strip(),
            is_open=bool(t.get("is_open", True)),
        )
        for t in raw.get("track", ())
    )
    return Season(
        title=season.get("title", "Третий сезон"),
        starts=season.get("starts", ""),
        about=season.get("about", "").strip(),
        tracks=tracks,
    )
