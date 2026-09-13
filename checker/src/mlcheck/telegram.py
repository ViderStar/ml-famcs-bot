"""Matching the registration form to the submission form: name → telegram username.

The homework submission form holds only a name and a repository link, while the
username lives in another table — the course registration form. Here the two are
stitched together by name.

Caution beats completeness. The username reaches the bot as a way to recognise a
student instantly, so a wrong link means a stranger sees someone's review. Only
rules that cannot merge two different people are accepted: a full "surname +
given name" match, a diminutive given name with an exact surname, and a lone
surname that appears exactly once in the registration. Anything doubtful stays
unmatched — that student goes through the usual binding by name and link, which
is more reliable than any guess.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

from .config import Config, load

# Names pick up Latin lookalikes of Cyrillic letters — some are typed in two
# alphabets at once. Normalise to one, or the surname will not be found.
_LAT2CYR = str.maketrans({
    "a": "а", "e": "е", "o": "о", "c": "с", "p": "р", "y": "у", "x": "х",
    "i": "и", "k": "к", "m": "м", "t": "т", "h": "н", "b": "в",
})
_USERNAME = re.compile(r"^[A-Za-z0-9_]{4,32}$")
# Telegram usernames are Latin only, but people type them on a Russian keyboard
# layout, so the first letter comes out Cyrillic. Put the Latin one back.
_CYR2LAT = str.maketrans({
    "а": "a", "е": "e", "о": "o", "с": "c", "р": "p", "у": "y", "х": "x",
    "к": "k", "м": "m", "т": "t", "в": "b", "н": "h", "и": "i",
    "А": "A", "Е": "E", "О": "O", "С": "C", "Р": "P", "У": "Y", "Х": "X",
    "К": "K", "М": "M", "Т": "T", "В": "B", "Н": "H",
})
_TME = re.compile(r"(?:https?://)?(?:t|telegram)\.me/(?:s/)?([A-Za-z0-9_]+)", re.I)

# Diminutive given names seen in these two forms. The list is deliberately
# short: it only applies when the surname matches exactly, and adding entries
# "for the future" is pointless — an extra rule only raises the risk.
_SHORT = {
    "лиза": "елизавета", "влад": "владислав", "саша": "александр",
    "женя": "евгений", "дима": "дмитрий", "миша": "михаил",
    "ваня": "иван", "катя": "екатерина", "настя": "анастасия",
    "маша": "мария", "даша": "дарья", "лёша": "алексей", "леша": "алексей",
    "коля": "николай", "толя": "анатолий", "паша": "павел",
    "юля": "юлия", "оля": "ольга", "таня": "татьяна", "света": "светлана",
    "сережа": "сергей", "андрюша": "андрей", "костя": "константин",
    "тимур": "тимур", "макс": "максим", "рома": "роман", "артем": "артём",
}


def normalize(s: str) -> str:
    s = (s or "").strip().lower().replace("ё", "е").translate(_LAT2CYR)
    return re.sub(r"\s+", " ", re.sub(r"[^а-я\s-]", " ", s)).strip()


def tokens(fio: str) -> list[str]:
    """The meaningful parts of a name. One-character fragments and initials are dropped."""
    return [t for t in normalize(fio).split() if len(t) > 1]


def clean_username(raw: str) -> str:
    """A username from a free-text field: link, @ and stray spaces removed."""
    raw = (raw or "").strip()
    if m := _TME.search(raw):
        raw = m.group(1)
    raw = raw.lstrip("@").strip().strip(".,;")
    raw = raw.split()[0] if raw.split() else ""
    if not _USERNAME.match(raw):
        raw = raw.translate(_CYR2LAT)
    return raw if _USERNAME.match(raw) else ""


@dataclass(frozen=True)
class Registration:
    fio: str
    username: str
    raw_username: str
    row: int


@dataclass
class Link:
    """One link between a submission-form student and a registration row."""

    key: str
    fio: str
    username: str = ""
    reg_fio: str = ""
    match: str = "none"          # exact | diminutive | surname | none
    exists: str = "unknown"      # yes | no | unknown
    note: str = ""

    @property
    def usable(self) -> bool:
        """Whether this username may be used to recognise the student automatically."""
        return bool(self.username) and self.match != "none" and self.exists != "no"


def read_registration(path: Path) -> list[Registration]:
    out: list[Registration] = []
    with path.open(encoding="utf-8", newline="") as fh:
        for i, row in enumerate(csv.DictReader(fh), start=2):
            fio = (row.get("ФИО") or "").strip()
            raw = ""
            for k, v in row.items():
                if k and "Telegram" in k:
                    raw = (v or "").strip()
                    break
            if fio:
                out.append(Registration(fio, clean_username(raw), raw, i))
    return out


def _confirms(reg_name: str, given: str) -> str:
    """Whether the registration given name confirms the submission one."""
    if reg_name == given:
        return "exact"
    if _SHORT.get(given) == reg_name or _SHORT.get(reg_name) == given:
        return "diminutive"
    if len(given) >= 4 and reg_name.startswith(given):
        return "diminutive"
    if len(reg_name) >= 4 and given.startswith(reg_name):
        return "diminutive"
    return ""


def match(roster: list[dict], regs: list[Registration]) -> list[Link]:
    by_pair: dict[frozenset[str], list[Registration]] = {}
    by_surname: dict[str, list[Registration]] = {}
    for r in regs:
        t = tokens(r.fio)
        if len(t) >= 2:
            by_pair.setdefault(frozenset(t[:2]), []).append(r)
        if t:
            by_surname.setdefault(t[0], []).append(r)

    links: list[Link] = []
    for st in roster:
        link = Link(key=st["key"], fio=st["fio"])
        t = tokens(st["fio"])

        # 1. A full "surname + given name" pair in either order.
        hit = by_pair.get(frozenset(t[:2])) if len(t) >= 2 else None
        kind = "exact"

        # 2. Exact surname plus a confirmed given name. In the submission form the
        #    surname is sometimes written second, so both orders are tried.
        if not hit and len(t) >= 2:
            for surname, given in ((t[0], t[1]), (t[1], t[0])):
                cands = [
                    r for r in by_surname.get(surname, [])
                    if len(tk := tokens(r.fio)) >= 2 and _confirms(tk[1], given)
                ]
                if len(cands) == 1:
                    hit, kind = cands, "diminutive"
                    break

        # 3. A lone surname with no given name — accepted only if the registration
        #    holds exactly one such surname. Namesakes stay unmatched.
        if not hit and len(t) == 1:
            cands = by_surname.get(t[0], [])
            if len(cands) == 1:
                hit, kind = cands, "surname"

        # Some people submitted the registration form twice. If every candidate
        # gave the same username, it is one person, not namesakes.
        if hit and len(hit) > 1 and len({r.username for r in hit}) == 1 and hit[0].username:
            hit = hit[:1]

        if hit and len(hit) == 1:
            reg = hit[0]
            link.reg_fio, link.match = reg.fio, kind
            if reg.username:
                link.username = reg.username
            else:
                link.note = f"в регистрации username не распознан: {reg.raw_username!r}"
        elif hit:
            link.note = f"в регистрации {len(hit)} однофамильцев — разобрать вручную"
        else:
            link.note = "регистрационную форму не заполнял"
        links.append(link)

    # One username for two students — the link is unreliable for both.
    seen: dict[str, list[Link]] = {}
    for lk in links:
        if lk.username:
            seen.setdefault(lk.username.lower(), []).append(lk)
    for name, group in seen.items():
        if len(group) > 1:
            who = ", ".join(g.fio for g in group)
            for lk in group:
                lk.match, lk.username = "none", ""
                lk.note = f"username @{name} указали несколько человек: {who}"
    return links


FIELDS = ("key", "fio", "reg_fio", "username", "match", "exists", "note")


def save(links: list[Link], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for lk in links:
            w.writerow({f: getattr(lk, f) for f in FIELDS})


def read_map(path: Path) -> list[Link]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return [Link(**{f: (row.get(f) or "") for f in FIELDS}) for row in csv.DictReader(fh)]


def build(cfg: Config | None = None) -> list[Link]:
    import json

    cfg = cfg or load()
    roster = json.loads((cfg.paths.out / "roster.json").read_text(encoding="utf-8"))
    regs = read_registration(cfg.paths.roster_csv.with_name("Registration_ML_s2_2026.csv"))
    return match(roster, regs)


# --- existence check ----------------------------------------------------------------
#
# The public t.me page returns the owner's name in og:title, and for a free
# username a placeholder "Telegram: Contact @...". This is the only check
# available without the bot sharing a chat: getChat by username works only for
# people who already wrote to the bot. A "no" means "this username does not exist
# right now" — it may have been renamed, so the link is flagged, not deleted.

_CONTACT = re.compile(r'og:title" content="Telegram: Contact @', re.I)
_TITLE = re.compile(r'og:title" content="([^"]*)"')


def probe(username: str, timeout: float = 15.0) -> tuple[str, str]:
    """('yes'|'no'|'unknown', display name)."""
    import urllib.error
    import urllib.request

    req = urllib.request.Request(
        f"https://t.me/{username}",
        headers={"User-Agent": "Mozilla/5.0 (compatible; mlcheck roster check)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read(60_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return ("no", "") if exc.code == 404 else ("unknown", f"HTTP {exc.code}")
    except Exception as exc:                                  # network, timeout, TLS
        return "unknown", type(exc).__name__
    if _CONTACT.search(body):
        return "no", ""
    m = _TITLE.search(body)
    return ("yes", m.group(1)) if m else ("unknown", "")


def verify(links: list[Link], workers: int = 4, pause: float = 0.15) -> list[Link]:
    """Checks the usernames of the links. Gently: t.me is someone else's service."""
    import time
    from concurrent.futures import ThreadPoolExecutor

    todo = [lk for lk in links if lk.username]

    def one(lk: Link) -> None:
        time.sleep(pause)
        state, title = probe(lk.username)
        lk.exists = state
        if state == "no":
            lk.note = (lk.note + "; " if lk.note else "") + "username не существует"
        elif state == "unknown" and title:
            lk.note = (lk.note + "; " if lk.note else "") + f"проверка не удалась: {title}"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, todo))
    return links
