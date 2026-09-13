"""Checking that a repository exists. Nothing more.

The bot never requests or clones the contents of someone's repository — no
`contents` endpoint, no clone. A structural test pins that: a student hands over
a link to their work, not access to it.

Binding is **never blocked** by the result. A GitHub 404 is indistinguishable
from "the repository is private", and refusing on it would reject honest work.
The check is a hint, not a gatekeeper, and the wording is non-judgemental.

Without a token GitHub allows 60 requests an hour — not enough for two hundred
students even on launch day. Hence a six-hour cache, `GITHUB_TOKEN`, and a
fallback: a plain HEAD against the HTML page, which has no such limit.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import aiohttp

log = logging.getLogger("github")

API = "https://api.github.com"
TIMEOUT = aiohttp.ClientTimeout(total=10)
TTL_HOURS = 6

_OWNER_REPO = re.compile(r"^([A-Za-z0-9][A-Za-z0-9-]{0,38})/([A-Za-z0-9._-]{1,100})$")


@dataclass(frozen=True)
class Repo:
    url: str
    owner: str
    name: str

    @property
    def full(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def html(self) -> str:
        return f"https://github.com/{self.full}"


def parse(url: str) -> Repo | None:
    """Link parsing — the same code the grader uses."""
    from mlcheck.roster import normalize_url

    slug = normalize_url(url)
    m = _OWNER_REPO.fullmatch(slug)
    if not m:
        return None
    return Repo(url=url.strip(), owner=m.group(1), name=m.group(2))


def _headers(cfg) -> dict:
    head = {"Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"}
    if cfg.github_token:
        head["Authorization"] = f"Bearer {cfg.github_token}"
    return head


async def exists(cfg, repo: Repo) -> tuple[bool | None, int]:
    """`True`/`False`/`None` — exists, does not, could not check. Plus the status code."""
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{API}/repos/{repo.full}",
                                   headers=_headers(cfg)) as r:
                if r.status == 200:
                    return True, 200
                if r.status == 404:
                    return False, 404
                if r.status in (403, 429):
                    # Rate limit hit. The HTML page knows no such limit.
                    log.info("github: rate limited, falling back to HTML")
                    async with session.head(repo.html,
                                            allow_redirects=True) as h:
                        if h.status == 200:
                            return True, 200
                        if h.status == 404:
                            return False, 404
                        return None, h.status
                return None, r.status
    except Exception as exc:
        log.info("github: %s", exc)
        return None, 0


async def check(cfg, store, url: str) -> tuple[Repo | None, bool | None, int]:
    """Parse the link and find out whether the repository exists. Cached."""
    repo = parse(url)
    if repo is None:
        return None, None, 0
    cached = await store.repo_check(repo.html, ttl_hours=TTL_HOURS)
    if cached is not None:
        return repo, cached["exists"], int(cached["code"] or 0)
    found, code = await exists(cfg, repo)
    await store.save_repo_check(repo.html, found, code)
    return repo, found, code
