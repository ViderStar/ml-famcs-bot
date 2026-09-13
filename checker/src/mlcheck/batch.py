"""Submitting to, waiting on and parsing the Batch API.

Batch gives half price and up to 24 hours to run — ideal for grading a course:
there is no hurry and there are more than a thousand submissions.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from .config import Config


def client():
    import anthropic

    return anthropic.Anthropic()


def submit(requests: list[dict], cfg: Config, mode: str) -> str:
    """requests: [{custom_id, params}]. Returns the batch id."""
    from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
    from anthropic.types.messages.batch_create_params import Request

    batch = client().messages.batches.create(
        requests=[
            Request(custom_id=r["custom_id"],
                    params=MessageCreateParamsNonStreaming(**r["params"]))
            for r in requests
        ]
    )
    state_path(cfg, mode).write_text(
        json.dumps({"batch_id": batch.id, "mode": mode, "count": len(requests)},
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    return batch.id


def state_path(cfg: Config, mode: str) -> Path:
    return cfg.paths.out / f"batch_{mode}.json"


def load_state(cfg: Config, mode: str) -> dict | None:
    p = state_path(cfg, mode)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def wait(batch_id: str, poll_sec: int = 60, on_tick=None) -> None:
    cl = client()
    while True:
        b = cl.messages.batches.retrieve(batch_id)
        if b.processing_status == "ended":
            return
        if on_tick:
            on_tick(b)
        time.sleep(poll_sec)


def collect(batch_id: str, cfg: Config, mode: str) -> dict:
    """Downloads the results. Returns statistics and writes the answers to disk."""
    from . import llm

    cl = client()
    stats = {"succeeded": 0, "errored": 0, "canceled": 0, "expired": 0, "unparsed": 0}
    errors: list[str] = []
    usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}

    for res in cl.messages.batches.results(batch_id):
        kind = res.result.type
        if kind != "succeeded":
            stats[kind] = stats.get(kind, 0) + 1
            errors.append(f"{res.custom_id}: {kind}")
            continue
        msg = res.result.message
        u = msg.usage
        usage["input"] += u.input_tokens
        usage["output"] += u.output_tokens
        usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        usage["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        text = next((b.text for b in msg.content if b.type == "text"), "")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            stats["unparsed"] += 1
            errors.append(f"{res.custom_id}: ответ не разобрался как JSON")
            continue
        stats["succeeded"] += 1
        llm.save_result(cfg, mode, res.custom_id, payload)

    return {"stats": stats, "usage": usage, "errors": errors}
