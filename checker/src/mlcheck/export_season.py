"""Сборка репозитория материалов второго сезона.

Командой, а не руками: ветку можно пересобрать после любой правки рубрик или
каталога, и она не начнёт расходиться с тем, что показывает бот. Раскладка —
как в репозитории первого сезона: `NN_Название_занятия/`, `Домашние_задания/`,
README с таблицей занятий.

Календарь восстановлен по самим слайдам — на титульном листе стоит дата, а в
шапке имя докладчика. Это надёжнее, чем метки файловой системы: те показывают
день, когда файлы скачали (31 августа), а не день занятия.

Чего не было у первого сезона — раздела `Типовые_ошибки`: 149 разборов,
собранных по итогам проверки 929 работ.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .catalog import load_dir as load_catalog_dir
from .config import Config
from .rubric import load_dir as load_rubrics_dir

SEASON = "Второй сезон · весна 2026"


@dataclass(frozen=True)
class Lesson:
    num: int
    date: str
    title: str
    lecturer: str = ""
    slides: tuple[str, ...] = ()        # презентации и конспекты
    notebooks: tuple[str, ...] = ()     # раздаточные ноутбуки
    homeworks: tuple[str, ...] = ()

    @property
    def folder(self) -> str:
        return f"{self.num:02d}_{slug(self.title)}"


def slug(text: str) -> str:
    """Имя папки в стиле первого сезона: слова через подчёркивание."""
    text = re.sub(r"[«»\"'(),.:;!?/\\]", "", text)
    text = re.sub(r"[\s—–-]+", "_", text.strip())
    return text.strip("_")


# Занятия второго сезона — по анонсам в канале курса (@ml_course_famcs).
# Канал авторитетнее всего остального: в нём стоит номер занятия, дата, место,
# спикер и файлы, выложенные в тот же день. Метаданные PDF врут дважды — часть
# слайдов переиспользована с первого сезона и хранит чужую дату и чужого автора
# («Докладчик: Тима Бовт» на логистической регрессии, которую читал Артём).
LESSONS: tuple[Lesson, ...] = (
    Lesson(1, "02.03.2026", "Лекция 1: История, инструменты и основные задачи",
           "Паша Кашмель",
           slides=("Lecture1slides.pdf", "MLCourse_Season2.pdf"),
           homeworks=("hw01",)),
    Lesson(2, "05.03.2026", "Разведочный анализ данных (EDA)", "Артём Лебедевич",
           homeworks=("hw02",)),
    Lesson(3, "09.03.2026", "Метод ближайших соседей (KNN)", "Артём Лебедевич",
           slides=("KNN_final.pptx",), notebooks=("KNN_empty.ipynb",),
           homeworks=("hw03",)),
    Lesson(4, "12.03.2026", "Линейная регрессия: теория", "Ваня Горохов",
           slides=("Лекция 4_ Линейная_регрессия.pdf",), homeworks=("hw04",)),
    Lesson(5, "16.03.2026", "Линейная регрессия: практика", "Ваня Горохов",
           notebooks=("lin_reg_practice.ipynb", "ToyotaCorolla.csv")),
    Lesson(6, "23.03.2026",
           "Логистическая регрессия и оценки качества классификации: теория",
           "Артём Лебедевич", slides=("Машинное обучение 09.pdf",)),
    Lesson(7, "26.03.2026", "Логистическая регрессия: практика", "Паша Кашмель",
           notebooks=("logreg_practice_student (2).ipynb",), homeworks=("hw05",)),
    Lesson(8, "30.03.2026", "Наивный Байес: лекция и практика", "Паша Кашмель",
           slides=("lecture2_slides.pdf", "lecture2_notes.pdf"),
           notebooks=("naive_bayes_practice_student.ipynb",), homeworks=("hw06",)),
    Lesson(9, "02.04.2026", "Деревья решений: лекция и практика", "Артём Лебедевич",
           slides=("Машинное_обучение_дерево_решений_лекция.pdf",),
           notebooks=("decision-tree-empty-cells.ipynb",), homeworks=("hw07",)),
    Lesson(10, "06.04.2026", "Метод опорных векторов (SVM)", "Паша Кашмель",
           slides=("svm_slides.pdf",),
           notebooks=("svm_practice_student.ipynb",), homeworks=("hw08",)),
    Lesson(11, "09.04.2026", "Ансамбли: лекция", "Ваня Горохов",
           slides=("lecture_9_ansambles.pdf",), homeworks=("hw09",)),
    Lesson(12, "13.04.2026", "Градиентный бустинг: лекция", "Ваня Горохов",
           slides=("lecture_9_10_ansambles.pdf",)),
    Lesson(13, "16.04.2026", "Градиентный бустинг: практика", "Ваня Горохов",
           slides=("GB_practice.pdf",),
           notebooks=("student_notebook.ipynb", "teacher_notebook.ipynb"),
           homeworks=("hw10",)),
    Lesson(14, "23.04.2026",
           "Подбор гиперпараметров и интерпретируемость моделей", "Паша Кашмель",
           slides=("lecture_hp_interp_slides.pdf", "lecture_hp_interp_notes.pdf"),
           notebooks=("hp_interp_practice_student.ipynb",), homeworks=("hw11",)),
    Lesson(15, "27.04.2026", "Современный ML: что, куда и зачем",
           "Алексей Толстиков · приглашённый спикер"),
    Lesson(16, "30.04.2026", "Кластеризация", "Ваня Горохов",
           slides=("Лекция_Кластеризация.pdf",)),
    Lesson(17, "04.05.2026", "Кластеризация II: DBSCAN и плотностной подход",
           "Паша Кашмель",
           slides=("clustering2_slides.pdf", "clustering2_notes.pdf"),
           notebooks=("clustering2_practice_student.ipynb",), homeworks=("hw12",)),
    Lesson(18, "07.05.2026", "Снижение размерности: PCA, t-SNE, UMAP", "Паша Кашмель",
           slides=("pca_slides.pdf", "pca_notes.pdf"),
           notebooks=("pca_practice_student.ipynb",), homeworks=("hw13",)),
    Lesson(19, "11.05.2026", "Введение в нейронные сети", "Ваня Горохов",
           slides=("Лекция_нейросети.pdf",)),
)

# Гостевые встречи после основной программы. Материалов почти не осталось —
# но без них список занятий неполон, а спикеры заслуживают упоминания.
@dataclass(frozen=True)
class Guest:
    date: str
    title: str
    speaker: str
    files: tuple[str, ...] = ()


GUESTS: tuple[Guest, ...] = (
    Guest("14.05.2026",
          "Стартап как новый способ работы инженера: почему рынок важнее "
          "красивого решения", "Константин Бичун"),
    Guest("25.05.2026", "Путь Алисы к LLM-агентам",
          "Евгений Ганкович, руководитель группы LLM в Алисе"),
    Guest("28.05.2026", "Как компьютер учится смотреть: основы CV",
          "Никита Киселёв, Data Scientist в instinctools"),
    Guest("07.09.2026", "Как найти себя в ML: поиск работы и развитие после курса",
          "Артём Лебедевич", files=("find_yourself_in_ml.html",)),
)

GUEST_DIR = "Гостевые_встречи"

# Куда класть то, что к конкретному занятию не привязано.
DATA_DIR = "Данные"
EXTRA_DIR = "Дополнительно"
HOMEWORK_DIR = "Домашние_задания"
MISTAKES_DIR = "Типовые_ошибки"

DATA_FILES = {".csv", ".zip"}

# Условия домашек, которые раздавались отдельным файлом.
HOMEWORK_FILES: dict[str, tuple[str, ...]] = {
    "hw03": ("ml_course_homework_3.pdf",),
    "hw04": ("ml_course_hw_4.pdf",),
    "hw09": ("hw_forest.md",),
    "hw10": ("hw_boosting.md",),
}
# Теорминимум по матанализу и линалу достался от первого сезона — он и там
# лежит, но студенты второго пользовались этими же тремя файлами.
# Другой экспорт того же материала. Байты различаются, поэтому проверка по
# хэшу их не ловит, но класть в репозиторий обе копии незачем.
SAME_AS = {
    "slides.pdf": "Lecture1slides.pdf",
    "Машинное_обучение_09.pdf": "Машинное обучение 09.pdf",
    "logreg_practice_student (1).ipynb": "logreg_practice_student.ipynb",
}

# Не выкладываем. Репозиторий публичный, а это операционные данные сервиса
# проката самокатов — идентификаторы инцидентов, треки, метки краж — и разбор,
# построенный на них. Кому они принадлежат и разрешена ли публикация, из
# материалов не следует, а публикация необратима: спрашивать надо до, а не после.
WITHHELD = {
    "ml_dataset_20k.csv": "операционные данные сервиса самокатов",
    "scooter_alerts.ipynb": "разбор на операционных данных сервиса самокатов",
}

EXTRA_NOTE = {
    "теормин1.pdf": "Теорминимум: матрицы и определители",
    "теормин2.pdf": "Теорминимум: векторные пространства",
    "теормин3.pdf": "Теорминимум: начала функционального анализа",
    "hw01_setup_tools_template.zip": "Заготовка первой домашки, как её раздавали",
}


@dataclass
class Report:
    copied: list[str] = field(default_factory=list)
    withheld: list[tuple[str, str]] = field(default_factory=list)
    skipped_dupes: list[tuple[str, str]] = field(default_factory=list)
    leftovers: list[str] = field(default_factory=list)
    homeworks: list[str] = field(default_factory=list)
    articles: int = 0


def sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def hw_folder(hw_id: str, title: str) -> str:
    """`03_KNN_метод_k_ближайших_соседей` — как в репозитории первого сезона."""
    return f"{hw_id.removeprefix('hw')}_{slug(title)}"


def nfc(name: str) -> str:
    """Имя файла в одной нормализации.

    macOS хранит имена в NFD: «й» лежит на диске как «и» плюс краткая. Литерал
    в коде — NFC, и сравнение строк молча не совпадает, хотя `exists()` даёт
    True: файловая система сравнивает сама и по-своему. Без этого три лекции
    попадали и в занятие, и в «без места».
    """
    return unicodedata.normalize("NFC", name)


def _copy(src: Path, dst_dir: Path, seen: dict[str, str], report: Report) -> bool:
    """Скопировать, если такого содержимого ещё не клали.

    Сравнение по хэшу, а не по имени: `logreg_practice_student.ipynb` и
    `logreg_practice_student (1).ipynb` — один и тот же файл.
    """
    digest = sha1(src)
    if digest in seen:
        report.skipped_dupes.append((src.name, seen[digest]))
        return False
    dst_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst_dir / src.name)
    seen[digest] = src.name
    report.copied.append(f"{dst_dir.name}/{src.name}")
    return True


def lesson_readme(lesson: Lesson, rubrics) -> str:
    lines = [f"# {lesson.title}", ""]
    lines.append(f"**{SEASON}** · занятие {lesson.num} · {lesson.date}")
    if lesson.lecturer:
        lines.append(f"  \n**Докладчик:** {lesson.lecturer}")
    lines.append("")
    if lesson.slides:
        lines += ["## Материалы", ""]
        lines += [f"- `{name}`" for name in lesson.slides]
        lines.append("")
    if lesson.notebooks:
        lines += ["## Раздаточные ноутбуки", ""]
        lines += [f"- `{name}`" for name in lesson.notebooks]
        lines.append("")
    if lesson.homeworks:
        lines += ["## Домашние задания", ""]
        for hw in lesson.homeworks:
            rubric = rubrics.get(hw)
            title = rubric.title if rubric else hw
            lines.append(f"- [{hw} — {title}](../{HOMEWORK_DIR}/{hw_folder(hw, title)})")
        lines.append("")
    return "\n".join(lines)


def homework_readme(hw_id: str, rubric, cfg: Config) -> str:
    """README домашки. Текст задания — если он сохранился отдельным файлом.

    У семи тем задание жило прямо в раздаточном ноутбуке, и восстанавливать его
    пересказом нечестно: вместо этого перечисляем пункты рубрики и говорим,
    откуда они взялись.
    """
    lines = [f"# {hw_id} — {rubric.title}", "", f"*{SEASON}*", ""]
    text = ""
    if rubric.task_path and Path(rubric.task_path).exists():
        text = Path(rubric.task_path).read_text(encoding="utf-8").strip()
    if text:
        lines += [text, ""]
    else:
        lines += [
            "> Отдельного текста задания по этой теме не было: условие лежало прямо",
            "> в раздаточном ноутбуке. Ниже — пункты, по которым работу проверяли.",
            "",
        ]
    if not rubric.graded:
        lines += ["> **Вне зачёта.** По этой теме задание не выдавалось, и на",
                  "> сертификат она не влияла.", ""]
    required = [c for c in rubric.checks if c.required]
    optional = [c for c in rubric.checks if not c.required]
    if required:
        lines += ["## Что проверялось", ""]
        lines += [f"- {c.title}" for c in required]
        lines.append("")
    if optional:
        lines += ["## Дополнительно (на вердикт не влияло)", ""]
        lines += [f"- {c.title}" for c in optional]
        lines.append("")
    lines += [f"Типовые ошибки по этой теме — в [`../../{MISTAKES_DIR}`]"
              f"(../../{MISTAKES_DIR}/README.md).", ""]
    return "\n".join(lines)


def mistakes_readme(catalog) -> str:
    by_hw: dict[str, list] = {}
    for art in catalog.values():
        by_hw.setdefault(art.hw, []).append(art)
    lines = [
        "# Типовые ошибки", "",
        f"*{SEASON}*", "",
        "Разборы, собранные по итогам проверки **929 работ**: что именно пошло не так,",
        "почему это важно и как надо. Общие ошибки не привязаны к теме и встречаются",
        "в любой работе; остальные — по темам.", "",
    ]
    common = sorted(by_hw.pop("common", []), key=lambda a: a.title)
    if common:
        lines += ["## Общие", ""]
        lines += [f"- [{a.title}](common/{a.code.split('.', 1)[1]}.md)" for a in common]
        lines.append("")
    for hw in sorted(by_hw):
        items = sorted(by_hw[hw], key=lambda a: a.title)
        lines += [f"## {hw}", ""]
        lines += [f"- [{a.title}]({hw}/{a.code.split('.', 1)[1]}.md)" for a in items]
        lines.append("")
    return "\n".join(lines)


def root_readme(rubrics, report: Report) -> str:
    lines = [
        "# Курс по машинному обучению — второй сезон", "",
        f"Материалы весеннего сезона 2026 года: {len(LESSONS)} занятий "
        f"с {LESSONS[0].date[:5].replace('.', '.')} по {LESSONS[-1].date[:5]}, "
        f"{len(GUESTS)} гостевые встречи, {len(rubrics)} домашних заданий, "
        "205 сдававших, 55 сертификатов.", "",
        "## Ход работы", "",
        "| Дата | Занятие | Докладчик | Материалы | Домашка |",
        "|------|---------|-----------|-----------|---------|",
    ]
    for lesson in LESSONS:
        folder = lesson.folder
        # Ссылка ведёт в папку всегда: даже без слайдов там README с темой,
        # спикером и ссылкой на домашку.
        materials = (f"[Материалы]({folder})" if (lesson.slides or lesson.notebooks)
                     else f"[Описание]({folder})")
        if lesson.homeworks:
            hw_links = ", ".join(
                f"[{hw}]({HOMEWORK_DIR}/{hw_folder(hw, rubrics[hw].title)})"
                for hw in lesson.homeworks if hw in rubrics)
        else:
            hw_links = "—"
        lines.append(f"| {lesson.date} | {lesson.title} | {lesson.lecturer or '—'} "
                     f"| {materials} | {hw_links} |")
    lines += ["", "## Гостевые встречи", "",
              "| Дата | Тема | Спикер |", "|------|------|--------|"]
    for g in GUESTS:
        lines.append(f"| {g.date} | {g.title} | {g.speaker} |")

    lines += [
        "", "## Что где лежит", "",
        f"- `NN_Название/` — слайды, конспекты и раздаточные ноутбуки занятия;",
        f"- `{HOMEWORK_DIR}/` — условия домашек и пункты, по которым их проверяли;",
        f"- `{MISTAKES_DIR}/` — {report.articles} разборов типовых ошибок "
        "по итогам проверки 929 работ;",
        f"- `{DATA_DIR}/` — наборы данных, которые раздавались к практикам;",
        f"- `{GUEST_DIR}/` — материалы гостевых встреч;",
        f"- `{EXTRA_DIR}/` — теорминимум по математике.", "",
        "## Как получался зачёт", "",
        "Домашка зачтена, если в ней **нет критичных замечаний** и закрыто не меньше",
        "70% обязательных пунктов. Замечания уровня «серьёзное» и «мелкое» вердикт",
        "не меняли никогда. Сертификат — за 7 зачтённых тем из 12 зачётных",
        "(тема «Деревья решений» в зачёт не входила: задания по ней не выдавалось).", "",
        "Свой разбор с объяснением каждой ошибки можно посмотреть в боте курса —",
        "[@ml_famcsl_hw_bot](https://t.me/ml_famcsl_hw_bot).", "",
    ]
    return "\n".join(lines)


def build(cfg: Config, out: Path) -> Report:
    report = Report()
    rubrics = load_rubrics_dir(cfg.rubrics_dir)
    catalog = load_catalog_dir(cfg.catalog_dir)
    report.articles = len(catalog)
    materials = cfg.paths.materials

    out.mkdir(parents=True, exist_ok=True)
    placed: set[str] = set()

    for lesson in LESSONS:
        folder = out / lesson.folder
        seen: dict[str, str] = {}
        for name in lesson.slides + lesson.notebooks:
            src = materials / name
            if not src.exists():
                report.leftovers.append(f"НЕ НАЙДЕН: {name}")
                continue
            _copy(src, folder, seen, report)
            placed.add(nfc(src.name))
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "README.md").write_text(lesson_readme(lesson, rubrics), encoding="utf-8")

    # Домашки
    for hw_id in sorted(rubrics):
        rubric = rubrics[hw_id]
        folder = out / HOMEWORK_DIR / hw_folder(hw_id, rubric.title)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "README.md").write_text(homework_readme(hw_id, rubric, cfg),
                                          encoding="utf-8")
        report.homeworks.append(hw_id)
        hw_seen: dict[str, str] = {}
        for name in tuple(rubric.all_templates) + HOMEWORK_FILES.get(hw_id, ()):
            src = materials / name
            if src.exists():
                _copy(src, folder, hw_seen, report)
                placed.add(nfc(src.name))

    # Типовые ошибки — то, чего у первого сезона нет
    mistakes = out / MISTAKES_DIR
    mistakes.mkdir(parents=True, exist_ok=True)
    (mistakes / "README.md").write_text(mistakes_readme(catalog), encoding="utf-8")
    for art in catalog.values():
        hw, _, short = art.code.partition(".")
        target = mistakes / hw
        target.mkdir(parents=True, exist_ok=True)
        # Копируем сам файл статьи: путь к нему каталог уже знает.
        if art.path.exists():
            shutil.copy2(art.path, target / f"{short}.md")

    # Гостевые встречи
    guests = out / GUEST_DIR
    guests.mkdir(parents=True, exist_ok=True)
    guest_seen: dict[str, str] = {}
    glines = ["# Гостевые встречи", "", f"*{SEASON}*", "",
              "После основной программы курс продолжился серией встреч про то,",
              "что бывает после базы: карьера, продукты, узкие направления.", ""]
    for g in GUESTS:
        glines += [f"## {g.date} — {g.title}", "", f"**{g.speaker}**", ""]
        for name in g.files:
            src = materials / name
            if src.exists():
                _copy(src, guests, guest_seen, report)
                placed.add(nfc(src.name))
                glines += [f"- [`{name}`]({name})", ""]
    (guests / "README.md").write_text("\n".join(glines), encoding="utf-8")

    # Данные и всё, что не привязано к занятию, — но не молча в корзину
    data_seen: dict[str, str] = {}
    extra_seen: dict[str, str] = {}
    for src in sorted(materials.iterdir()):
        name = nfc(src.name)
        if not src.is_file() or name in placed:
            continue
        if name in SAME_AS:
            report.skipped_dupes.append((name, SAME_AS[name]))
            continue
        if name in WITHHELD:
            report.withheld.append((name, WITHHELD[name]))
            continue
        if src.suffix.lower() in DATA_FILES:
            _copy(src, out / DATA_DIR, data_seen, report)
        else:
            _copy(src, out / EXTRA_DIR, extra_seen, report)
            if name not in EXTRA_NOTE:
                report.leftovers.append(name)

    extra = out / EXTRA_DIR
    if extra.exists():
        lines = ["# Дополнительно", "", f"*{SEASON}*", ""]
        for name in sorted(p.name for p in extra.iterdir() if p.name != "README.md"):
            lines.append(f"- `{name}` — {EXTRA_NOTE.get(name, 'без описания')}")
        lines.append("")
        (extra / "README.md").write_text("\n".join(lines), encoding="utf-8")

    (out / "README.md").write_text(root_readme(rubrics, report), encoding="utf-8")
    return report
