"""Loading config.toml and resolving paths relative to the checker/ root."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # checker/


@dataclass(frozen=True)
class Paths:
    roster_csv: Path
    materials: Path
    out: Path

    @property
    def raw(self) -> Path:
        return self.out / "raw"

    @property
    def findings(self) -> Path:
        return self.out / "findings"

    @property
    def reports(self) -> Path:
        return self.out / "reports"

    @property
    def cache(self) -> Path:
        return self.out / "cache"


# eq=False gives identity hashing: it holds dicts inside, and the object is a
# singleton from load() anyway, so lru_cache over it works correctly.
@dataclass(frozen=True, eq=False)
class Config:
    paths: Paths
    verdict: dict
    fetch: dict
    llm: dict
    similarity: dict

    @property
    def rubrics_dir(self) -> Path:
        return ROOT / "rubrics"

    @property
    def catalog_dir(self) -> Path:
        return ROOT / "catalog"


@lru_cache(maxsize=1)
def load(path: Path | None = None) -> Config:
    cfg_path = path or (ROOT / "config.toml")
    raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    p = raw["paths"]
    paths = Paths(
        roster_csv=(ROOT / p["roster_csv"]).resolve(),
        materials=(ROOT / p["materials"]).resolve(),
        out=(ROOT / p["out"]).resolve(),
    )
    return Config(
        paths=paths,
        verdict=raw["verdict"],
        fetch=raw["fetch"],
        llm=raw["llm"],
        similarity=raw["similarity"],
    )
