"""The Notion table — plain HTTP over aiohttp.

`aiohttp` is already there transitively via aiogram; `notion-client` would drag
in `httpx` to save forty lines that would need testing anyway. Three calls are
needed: find a page by tg_id, create, update.

The API version is pinned in a header: without it Notion serves "the latest",
and the response schema changes silently one day.

Creation is idempotent: a query by the numeric `tg_id` property precedes the
`POST`. A restart between "page created" and "id recorded" will not make a
duplicate.
"""

from __future__ import annotations

import logging

import aiohttp

log = logging.getLogger("notion")

API = "https://api.notion.com/v1"
VERSION = "2022-06-28"
TIMEOUT = aiohttp.ClientTimeout(total=20)

# Table properties. Names as they appear in the Notion UI; the type decides
# which key the value is sent under.
PROPS: tuple[tuple[str, str, str], ...] = (
    ("tg_id", "number", "tg_id"),
    ("Телеграм", "rich_text", "username"),
    ("ФИО", "title", "fio"),
    ("Почта", "email", "email"),
    ("Университет", "select", "university"),
    ("Факультет", "rich_text", "faculty"),
    ("Курс", "select", "year"),
    ("Уровень", "select", "level"),
    ("Python", "select", "python"),
    ("Математика", "select", "math"),
    ("ML", "select", "ml"),
    ("Направления", "multi_select", "tracks"),
    ("Знает", "multi_select", "knows"),
    ("Почему", "rich_text", "why"),
)


class NotionError(RuntimeError):
    pass


def _headers(cfg) -> dict:
    return {
        "Authorization": f"Bearer {cfg.notion_token}",
        "Notion-Version": VERSION,
        "Content-Type": "application/json",
    }


def _value(kind: str, value) -> dict | None:
    if value in (None, "", []):
        return None
    if kind == "number":
        return {"number": int(value)}
    if kind == "title":
        return {"title": [{"text": {"content": str(value)[:2000]}}]}
    if kind == "rich_text":
        return {"rich_text": [{"text": {"content": str(value)[:2000]}}]}
    if kind == "email":
        return {"email": str(value)[:200]}
    if kind == "select":
        return {"select": {"name": str(value)[:100]}}
    if kind == "multi_select":
        return {"multi_select": [{"name": str(v)[:100]} for v in value][:100]}
    return None


def properties(row: dict) -> dict:
    out = {}
    for name, kind, key in PROPS:
        value = row.get(key)
        if kind == "multi_select" and isinstance(value, str):
            value = [v for v in value.split(";") if v]
        prepared = _value(kind, value)
        if prepared is not None:
            out[name] = prepared
    return out


async def _post(session, url: str, cfg, payload: dict) -> dict:
    async with session.post(url, headers=_headers(cfg), json=payload) as r:
        body = await r.json(content_type=None)
        if r.status >= 400:
            raise NotionError(f"{r.status}: {str(body)[:300]}")
        return body


async def find_page(session, cfg, tg_id: int) -> str | None:
    """The page with this tg_id, if one already exists.

    This is what makes creation idempotent: without the query, a restart between
    "created" and "id remembered" would put the same person in twice.
    """
    payload = {"filter": {"property": "tg_id", "number": {"equals": int(tg_id)}},
               "page_size": 1}
    body = await _post(session, f"{API}/databases/{cfg.notion_db}/query", cfg, payload)
    results = body.get("results") or []
    return results[0]["id"] if results else None


async def upsert(cfg, row: dict, page_id: str | None = None) -> str:
    if not cfg.notion_ready:
        raise NotionError("нет NOTION_TOKEN или NOTION_DB")
    props = properties(row)
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        if page_id is None:
            page_id = await find_page(session, cfg, row["tg_id"])
        if page_id is None:
            body = await _post(session, f"{API}/pages", cfg, {
                "parent": {"database_id": cfg.notion_db}, "properties": props})
            return body["id"]
        async with session.patch(f"{API}/pages/{page_id}", headers=_headers(cfg),
                                 json={"properties": props}) as r:
            body = await r.json(content_type=None)
            if r.status >= 400:
                raise NotionError(f"{r.status}: {str(body)[:300]}")
        return page_id


async def sync(cfg, store, task: dict) -> str | None:
    from .csv_file import row_of

    apps = {str(a["tg_id"]): a for a in await store.applications("submitted")}
    app = apps.get(task["key"])
    if app is None:
        return None
    page_id = await store.remote_id("notion", "application", task["key"])
    row = row_of(app)
    row["tracks"] = app.get("tracks", [])
    row["knows"] = app["answers"].get("knows", [])
    return await upsert(cfg, row, page_id)


async def fetch_all(cfg) -> list[dict]:
    """What the table holds — for the reconciliation screen. Changes nothing."""
    if not cfg.notion_ready:
        raise NotionError("нет NOTION_TOKEN или NOTION_DB")
    out, cursor = [], None
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        while True:
            payload = {"page_size": 100}
            if cursor:
                payload["start_cursor"] = cursor
            body = await _post(session, f"{API}/databases/{cfg.notion_db}/query",
                               cfg, payload)
            out += body.get("results") or []
            cursor = body.get("next_cursor")
            if not body.get("has_more"):
                break
    return out
