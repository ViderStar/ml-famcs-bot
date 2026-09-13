"""Дерево меню: связность, бюджет кнопок, доступность, старые ссылки.

Обход реестра — главное, ради чего он заводился. Эти проверки покрывают и те
узлы, которых на момент написания теста ещё не существует: раздел, добавленный
в третьем сезоне, попадёт под них сам.
"""

import pytest

from harness import Bench, crawl
from mlbot.menu import core, screens  # noqa: F401 — импорт наполняет реестр
from mlbot.menu.router import COMMANDS, legacy
from mlbot.store import Store


@pytest.fixture
async def store(tmp_path):
    s = Store(tmp_path / "menu.sqlite3")
    await s.init()
    return s


@pytest.fixture
async def bound(course, store):
    st = next(s for s in course.active if s.certificate and s.submitted())
    await store.bind(555, st.key, None, None)
    return st


# --- связность ------------------------------------------------------------------

def test_every_node_has_a_reachable_root():
    """Узел без пути к корню недостижим кнопками — только прямой ссылкой."""
    assert core.NODES, "реестр пуст"
    for n in core.NODES.values():
        seen, cur = [], n
        while cur.parent not in (None, core.ROOT):
            assert cur.parent in core.NODES, f"{cur.id}: родителя {cur.parent!r} нет"
            assert cur.parent not in seen, f"цикл в дереве через {cur.id}"
            seen.append(cur.parent)
            cur = core.NODES[cur.parent]


def test_declared_children_exist():
    for n in core.NODES.values():
        if callable(n.kids):
            continue
        for kid in n.kids:
            assert kid in core.NODES, f"{n.id} ссылается на несуществующий {kid!r}"
            assert core.NODES[kid].parent == n.id, (
                f"{kid} числится ребёнком {n.id}, а родителем указан "
                f"{core.NODES[kid].parent!r} — «назад» уведёт не туда")


def test_a_child_that_needs_a_student_lives_under_a_parent_that_needs_one_too():
    """Иначе гость видит кнопку, которая ему отвечает «сначала привяжись»."""
    for n in core.NODES.values():
        if not n.needs_student or n.parent in (None, core.ROOT):
            continue
        parent = core.NODES[n.parent]
        assert parent.needs_student or parent.visible is not core.PUBLIC, (
            f"{n.id} требует привязки, а его родитель {parent.id} открыт всем")


# --- бюджет телеграма -----------------------------------------------------------

def test_callback_data_fits_in_64_bytes_on_real_codes(course):
    """64 байта — жёсткий предел телеграма. Кириллица в аргументах съедает вдвое."""
    checked = 0
    for code in course.catalog:
        core.cb("ref.a", code)
        checked += 1
    for hw_id in course.rubrics:
        core.cb("s2.hw.card", hw_id)
        core.cb("s2.f", f"{hw_id}:11")
        checked += 2
    assert checked > 100, "проверять оказалось нечего"


def test_cb_refuses_to_silently_truncate():
    with pytest.raises(ValueError):
        core.cb("ref.a", "я" * 40)


# --- старые кнопки из истории чата ------------------------------------------------

def test_every_old_button_still_opens_something():
    """Инлайновые кнопки живут в переписке вечно — прошлогодняя обязана работать."""
    old = ["hw:list", "hw:hw03", "f:hw03:2", "task:hw01", "mat:hw04", "read:hw09",
           "ref:list", "ref:hw:common", "ref:art:common.no_seed", "res:strengths",
           "cert:pdf", "cert:photo", "learn:random", "noop"]
    for data in old:
        translated = legacy(data)
        assert translated is not None, f"{data!r} перестал открываться"
        assert translated[0] in core.NODES, f"{data!r} ведёт в несуществующий узел"


def test_commands_point_at_existing_nodes():
    for command, node_id in COMMANDS.items():
        assert node_id in core.NODES, f"/{command} ведёт в несуществующий узел"


# --- поведение ---------------------------------------------------------------------

async def test_a_guest_is_asked_to_bind_instead_of_getting_a_traceback(cfg, course, store):
    guest = Bench(cfg, course, store, user_id=404)
    for node_id in (n.id for n in core.NODES.values() if n.needs_student):
        out = await guest.press(core.cb(node_id, "hw03"))
        shown = " ".join(s.text for s in out)
        assert "Traceback" not in shown and "Error" not in shown, node_id


