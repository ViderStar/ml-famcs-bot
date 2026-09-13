"""The award registry: whose certificate is in which PDF and whose ceremony photo.

Certificate files are called `sertificate_original-N.pdf` — the name tells you
nothing about the owner, and sending a student someone else's certificate is not
an option: it carries their name. So the name is read from the PDF's own text
layer and matched against the list of people who passed. Photos are named after
people, but macOS stores file names in NFD form, so everything is normalised to
NFC before comparison.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .config import Config, load

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
# Below this similarity a match counts as unproven and does not reach the registry.
FUZZY_MIN = 88


def norm(text: str) -> str:
    """Letters only, case-folded, ё=е, normalised to NFC."""
    text = unicodedata.normalize("NFC", text or "")
    return re.sub(r"[^а-яё]", "", text.lower().replace("ё", "е"))


def word_set(text: str) -> frozenset[str]:
    """Name words without order: in some files surname and given name are swapped."""
    text = unicodedata.normalize("NFC", text or "").lower().replace("ё", "е")
    return frozenset(re.findall(r"[а-я]+", text))


def name_in_pdf(path: Path) -> str | None:
    """The name from a certificate. Letters are space-separated in the text — join them."""
    import pypdf

    try:
        text = pypdf.PdfReader(path).pages[0].extract_text()
    except Exception:
        return None
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        if "learn" in line.lower().replace(" ", "") and i + 1 < len(lines):
            return lines[i + 1]
    return None


@dataclass
class Award:
    key: str
    fio: str
    certificate: str = ""     # path from the project root
    photo: str = ""
    note: str = ""


def _match(candidate: str, targets: dict[str, str]) -> tuple[str | None, str]:
    """(name from the list, how it matched). targets: normalised name → name."""
    n = norm(candidate)
    if n in targets:
        return targets[n], "точно"
    by_words = {word_set(fio): fio for fio in targets.values()}
    if (ws := word_set(candidate)) in by_words:
        return by_words[ws], "другой порядок слов"
    from rapidfuzz import fuzz

    best = max(targets.values(), key=lambda f: fuzz.token_set_ratio(norm(f), n), default=None)
    if best and fuzz.token_set_ratio(norm(best), n) >= FUZZY_MIN:
        return best, f"похоже ({fuzz.token_set_ratio(norm(best), n):.0f})"
    return None, "не сопоставлено"


def build(src: Path, cfg: Config | None = None) -> tuple[list[Award], list[str]]:
    """A registry from a directory with `pdf/` and `photos/`. The second list needs eyes."""
    cfg = cfg or load()
    root = cfg.paths.out.parent
    holders: dict[str, str] = {}
    keys: dict[str, str] = {}
    with (cfg.paths.out / "certificates.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            holders[norm(row["ФИО"])] = row["ФИО"]

    import json

    for p in sorted(cfg.paths.findings.glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        keys[d["fio"]] = d["key"]

    awards = {fio: Award(key=keys.get(fio, ""), fio=fio) for fio in holders.values()}
    problems: list[str] = []

    for pdf in sorted((src / "pdf").glob("*.pdf")):
        raw = name_in_pdf(pdf)
        if not raw:
            problems.append(f"{pdf.name}: не удалось прочитать имя")
            continue
        fio, how = _match(raw, holders)
        if not fio:
            problems.append(f"{pdf.name}: имя «{raw.replace(' ', '')}» не в списке прошедших")
            continue
        if awards[fio].certificate:
            problems.append(f"{pdf.name}: на {fio} уже есть {awards[fio].certificate}")
            continue
        awards[fio].certificate = str(pdf.relative_to(root))
        if how != "точно":
            awards[fio].note = f"сертификат — {how}"

    photos = (src / "photos")
    if photos.exists():
        for img in sorted(p for p in photos.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES):
            fio, how = _match(img.stem, holders)
            if not fio:
                problems.append(f"{img.name}: имя не в списке прошедших")
                continue
            awards[fio].photo = str(img.relative_to(root))
            if how != "точно":
                awards[fio].note = (awards[fio].note + "; " if awards[fio].note else "") \
                    + f"фото — {how}"

    for fio, a in awards.items():
        if not a.certificate:
            problems.append(f"{fio}: сертификата нет")
    return sorted(awards.values(), key=lambda a: a.fio.casefold()), problems


FIELDS = ("key", "fio", "certificate", "photo", "note")


def save(awards: list[Award], cfg: Config | None = None) -> Path:
    cfg = cfg or load()
    path = cfg.paths.out / "awards.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for a in awards:
            w.writerow({f: getattr(a, f) for f in FIELDS})
    return path


def load_awards(path: Path) -> dict[str, Award]:
    """A registry keyed by student — for the bot."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return {r["key"]: Award(**{f: r.get(f, "") for f in FIELDS})
                for r in csv.DictReader(fh) if r.get("key")}
