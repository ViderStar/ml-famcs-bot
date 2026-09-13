# mlbot — the course Telegram bot

Gives students their homework review with explanations and links, gives teachers
stream statistics, and sends broadcasts from the interface.

Everything the bot says is Russian — that is the language of the course. This
document, the code and the tests are English.

## Safety catch: `SAFE_MODE`

**On by default.** While it is on, no message can reach an outsider: a letter to
a student is redirected to the admin tagged `🧪 ПЕСОЧНИЦА · ушло бы: id 12345`,
so you see exactly the letter that would have gone out. Editing someone else's
message fails loudly — there is nowhere to redirect an edit, so it is a bug.

The interception is a [session middleware](src/mlbot/safety.py), not a
dispatcher one: **every** Telegram API call goes through `bot.session`,
including `message.answer()` and `edit_text()`, which both a dispatcher
middleware (it only sees incoming updates) and a `Bot` subclass would miss.

Second lock, at the broadcast level: in the sandbox the audience registry only
offers "me" and "demo accounts", so a broadcast has nowhere to get a list of
real students even if the catch itself breaks.

Released only through the environment; there is deliberately no button:

```
SAFE_MODE=0   # in bot/.env, then docker compose up -d
```

## Fictional students

*Admin → Debug → Fictional students* — four invented records covering every
screen state: a graduate with a certificate and a photo, someone who fell short
with critical findings, an excluded student, and one who submitted nothing.

They live in [`demo/findings`](demo/findings) as a separate `Course` object
rather than mixed into the real corpus. Mixed in, they would have to be filtered
out in ten places in `data.py`, and a forgotten filter would show up only as a
quietly shifted median. Their clicks are flagged in the database
(`events.demo`) and stay out of both the summary and "what people read".
Rebuild with `python demo/make_demo.py`.

## Setup

Get a token from @BotFather; the script does the rest — validates the token,
finds your telegram id, writes `.env` with mode 600.

```bash
./setup.sh
```

`ADMIN_IDS` is a comma-separated list of telegram ids. `/id` tells you yours and
whether the bot sees you as an admin.

`ADMIN_USERNAMES` does the same by username. It is weaker — a released username
can be claimed by anyone — so as soon as someone writes to the bot, take their
`/id` and move them to `ADMIN_IDS`.

Admins are not pushed through student binding: a teacher has no student record.
They get the Admin button straight away and can still bind as a student by
sending a repository link.

## Why a homework did not pass

Homework passes with **no critical findings** and at least `hw_pass_ratio` (70%)
of the required items closed. Nothing else affects the verdict: major and minor
findings never fail a topic.

The bot says this outright instead of leaving a list of thirty findings that
reads like thirty reasons for failure:

* the topic card carries a "why it did not pass" block and a separate line
  saying the remaining findings did not matter;
* each finding is marked "this cost the verdict" or "this did not";
* "what to improve" opens with the reasons work failed;
* the results screen explains the gap between "submitted 12" and "passed 6".

The reasoning lives in [`views.blockers`](src/mlbot/views.py) and mirrors the
grader's decision. `test_verdict_explanation_agrees_with_the_recorded_status`
runs over every submission in the stream and fails if a failed topic has no
reason.

## Menu: a tree, not forty buttons

Three buttons under the input field, plus Admin for teachers:

```
🎓 Season 2           🔎 Reference          🆘 Help
├─ Results            ├─ Common mistakes    ├─ Write to the teacher
│   └─ Strengths      └─ hw01…hw13          ├─ Who am I to the bot
├─ Homework                                 ├─ My data
│   └─ topic → finding (◀ 3/7 ▶)            └─ Commands
├─ What to improve
├─ Season materials   ← slides and tasks for every topic, submitted or not
└─ Certificate → PDF, ceremony photo
```

The tree is a node registry in [`menu/core.py`](src/mlbot/menu/core.py): one
node is one `@node(...)` with its renderer beside it. `callback_data` is
assembled **in one place** (`cb()`), "back" is derived from the declared parent,
and the root keyboard is built from the root's children by visibility — so there
are no longer separate lists for guests and admins.

The point of a registry is that you can **walk** it. Tests traverse the whole
tree and check nodes that did not exist when the test was written: connectivity,
absence of cycles, the 64-byte `callback_data` budget, and that every "back"
label matches its real parent.

