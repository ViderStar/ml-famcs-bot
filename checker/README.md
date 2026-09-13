# mlcheck — automatic homework grading

Pipeline: student repositories → topic detection → deterministic rules → model
review → per-student reports and the certificate verdict.

Course content — rubrics, the error catalog, report text — stays in Russian:
students read it.

## Run

```bash
cd checker && uv sync --extra dev
```

Steps are independent; each writes its own artifact and restarts on its own:

```bash
uv run mlcheck roster       # parse the form, check repositories are reachable
uv run mlcheck fetch        # download repositories (--force to refresh)
uv run mlcheck classify     # detect each notebook's topic from its content
uv run mlcheck similarity   # look for copied work
uv run mlcheck report       # verdicts, reports, summary tables
```

`report` works without the `llm` step — the verdict then rests on static checks
alone.

## Model review: two routes

**Batch API.** Needs `ANTHROPIC_API_KEY`; a full pass over 966 submissions costs
about $10 and takes up to an hour.

```bash
uv run mlcheck llm estimate
uv run mlcheck llm submit
uv run mlcheck llm collect --wait
```

**Claude Code subagents.** No key — runs on a subscription. Each agent takes one
batch of a single topic and writes reviews into `out/llm/`.

```bash
uv run mlcheck llm export --delta
uv run mlcheck llm batches --per-batch 25
```

Then one subagent per batch: *"Read `checker/AGENT_PROMPT.md`. Topic `hw12`,
batch `hw12_01.txt`."* The instruction is self-contained. The pass is resumable —
`batches` skips what is already reviewed, so a crashed batch is simply reissued.

```bash
uv run mlcheck llm verify --show-left
```

`verify` catches broken JSON, missing fields and error codes outside the catalog.

Rule for subagents in any mode: **no more than six at once**, and the task must
forbid them from spawning their own. Otherwise the session limit is gone in
minutes.

## Student portrait (`--mode student`)

A third review mode. Input is not a notebook but a digest of everything checked
for one student (built from `out/findings/<key>.json` — the same file the bot
reads); output is their strengths across the course and 2–5 growth directions in
ML/DS methodology, with links.

```bash
uv run mlcheck report
uv run mlcheck llm export --mode student
uv run mlcheck llm batches --mode student --per-batch 12
uv run mlcheck llm verify --mode student
uv run mlcheck report                       # portrait lands in findings
```

The model cannot invent links: the prompt carries a closed list of catalog URLs,
`verify` rejects a file with an outside link, `report` sanitises the answer, and
the bot filters once more against `Course.known_links`.

## Rerun and comparison

Before rerunning reviews, keep the old ones: `mv out/llm out/llm_v1`,
`cp -r out/findings out/findings_v1`. Afterwards `uv run mlcheck diff
out/findings_v1` writes `out/rerun_diff.md`: certificates before and after, who
gained and lost one, per-topic verdict flips with reasons.

Read the "was passed — now failed" section every time. Behind each line is a
student who may already have seen the old verdict.

A model finding whose code has `detector: rule` is never critical in the report:
the rule already checked and found nothing, while the model sees only the diff
without the handout and gets it wrong.

## Layout

| Path | What |
|---|---|
| `config.toml` | verdict thresholds, model, limits |
| `rubrics/hwNN.yaml` | one homework: topic signature and check items |
| `rubrics/tasks/*.md` | assignment texts extracted from `materials/` |
| `rubrics/templates/` | reference handouts missing from `materials/` |
| `catalog/<hw>/<code>.md` | error catalog: explanation and links |
| `../out/findings/<key>.json` | machine-readable report — this is what the bot reads |
| `../out/reports/<key>.md` | human-readable report |
| `../out/summary.csv` | summary table for teachers |
| `../out/similarity.csv` | pairs of similar submissions |

## Three facts that shape the design

**A folder name does not tell you the topic.** There is an `hw04 (LOG
REGRESSION)` holding linear regression, and a repository where every folder is
called `*_setup_tools`. Content decides (`classify.py`); the path is a weak hint
at best. Classification is multi-label: the random-forest assignment asked
students to extend their linear-regression notebook, so one file closes two
topics.

**`# YOUR CODE HERE` survives in submitted work.** Across the corpus: 3744 such
cells against 23 genuinely empty ones. Students write under the marker without
deleting it, so "not done" is decided by an empty cell body after comments are
subtracted.

**A mistake inherited from the handout is not the student's.**
`pca_practice_student.ipynb` scales the whole dataset before `train_test_split`.
Reference lines are subtracted (`templates.py`), and anything repeated verbatim
by five or more students counts as handout automatically — not every template
survived in `materials/`.

## Diff scope

For template-based homework, rubric items are checked **only against what the
student added** (`check_scope: delta`, the default). Otherwise the scaffolding —
`def sigmoid`, `class MyLogisticRegressionGD`, lecture code — closes the
requirements for them: before this rule, untouched handout notebooks passed 67
required items across 13 rubrics.

hw01 and hw07 are the exception (`check_scope: full`): they were handed out
already solved, so their content items are advisory and the verdict rests on
whether the notebook runs.

## Verdict

Homework passes with no `critical` findings and at least `hw_pass_ratio` of the
required rubric items closed. A certificate needs `certificate_ratio` of the
homework passed. Both live in `config.toml`.

An unreachable repository is terminal: the student is out of the analysis and
gets no certificate.

A topic with `graded: false` shows up in the report but stays out of the
certificate denominator. hw07 is marked that way — no decision-tree assignment
was ever issued.

## Contract with the bot

`out/findings/<key>.json` holds everything the student should see: name,
repository link, certificate verdict, and per-homework findings. A finding
carries `code`, `severity`, `title`, `detail` (specific to this work), `comment`
(the model's text), `links` and `article`. Explanatory text comes from
`catalog/` by code, so catalog edits show up immediately without rebuilding
reports.

## Adding a check

A rubric item in `rubrics/hwNN.yaml`:

```yaml
  - id: my_check
    title: Human-readable name
    required: true
    kind: rule           # rule — regexes, llm — model judgement
    any_regex: ['GridSearchCV']
```

plus an article at `catalog/hwNN/my_check.md`. The test
`test_every_finding_has_a_catalog_article` will not let you forget the second.
