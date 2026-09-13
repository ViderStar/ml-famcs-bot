"""Entry point: mlcheck <step>. Each step writes its own artifact and runs on its own."""

from __future__ import annotations

import argparse
import re
import sys


def cmd_roster(args: argparse.Namespace) -> int:
    from . import roster
    from .config import load

    cfg = load()
    students = roster.build(cfg)
    roster.save(students, cfg)

    ok = [s for s in students if s.ok]
    bad = [s for s in students if not s.ok]
    resolved = [s for s in ok if s.resolved_from_profile]

    print(f"всего в форме:      {len(students)}")
    print(f"идут в анализ:      {len(ok)}")
    print(f"исключены:          {len(bad)}")
    if resolved:
        print(f"найдено по профилю: {len(resolved)}")
        for s in resolved:
            print(f"    {s.fio} -> {s.slug}")
    print()
    print(f"roster:   {cfg.paths.out / 'roster.json'}")
    print(f"исключены: {cfg.paths.out / 'excluded.csv'}")
    if bad:
        from .roster import _score_repo_name

        print()
        print("Исключённые:")
        hints = []
        for s in bad:
            print(f"    {s.fio:<28} {s.raw_url}")
            if s.owner_repos:
                best = max(s.owner_repos, key=_score_repo_name)
            # Only confident matches are shown ("ml-course", "mlcourse");
            # weak ones like "bsu" or "famcs" produce false leads.
                if _score_repo_name(best) >= 80:
                    hints.append(f"    {s.fio:<28} возможно {s.owner}/{best}")
        if hints:
            print()
            print("Похоже на переименование — проверьте глазами:")
            print("\n".join(hints))
        print()
        print("Полные списки репозиториев владельцев — в excluded.csv.")
    return 0


def cmd_fetch(args: argparse.Namespace) -> int:
    from . import fetch
    from .config import load

    cfg = load()
    students = fetch.load_roster(cfg)
    results = fetch.run(students, cfg, force=args.force)

    by_status: dict[str, int] = {}
    for r in results:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    for status in ("cloned", "cached", "empty", "failed"):
        if status in by_status:
            print(f"{status:8} {by_status[status]}")
    failed = [r for r in results if r.status == "failed"]
    if failed:
        print()
        print("Не выкачались:")
        for r in failed:
            print(f"    {r.slug}: {r.reason}")
    return 0


def cmd_classify(args: argparse.Namespace) -> int:
    from collections import Counter

    from . import pipeline
    from .config import load
    from .rubric import load_all

    cfg = load()
    rubrics = load_all()
    works = list(pipeline.iter_work(cfg))
    path = pipeline.save_submissions(works, cfg)

    per_hw = Counter()
    for w in works:
        for hw in w.submissions:
            per_hw[hw] += 1

    print(f"участников: {len(works)}   сдач найдено: {sum(per_hw.values())}\n")
    for hw in sorted(rubrics):
        n = per_hw[hw]
        print(f"  {hw}  {rubrics[hw].title[:40]:42} {n:3}  {'█' * round(n / 4)}")

    broken = [(w.student.fio, b) for w in works for b in w.broken]
    empty = [w.student.fio for w in works if w.repo_dir_empty]
    unmatched = sum(len(w.unmatched) for w in works)
    print(f"\nнеопознанных ноутбуков: {unmatched}")
    print(f"битых ноутбуков:        {len(broken)}")
    for fio, nb in broken:
        print(f"    {fio:<26} {nb.rel} — {nb.error}")
    print(f"репозиториев без ноутбуков: {len(empty)}")
    for fio in empty:
        print(f"    {fio}")
    print(f"\nсохранено: {path}")
    return 0


