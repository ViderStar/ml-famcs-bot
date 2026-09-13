"""Анкета третьего сезона — данные, а не двенадцать обработчиков.

Каждый шаг описан кортежем: что спросить, чем ответить, как проверить. Дальше
один обработчик текста, один обработчик нажатия и одна функция перехода. Добавить
поле — добавить строку.

Почему шкалы и университет — кнопками. В форме второго сезона те же поля были
текстовыми, и в числовых ответах лежит «Бро», «1.5», «между 2 и 3» и целое
предложение про свёрточные архитектуры. Это не небрежность анкетируемых, это
свойство поля ввода. Кнопка делает такой ответ физически невозможным.

Телеграм не спрашиваем: `tg_id` и `username` приходят с апдейтом и подделать их
нельзя. Именно это упрощение снимает весь класс проблем, из-за которого во
втором сезоне появились заявки на доступ.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

Option = tuple[str, str]          # значение, подпись на кнопке
OTHER = "__other__"               # «другое» — переводит шаг в свободный ввод
SKIP = "__skip__"


@dataclass(frozen=True)
class Step:
    id: str
    prompt: str
    kind: str                                     # text | choice | multi
    options: tuple[Option, ...] = ()
    validate: Callable[[str], str | None] | None = None
    optional: bool = False
    min_choices: int = 0
    # Варианты, зависящие от уже данных ответов (факультет — от университета).
    options_for: Callable[[dict], tuple[Option, ...]] | None = None
    allow_other: bool = False
    hint: str = ""
    short: str = ""          # короткое имя поля: для сводки и заголовка таблицы

    @property
    def name(self) -> str:
        return self.short or self.prompt.rstrip("?.")

    def choices(self, answers: dict) -> tuple[Option, ...]:
        return self.options_for(answers) if self.options_for else self.options


# --- проверки -------------------------------------------------------------------

_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")


def check_fio(value: str) -> str | None:
    parts = [p for p in value.replace("\n", " ").split() if p]
    if len(parts) < 2:
        return "Нужны хотя бы фамилия и имя — как в зачётке."
    if not all(re.fullmatch(r"[А-Яа-яЁёA-Za-z'’\-]+", p) for p in parts):
        return "Похоже, сюда попало лишнее. Только фамилия, имя и отчество."
    if len(value) > 120:
        return "Слишком длинно — до 120 символов."
    return None


def check_email(value: str) -> str | None:
    if not _EMAIL.fullmatch(value.strip()):
        return "Не похоже на адрес почты. Пример: <code>ivanov@gmail.com</code>"
    return None


def check_free(value: str) -> str | None:
    if len(value) > 1000:
        return "Слишком длинно — до 1000 символов."
    return None


# --- справочники ------------------------------------------------------------------

UNIVERSITIES: tuple[Option, ...] = (
    ("БГУ", "БГУ"),
    ("БГУИР", "БГУИР"),
    ("БНТУ", "БНТУ"),
    ("БГТУ", "БГТУ"),
    ("Лицей БГУ", "Лицей БГУ"),
)

# Факультеты по университетам — из регистрации второго сезона, где они
# встречались не единожды. Остальное закрывает «другой».
FACULTIES: dict[str, tuple[Option, ...]] = {
    "БГУ": (("ФПМИ", "ФПМИ"), ("ММФ", "ММФ"), ("ФизФак", "Физфак"),
            ("ЭФ", "ЭФ"), ("БиоФак", "Биофак")),
    "БГУИР": (("ФКСИС", "ФКСИС"), ("ФИТУ", "ФИТУ"), ("ФКП", "ФКП"),
              ("ИЭФ", "ИЭФ"), ("РФИКТ", "РФИКТ"), ("ИБ", "ИБ")),
}

LEVELS: tuple[Option, ...] = (
    ("novice", "Новичок — знаю, что такое Python"),
    ("basic", "Базовый — писал скрипты, слышал про pandas"),
    ("advanced", "Продвинутый — обучал модели, знаю sklearn"),
    ("pro", "Профи — хочу систематизировать и нетворкинг"),
)

SCALE: tuple[Option, ...] = (
    ("0", "0 — не сталкивался"),
    ("1", "1 — основы"),
    ("2", "2 — уверенно"),
    ("3", "3 — глубоко"),
)

KNOWS: tuple[Option, ...] = (
    ("derivative", "Производная"),
    ("gradient", "Градиент"),
    ("median", "Медиана"),
    ("bayes", "Теорема Байеса"),
    ("linreg", "Линейная регрессия"),
    ("overfit", "Переобучение"),
    ("mse", "MSE"),
    ("reg", "Регуляризация"),
    ("perceptron", "Перцептрон"),
    ("dropout", "Drop-out"),
    ("love", "✨ l o v e ✨"),
)

YEARS: tuple[Option, ...] = (
    ("1", "1 курс"), ("2", "2 курс"), ("3", "3 курс"), ("4", "4 курс"),
    ("master", "Магистратура"), ("alumni", "Выпускник"), ("school", "Школа, лицей"),
)


def _faculties(answers: dict) -> tuple[Option, ...]:
    return FACULTIES.get(answers.get("university", ""), ())


def _tracks(answers: dict) -> tuple[Option, ...]:
    """Направления живут в TOML: преподаватели уточняются до самого старта."""
    from . import current_season
    return tuple((t.id, t.button) for t in current_season().open)


# --- сами шаги ---------------------------------------------------------------------

STEPS: tuple[Step, ...] = (
    Step("fio", "Как тебя зовут? Фамилия, имя, отчество.", "text", validate=check_fio,
         hint="Пример: <code>Иванов Иван Иванович</code>", short="ФИО"),
    Step("email", "Почта — на неё придёт подтверждение и материалы.", "text",
         validate=check_email, short="Почта"),
    Step("university", "Где учишься?", "choice", options=UNIVERSITIES,
         allow_other=True, short="Университет"),
    Step("faculty", "Факультет?", "choice", options_for=_faculties,
         allow_other=True, optional=True, short="Факультет"),
    Step("year", "Курс?", "choice", options=YEARS, short="Курс"),
    Step("level", "Твой текущий уровень — субъективно.", "choice", options=LEVELS,
         short="Уровень"),
    Step("python", "Python — насколько уверенно?", "choice", options=SCALE,
         short="Python"),
    Step("math", "Математика 1–2 курса: линал, матанализ, статистика, теорвер.",
         "choice", options=SCALE, short="Математика"),
    Step("ml", "Машинное обучение — сталкивался?", "choice", options=SCALE, short="ML"),
    Step("knows", "Что из этого тебе знакомо? Отметь всё, что знаешь.", "multi",
         options=KNOWS, optional=True, short="Знает"),
    Step("tracks", "Какие направления интересны? Можно несколько.", "multi",
         options_for=_tracks, min_choices=1, short="Направления",
         hint="У каждого направления свой преподаватель и 6–8 занятий."),
    Step("why", "Почему хочешь на курс? Насколько заряжен дойти до конца?", "text",
         validate=check_free, optional=True, short="Почему"),
)

BY_ID: dict[str, Step] = {s.id: s for s in STEPS}
ORDER: tuple[str, ...] = tuple(s.id for s in STEPS)


def step(step_id: str) -> Step | None:
    return BY_ID.get(step_id)


def first() -> Step:
    return STEPS[0]


def index(step_id: str) -> int:
    return ORDER.index(step_id) if step_id in ORDER else -1


def next_step(step_id: str, answers: dict) -> Step | None:
    """Следующий шаг. Пропускает те, спрашивать которые незачем.

    Факультет у школьника и у выпускника не спрашиваем — во втором сезоне на
    этом месте появлялись «-», «Ф» и прочерки.
    """
    i = index(step_id)
    for nxt in STEPS[i + 1:]:
        if nxt.id == "faculty" and not _faculties(answers):
            continue
        return nxt
    return None


def missing(answers: dict) -> list[Step]:
    """Обязательные шаги без ответа — их показывает сводка перед отправкой."""
    out = []
    for s in STEPS:
        if s.optional:
            continue
        if s.id == "faculty" and not _faculties(answers):
            continue
        value = answers.get(s.id)
        if value in (None, "", []) or (s.kind == "multi" and len(value) < s.min_choices):
            out.append(s)
    return out


def label_of(s: Step, value, answers: dict) -> str:
    """Человеческая подпись ответа для сводки."""
    if value in (None, "", []):
        return "—"
    if s.kind == "multi":
        known = dict(s.choices(answers))
        return ", ".join(known.get(v, v) for v in value) or "—"
    return dict(s.choices(answers)).get(value, str(value))
