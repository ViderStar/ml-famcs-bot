"""Model review of submissions through the Batch API.

Two passes:
* discovery — the open question "what is wrong here" on a sample of work; the
  error catalog is then assembled by hand from the answers;
* grading — all work against the closed list of catalog codes.

The request is shaped so the prefix is cacheable: the constant part (role,
assignment text, code list) goes into `system` with `cache_control`, while the
variable part — the student's notebook — goes into the user message. There are
exactly as many distinct prefixes as there are homework topics.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .catalog import Article
from .config import Config, load
from .nbio import Notebook, to_llm_text
from .rubric import Rubric

ROLE = """\
Ты — преподаватель курса классического машинного обучения для студентов второго
курса. Проверяешь домашнюю работу: студент прислал Jupyter-ноутбук.

Как оценивать:
* Опирайся на текст задания и список обязательных пунктов ниже.
* Оценивай то, что реально написано в ноутбуке, а не то, что подразумевалось.
* Учитывай сохранённые выводы ячеек: если вывода нет, ячейка не выполнялась.
* Отсутствие текстовых пояснений — недостаток: задание требует, чтобы работа
  читалась как исследование.
* Будь конкретен и доброжелателен. Формулируй так, чтобы студент понял, что
  именно исправить. Не пересказывай код словами.
* Не придирайся к стилю кода, именам переменных и оформлению графиков, если
  это не мешает решению задачи.
"""

GRADING_TAIL = """\
Верни JSON:
* `checks` — по одному элементу на каждый пункт из списка «Смысловые пункты»
  с его `id`, полем `passed` и коротким обоснованием в `comment`.
* `findings` — найденные ошибки. Поле `code` бери ТОЛЬКО из списка допустимых
  кодов. Если ошибка важная, но её нет в списке, используй код `other` и
  подробно опиши суть в `comment`. Не выдумывай новых кодов.
* `strengths` — что в работе сделано хорошо, одно-два предложения. Формулируй
  как проявленное умение, которое переносится на другие задачи («умеешь
  подбирать гиперпараметры по кросс-валидации, а не по тесту»), а не как
  протокол («в ячейке 7 посчитан F1»). Опирайся на конкретику работы.
* `summary` — итог для студента, 2–4 предложения: главное, что получилось,
  главное, что мешает, и в конце — один конкретный следующий шаг по этой теме
  (что доделать, перечитать или попробовать на другом датасете).

Комментарии пиши по-русски, обращаясь к студенту на «ты».
"""

DISCOVERY_TAIL = """\
Это разведочный проход: каталог типовых ошибок ещё не составлен.

Перечисли всё, что в работе сделано неверно, неполно или методологически
сомнительно. По каждому пункту: короткое название ошибки (5–7 слов), в чём
именно она состоит в этой работе, и насколько серьёзна (critical — работа не
может быть зачтена, major — существенный недочёт, minor — совет).