def cmd_similarity(args: argparse.Namespace) -> int:
    import csv as _csv
    from collections import Counter

    from . import pipeline, similarity
    from .config import load
    from .rubric import load_all

    cfg = load()
    rubrics = load_all()
    size = cfg.similarity["shingle_size"]

    # First pass: collect cells so the handout can be inferred from the stream.
    collected: list[tuple[str, str, str, object]] = []
    cells_by_hw: dict[str, dict[str, list[str]]] = {}
    for w in pipeline.iter_work(cfg):
        for hw, sub in w.submissions.items():
            collected.append((w.student.key, w.student.fio, hw, sub.notebook))
            bodies = [b for b, _ in similarity.cell_bodies(sub.notebook)]
            cells_by_hw.setdefault(hw, {})[w.student.key] = bodies

    min_students = cfg.similarity["boilerplate_min_students"]
    boiler = {
        hw: similarity.corpus_boilerplate(
            per_student, min_students, cfg.similarity["boilerplate_min_share"])
        for hw, per_student in cells_by_hw.items()
    }
    shared = sum(len(v) for v in boiler.values())
    print(f"ячеек распознано как раздатка потока: {shared}")

    from .templates import union_cell_bodies

    works = [
        similarity.build_work(
            key, fio, hw, nb, None, size,
            boiler.get(hw, frozenset()) | union_cell_bodies(rubrics[hw].all_templates))
        for key, fio, hw, nb in collected
    ]

    pairs = similarity.find_pairs(
        works, cfg.similarity["report_threshold"], cfg.similarity["near_min_tokens"]
    )
    kinds = Counter(p.kind for p in pairs)
    print(f"работ сравнено: {len(works)}")
    print(f"точных совпадений дельты: {kinds['exact']}")
    print(f"близких пар:              {kinds['near']}")

    # Dates are needed only where there is an exact match: history is deepened selectively.
    need = {p.a.key for p in pairs if p.kind == "exact"} | {p.b.key for p in pairs if p.kind == "exact"}
    if need:
        print(f"\nдотягиваю историю коммитов для {len(need)} репозиториев…")
        for key in sorted(need):
            similarity.unshallow(cfg.paths.raw / key)
        for p in pairs:
            if p.kind != "exact":
                continue
            for w in (p.a, p.b):
                if w.added_at is None:
                    w.added_at = similarity.first_commit_date(cfg.paths.raw / w.key, w.rel)

    path = cfg.paths.out / "similarity.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        wr = _csv.writer(fh)
        wr.writerow(["тема", "тип", "сходство", "объём дельты", "студент A", "работа A",
                     "дата A", "студент B", "работа B", "дата B", "кто раньше"])
        for p in pairs:
            e = p.earlier
            wr.writerow([p.hw, p.kind, p.similarity, min(p.a.n_tokens, p.b.n_tokens),
                         p.a.fio, p.a.rel, p.a.added_at or "",
                         p.b.fio, p.b.rel, p.b.added_at or "",
                         e.fio if e else "не определить"])

    if kinds["exact"]:
        print("\nточные совпадения (решение за преподавателями):")
        for p in pairs:
            if p.kind != "exact":
                continue
            e = p.earlier
            first = f"раньше: {e.fio}" if e else "даты не различить"
            print(f"    {p.hw}  {p.a.fio} <-> {p.b.fio}   {first}")
    print(f"\nсохранено: {path}")
    return 0


