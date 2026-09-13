"""Сравнение сборок: перевороты вердиктов и сертификаты."""

import json

from mlcheck import diff


def _student(tmp, dirname, key, cert, hws):
    d = tmp / dirname
    d.mkdir(exist_ok=True)
    (d / f"{key}.json").write_text(json.dumps({
        "key": key, "fio": f"Ф {key}", "status": "ok", "certificate": cert,
        "passed_hw": sum(1 for s in hws.values() if s == "passed"),
        "homeworks": {hw: {"status": s, "required_passed": 3, "required_total": 4,
                           "findings": [{"severity": "critical", "title": "упало"}]
                           if s == "failed" else []} for hw, s in hws.items()},
    }, ensure_ascii=False), encoding="utf-8")
    return d


def test_compare_counts_certificates_and_flips(tmp_path):
    _student(tmp_path, "v1", "a", False, {"hw01": "failed", "hw02": "passed"})
    _student(tmp_path, "v1", "b", True, {"hw01": "passed", "hw02": "passed"})
    _student(tmp_path, "v2", "a", True, {"hw01": "passed", "hw02": "passed"})
    _student(tmp_path, "v2", "b", False, {"hw01": "failed", "hw02": "passed"})
    d = diff.compare(tmp_path / "v1", tmp_path / "v2")
    assert (d.cert_before, d.cert_after) == (1, 1)
    assert d.cert_gained == ["Ф a"] and d.cert_lost == ["Ф b"]
    assert d.passed_delta == {1: 1, -1: 1}
    assert {(f.key, f.hw, f.before, f.after) for f in d.flips} == {
        ("a", "hw01", "failed", "passed"), ("b", "hw01", "passed", "failed")}
    text = diff.render(d, "v1", "v2")
    assert "смотреть обязательно" in text and "упало" in text
    assert text.count("<") == 0                      # markdown, не html


def test_excluded_students_are_skipped(tmp_path):
    _student(tmp_path, "v1", "a", False, {"hw01": "failed"})
    d1 = tmp_path / "v2"; d1.mkdir()
    (d1 / "a.json").write_text(json.dumps({"key": "a", "fio": "x", "status": "excluded",
                                           "homeworks": {}}), encoding="utf-8")
    d = diff.compare(tmp_path / "v1", tmp_path / "v2")
    assert d.students == 0 and d.flips == []
