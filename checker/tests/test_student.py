"""Режим «портрет студента»: дайджест, промпт, проверка и санация ответа."""

import json

import pytest

from mlcheck import llm
from mlcheck.catalog import load_all as load_catalog
from mlcheck.config import load
from mlcheck.report import points_needed_for
from mlcheck.rubric import load_all as load_rubrics


@pytest.fixture(scope="module")
def env():
    cfg = load()
    return cfg, load_rubrics(cfg), load_catalog(cfg)


def _report(cfg):
    """Любой отчёт настоящего прогона.

    В открытый репозиторий out/ не входит — там ФИО и рецензии, — поэтому без
    него тест честно пропускается, а не зеленеет на пустом месте.
    """
    files = sorted(cfg.paths.findings.glob("*.json"))
    if not files:
        pytest.skip("нет результатов прогона: out/findings пуст")
    return json.loads(files[0].read_text(encoding="utf-8"))


def test_points_needed_for_matches_ratio_comparison():
    for ratio in (0.7, 0.66, 0.28):
        for total in range(1, 40):
            need = points_needed_for(ratio, total)
            assert need / total >= ratio and (need == 0 or (need - 1) / total < ratio)
    assert points_needed_for(0.7, 0) == 0


def test_digest_lists_every_topic_and_hides_fio(env):
    cfg, rubrics, catalog = env
    rep = _report(cfg)
    text = llm.student_digest(rep, rubrics, catalog, cfg)
    for hw_id in rep["homeworks"]:
        assert f"## {hw_id}" in text
    assert rep["fio"] not in text
    assert rep["key"] in text
    assert "[critical, " in text or "[major, " in text or "не сдано" in text


def test_prompt_lists_only_catalog_links(env):
    cfg, rubrics, catalog = env
    prompt = llm.student_prompt(rubrics, catalog)
    urls = set(__import__("re").findall(r"https?://\S+", prompt))
    assert urls <= llm.allowed_urls(catalog)
    assert llm.HANDBOOK_ROOT in urls
    assert "hygiene" in prompt and "ТОЛЬКО ссылки" in prompt


def _good():
    return {"portrait": "Хорошо.", "next_steps": "Дальше.",
            "growth": [{"topic": "hw04", "title": "Утечка", "why": "Потому.",
                        "codes": ["common.fit_before_split"],
                        "links": [{"title": "КВ", "url": llm.HANDBOOK_ROOT}]}]}


def test_validate_accepts_good_and_rejects_bad(env):
    cfg, rubrics, catalog = env
    allowed = llm.allowed_urls(catalog)
    assert llm.validate_student(_good(), rubrics, catalog, allowed) == []

    bad = _good(); bad["growth"][0]["links"][0]["url"] = "https://example.com/made-up"
    assert any("ссылка вне списка" in e for e in llm.validate_student(bad, rubrics, catalog, allowed))

    bad = _good(); bad["growth"][0]["topic"] = "hw99"
    assert any("тема вне рубрик" in e for e in llm.validate_student(bad, rubrics, catalog, allowed))

    bad = _good(); del bad["next_steps"]
    assert llm.validate_student(bad, rubrics, catalog, allowed) == ["нет поля next_steps"]

    bad = _good(); bad["growth"][0]["codes"] = ["hw04.nonexistent"]
    assert any("код вне каталога" in e for e in llm.validate_student(bad, rubrics, catalog, allowed))

    # «hwNN.other» — замечание вне каталога, но оно есть в дайджесте: допустимо.
    ok = _good(); ok["growth"][0]["codes"] = ["hw04.other"]
    assert llm.validate_student(ok, rubrics, catalog, allowed) == []
    assert llm.sanitize_student(ok, rubrics, catalog, allowed)["growth"][0]["codes"] == ["hw04.other"]


def test_sanitize_strips_foreign_links_but_keeps_the_rest(env):
    cfg, rubrics, catalog = env
    allowed = llm.allowed_urls(catalog)
    raw = _good()
    raw["growth"][0]["links"].append({"title": "x", "url": "https://evil.example/phish"})
    raw["growth"].append({"topic": "hw99", "title": "чужая тема"})
    raw["portrait"] = "п" * 5000
    clean = llm.sanitize_student(raw, rubrics, catalog, allowed)
    assert [l["url"] for l in clean["growth"][0]["links"]] == [llm.HANDBOOK_ROOT]
    assert len(clean["growth"]) == 1
    assert len(clean["portrait"]) == llm.STUDENT_LIMITS["portrait"]
    assert llm.sanitize_student({"portrait": "x"}, rubrics, catalog, allowed) is None


def test_to_json_carries_portrait_field(env):
    """Поле есть всегда — None до прогона, dict после. Бот обязан уметь без него."""
    from mlcheck.report import StudentReport, to_json
    cfg, *_ = env
    rep = StudentReport(key="k", fio="Ф И", slug=None, status="ok")
    assert to_json(rep, 12, cfg)["portrait"] is None
    rep.portrait = {"portrait": "x", "growth": [], "next_steps": "y"}
    assert to_json(rep, 12, cfg)["portrait"]["portrait"] == "x"


def test_broken_review_is_skipped_not_fatal(tmp_path, monkeypatch, env):
    """Один битый JSON от субагента не должен ронять сборку всех отчётов.

    Случай живой: агент записал управляющий символ внутрь строки, и `report`
    падал JSONDecodeError, не называя виновника. Теперь файл пропускается,
    а ловит его `mlcheck llm verify`.
    """
    cfg, *_ = env
    good = {"checks": [], "findings": [], "strengths": "ок", "summary": "ок"}
    d = tmp_path / "llm"
    d.mkdir()
    (d / "alice__hw01.json").write_text(json.dumps(good), encoding="utf-8")
    (d / "bob__hw02.json").write_text('{"summary": "обрыв\x07строки"', encoding="utf-8")

    monkeypatch.setattr(type(cfg.paths), "out", property(lambda self: tmp_path), raising=False)
    res = llm.load_results(cfg, "grading")
    assert set(res) == {"alice|hw01"}
    assert res["alice|hw01"]["summary"] == "ок"