Old buttons (`hw:hw03`, `ref:art:…`) still work: they live in chat history
forever, and [`menu/router.py`](src/mlbot/menu/router.py) translates them into
nodes — translates, rather than implementing the screen a second time.

Every button is mirrored by a command (`/results`, `/homeworks`, `/improve`,
`/materials`, `/certificate`, `/reference`, `/support`, `/whoami`).
`test_every_menu_command_has_a_handler` keeps the list honest.

## Admin panel

Four groups instead of eleven buttons in a column: Analytics, People,
Broadcasts, Season 3, Debug.

Rights come from the [`AdminOnly` filter](src/mlbot/menu/filters.py) on both
router observers plus node visibility — not from an `if not _is_admin(...)` line
in every handler. That line gets forgotten, and a test that greps for it does
not notice. That an outsider gets no admin button at all is verified by
traversal: the bot shows an admin the whole tree, and a stranger's account
presses every button found.

## Broadcasts

*Admin → Broadcasts* → pick an audience → write the message → preview → send.
Formatting survives because the bot reads `message.html_text`, not
`message.text` — otherwise bold and links typed in Telegram would vanish
silently, and a stray `<` would break delivery for everyone at once.

Audiences are a registry
([`broadcast/audiences.py`](src/mlbot/broadcast/audiences.py)): everyone bound,
with a certificate, without one, demo accounts, just me. The "with a
certificate" query is the same one `announce.py` uses — it imports it from here,
and a test pins that.

Two properties the schema exists for:

* **the recipient list is frozen** at confirmation, in one transaction with
  creating the broadcast. Resuming sends exactly the remainder and never
  re-decides the audience — otherwise people who bound between the start and the
  crash would be swept in;
* **the composite primary key** `(broadcast_id, tg_id)` makes a duplicate
  physically impossible. The draft → sending transition is atomic, so a double
  click is harmless.

Sending runs as a background task with progress. Someone who blocked the bot is
marked and not retried. A restart mid-broadcast marks it interrupted and tells
the admin; the history screen has a resume button.

The bot cannot write to unbound people — Telegram does not allow writing first.
Their count is shown on the audience screen as a separate line.

## Season 3: registration through the bot

February 2027, narrow tracks for people past the basics: CV, NLP, RecSys, DL,
time series, RL, speech. Each has its own teacher and 6–8 sessions; several can
be chosen. Tracks are described in
[`season3/tracks.toml`](src/mlbot/season3/tracks.toml) and mounted into the
container, so a teacher or session count changes without a rebuild.

**The key simplification.** Registration goes through the bot, so `tg_id` is
known from the first message and cannot be forged. The whole class of problems
that produced access claims and name-based matching simply does not arise;
`username` is stored but is **never a key** — only an attribute and a log
(`identity_history`), because a released username goes to someone else.

**The form is data, not twelve handlers.** Steps are tuples in
[`season3/wizard.py`](src/mlbot/season3/wizard.py): what to ask, how it is
answered, how to validate. Every field of last year's Google form is there, plus
tracks.

Scales, university and year are answered with **buttons**. This is not about
convenience: the numeric fields of the old form contain "Бро", "1.5", "between 2
and 3" and a whole sentence about convolutional architectures. That is how a
free-text field behaves, not how respondents do; a button makes such an answer
impossible.

The draft lives in SQLite, not in FSM state: `MemoryStorage` does not survive a
container restart, and a twelve-step form is not filled in a minute.

**Three sinks through a queue, not try/except.** Saving the form and enqueueing
the sink tasks happen in **one transaction**: there is no window between "form
saved" and "task created" to crash in, so "do not lose the form" holds by
construction rather than by hope.

| Sink | How |
|---|---|
| SQLite | primary, always right |
| `EXPORT_DIR/s3_applications.csv` | not appended — regenerated whole from the database via `tmp` + `os.replace` |
| Notion | plain HTTP; creation is idempotent — a query by numeric `tg_id` before `POST` |

**One** background consumer drains the queue, so there are no races. Stale tasks
are skipped by `synced_rev` — a run of edits collapses to the last one. After
eight failures a task becomes `diverged` and raises a flag for the admin instead
of vanishing. There is no reverse import: two writers into one model lose data
silently, so the reconciliation screen **reports differences and deletes
nothing**.

