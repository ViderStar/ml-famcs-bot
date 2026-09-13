"""Season 3: the form, three sinks, the repository.

The point here is that the form cannot be lost. It is filled in twelve steps,
survives a restart, and saving it plus enqueueing the sink tasks happen in one
transaction: there is no window between them to crash in.
"""


import pytest

from harness import Bench
from mlbot.menu import core
from mlbot.season3 import wizard
from mlbot.sinks import worker
from mlbot.store import Store

ME = 4242


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "s3.sqlite3")
    await s.init()
    return s


@pytest.fixture
def cfg3(cfg, tmp_path):
    import dataclasses
    return dataclasses.replace(cfg, export_dir=tmp_path / "export")


async def fill(bench, store, *, tracks=("cv", "dl")) -> dict:
    """Walk the form to the end the way a person does."""
    await bench.press(core.cb("s3.reg"))
    await bench.send("Иванов Иван Иванович")
    await bench.send("ivanov@gmail.com")
    await bench.press(core.cb("s3.a", "university:БГУ"))
    await bench.press(core.cb("s3.a", "faculty:ФПМИ"))
    await bench.press(core.cb("s3.a", "year:2"))
    await bench.press(core.cb("s3.a", "level:basic"))
    await bench.press(core.cb("s3.a", "python:2"))
    await bench.press(core.cb("s3.a", "math:2"))
    await bench.press(core.cb("s3.a", "ml:1"))
    await bench.press(core.cb("s3.m", "knows:derivative"))
    await bench.press(core.cb("s3.nx", "knows"))
    for t in tracks:
        await bench.press(core.cb("s3.m", f"tracks:{t}"))
    await bench.press(core.cb("s3.nx", "tracks"))
    await bench.send("Хочу дойти до конца.")
    return (await store.application(ME))["answers"]


# --- the form ------------------------------------------------------------------------

async def test_a_person_can_walk_the_whole_form(cfg3, course, store):
    bench = Bench(cfg3, course, store, user_id=ME, username="newbie")
    answers = await fill(bench, store)
    assert answers["fio"] == "Иванов Иван Иванович"
    assert answers["email"] == "ivanov@gmail.com"
    assert answers["tracks"] == ["cv", "dl"]
    assert not wizard.missing(answers)


async def test_the_form_covers_every_field_of_the_google_form(cfg3, course, store):
    """No field of last year's form was lost in the move into the bot."""
    ours = set(wizard.ORDER)
    # What the season 2 Google form asked (telegram does not count — it arrives
    # with the update and cannot be forged).
    was = {"fio", "email", "university", "faculty", "year", "level",
           "python", "math", "ml", "knows", "why"}
    assert was <= ours, was - ours
    assert "tracks" in ours, "tracks are a new season 3 field"


async def test_scales_cannot_take_garbage(cfg3, course, store):
    """The old form's numeric fields contain "Бро", "1.5" and whole sentences.

    That is a property of the input field, not carelessness by respondents. A
    button makes such an answer impossible.
    """
    for step_id in ("python", "math", "ml", "level", "year"):
        step = wizard.step(step_id)
        assert step.kind == "choice", f"{step_id} went back to free text"
        assert step.validate is None
        assert step.choices({}), f"{step_id} has no options"


async def test_a_bad_answer_does_not_advance_the_form(cfg3, course, store):
    bench = Bench(cfg3, course, store, user_id=ME)
    await bench.press(core.cb("s3.reg"))
    await bench.send("Иванов")                    # one word is not a full name
    assert "фамилия и имя" in bench.text.lower()
    app = await store.application(ME)
    assert app["answers"].get("fio") is None


async def test_the_draft_survives_a_restart(cfg3, course, store):
    """The draft is in SQLite, not in state: MemoryStorage does not survive a restart."""
    bench = Bench(cfg3, course, store, user_id=ME)
    await bench.press(core.cb("s3.reg"))
    await bench.send("Иванов Иван Иванович")
    await bench.send("ivanov@gmail.com")

    reborn = Bench(cfg3, course, store, user_id=ME)   # a fresh dispatcher, empty FSM
    out = await reborn.press(core.cb("s3.reg"))
    shown = " ".join(s.text for s in out)
    assert "Где учишься" in shown, "the form restarted instead of continuing"


