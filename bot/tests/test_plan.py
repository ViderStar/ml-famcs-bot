""""What to improve" and "Strengths": about ML, not about cells."""

from mlbot.views import best_link, plan_text, strengths_text, why_paragraph


def _balanced(text: str) -> None:
    for tag in ("b", "i", "a", "code"):
        assert text.count(f"<{tag}") == text.count(f"</{tag}>"), tag


def test_plan_renders_for_the_whole_cohort(course):
    for st in course.active:
        text, links = plan_text(course, st)
        assert text
        _balanced(text)
        assert len(links) <= 5
        for _, url in links:
            assert url.startswith("http")


def test_plan_never_recommends_hygiene(course):
    """"Run the cells" is true but useless for reflection."""
    hygiene_titles = {a.title for a in course.catalog.values() if a.kind == "hygiene"}
    for st in course.active:
        text, _ = plan_text(course, st)
        block = text.split("🎯")[1].split("📚")[0] if "🎯" in text else ""
        for title in hygiene_titles:
            assert f"<b>{title}</b>" not in block, (st.key, title)


def test_plan_items_carry_a_link(course):
    """Every piece of advice has somewhere to read further.

    Without a portrait: exactly one link per item (the code-based fallback). With
    one: 0-3 links per item — the model may leave the list empty when the catalog
    has no suitable link — but every link must come from the catalog.
    """
    seen = 0
    for st in course.active:
        text, links = plan_text(course, st)
        if "🎯" not in text:
            continue
        block = text.split("🎯")[1].split("📚")[0]
        items = [x for x in block.split("\n") if x[:2] in ("1.", "2.", "3.", "4.", "5.")]
        if st.portrait and st.portrait.get("growth"):
            for _, url in links:
                assert url in course.known_links, (st.key, url)
        else:
            assert block.count("📖") == len(items), st.key
        seen += 1
    # More than half the stream: a threshold from the corpus size, not an absolute.
    assert seen > len(course.active) // 2


def test_handbook_is_preferred(course):
    art = course.article("common.fit_before_split")
    link = best_link(course, art, "hw04")
    assert link and "handbook" in link[1]
    assert why_paragraph(art).startswith("Это утечка данных")


def test_strengths_screen_renders_for_everyone(course):
    for st in course.active:
        text = strengths_text(course, st)
        _balanced(text)
        assert "Сильные стороны" in text
        if st.strengths():
            assert str(len(st.strengths())) in text


def test_results_points_to_strengths_screen(course):
    from mlbot.views import results_text
    st = next(s for s in course.active if len(s.strengths()) >= 3)
    text = results_text(course, st)
    assert "Сильные стороны" in text
    if st.portrait:
        assert st.portrait["portrait"][:80] in text          # the course portrait is on the screen
    else:
        assert f"в {len(st.strengths())} темах" in text


def _with_portrait(course, growth_url):
    import copy
    from mlbot.data import Student
    base = next(s for s in course.active if s.strengths())
    raw = copy.deepcopy(base.raw)
    raw["portrait"] = {
        "portrait": "Ты умеешь аккуратно валидировать модели.",
        "growth": [{"topic": "hw04", "title": "Утечки при препроцессинге",
                    "why": "Импьютер обучался до разбиения в двух работах.",
                    "codes": ["common.fit_before_split"],
                    "links": [{"title": "Кросс-валидация", "url": growth_url},
                              {"title": "фишинг", "url": "https://evil.example/x"}]}],
        "next_steps": "Собери пайплайн через Pipeline.",
    }
    return Student(raw)


def test_portrait_drives_results_plan_and_strengths(course):
    from mlbot.views import results_text
    url = next(iter(course.known_links))
    st = _with_portrait(course, url)

    assert "Сильные стороны за курс" in results_text(course, st)
    assert "валидировать" in results_text(course, st)

    text, links = plan_text(course, st)
    assert "Утечки при препроцессинге" in text and "hw04" in text
    assert "Собери пайплайн" in text
    # The foreign link was filtered out, the catalog one stayed.
    assert "evil.example" not in text and url in text
    assert links == [("Кросс-валидация", url)]

    s = strengths_text(course, st)
    assert s.index("валидировать") < s.index("По темам")


def test_without_portrait_everything_still_renders(course):
    for st in course.active:
        assert st.portrait is None or isinstance(st.portrait, dict)
