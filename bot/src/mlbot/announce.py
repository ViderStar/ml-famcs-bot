"""The graduate mailing: congratulations, certificate, photo, feedback form.

A one-off action, but written as resumable: every send records an `awards_sent`
event, and a rerun skips that student. If the mailing breaks halfway — rate
limit, network, anything — it can simply be started again, and nobody receives
two certificates.

Run inside the container; the token comes from the environment:

    docker compose run --rm --entrypoint "" -T mlbot \\
        uv run --no-dev python -m mlbot.announce --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import FSInputFile

from . import config, texts
from .broadcast.sender import guard
from .data import Course, Student
from .store import Store

SENT = "awards_sent"
# Pause between sends. Telegram allows more, but the files are heavy and there is
# no hurry: fifty people go out in a couple of minutes.
PAUSE = 1.0


def recipients(course: Course, bound: dict[str, int]) -> list[tuple[Student, int]]:
    """Graduates who have a bound account."""
    out = []
    for st in course.active:
        if st.certificate and st.key in bound:
            out.append((st, bound[st.key]))
    return sorted(out, key=lambda p: p[0].fio.casefold())


def message_for(course: Course, st: Student) -> str:
    has_photo = course.ceremony_photo(st.key) is not None
    return texts.AWARDS_ANNOUNCE.format(
        fio=st.fio,
        passed=st.passed,
        total=course.total_graded,
        photo_note=" и фотографию с вручения" if has_photo else "",
        feedback=texts.FEEDBACK_URL,
    )


async def _send(bot: Bot, tg_id: int, course: Course, st: Student) -> None:
    await guard(lambda: bot.send_message(tg_id, message_for(course, st),
                                         disable_web_page_preview=True))
    cert = course.certificate_file(st.key)
    if cert:
        await asyncio.sleep(PAUSE)
        await guard(lambda: bot.send_document(
            tg_id, FSInputFile(cert, filename=f"Сертификат ML FAMCS — {st.fio}.pdf"),
            caption=texts.CERT_FILE_CAPTION.format(fio=st.fio)))
    photo = course.ceremony_photo(st.key)
    if photo:
        await asyncio.sleep(PAUSE)
        await guard(lambda: bot.send_document(
            tg_id, FSInputFile(photo, filename=f"Вручение ML FAMCS — {st.fio}.jpg"),
            caption=texts.PHOTO_CAPTION.format(fio=st.fio)))


async def run(dry_run: bool, limit: int | None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    log = logging.getLogger("announce")

    cfg = config.load()
    course = Course.load(cfg)
    store = Store(cfg.db_path)
    await store.init()

    bound = {b.student_key: b.tg_id for b in await store.all_bindings()}
    people = recipients(course, bound)
    done = {r["tg_id"] for r in await store.sent_awards()} if hasattr(store, "sent_awards") else set()
    todo = [(st, tg) for st, tg in people if tg not in done]

    graduates = [s for s in course.active if s.certificate]
    log.info("выпускников: %d", len(graduates))
    log.info("из них с привязанным аккаунтом: %d", len(people))
    log.info("уже получили рассылку: %d", len(people) - len(todo))
    unreachable = [s.fio for s in graduates if s.key not in bound]
    if unreachable:
        log.info("написать не можем (нет привязки): %s", ", ".join(unreachable))
    if limit:
        todo = todo[:limit]
    log.info("к отправке сейчас: %d", len(todo))

    if dry_run:
        st, _ = todo[0] if todo else (None, None)
        if st:
            log.info("\n--- пример сообщения (%s) ---\n%s", st.fio, message_for(course, st))
            log.info("--- вложения: сертификат %s, фото %s ---",
                     bool(course.certificate_file(st.key)), bool(course.ceremony_photo(st.key)))
        log.info("\nЭто пробный прогон, ничего не отправлено.")
        return 0

    bot = Bot(cfg.token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    ok, failed = 0, []
    try:
        for st, tg_id in todo:
            try:
                await _send(bot, tg_id, course, st)
            except Exception as exc:               # blocked the bot, deleted the account
                failed.append((st.fio, type(exc).__name__))
                log.info("  ✗ %s: %s", st.fio, exc)
                continue
            await store.log(tg_id, SENT, {"key": st.key})
            ok += 1
            log.info("  ✓ %s", st.fio)
            await asyncio.sleep(PAUSE)
    finally:
        await bot.session.close()

    log.info("\nотправлено: %d", ok)
    if failed:
        log.info("не доставлено: %d", len(failed))
        for fio, err in failed:
            log.info("    %s — %s", fio, err)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="показать, кому и что уйдёт")
    ap.add_argument("--limit", type=int, help="отправить только первым N — для проверки")
    args = ap.parse_args()
    return asyncio.run(run(args.dry_run, args.limit))


if __name__ == "__main__":
    raise SystemExit(main())
