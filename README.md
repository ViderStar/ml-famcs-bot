# ML FAMCS — homework grader and course bot

Two tools for one machine-learning course at BSU.

**`checker/`** grades homework: fetches student repositories, detects each
notebook's topic from its content, runs deterministic rules and a model review,
issues a verdict and builds reports.

**`bot/`** delivers the review in Telegram: which topics passed, why the rest
did not, every finding explained with links, strengths across the course and
what to improve. For teachers: stream statistics, broadcasts, homework
publishing and registration for the next season.

929 submissions from 205 students went through this in season 2.

Code, comments and docs are English. What the bot says to students and the
course content — rubrics, the error catalog, report text — stay Russian.

## Safety catch

**`SAFE_MODE` is on by default.** While it is on, no message can reach an
outsider: a letter to a student is redirected to the admin with a sandbox tag,
so you see exactly the letter that would have gone out. Editing someone else's
message fails loudly — there is nowhere to redirect an edit, so it is a bug.

The interception is a [session middleware](bot/src/mlbot/safety.py), not a
dispatcher one: **every** Telegram API call goes through `bot.session`,
including `message.answer()` and `edit_text()`, which both a dispatcher
middleware and a `Bot` subclass would miss.

Released only through the environment and a restart; there is deliberately no
button.

## What is not in this repository

The course handles personal data: names, emails, links to private repositories,
reviews of specific work. None of it is here — not as files, not in tests, not
in examples.

| What | Where it lives |
|---|---|
| Student reports (`out/`) | the teacher's machine only |
| Registration and submission form exports | same |
| Certificates and ceremony photos | same |
| Bot token (`bot/.env`) | same, mode 600 |
| Slides and handouts | the [course repository](https://github.com/ScienceSUFAMCS/science-famcs-ml) |

So that the tests do not become green theatre, a **synthetic stream** ships
alongside: 60 invented students with reports of the same shape
([`fixtures/`](fixtures/make_fixture.py)). Tests pick their corpus themselves —
real `out/findings` if it is there, synthetic otherwise. The few checks that
genuinely need a real run skip with a stated reason instead of pretending to
pass.

```bash
python fixtures/make_fixture.py     # rebuild the synthetic stream
```

## Run

```bash
cd bot && ./setup.sh                # asks @BotFather for a token, writes .env
docker compose up -d --build
```

Without Docker:

```bash
cd bot && uv sync --extra dev
uv run pytest                       # 204 tests
DATA_ROOT=.. uv run --env-file .env mlbot
```

Grading:

```bash
cd checker && uv sync --extra dev
uv run pytest                       # 117 tests
uv run mlcheck roster               # parse the form, check repositories
uv run mlcheck fetch                # download submissions
uv run mlcheck classify             # detect each notebook's topic
uv run mlcheck report               # verdicts and reports
```

## What is worth reading

**[Menu tree](bot/src/mlbot/menu/core.py)** — a node registry instead of
hardcoded "back" buttons. The parent is declared once, `callback_data` is
assembled in one place, the root keyboard is derived from the root's children by
visibility. The point: a registry can be walked, and tests traverse nodes that
did not exist when the test was written.

**[Test harness](bot/tests/harness.py)** feeds real updates through the real
dispatcher and intercepts outgoing calls at the session level. That is what
makes the privacy checks behavioural: the bot shows an admin the whole tree, and
a stranger's account presses every button found. Grep-based checks ("the file
contains `_is_admin`") cannot do that — after the code moves they pass silently.

**[Broadcasts](bot/src/mlbot/broadcast/)**: the recipient list is frozen at
confirmation, so resuming sends exactly the remainder and never re-decides the
audience. A composite primary key makes duplicates physically impossible.

**[Season 3 registration](bot/src/mlbot/season3/wizard.py)** — the form is data,
not twelve handlers. Scales are answered with buttons: the numeric fields of
last year's Google form contain "Бро", "1.5" and "between 2 and 3". That is how
a free-text field behaves, not how respondents do.

**[Error catalog](checker/catalog/)** — 149 write-ups: what went wrong, why it
matters, how it should be done, with links. The bot serves the same articles in
its reference section.

## Licence

Code as is, for anyone running a similar course. Course materials live in a
[separate repository](https://github.com/ScienceSUFAMCS/science-famcs-ml).
