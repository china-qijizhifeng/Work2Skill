"""Data loading helpers for the skill extraction Streamlit dashboard."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import cast


@dataclass(frozen=True)
class RunData:
    path: Path
    summary: dict[str, object]
    events: list[dict[str, object]]
    artifacts: list[Path]


def _json_object(path: Path) -> dict[str, object]:
    loaded: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return {str(key): value for key, value in cast(dict[object, object], loaded).items()}


def discover_runs(root: Path) -> list[Path]:
    """Return run directories containing a summary, newest first."""
    resolved = root.expanduser().resolve(strict=False)
    if not resolved.is_dir():
        return []
    runs = {summary.parent for summary in resolved.rglob("run-summary.json") if summary.is_file()}
    return sorted(runs, key=lambda path: (path.stat().st_mtime_ns, str(path)), reverse=True)


def load_events(path: Path) -> list[dict[str, object]]:
    """Load JSONL events and preserve malformed lines as visible errors."""
    events: list[dict[str, object]] = []
    if not path.is_file():
        return events
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            loaded: object = json.loads(line)
        except json.JSONDecodeError as exc:
            events.append({"type": "LOG_PARSE_ERROR", "line_number": line_number, "error": str(exc), "raw": line[:1000]})
            continue
        if isinstance(loaded, dict):
            event = {str(key): value for key, value in cast(dict[object, object], loaded).items()}
            event["line_number"] = line_number
            events.append(event)
    return events


def load_run(path: Path) -> RunData:
    """Load one run summary, event stream, and generated text artifacts."""
    resolved = path.expanduser().resolve(strict=True)
    summary = _json_object(resolved / "run-summary.json")
    events_file = summary.get("events_file")
    events_path = resolved / events_file if isinstance(events_file, str) else resolved / "run-events.jsonl"
    excluded = {events_path.resolve(strict=False), (resolved / "run-summary.json").resolve(strict=False)}
    artifacts = sorted(
        candidate
        for candidate in resolved.rglob("*")
        if candidate.is_file()
        and candidate.resolve(strict=False) not in excluded
        and candidate.suffix.lower() in {".json", ".jsonl", ".md", ".txt", ".yaml", ".yml"}
    )
    return RunData(path=resolved, summary=summary, events=load_events(events_path), artifacts=artifacts)


def token_rows(summary: dict[str, object]) -> list[dict[str, int]]:
    """Normalize per-model-call token usage for tables and charts."""
    raw_rows = summary.get("token_usage_by_model_call")
    if not isinstance(raw_rows, list):
        return []
    rows: list[dict[str, int]] = []
    for call_number, raw_row in enumerate(cast(list[object], raw_rows), start=1):
        if not isinstance(raw_row, dict):
            continue
        mapping = cast(dict[object, object], raw_row)
        row = {"call": call_number}
        for key in (
            "input_tokens",
            "completion_tokens",
            "reasoning_tokens",
            "cache_creation_tokens",
            "cache_read_tokens",
            "total_tokens",
        ):
            value = mapping.get(key, 0)
            row[key] = value if isinstance(value, int) else 0
        rows.append(row)
    return rows


def tool_rows(summary: dict[str, object]) -> list[dict[str, object]]:
    """Normalize tool calls and derive execution duration."""
    raw_calls = summary.get("tool_calls")
    if not isinstance(raw_calls, list):
        return []
    rows: list[dict[str, object]] = []
    for index, raw_call in enumerate(cast(list[object], raw_calls), start=1):
        if not isinstance(raw_call, dict):
            continue
        call = {str(key): value for key, value in cast(dict[object, object], raw_call).items()}
        started = call.get("started_at_ms")
        result_at = call.get("result_at_ms")
        duration_ms = result_at - started if isinstance(started, int) and isinstance(result_at, int) else None
        rows.append(
            {
                "index": index,
                "name": call.get("name", "unknown"),
                "status": call.get("status", "unknown"),
                "duration_ms": duration_ms,
                "arguments": call.get("arguments"),
                "result_preview": call.get("result_preview"),
                "tool_call_id": call.get("tool_call_id"),
            }
        )
    return rows


def event_rows(events: list[dict[str, object]]) -> list[dict[str, object]]:
    """Add relative time and compact event details for display."""
    timestamps = [event.get("timestamp") for event in events]
    integer_timestamps = [value for value in timestamps if isinstance(value, int)]
    start_ms = min(integer_timestamps) if integer_timestamps else 0
    rows: list[dict[str, object]] = []
    for event in events:
        timestamp = event.get("timestamp")
        elapsed_s = round((timestamp - start_ms) / 1000, 3) if isinstance(timestamp, int) else None
        detail = event.get("tool_call_name") or event.get("stop_reason") or event.get("message") or event.get("delta") or ""
        if not isinstance(detail, str):
            detail = json.dumps(detail, ensure_ascii=False)
        rows.append(
            {
                "line": event.get("line_number"),
                "elapsed_s": elapsed_s,
                "type": event.get("type", "UNKNOWN"),
                "detail": detail[:300],
            }
        )
    return rows
