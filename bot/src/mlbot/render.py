"""Catalog markdown → Telegram HTML, and splitting long messages.

Telegram understands a narrow set of tags and fails on invalid markup, so code
blocks are hidden first, everything else is escaped, and only then are tags put
back. Splitting never tears a code block in half.
"""

from __future__ import annotations

import html
import re

LIMIT = 4096
SAFE = 3900          # headroom for a caption and buttons

_FENCE = re.compile(r"```(\w*)\n(.*?)```", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_HEADING = re.compile(r"^#{1,6}\s*(.+)$", re.M)
_QUOTE = re.compile(r"^>\s?(.*)$", re.M)
_BULLET = re.compile(r"^[-*]\s+", re.M)


def to_html(md: str) -> str:
    """Converts article markdown into the markup Telegram accepts."""
    blocks: list[str] = []

    def stash(m: re.Match) -> str:
        blocks.append(html.escape(m.group(2).rstrip()))
        return f"\x00CODE{len(blocks) - 1}\x00"

    text = _FENCE.sub(stash, md)
    text = html.escape(text)

    text = _HEADING.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _BOLD.sub(lambda m: f"<b>{m.group(1)}</b>", text)
    text = _INLINE_CODE.sub(lambda m: f"<code>{m.group(1)}</code>", text)
    # Links: after escaping, markdown brackets look like plain text.
    text = _LINK.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
    text = _QUOTE.sub(lambda m: f"<i>{m.group(1)}</i>", text)
    text = _BULLET.sub("• ", text)

    for i, block in enumerate(blocks):
        text = text.replace(f"\x00CODE{i}\x00", f"<pre>{block}</pre>")

    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_plain(text: str, limit: int) -> list[str]:
    """Splits a code-free chunk by paragraphs, then by lines."""
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for para in text.split("\n\n"):
        candidate = f"{current}\n\n{para}" if current else para
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            parts.append(current)
        while len(para) > limit:
            cut = para.rfind("\n", 0, limit)
            if cut <= 0:
                cut = limit
            parts.append(para[:cut])
            para = para[cut:].lstrip("\n")
        current = para
    if current:
        parts.append(current)
    return parts


def split(text: str, limit: int = SAFE) -> list[str]:
    """Splits ready HTML into messages without breaking a <pre>."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    buffer = ""
    # Chunks outside <pre> can be split freely; a <pre> only goes whole.
    for piece in re.split(r"(<pre>.*?</pre>)", text, flags=re.S):
        if not piece:
            continue
        if piece.startswith("<pre>"):
            if len(buffer) + len(piece) > limit and buffer:
                chunks.append(buffer.strip())
                buffer = ""
            if len(piece) > limit:
                # A giant code block — send it as is, with the tail cut off.
                chunks.append(piece[: limit - len("\n…</pre>")] + "\n…</pre>")
                continue
            buffer += piece
            continue
        for part in _split_plain(piece, limit):
            if len(buffer) + len(part) > limit and buffer:
                chunks.append(buffer.strip())
                buffer = ""
            buffer += part
    if buffer.strip():
        chunks.append(buffer.strip())
    return [c for c in chunks if c]


def progress_bar(done: int, total: int, width: int = 12) -> str:
    filled = round(width * done / total) if total else 0
    return "▓" * filled + "░" * (width - filled)


def escape(text: str) -> str:
    return html.escape(text or "")