Отдельно отметь ошибки, которые кажутся тебе типовыми для студентов на этой
теме, — их мы вынесем в общий каталог.
"""

DISCOVERY_SCHEMA = {
    "type": "object",
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "detail": {"type": "string"},
                    "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
                    "typical": {"type": "boolean"},
                },
                "required": ["name", "detail", "severity", "typical"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["issues", "summary"],
    "additionalProperties": False,
}


def grading_schema(codes: list[str], check_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "checks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "enum": check_ids or ["none"]},
                        "passed": {"type": "boolean"},
                        "comment": {"type": "string"},
                    },
                    "required": ["id", "passed", "comment"],
                    "additionalProperties": False,
                },
            },
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "enum": codes + ["other"]},
                        "comment": {"type": "string"},
                    },
                    "required": ["code", "comment"],
                    "additionalProperties": False,
                },
            },
            "strengths": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": ["checks", "findings", "strengths", "summary"],
        "additionalProperties": False,
    }


def normalize_code(code: str, hw: str, catalog: dict[str, Article]) -> str | None:
    """Normalises a finding code.

    The reviewer sometimes drops the prefix and writes
    `conclusions_in_code_comments` instead of the qualified code. That is a
    formatting slip, not a reason to reject the whole review.
    """
    code = (code or "").strip()
    if not code:
        return None
    if code in catalog or code == "other":
        return code
    for candidate in (f"common.{code}", f"{hw}.{code}"):
        if candidate in catalog:
            return candidate
    return None


def _codes_for(rubric: Rubric, catalog: dict[str, Article]) -> list[str]:
    """Codes available to the model for this homework: the common ones plus its own."""
    return sorted(
        c for c in catalog
        if c.startswith("common.") or c.startswith(f"{rubric.id}.")
    )


def system_prompt(rubric: Rubric, catalog: dict[str, Article], mode: str) -> str:
    parts = [ROLE, f"\n# Домашняя работа {rubric.id}: {rubric.title}\n"]

    task = rubric.task_text().strip()
    if task:
        parts.append("## Текст задания\n\n" + task + "\n")

    llm_checks = rubric.llm_checks
    if llm_checks and mode == "grading":
        parts.append("## Смысловые пункты, которые нужно оценить\n")
        for c in llm_checks:
            req = "обязательный" if c.required else "необязательный"
            parts.append(f"* `{c.id}` — {c.title} ({req})")
        parts.append("")

    if mode == "grading":
        parts.append("## Допустимые коды ошибок\n")
        for code in _codes_for(rubric, catalog):
            parts.append(f"* `{code}` — {catalog[code].title}")
        parts.append("")
        parts.append(GRADING_TAIL)
    else:
        parts.append(DISCOVERY_TAIL)
    return "\n".join(parts)


@dataclass
class Item:
    custom_id: str
    student_key: str
    hw: str
    notebook: Notebook


def build_params(item: Item, rubric: Rubric, catalog: dict[str, Article],
                 cfg: Config, mode: str) -> dict:
    max_chars = cfg.llm["max_notebook_tokens"] * 3   # ~3 characters per token for a mix of code and Russian
    text, truncated = to_llm_text(item.notebook, max_chars)
    note = "\n\n(Ноутбук обрезан по длине — оценивай по доступной части.)" if truncated else ""

    if mode == "grading":
        schema = grading_schema(_codes_for(rubric, catalog),
                                [c.id for c in rubric.llm_checks])
    else:
        schema = DISCOVERY_SCHEMA

    return {
        "model": cfg.llm["model"],
        "max_tokens": cfg.llm["max_output_tokens"],
        "system": [{
            "type": "text",
            "text": system_prompt(rubric, catalog, mode),
            "cache_control": {"type": "ephemeral"},
        }],
        "messages": [{
            "role": "user",
            "content": f"Файл: `{item.notebook.rel}`\n\n{text}{note}",
        }],
        "output_config": {"format": {"type": "json_schema", "schema": schema}},
    }


def estimate(items: list[Item], cfg: Config) -> dict:
    """A rough size estimate before the run: characters divided by three."""
    max_chars = cfg.llm["max_notebook_tokens"] * 3
    total_in = 0
    truncated = 0
    for it in items:
        text, cut = to_llm_text(it.notebook, max_chars)
        truncated += int(cut)
        total_in += len(text) // 3
    out_tokens = len(items) * 900
    return {
        "работ": len(items),
        "обрезано": truncated,
        "входных токенов": total_in,
        "выходных токенов": out_tokens,
    }


# Three modes, three pairs of directories. The mapping used to be smeared across
# ternaries in cli.py; adding a third mode broke that.
_INPUT = {"grading": "llm_input", "discovery": "llm_input_discovery",
          "student": "llm_input_student"}
_RESULTS = {"grading": "llm", "discovery": "llm_discovery", "student": "llm_student"}
MODES = tuple(_INPUT)


def input_dir(cfg: Config, mode: str) -> Path:
    d = cfg.paths.out / _INPUT[mode]
    d.mkdir(parents=True, exist_ok=True)
    return d


def results_dir(cfg: Config, mode: str) -> Path:
    d = cfg.paths.out / _RESULTS[mode]
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_result(cfg: Config, mode: str, custom_id: str, payload: dict) -> None:
    (results_dir(cfg, mode) / f"{custom_id.replace('|', '__')}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_results(cfg: Config | None = None, mode: str = "grading") -> dict[str, dict]:
    cfg = cfg or load()
    d = cfg.paths.out / _RESULTS[mode]
    if not d.exists():
        return {}
    out = {}
    for p in sorted(d.glob("*.json")):
        try:
            out[p.stem.replace("__", "|")] = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
        # A subagent writes the review, and once it put a control character
        # inside a string. Crashing the build of every report over one file is
        # not acceptable: that submission keeps its rule-based check, and
        # `llm verify` catches the file.
            print(f"пропущен нечитаемый разбор {p.name}: {exc}", file=sys.stderr)
    return out


# --- the student's course portrait ------------------------------------------------------
#
# The third mode. Input is not a notebook but a digest of every check for one
# student; output is their strengths across the course and growth directions in
# ML/DS methodology, with links. The model cannot invent links: it receives a
# closed list from the catalog, and anything outside it is dropped both at verify
# time and when the report is built.

HANDBOOK_ROOT = "https://education.yandex.ru/handbook/ml"

STUDENT_ROLE = """\
Ты — преподаватель курса классического машинного обучения для студентов второго
курса (БГУ, ФПМИ). Перед тобой не ноутбук, а дайджест: итоги проверки всех
домашних работ одного студента за курс. По каждой теме — статус, закрытые пункты
задания, причины незачёта, итог и сильные стороны, отмеченные проверяющим, и
список замечаний с кодами. У каждого замечания указан вид: methodology — ошибка
в ML-методологии или теории, hygiene — дисциплина работы с ноутбуком.