Notion needs `NOTION_TOKEN` and `NOTION_DB`. Until they exist, forms pile up in
the queue and arrive later. Both fields are declared `field(repr=False)`: a
frozen dataclass prints itself whole in any traceback, and the token would reach
the log on the first error.

**Repositories.** The link is parsed by the same code the grader uses; one
request, `GET /repos/{owner}/{repo}`, and only existence — no `contents`, no
clone (pinned by a structural test over the literals in
[`github.py`](src/mlbot/github.py)). Binding is **never blocked** by the result:
a 404 is indistinguishable from a private repository, and refusing on it would
reject honest work. Without `GITHUB_TOKEN` GitHub allows 60 requests an hour,
which is not enough for two hundred students — hence a six-hour cache and a
fallback `HEAD` against the HTML page.

**Homework.** The admin picks tracks, sends the assignment as one message (first
line is the title, the last may be `срок: 14.03 23:59`) and publishes it.
Recipients are deduplicated by `tg_id`: a student on both CV and DL gets **one**
message. Deadlines are stored in UTC and shown in Minsk time with a label —
otherwise moving the server would shift everyone's deadline at once, silently.

## Run

```bash
docker compose up -d --build
docker compose logs -f
```

Without Docker:

```bash
uv sync --extra dev
DATA_ROOT=.. uv run --env-file .env mlbot
```

## Where the data comes from

The bot computes nothing itself — it reads what `checker` produced.

| What | Where |
|---|---|
| Per-student reports | `out/findings/<key>.json` |
| Error catalog | `checker/catalog/<hw>/<code>.md` |
| Topics and rubrics | `checker/rubrics/hw*.yaml` |
| Assignment texts | `checker/rubrics/tasks/*.md` |
| Lecture slides | `materials/*.pdf` |

Everything loads into memory at startup (about six megabytes). After a new
grading pass, *Admin → Debug → Reload data* picks it up without restarting the
container.

SQLite (`/state/mlbot.sqlite3`) holds only what the bot itself produces:
bindings, analytics events, support tickets, broadcasts, season-3 forms. No
grades.

The schema is versioned through `PRAGMA user_version`
([`migrations.py`](src/mlbot/migrations.py)): migrations are append-only and
contain nothing but `CREATE` and `ALTER TABLE ADD COLUMN` — pinned by a test,
because the bot applies them at startup without asking. A copy of the database
is made before the version goes up.

## How a student proves who they are

**Instant binding only on proven ownership.** Telegram guarantees the username
belongs to the account writing to the bot; if it matches the one recorded for
that student in the registration form, that is the owner. This covers 158
students out of 205.

**Everything else waits for a human.** A name and a repository link are not
proof — classmates know both, and in the very first week an outsider used them
to open someone else's review. The remaining 47 — a changed username, or none in
the form at all — become access claims: the student sees the request was sent,
admins get a notification, and *Admin → People → Access claims* shows which
username is recorded, who is asking, their id, the repository and the time, with
approve and reject buttons.

One binding per account and one per student. Repeated attempts do not create
duplicates, but two claims on the same record are both shown — that is exactly
the case a human should decide.

## Privacy

A student identifier never reaches `callback_data`: it always comes from the
binding in the database. Substituting a button to get someone else's review is
impossible, and
[`tests/test_privacy.py`](tests/test_privacy.py) proves it by behaviour — the
bot is traversed as one account and every button found is then pressed by
another.

## Tests

```bash
uv run pytest
```

The suite renders every screen for every report and every finding: each must fit
Telegram's 4096-character limit with balanced tags. Without the real corpus it
runs against the synthetic stream in `fixtures/` — see the root README.

## Layout

```
src/mlbot/
  config.py       environment and paths
  data.py         course data in memory, stream aggregates
  store.py        SQLite: bindings, events, tickets, broadcasts, forms
  migrations.py   versioned schema
  safety.py       the SAFE_MODE catch
  matching.py     finding a student by link and name
  render.py       markdown → Telegram HTML, splitting long messages
  views.py        screen text (pure functions, tested separately)
  texts.py        all Russian strings in one place
  menu/           node registry, screens, admin panel, season 3
  broadcast/      audience registry and sender
  season3/        tracks, form, deadlines
  sinks/          CSV and Notion, drained by one worker
  handlers/       onboarding, admin dialogs, support, easter eggs
```