async def test_the_whole_tree_renders_for_a_real_student(cfg, course, store, bound):
    """Обход всего, до чего можно дожать кнопками, — ни одного падения."""
    me = Bench(cfg, course, store, user_id=555)
    out = await crawl(me, limit=250)
    assert len(out.pressed) > 100
    assert not [s for s in out.sent if "Traceback" in s.text]
    # Разделы, ради которых дерево и затевалось.
    assert any("Материалы сезона" in s.text for s in out.sent)
    assert any("Второй сезон" in s.text for s in out.sent)


async def test_materials_are_open_to_someone_who_submitted_nothing(cfg, course, store):
    """Слайды и задания жили внутри карточки домашки — не сдававшему никак."""
    silent = next(s for s in course.active if not s.submitted())
    await store.bind(556, silent.key, None, None)
    bench = Bench(cfg, course, store, user_id=556)
    out = await bench.press(core.cb("s2.lib"))
    assert out and any("Материалы сезона" in s.text for s in out)
    topics = [d for s in out for _, d in s.buttons if d and "s2.lib.hw" in d]
    assert topics, "в материалах сезона не оказалось ни одной темы"
    assert (await bench.press(topics[0]))


async def test_back_always_leads_to_the_declared_parent(cfg, course, store, bound):
    """«Назад» строится из родителя — руками его нигде не проставляют."""
    me = Bench(cfg, course, store, user_id=555)
    out = await crawl(me, limit=120)
    backs = [(s, label, data) for s in out.sent for label, data in s.buttons
             if label.startswith("◀") and data]
    assert len(backs) > 20, "кнопок «назад» почти нет — обход прошёл мимо дерева"
    for _, label, data in backs:
        node_id, _ = core.parse(data)
        assert node_id in core.NODES, f"«назад» ведёт в никуда: {data!r}"
        assert core.NODES[node_id].button in label, (
            f"подпись {label!r} не совпадает с узлом {node_id}")


# --- нововведения -------------------------------------------------------------------

async def test_a_person_can_see_and_erase_what_the_bot_keeps(cfg, course, store, bound):
    """«Мои данные» показывают правду и стирают именно то, что обещали."""
    me = Bench(cfg, course, store, user_id=555)
    await me.press(core.cb("s2.res"))          # нажатие, которое должно попасть в счёт
    out = await me.press(core.cb("help.data"))
    assert "555" in me.text and str(bound.key) in me.text

    dump = await me.press(core.cb("help.data.dl"))
    assert [s for s in dump if s.api == "SendDocument"], "выгрузка не пришла"

    await me.press(core.cb("help.data.rm.yes"))
    assert await store.binding(555) is None
    assert await store.about(555) == {"tg_id": 555, "binding": None, "events": [],
                                      "support": [], "claims": []}
    assert out


async def test_erasing_does_not_touch_the_conversation_with_a_human(cfg, course, store,
                                                                    bound):
    """Обращения — переписка с живым человеком; стирать её в одностороннем порядке нельзя."""
    await store.add_support(555, None, "не согласен с оценкой")
    me = Bench(cfg, course, store, user_id=555)
    await me.press(core.cb("help.data.rm.yes"))
    assert len(await store.open_support()) == 1


async def test_answering_a_ticket_closes_it(cfg, course, store):
    """Флаг `answered` только читался — пометить обращение было нечем."""
    ticket = await store.add_support(777, "student", "как пересдать?")
    adm = Bench(cfg, course, store, user_id=1, username="chief", safe=True)
    await adm.press(core.cb("a.ppl.sup.re", str(ticket)))
    await adm.send("Пересдача через неделю, напишу деталями.")
    assert await store.open_support() == []
    letters = [s for s in adm.session.calls
               if s.api == "SendMessage" and "Пересдача через неделю" in s.text]
    assert letters, "ответ не ушёл"
    # Песочница: письмо развернулось на преподавателя, студент его не получил.
    assert all(s.chat_id == 1 for s in letters)