async def test_tracks_require_at_least_one(cfg3, course, store):
    bench = Bench(cfg3, course, store, user_id=ME)
    await bench.press(core.cb("s3.reg"))
    out = await bench.press(core.cb("s3.nx", "tracks"))
    assert not [s for s in out if s.api.startswith("Send") and "Анкета · 12" in s.text]
    app = await store.application(ME)
    assert not (app and app["answers"].get("tracks"))


async def test_the_summary_never_carries_personal_data_in_a_button(cfg3, course, store):
    bench = Bench(cfg3, course, store, user_id=ME)
    await fill(bench, store)
    out = await bench.press(core.cb("s3.sum"))
    payloads = [d for s in out for _, d in s.buttons if d]
    assert payloads
    for data in payloads:
        assert "Иванов" not in data and "ivanov@gmail.com" not in data


async def test_submitting_fills_all_three_sources_in_one_transaction(cfg3, course, store):
    bench = Bench(cfg3, course, store, user_id=ME, username="newbie")
    await fill(bench, store)
    await bench.press(core.cb("s3.go"))

    app = (await store.application(ME))
    assert app["status"] == "submitted"
    assert sorted((await store.track_counts()).items()) == [("cv", 1), ("dl", 1)]
    # The sink tasks were created in the same transaction — no window between.
    queued = {t["sink"] for t in await store.outbox_batch()}
    assert queued == {"csv", "notion"}


async def test_notion_being_down_does_not_lose_the_application(cfg3, course, store):
    """A sink is down — the form is already in our database, the task waits in the queue."""
    bench = Bench(cfg3, course, store, user_id=ME, username="newbie")
    await fill(bench, store)
    await bench.press(core.cb("s3.go"))
    assert not cfg3.notion_ready

    await worker.once(cfg3, store)

    path = cfg3.export_dir / "s3_applications.csv"
    assert path.exists(), "the local file must appear without any Notion"
    assert "ivanov@gmail.com" in path.read_text(encoding="utf-8-sig")
    left = {t["sink"] for t in await store.outbox_batch()}
    assert left == {"notion"}, "the Notion task must wait, not vanish"
    assert (await store.application(ME))["status"] == "submitted"


async def test_the_csv_is_a_projection_not_an_append_log(cfg3, course, store):
    """Regenerated whole: appending would add a second row for the same person."""
    bench = Bench(cfg3, course, store, user_id=ME, username="newbie")
    await fill(bench, store)
    await bench.press(core.cb("s3.go"))
    await worker.once(cfg3, store)
    await worker.once(cfg3, store)          # the same task run again
    path = cfg3.export_dir / "s3_applications.csv"
    body = path.read_text(encoding="utf-8-sig").strip().splitlines()
    assert len(body) == 2, body            # a header and one application


async def test_a_stale_task_is_skipped(cfg3, course, store):
    """A run of edits collapses to the last revision instead of ten requests."""
    bench = Bench(cfg3, course, store, user_id=ME, username="newbie")
    await fill(bench, store)
    await bench.press(core.cb("s3.go"))
    tasks = await store.outbox_batch()
    csv_task = next(t for t in tasks if t["sink"] == "csv")
    await store.mark_synced({**csv_task, "rev": csv_task["rev"] + 5})
    # Another task of the same, already stale revision.
    await store.submit_application(ME, ["cv"], sinks=("csv",))
    before = (cfg3.export_dir / "s3_applications.csv").exists()
    await worker.once(cfg3, store)
    assert not [t for t in await store.outbox_batch() if t["sink"] == "csv"]
    assert before is False


# --- repository ------------------------------------------------------------------------

async def test_a_repo_is_never_rejected(cfg3, course, store, monkeypatch):
    """A 404 is indistinguishable from private — refusing on it loses honest work."""
    from mlbot import github

    async def nowhere(cfg, repo):
        return False, 404

    monkeypatch.setattr(github, "exists", nowhere)
    bench = Bench(cfg3, course, store, user_id=ME)
    await bench.press(core.cb("s3.repo"))
    await bench.send("https://github.com/newbie/ml-season3")

    saved = await store.repo_of(ME)
    assert saved and saved["repo"] == "ml-season3"
    assert "приватный" in bench.text


async def test_a_broken_link_is_not_saved(cfg3, course, store):
    bench = Bench(cfg3, course, store, user_id=ME)
    await bench.press(core.cb("s3.repo"))
    await bench.send("вот моя работа")
    assert await store.repo_of(ME) is None