Твоя задача — написать студенту портрет его прохождения курса: честный,
доброжелательный, с опорой только на факты из дайджеста.
"""

STUDENT_TAIL = """\
## Что написать

* `portrait` — 2–4 предложения о сильных сторонах по всему курсу: что реально
  получалось, какие умения проявлены в нескольких работах. Не пересказывай
  оценки и не хвали за то, чего в дайджесте нет. Если сдано мало — скажи об этом
  прямо, но по-доброму.
* `growth` — 2–5 направлений роста по ML/DS-теории и практике, по приоритету:
  1. методологические ошибки, из-за которых темы не зачтены;
  2. методологические замечания, повторяющиеся в нескольких работах;
  3. если работ мало — ключевые темы курса, которых студент не сдал.
  Замечания вида hygiene («часть ячеек не выполнена», «нет выводов», warnings)
  в `growth` НЕ включай — про них можно одной фразой в `next_steps`.
  Для каждого направления: `topic` (hwNN либо common), `title` (5–8 слов),
  `why` (1–3 предложения: что именно повторяется и почему это важно для
  практики), `codes` (коды из дайджеста, на которые опираешься), `links`
  (1–3 ссылки из списка ниже).
* `next_steps` — 1–3 предложения: что сделать дальше.

## Ссылки

Используй ТОЛЬКО ссылки из списка ниже, дословно, не меняя URL. Если по теме
подходящей ссылки нет — оставь `links` пустым. Выдуманная ссылка обесценивает
весь ответ: такой файл бракуется целиком.
"""

STUDENT_FORMAT = """\
## Формат

Верни JSON без markdown-обёртки:
{"portrait": str,
 "growth": [{"topic": str, "title": str, "why": str, "codes": [str], "links": [{"title": str, "url": str}]}],
 "next_steps": str}
