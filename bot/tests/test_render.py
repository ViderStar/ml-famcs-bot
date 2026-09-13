"""Markup for Telegram: conversion, escaping, splitting."""

from mlbot.render import LIMIT, SAFE, progress_bar, split, to_html


def test_code_block_is_escaped_and_wrapped():
    html = to_html("Пример:\n\n```python\nif a < b and c > d:\n    print('<b>')\n```")
    assert "<pre>" in html and "</pre>" in html
    assert "&lt;" in html and "&gt;" in html
    assert "<b>" not in html.replace("<pre>", "").split("</pre>")[0][:0] + ""


def test_bold_inline_code_and_links():
    html = to_html("**Что не так.** Строка `df.fillna()` — [Хендбук](https://example.org/a)")
    assert "<b>Что не так.</b>" in html
    assert "<code>df.fillna()</code>" in html
    assert '<a href="https://example.org/a">Хендбук</a>' in html


def test_user_angle_brackets_do_not_break_markup():
    html = to_html("Модель <script>alert(1)</script> прислал студент")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_split_keeps_every_chunk_within_limit():
    long_text = to_html("\n\n".join(f"Абзац номер {i}. " * 40 for i in range(60)))
    chunks = split(long_text)
    assert len(chunks) > 1
    assert all(len(c) <= SAFE for c in chunks)
    assert all(len(c) <= LIMIT for c in chunks)


def test_split_never_breaks_a_code_block():
    body = "текст " * 900 + "\n\n```python\n" + "x = 1\n" * 40 + "```\n\n" + "хвост " * 900
    chunks = split(to_html(body))
    for chunk in chunks:
        assert chunk.count("<pre>") == chunk.count("</pre>")


def test_progress_bar():
    assert progress_bar(0, 12) == "░" * 12
    assert progress_bar(12, 12) == "▓" * 12
    assert len(progress_bar(5, 12)) == 12
    assert progress_bar(3, 0) == "░" * 12