def _collect_items(cfg, rubrics, mode: str, per_hw: int):
    """Submissions that go to the model. For discovery, a small sample per topic."""
    from . import llm, pipeline

    by_hw: dict[str, list] = {}
    for w in pipeline.iter_work(cfg):
        for hw, sub in w.submissions.items():
            by_hw.setdefault(hw, []).append(
                llm.Item(custom_id=f"{w.student.key}|{hw}", student_key=w.student.key,
                         hw=hw, notebook=sub.notebook))
    items = []
    for hw in sorted(by_hw):
        group = by_hw[hw]
        if mode == "discovery":
            # Sampled evenly across the list, so both strong and weak work is included.
            step = max(1, len(group) // per_hw)
            group = group[::step][:per_hw]
        items.extend(group)
    return items


def cmd_llm(args: argparse.Namespace) -> int:
    from . import batch, llm
    from .catalog import load_all as load_catalog
    from .config import load
    from .rubric import load_all as load_rubrics

    cfg = load()
    rubrics = load_rubrics(cfg)
    catalog = load_catalog(cfg)
    mode = args.mode

    if mode == "student":
        return _cmd_llm_student(args, cfg, rubrics, catalog)

    # Reading every notebook takes a minute; only needed where work is inspected.
    items = (_collect_items(cfg, rubrics, mode, cfg.llm["discovery_per_hw"])
             if args.action in ("estimate", "export", "submit") else [])

    if args.action == "estimate":
        est = llm.estimate(items, cfg)
        model = cfg.llm["model"]
        price = {"claude-sonnet-5": (2.0, 10.0), "claude-opus-5": (5.0, 25.0),
                 "claude-haiku-4-5": (1.0, 5.0)}.get(model, (2.0, 10.0))
        cost = (est["входных токенов"] / 1e6 * price[0]
                + est["выходных токенов"] / 1e6 * price[1])
        for k, v in est.items():
            print(f"{k:20} {v:>10,}".replace(",", " "))
        print(f"{'модель':20} {model:>10}")
        print(f"{'цена без batch':20} {cost:>9.2f}$")
        print(f"{'через Batch API':20} {cost / 2:>9.2f}$  (скидка 50%)")
        return 0

    if args.action == "export":
        # Export for manual review: submission texts and one prompt per topic.
        outdir = llm.input_dir(cfg, mode)
        (outdir / "_prompts").mkdir(exist_ok=True)
        seen_hw = set()
        max_chars = cfg.llm["max_notebook_tokens"] * 3
        from .nbio import to_llm_text
        for it in items:
            if it.hw not in seen_hw:
                (outdir / "_prompts" / f"{it.hw}.md").write_text(
                    llm.system_prompt(rubrics[it.hw], catalog, mode), encoding="utf-8")
                seen_hw.add(it.hw)
            text, cut = to_llm_text(it.notebook, max_chars)
            note = "\n\n(Ноутбук обрезан по длине.)" if cut else ""
            if args.delta and rubrics[it.hw].template_name:
            # For template-based homework only the student's additions are
            # shown: the template is identical for everyone.
                import dataclasses
                from .templates import template_cell_bodies
                tpl = template_cell_bodies(rubrics[it.hw].template_name)
            # A template cell is kept if the student executed it: that is where
            # the metrics and tracebacks used for grading live.
                kept = [
                    c for c in it.notebook.cells
                    if re.sub(r"\s+", "", c.source) not in tpl
                    or (c.is_code and (c.outputs or c.execution_count is not None))
                ]
                if kept:
                    slim = dataclasses.replace(it.notebook, cells=kept)
                    text, cut = to_llm_text(slim, max_chars)
                    note = ("\n\n(Показаны только ячейки, которых нет в раздаточной "
                            f"заготовке: {len(kept)} из {len(it.notebook.cells)}.)")
            (outdir / f"{it.custom_id.replace('|', '__')}.txt").write_text(
                f"Файл: `{it.notebook.rel}`\n\n{text}{note}", encoding="utf-8")
        print(f"выгружено работ: {len(items)}")
        print(f"промптов по темам: {len(seen_hw)}")
        print(f"каталог: {outdir}")
        return 0

    if args.action == "batches":
        # Batching for subagents: one topic per batch, so an agent has one prompt
        # and a single criterion for its whole list.
        import math

        indir = llm.input_dir(cfg, mode)
        outdir = cfg.paths.out / "batches"
        outdir.mkdir(parents=True, exist_ok=True)
        # Only this mode's batches are cleared: student_*.txt live alongside, and
        # rebatching one mode must not pull another mode's lists out from under agents.
        for old in outdir.glob("*.txt"):
            if not old.name.startswith("student_"):
                old.unlink()

        # Already reviewed work is skipped — the pass is resumable.
        done = {f.stem for f in llm.results_dir(cfg, mode).glob("*.json")}
        by_hw: dict[str, list[str]] = {}
        skipped = 0
        for f in sorted(indir.glob("*.txt")):
            if f.stem in done:
                skipped += 1
                continue
            hw = f.stem.rsplit("__", 1)[-1]
            if args.only and hw not in args.only.split(","):
                continue
            by_hw.setdefault(hw, []).append(f.name)
        if skipped:
            print(f"уже разобрано, пропущено: {skipped}")

        made = []
        for hw in sorted(by_hw):
            if not rubrics[hw].graded:
                continue
            files = by_hw[hw]
            n = math.ceil(len(files) / args.per_batch)
            for i in range(n):
                chunk = files[i * args.per_batch:(i + 1) * args.per_batch]
                name = f"{hw}_{i + 1:02d}.txt"
                (outdir / name).write_text("\n".join(chunk) + "\n", encoding="utf-8")
                made.append((name, hw, len(chunk)))
        print(f"пачек: {len(made)}  (по {args.per_batch} работ)")
        for name, hw, k in made:
            print(f"    {name:14} {hw}  работ: {k}")
        print(f"\nкаталог: {outdir}")
        return 0

    if args.action == "verify":
        # What is reviewed, what is left, and whether it all matches the schema.
        import json as _json

        indir = llm.input_dir(cfg, mode)
        done_dir = llm.results_dir(cfg, mode)
        expected = {f.stem for f in indir.glob("*.txt")
                    if rubrics[f.stem.rsplit("__", 1)[-1]].graded}
        done, broken = set(), []
        for f in done_dir.glob("*.json"):
            try:
                payload = _json.loads(f.read_text(encoding="utf-8"))
            except _json.JSONDecodeError as exc:
                broken.append(f"{f.name}: не разбирается ({exc})")
                continue
            missing = [k for k in ("checks", "findings", "strengths", "summary")
                       if k not in payload]
            if missing:
                broken.append(f"{f.name}: нет полей {missing}")
                continue
            hw = f.stem.rsplit("__", 1)[-1]
            allowed = set(llm._codes_for(rubrics[hw], catalog)) | {"other"}
            bad = [
                x.get("code") for x in payload["findings"]
                if llm.normalize_code(x.get("code", ""), hw, catalog) not in allowed
            ]
            if bad:
                broken.append(f"{f.name}: коды вне каталога {sorted(set(bad))[:3]}")
                continue
            done.add(f.stem)
        left = expected - done
        print(f"ожидается: {len(expected)}")
        print(f"готово:    {len(done)}")
        print(f"осталось:  {len(left)}")
        print(f"с ошибками:{len(broken)}")
        for b in broken[:15]:
            print("    ", b)
        if left and args.show_left:
            print("\nне разобраны:")
            for name in sorted(left)[:40]:
                print("    ", name)
        return 0 if not left and not broken else 1

    if args.action == "submit":
        requests = [
            {"custom_id": it.custom_id,
             "params": llm.build_params(it, rubrics[it.hw], catalog, cfg, mode)}
            for it in items
        ]
        print(f"отправляю {len(requests)} запросов, режим {mode}…")
        batch_id = batch.submit(requests, cfg, mode)
        print(f"батч создан: {batch_id}")
        print(f"дальше: uv run mlcheck llm --mode {mode} collect")
        return 0

    if args.action == "collect":
        state = batch.load_state(cfg, mode)
        if not state:
            print(f"нет сохранённого батча для режима {mode}; сначала submit")
            return 1
        bid = state["batch_id"]
        if args.wait:
            print(f"жду завершения {bid}…")
            batch.wait(bid, on_tick=lambda b: print(
                f"   статус {b.processing_status}, в работе {b.request_counts.processing}"))
        out = batch.collect(bid, cfg, mode)
        print("результаты:", out["stats"])
        u = out["usage"]
        print(f"токенов: вход {u['input']}, выход {u['output']}, "
              f"из кэша {u['cache_read']}")
        for e in out["errors"][:20]:
            print("   ", e)
        return 0
    return 1


def cmd_report(args: argparse.Namespace) -> int:
    from . import report
    from .config import load

    from .rubric import load_all as load_rubrics

    cfg = load()
    reports = report.build_all(cfg)
    rubrics = load_rubrics(cfg)
    total = sum(1 for r in rubrics.values() if r.graded)
    ungraded = [r.id for r in rubrics.values() if not r.graded]
    ok = [r for r in reports if r.status == "ok"]
    cert = [r for r in ok if report.certificate(r, total, cfg)]

    print(f"отчётов собрано:  {len(reports)}")
    print(f"проверено:        {len(ok)}")
    print(f"исключено:        {len(reports) - len(ok)}")
    need = report.required_passed(total, cfg)
    print(f"сертификат:       {len(cert)}  (порог {cfg.verdict['certificate_ratio']:.0%} "
          f"= {need} из {total} зачётных домашек)")
    if ungraded:
        print(f"вне зачёта:       {', '.join(ungraded)} — задания не выдавалось")
    print()
    dist: dict[int, int] = {}
    for r in ok:
        dist[r.passed_count] = dist.get(r.passed_count, 0) + 1
    print("распределение по числу засчитанных домашек:")
    for n in sorted(dist, reverse=True):
        print(f"  {n:2} -> {dist[n]:3} {'█' * dist[n]}")
    print()
    print(f"отчёты:  {cfg.paths.reports}")
    print(f"данные:  {cfg.paths.findings}")
    print(f"сводка:  {cfg.paths.out / 'summary.csv'}")
    return 0


def _cmd_llm_student(args: argparse.Namespace, cfg, rubrics, catalog) -> int:
    """Student portrait mode: digests from findings, batches, answer validation."""
    import json as _json
    import math

    from . import llm

    indir = llm.input_dir(cfg, "student")
    done_dir = llm.results_dir(cfg, "student")

    if args.action in ("submit", "collect"):
        print("портреты делаются только субагентами Claude Code — см. AGENT_PROMPT_STUDENT.md")
        return 1

    if args.action == "export":
        (indir / "_prompts").mkdir(exist_ok=True)
        (indir / "_prompts" / "student.md").write_text(
            llm.student_prompt(rubrics, catalog), encoding="utf-8")
        sizes = []
        for f in sorted(cfg.paths.findings.glob("*.json")):
            rep = _json.loads(f.read_text(encoding="utf-8"))
            if rep.get("status") != "ok":
                continue
            if not any(h["status"] != "missing" for h in rep["homeworks"].values()):
                continue                      # no submissions — nothing to write a portrait about
            text = llm.student_digest(rep, rubrics, catalog, cfg)
            (indir / f"{rep['key']}.txt").write_text(text, encoding="utf-8")
            sizes.append(len(text))
        print(f"дайджестов: {len(sizes)}")
        if sizes:
            sizes.sort()
            print(f"символов: медиана {sizes[len(sizes)//2]}, максимум {sizes[-1]} "
                  f"(≈ {sizes[len(sizes)//2]//3} / {sizes[-1]//3} токенов)")
        print(f"промпт: {indir / '_prompts' / 'student.md'}")
        return 0

    if args.action == "estimate":
        files = list(indir.glob("*.txt"))
        total = sum(len(f.read_text(encoding="utf-8")) for f in files) // 3
        prompt = len((indir / "_prompts" / "student.md").read_text(encoding="utf-8")) // 3
        n_batches = math.ceil(len(files) / args.per_batch) if files else 0
        print(f"{'студентов':20} {len(files):>10}")
        print(f"{'входных токенов':20} {total + prompt * n_batches:>10,}".replace(",", " "))
        print(f"{'выходных токенов':20} {len(files) * 700:>10,}".replace(",", " "))
        return 0

    if args.action == "batches":
        outdir = cfg.paths.out / "batches"
        outdir.mkdir(parents=True, exist_ok=True)
        for old in outdir.glob("student_*.txt"):
            old.unlink()
        done = {f.stem for f in done_dir.glob("*.json")}
        todo = sorted(f.name for f in indir.glob("*.txt") if f.stem not in done)
        if len(done):
            print(f"уже готово, пропущено: {len(done)}")
        n = math.ceil(len(todo) / args.per_batch) if todo else 0
        for i in range(n):
            chunk = todo[i * args.per_batch:(i + 1) * args.per_batch]
            (outdir / f"student_{i + 1:02d}.txt").write_text("\n".join(chunk) + "\n", encoding="utf-8")
            print(f"    student_{i + 1:02d}.txt  студентов: {len(chunk)}")
        print(f"пачек: {n}  (по {args.per_batch} студентов)")
        return 0

    if args.action == "verify":
        allowed = llm.allowed_urls(catalog)
        expected = {f.stem for f in indir.glob("*.txt")}
        done, broken = set(), []
        for f in done_dir.glob("*.json"):
            try:
                payload = _json.loads(f.read_text(encoding="utf-8"))
            except _json.JSONDecodeError as exc:
                broken.append(f"{f.name}: не разбирается ({exc})")
                continue
            errors = llm.validate_student(payload, rubrics, catalog, allowed)
            if errors:
                broken.append(f"{f.name}: {'; '.join(errors[:3])}")
                continue
            done.add(f.stem)
        left = expected - done
        print(f"ожидается: {len(expected)}")
        print(f"готово:    {len(done)}")
        print(f"осталось:  {len(left)}")
        print(f"с ошибками:{len(broken)}")
        for b in broken[:15]:
            print("    ", b)
        if left and args.show_left:
            for name in sorted(left)[:40]:
                print("    ", name)
        return 0
    return 1


def cmd_diff(args: argparse.Namespace) -> int:
    from pathlib import Path

    from . import diff
    from .config import load

    cfg = load()
    before = Path(args.before).resolve()
    after = Path(args.after).resolve() if args.after else cfg.paths.findings
    d = diff.compare(before, after)
    text = diff.render(d, before.name, after.name)
    out = cfg.paths.out / "rerun_diff.md"
    out.write_text(text, encoding="utf-8")
    print(f"студентов: {d.students}")
    print(f"сертификатов: {d.cert_before} → {d.cert_after} "
          f"(+{len(d.cert_gained)} / −{len(d.cert_lost)})")
    print(f"переворотов вердиктов: {len(d.flips)}, из них зачтено→не зачтено: "
          f"{sum(1 for f in d.flips if f.before == 'passed')}")
    print(f"отчёт: {out}")
    return 0


def cmd_awards(args: argparse.Namespace) -> int:
    from pathlib import Path

    from . import awards as aw
    from .config import load

    cfg = load()
    src = Path(args.dir)
    if not src.is_absolute():
        src = (cfg.paths.out.parent / src).resolve()
    items, problems = aw.build(src, cfg)
    path = aw.save(items, cfg)

    with_cert = sum(1 for a in items if a.certificate)
    with_photo = sum(1 for a in items if a.photo)
    print(f"прошедших курс: {len(items)}")
    print(f"с сертификатом: {with_cert}")
    print(f"с фотографией:  {with_photo}")
    notes = [a for a in items if a.note]
    if notes:
        print("\nсопоставлено не дословно:")
        for a in notes:
            print(f"    {a.fio}: {a.note}")
    if problems:
        print(f"\nтребует внимания: {len(problems)}")
        for p in problems[:20]:
            print("    ", p)
    print(f"\nреестр: {path}")
    return 0 if with_cert == len(items) else 1


def cmd_telegram(args: argparse.Namespace) -> int:
    from collections import Counter

    from . import telegram
    from .config import load

    cfg = load()
    path = cfg.paths.out / "telegram_map.csv"

    if args.action == "verify":
        links = telegram.read_map(path)
        if not links:
            print("сначала: mlcheck telegram match")
            return 1
        print(f"проверяю {sum(1 for l in links if l.username)} username через t.me…")
        telegram.verify(links)
    else:
        links = telegram.build(cfg)

    telegram.save(links, path)

    kinds = Counter(lk.match for lk in links)
    print(f"студентов в форме сдачи: {len(links)}")
    for kind, label in (("exact", "точное ФИО"), ("diminutive", "уменьшительное имя"),
                        ("surname", "по фамилии"), ("none", "нет в регистрации")):
        if kinds[kind]:
            print(f"  {label:22} {kinds[kind]:3}")
    named = [lk for lk in links if lk.username]
    print(f"\nusername найден:          {len(named)}")
    if args.action == "verify":
        states = Counter(lk.exists for lk in named)
        for state, label in (("yes", "существует"), ("no", "не существует"),
                             ("unknown", "проверить не удалось")):
            if states[state]:
                print(f"  {label:22} {states[state]:3}")
        dead = [lk for lk in named if lk.exists == "no"]
        if dead:
            print("\nне существуют — привязка только вручную, "
                  "первый подтвердивший ФИО и ссылку станет владельцем:")
            for lk in dead:
                print(f"  @{lk.username:20} {lk.fio}")
    print(f"\nузнавать по username можно: {sum(1 for lk in links if lk.usable)}")
    print(f"таблица: {path}")
    return 0


def cmd_export_season(args) -> int:
    """Build the season materials branch. Rebuilding is safe and idempotent."""
    from pathlib import Path

    from . import export_season
    from .config import load

    cfg = load()
    out = Path(args.out)
    if not out.is_absolute():
        out = (Path.cwd() / out).resolve()
    report = export_season.build(cfg, out)

    print(f"Собрано в {out}")
    print(f"  занятий: {len(export_season.LESSONS)}")
    print(f"  домашек: {len(report.homeworks)}")
    print(f"  разборов типовых ошибок: {report.articles}")
    print(f"  файлов скопировано: {len(report.copied)}")
    for name, same_as in report.skipped_dupes:
        print(f"  дубликат пропущен: {name} == {same_as}")
    for name, why in report.withheld:
        print(f"  ⛔ не выложено: {name} — {why}")
    for item in report.leftovers:
        print(f"  ⚠️  без места в программе: {item}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mlcheck", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("roster", help="разобрать форму и проверить доступность репозиториев")
    p.set_defaults(func=cmd_roster)

    p = sub.add_parser("fetch", help="выкачать репозитории участников")
    p.add_argument("--force", action="store_true", help="перекачать даже то, что уже в кэше")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("classify", help="определить тему каждого ноутбука по содержимому")
    p.set_defaults(func=cmd_classify)

    p = sub.add_parser("similarity", help="поиск заимствований по дельте поверх эталона")
    p.set_defaults(func=cmd_similarity)

    p = sub.add_parser("llm", help="смысловая рецензия работ моделью через Batch API")
    p.add_argument("action",
                   choices=["estimate", "submit", "collect", "export", "batches", "verify"])
    p.add_argument("--mode", choices=["grading", "discovery", "student"], default="grading")
    p.add_argument("--wait", action="store_true", help="дождаться завершения батча")
    p.add_argument("--per-batch", type=int, default=20,
                   help="сколько работ в одной пачке для субагента")
    p.add_argument("--show-left", action="store_true", help="перечислить неразобранные")
    p.add_argument("--only", help="только эти темы через запятую, например hw02,hw03")
    p.add_argument("--delta", action="store_true",
                   help="для домашек на заготовке выгружать только дописанное студентом")
    p.set_defaults(func=cmd_llm)

    p = sub.add_parser("telegram", help="сшить форму регистрации с формой сдачи по ФИО")
    p.add_argument("action", nargs="?", choices=["match", "verify"], default="match",
                   help="match — сопоставить ФИО, verify — проверить username через t.me")
    p.set_defaults(func=cmd_telegram)

    p = sub.add_parser("awards", help="сопоставить сертификаты и фото с вручения со студентами")
    p.add_argument("--dir", default="certificates_2nd_season",
                   help="каталог с подпапками pdf/ и photos/")
    p.set_defaults(func=cmd_awards)

    p = sub.add_parser("diff", help="сравнить две сборки findings: сертификаты и перевороты вердиктов")
    p.add_argument("before", help="каталог старой сборки, например out/findings_v1")
    p.add_argument("after", nargs="?", help="каталог новой сборки (по умолчанию out/findings)")
    p.set_defaults(func=cmd_diff)

    p = sub.add_parser("report", help="собрать вердикт, отчёты и сводную таблицу")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("export-season",
                       help="собрать репозиторий материалов сезона для публикации")
    p.add_argument("--out", default="../season2_repo", help="куда складывать ветку")
    p.set_defaults(func=cmd_export_season)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