Пиши по-русски, обращаясь к студенту на «ты», конкретно и доброжелательно.
"""

STUDENT_REQUIRED = ("portrait", "growth", "next_steps")
STUDENT_LIMITS = {"portrait": 1200, "why": 500, "next_steps": 600, "title": 120,
                  "growth": 5, "links": 3}


def external_links_by_topic(catalog: dict[str, Article]) -> dict[str, list[tuple[str, str]]]:
    """Catalog links by topic: hwNN → [(title, url)], plus common."""
    out: dict[str, dict[str, str]] = {}
    for code, art in catalog.items():
        topic = code.split(".", 1)[0]
        for title, url in art.links:
            if url.startswith("http"):
                out.setdefault(topic, {}).setdefault(url, title)
    return {t: sorted(((title, url) for url, title in d.items()), key=lambda x: x[0])
            for t, d in sorted(out.items())}


def allowed_urls(catalog: dict[str, Article]) -> set[str]:
    urls = {u for links in external_links_by_topic(catalog).values() for _, u in links}
    urls.add(HANDBOOK_ROOT)
    return urls


def student_prompt(rubrics: dict[str, Rubric], catalog: dict[str, Article]) -> str:
    parts = [STUDENT_ROLE, STUDENT_TAIL]
    for topic, links in external_links_by_topic(catalog).items():
        title = "Общие ошибки" if topic == "common" else rubrics[topic].title if topic in rubrics else topic
        parts.append(f"### {topic} · {title}")
        parts += [f"- {t} — {u}" for t, u in links]
        parts.append("")
    parts.append(f"### Весь учебник\n- Яндекс.Хендбук по ML — {HANDBOOK_ROOT}\n")
    parts.append(STUDENT_FORMAT)
    return "\n".join(parts)


def student_digest(report: dict, rubrics: dict[str, Rubric], catalog: dict[str, Article],
                   cfg: Config) -> str:
    """A digest built from the student's final JSON (`out/findings/<key>.json`).

    The source is the same file the bot reads: no rerunning the rules and no
    drifting from it. The name is left out — the model does not need it.
    """
    from .report import points_needed_for

    ratio = cfg.verdict["hw_pass_ratio"]
    lines = [f"# Студент `{report['key']}`",
             f"Засчитано тем: {report['passed_hw']} из {report['total_hw']}. "
             f"Сертификат: {'да' if report.get('certificate') else 'нет'}.", ""]
    for hw_id, h in sorted(report["homeworks"].items()):
        title = rubrics[hw_id].title if hw_id in rubrics else h.get("title", hw_id)
        graded = rubrics[hw_id].graded if hw_id in rubrics else True
        head = f"## {hw_id} · {title}" + ("" if graded else " (вне зачёта)")
        if h["status"] == "missing":
            lines += [head, "не сдано", ""]
            continue
        word = {"passed": "зачтено", "failed": "не зачтено"}[h["status"]]
        lines.append(f"{head} — {word}")
        if h.get("required_total"):
            need = points_needed_for(ratio, h["required_total"])
            lines.append(f"Пунктов задания: {h['required_passed']} из {h['required_total']} "
                         f"(нужно {need})")
        blockers = [f for f in h.get("findings", []) if f["severity"] == "critical"]
        if h["status"] == "failed":
            why = [f"недобор пунктов" ] if h.get("required_total") and \
                  h["required_passed"] < points_needed_for(ratio, h["required_total"]) else []
            why += [f"{f['code']} — {f['title']}" for f in blockers]
            lines.append("Почему не зачтено: " + "; ".join(why))
        if h.get("summary"):
            lines.append(f"Итог проверяющего: {h['summary']}")
        if h.get("strengths"):
            lines.append(f"Сильные стороны: {h['strengths']}")
        finds = h.get("findings", [])
        if finds:
            lines.append("Замечания:")
            for f in finds:
                art = catalog.get(f["code"])
                kind = art.kind if art else "methodology"
                row = f"- {f['code']} — {f['title']} [{f['severity']}, {kind}]"
                if kind == "methodology" and f.get("comment"):
                    row += f": {f['comment'][:200]}"
                lines.append(row)
        lines.append("")
    lines.append("Ссылки в ответе — только из списка в инструкции.")
    return "\n".join(lines)


def validate_student(payload: dict, rubrics: dict[str, Rubric], catalog: dict[str, Article],
                     allowed: set[str]) -> list[str]:
    """A list of complaints about the answer. An empty list means it is fine."""
    errors = [f"нет поля {k}" for k in STUDENT_REQUIRED if k not in payload]
    if errors:
        return errors
    if not isinstance(payload["portrait"], str) or not payload["portrait"].strip():
        errors.append("portrait пустой")
    elif len(payload["portrait"]) > STUDENT_LIMITS["portrait"]:
        errors.append("portrait длиннее лимита")
    if not isinstance(payload["growth"], list):
        return errors + ["growth не список"]
    if len(payload["growth"]) > STUDENT_LIMITS["growth"]:
        errors.append("growth длиннее 5")
    for i, g in enumerate(payload["growth"]):
        if not isinstance(g, dict):
            errors.append(f"growth[{i}] не объект"); continue
        topic = g.get("topic", "")
        if topic not in rubrics and topic != "common":
            errors.append(f"growth[{i}]: тема вне рубрик: {topic!r}")
        for code in g.get("codes", []) or []:
    # `hwNN.other` is a model finding outside the catalog; it is present in the
    # digest, so referring to it is legitimate.
            if code not in catalog and not code.endswith(".other"):
                errors.append(f"growth[{i}]: код вне каталога: {code}")
        for link in g.get("links", []) or []:
            url = (link or {}).get("url", "") if isinstance(link, dict) else ""
            if url not in allowed:
                errors.append(f"growth[{i}]: ссылка вне списка: {url}")
        if len(g.get("links", []) or []) > STUDENT_LIMITS["links"]:
            errors.append(f"growth[{i}]: больше 3 ссылок")
        if len(g.get("why", "") or "") > STUDENT_LIMITS["why"]:
            errors.append(f"growth[{i}]: why длиннее лимита")
    if len(payload.get("next_steps", "") or "") > STUDENT_LIMITS["next_steps"]:
        errors.append("next_steps длиннее лимита")
    return errors


def sanitize_student(payload: dict, rubrics: dict[str, Rubric], catalog: dict[str, Article],
                     allowed: set[str]) -> dict | None:
    """Brings the answer into a safe shape for the report and the bot.

    The second line of defence after verify: foreign links and unknown topics are
    dropped, lengths are trimmed. An invented URL will not reach a student even
    if verify was never run.
    """
    if any(k not in payload for k in STUDENT_REQUIRED):
        return None
    growth = []
    for g in payload["growth"] if isinstance(payload["growth"], list) else []:
        if not isinstance(g, dict):
            continue
        topic = g.get("topic", "")
        if topic not in rubrics and topic != "common":
            continue
        links = [{"title": str(l.get("title", ""))[:120], "url": l["url"]}
                 for l in (g.get("links") or []) if isinstance(l, dict) and l.get("url") in allowed]
        growth.append({
            "topic": topic,
            "title": str(g.get("title", ""))[:STUDENT_LIMITS["title"]],
            "why": str(g.get("why", ""))[:STUDENT_LIMITS["why"]],
            "codes": [c for c in (g.get("codes") or []) if c in catalog or c.endswith(".other")],
            "links": links[:STUDENT_LIMITS["links"]],
        })
    return {
        "portrait": str(payload["portrait"])[:STUDENT_LIMITS["portrait"]],
        "growth": growth[:STUDENT_LIMITS["growth"]],
        "next_steps": str(payload["next_steps"])[:STUDENT_LIMITS["next_steps"]],
    }
