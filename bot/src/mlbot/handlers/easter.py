"""Easter eggs. Warm and strictly on topic — nothing about anyone's grades."""

from __future__ import annotations

import random
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from .. import texts

router = Router()

SIGMOID = """\
<pre>1.0 ┤                    ╭────────
    │                ╭───╯
0.5 ┤            ╭───╯
    │        ╭───╯
0.0 ┤────────╯
    └────────┬────────┬────────
           -5        0        5</pre>
Она берёт любое число и превращает его в вероятность.
Ровно поэтому логистическая регрессия умеет отвечать «на 87% это класс 1»,
а не просто «примерно 12.4»."""

JOKES = (
    "Модель с accuracy 100% на train — это не модель, это словарь.",
    "Самый честный бейзлайн — предсказывать самый частый класс. "
    "Обидно, когда он выигрывает.",
    "Хороший признак стоит десяти слоёв. Плохой — портит все десять.",
    "«У меня работало» — самая дорогая фраза в машинном обучении. "
    "Restart & Run All решает.",
)


@router.message(Command("42"))
async def answer_42(message: Message) -> None:
    await message.answer(
        "Ответ на главный вопрос жизни, вселенной и всего такого — <b>42</b>.\n\n"
        "На вопрос «почему у меня R² отрицательный» он, к сожалению, не отвечает. "
        "А ответ там простой: модель предсказывает хуже, чем среднее по выборке.")


@router.message(Command("knn"))
async def knn(message: Message) -> None:
    await message.answer(
        "Скажи мне, кто твои <i>k</i> ближайших соседей, и я скажу, кто ты.\n\n"
        "Правда, при <code>k=1</code> ближайший сосед — это ты сам, "
        "и метод торжественно сообщает, что ты — это ты. "
        "Точность на обучающей выборке 100%, пользы ноль.")


@router.message(Command("sigmoid"))
@router.message(F.text.lower() == "сигмоида")
async def sigmoid(message: Message) -> None:
    await message.answer(SIGMOID)


@router.message(Command("overfit"))
async def overfit(message: Message) -> None:
    await message.answer(
        "Переобучение — это когда студент выучил билеты наизусть, "
        "а на экзамене спросили своими словами.\n\n"
        "Лечится тем же, чем и у людей: больше разных примеров и меньше зубрёжки "
        "(регуляризация).")


@router.message(F.text.lower().in_({"спасибо", "спс", "благодарю"}))
async def thanks(message: Message) -> None:
    await message.answer(random.choice((
        "Не за что. Удачи с моделями 🙂",
        "Обращайся. И не забывай про Restart & Run All.",
        "На здоровье. Пусть твой R² будет положительным.",
    )))


@router.message(Command("joke"))
async def joke(message: Message) -> None:
    await message.answer(random.choice(JOKES))


def night_note() -> str | None:
    """A postscript for whoever is in the bot deep at night."""
    hour = datetime.now().hour
    if 2 <= hour < 5:
        return "\n\n<i>Коммитить в три ночи — традиция курса. Но выспаться тоже полезно.</i>"
    return None


@router.message(F.text.startswith("/"))
async def unknown_command(message: Message) -> None:
    """The last handler in the chain: a command nobody claimed."""
    await message.answer(texts.UNKNOWN_COMMAND)
