"""
tracing.py — Lightweight "Vibe Trajectory" tracer (Day 5: Spec-Driven Production Grade Dev).

This is intentionally NOT a full OpenTelemetry integration (no collector, no exporter
config) — that's out of scope for a Kaggle capstone demo. But it follows the same
*shape* the course describes so it's a one-line swap to real OTel later:

    agent.session  -> the whole turn (one user message -> one final answer)
    agent.think    -> an LLM call (orchestrator classification, first/second Gemini call)
    agent.tool     -> a tool execution (get_support_resources, forced safety lookup)

Each span is a dict with: name, session_id, attributes, start_ts, duration_ms, status,
error (if any). Spans are written as one JSON object per line to TRACE_LOG_PATH, so the
file can be tailed, grepped, or loaded into pandas/jq without any extra dependency.

Why this matters for an agentic system (per the course): an HTTP 200-style "it ran without
crashing" signal can hide a quietly-looping or hallucinating agent. Spans give a
chronological, inspectable trail to answer "why did the agent do that?" — which tool fired,
how long the model took to think, whether the safety backstop kicked in — without re-reading
the whole chat transcript by eye.
"""

import os
import json
import time
import logging
import contextlib
import threading

TRACE_LOG_PATH = os.environ.get("BULLYSTOP_TRACE_LOG", "traces.jsonl")

_lock = threading.Lock()


def _write_span(span: dict) -> None:
    """Appends one span as a JSON line. Best-effort: tracing must never crash the app."""
    try:
        with _lock:
            with open(TRACE_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(span, ensure_ascii=False) + "\n")
    except Exception as e:  # pragma: no cover — tracing failures are non-fatal by design
        logging.warning(f"[TRACE] failed to persist span: {e}")


@contextlib.contextmanager
def span(name: str, session_id: str = "?", **attributes):
    """
    Context manager for a single span. Usage:

        with span("agent.tool", session_id=sid, tool="get_support_resources", country="ar"):
            result = do_the_thing()

    Extra attributes can be attached after the fact via `set_attr` on the yielded handle,
    which is useful when you only know e.g. token counts or a tool's result *after* running
    it (e.g. `s.set_attr(result_size=len(result))`).
    """
    start = time.time()
    record = {
        "name": name,
        "session_id": session_id,
        "attributes": dict(attributes),
        "start_ts": start,
        "status": "ok",
        "error": None,
    }

    class _Handle:
        def set_attr(self, **kw):
            record["attributes"].update(kw)

    handle = _Handle()
    try:
        yield handle
    except Exception as e:
        record["status"] = "error"
        record["error"] = str(e)
        raise
    finally:
        record["duration_ms"] = int((time.time() - start) * 1000)
        # Human-readable line in the normal app log (cheap, always visible during dev)...
        logging.info(
            f"[TRACE] {name} session={session_id} status={record['status']} "
            f"latency_ms={record['duration_ms']} attrs={record['attributes']}"
        )
        # ...plus the structured JSONL line for later analysis/eval/cost tracking.
        _write_span(record)


def load_spans(path: str = None) -> list:
    """Reads back all spans from the trace log (used by evals / debugging / a future dashboard)."""
    path = path or TRACE_LOG_PATH
    spans = []
    if not os.path.exists(path):
        return spans
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                spans.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return spans


def session_cost_summary(session_id: str, path: str = None) -> dict:
    """
    Aggregates a session's spans into a tiny cost/latency summary — the kind of rollup the
    course calls out under "Tracking Costs" (token consumption, latency, self-repair loops).
    We don't have real token counts without wiring usage_metadata through every call site, so
    this currently reports call counts and total latency per span name — still enough to spot
    a session that's looping or unusually slow.
    """
    spans = [s for s in load_spans(path) if s.get("session_id") == session_id]
    summary = {}
    for s in spans:
        name = s["name"]
        bucket = summary.setdefault(name, {"count": 0, "total_ms": 0, "errors": 0})
        bucket["count"] += 1
        bucket["total_ms"] += s.get("duration_ms", 0)
        if s.get("status") == "error":
            bucket["errors"] += 1
    return summary