async def test_the_repo_check_is_cached(cfg3, course, store, monkeypatch):
    """Without a token GitHub allows 60 requests an hour — not enough for a stream."""
    from mlbot import github

    calls = []

    async def counting(cfg, repo):
        calls.append(repo.full)
        return True, 200

    monkeypatch.setattr(github, "exists", counting)
    for _ in range(3):
        await github.check(cfg3, store, "https://github.com/newbie/ml-season3")
    assert len(calls) == 1


def test_the_bot_never_asks_for_repository_contents():
    """A link to the work is not access to it. A structural check, not a promise.

    String literals specifically: a path like `/contents` would appear inside an
    f-string with the URL. Docstrings are excluded — otherwise the test would
    catch the paragraph explaining this rule rather than the code.
    """
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "mlbot" / "github.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))

    docstrings = set()
    for holder in ast.walk(tree):
        if isinstance(holder, (ast.Module, ast.ClassDef, ast.FunctionDef,
                               ast.AsyncFunctionDef)):
            first = (holder.body or [None])[0]
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                docstrings.add(id(first.value))

    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docstrings]
    assert len(literals) > 10, "no literals found — the check has degenerated"

    haystack = " ".join(literals).lower()
    for forbidden in ("contents", "zipball", "tarball", "raw.", "clone", "/git/"):
        assert forbidden not in haystack, (
            f"the bot requests repository contents: {forbidden!r}")
    # And what it does request is exactly the fact of existence.
    assert any("/repos/" in lit for lit in literals)


def test_every_option_fits_the_callback_budget():
    """Cyrillic in a value costs two bytes per character — checked on the real options."""
    checked = 0
    for step in wizard.STEPS:
        for value, _ in step.choices({"university": "БГУ"}):
            core.cb("s3.a", f"{step.id}:{value}")
            core.cb("s3.m", f"{step.id}:{value}")
            checked += 1
    assert checked > 30


# --- homework --------------------------------------------------------------------------

async def test_two_tracks_give_one_message_not_two(cfg3, course, store):
    """A student on CV and DL gets one message — signing up twice is not punished with duplicates."""
    bench = Bench(cfg3, course, store, user_id=ME, username="newbie")
    await fill(bench, store, tracks=("cv", "dl"))
    await bench.press(core.cb("s3.go"))

    hw_id = await store.create_homework(
        title="Свёртки руками", body="Соберите VGG-блок.", tracks=["cv", "dl"],
        created_by=1)
    who = await store.recipients_for_tracks(["cv", "dl"])
    assert who == [(ME, "Иванов Иван Иванович")]
    assert await store.publish_homework(hw_id, who)
    assert await store.pending_deliveries(hw_id) == [ME]


async def test_a_homework_is_only_visible_to_its_tracks(cfg3, course, store):
    bench = Bench(cfg3, course, store, user_id=ME, username="newbie")
    await fill(bench, store, tracks=("cv",))
    await bench.press(core.cb("s3.go"))

    mine = await store.create_homework("Своя", "текст", ["cv"], 1)
    alien = await store.create_homework("Чужая", "текст", ["rl"], 1)
    await store.publish_homework(mine, await store.recipients_for_tracks(["cv"]))
    await store.publish_homework(alien, await store.recipients_for_tracks(["rl"]))

    visible = {h["id"] for h in await store.homeworks_for(ME)}
    assert visible == {mine}
    out = await bench.press(core.cb("s3.hw.one", str(alien)))
    assert not [s for s in out if s.api.startswith("Send")]


async def test_a_deadline_is_kept_in_utc_and_shown_in_minsk():
    """Moving the server to another timezone must not shift everyone's deadline."""
    from datetime import datetime

    from mlbot.season3 import deadline

    now = datetime(2027, 3, 1, tzinfo=deadline.MINSK)
    iso = deadline.parse("срок: 14.03 23:59", now=now)
    assert iso is not None and iso.endswith("+00:00")
    assert "20:59" in iso, iso            # 23:59 Minsk is 20:59 UTC
    assert deadline.show(iso) == "14.03 23:59 по Минску"
    assert deadline.parse("завтра") is None
    assert deadline.parse("срок: 31.02") is None      # no such date exists


async def test_username_changes_are_written_down(cfg3, course, store):
    """A username change must be visible, not reconstructed from memory."""
    first = Bench(cfg3, course, store, user_id=ME, username="oldname")
    await first.send("/start")
    second = Bench(cfg3, course, store, user_id=ME, username="newname")
    await second.send("/start")
    trail = [r["username"] for r in await store.identity_trail(ME)]
    assert trail == ["oldname", "newname"]
