"""Проверка, что репозиторий существует. Больше ничего.

Содержимое чужого репозитория бот не запрашивает и не клонирует — ни
`contents`, ни `git clone`. Это закреплено структурным тестом: студент отдаёт
ссылку на свою работу, а не доступ к ней.

Привязка **никогда не блокируется** результатом проверки. 404 от GitHub не
отличить от «репозиторий приватный», и отказывать по нему значило бы отвергать
честные работы. Проверка — подсказка, а не вахтёр, и формулировка неосуждающая.

Без токена GitHub даёт 60 запросов в час — на поток в двести человек этого не
хватает даже в день старта. Отсюда кэш на шесть часов, `GITHUB_TOKEN` и
запасной путь: обычный HEAD по HTML-странице, у него лимита нет.
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
    """Разбор ссылки — тем же кодом, что и у проверки домашек."""
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
    """`True`/`False`/`None` — есть, нет, не смогли проверить. Плюс код ответа."""
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(f"{API}/repos/{repo.full}",
                                   headers=_headers(cfg)) as r:
                if r.status == 200:
                    return True, 200
                if r.status == 404:
                    return False, 404
                if r.status in (403, 429):
                    # Лимит исчерпан. HTML-страница лимита не знает.
                    log.info("github: лимит запросов, пробуем HTML")
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
    """Разобрать ссылку и узнать, существует ли репозиторий. С кэшем."""
    repo = parse(url)
    if repo is None:
        return None, None, 0
    cached = await store.repo_check(repo.html, ttl_hours=TTL_HOURS)
    if cached is not None:
        return repo, cached["exists"], int(cached["code"] or 0)
    found, code = await exists(cfg, repo)
    await store.save_repo_check(repo.html, found, code)
    return repo, found, code
