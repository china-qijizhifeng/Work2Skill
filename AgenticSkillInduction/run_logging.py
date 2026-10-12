"""Durable event and usage logging for skill extraction runs."""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from ag_ui.core.events import (  # pyright: ignore[reportMissingTypeStubs]
    RunFinishedEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)

from nexau.archs.llm.llm_aggregators.events import (
    Event,
    ModelCallFinishedEvent,
    RunErrorEvent,
    RunStartedEvent,
    ThinkingTextMessageContentEvent,
    ThinkingTextMessageEndEvent,
    ThinkingTextMessageStartEvent,
    ToolCallResultEvent,
    UsageUpdateEvent,
)
from nexau.core.usage import TokenUsage

_DATA_URL_PATTERN = re.compile(r"data:([\w.+-]+/[\w.+-]+);base64,[A-Za-z0-9+/=\r\n]+")
_MAX_LOG_STRING = 50_000
_MAX_RESULT_PREVIEW = 2_000


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso_time(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _sanitize_string(value: str, limit: int = _MAX_LOG_STRING) -> str:
    sanitized = _DATA_URL_PATTERN.sub(lambda match: f"data:{match.group(1)};base64,[omitted]", value)
    if len(sanitized) > limit:
        return sanitized[:limit] + f"... [truncated {len(sanitized) - limit} chars]"
    return sanitized


def _sanitize(value: object) -> object:
    if isinstance(value, str):
        return _sanitize_string(value)
    if isinstance(value, dict):
        mapping = cast(dict[object, object], value)
        return {str(key): _sanitize(item) for key, item in mapping.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in cast(list[object], value)]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in cast(tuple[object, ...], value)]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)


def _parse_json_object(value: str) -> dict[str, object] | None:
    try:
        loaded: object = json.loads(value)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    return {str(key): item for key, item in cast(dict[object, object], loaded).items()}


@dataclass
class ToolCallRecord:
    tool_call_id: str
    name: str
    started_at_ms: int | None
    arguments_fragments: list[str] = field(default_factory=lambda: [])
    ended_at_ms: int | None = None
    result_at_ms: int | None = None
    status: str = "started"
    result_preview: str | None = None

    def to_dict(self) -> dict[str, object]:
        raw_arguments = "".join(self.arguments_fragments)
        parsed_arguments = _parse_json_object(raw_arguments)
        arguments: object = parsed_arguments if parsed_arguments is not None else _sanitize_string(raw_arguments)
        return {
            "tool_call_id": self.tool_call_id,
            "name": self.name,
            "arguments": _sanitize(arguments),
            "started_at_ms": self.started_at_ms,
            "ended_at_ms": self.ended_at_ms,
            "result_at_ms": self.result_at_ms,
            "status": self.status,
            "result_preview": self.result_preview,
        }


@dataclass
class ReasoningSummaryRecord:
    thinking_message_id: str
    parent_message_id: str
    started_at_ms: int
    fragments: list[str] = field(default_factory=lambda: [])
    ended_at_ms: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "thinking_message_id": self.thinking_message_id,
            "parent_message_id": self.parent_message_id,
            "summary": _sanitize_string("".join(self.fragments)),
            "started_at_ms": self.started_at_ms,
            "ended_at_ms": self.ended_at_ms,
        }


class ExtractionRunLogger:
    """Write normalized NexAU events and an aggregate run summary."""

    def __init__(
        self,
        output_root: Path,
        *,
        input_root: Path,
        model: str,
        provenance: dict[str, object] | None = None,
    ):
        self.output_root = output_root.resolve(strict=False)
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.events_path = self.output_root / "run-events.jsonl"
        self.summary_path = self.output_root / "run-summary.json"
        self.input_root = input_root.resolve(strict=False)
        self.model = model
        self.provenance = dict(provenance or {})
        self.started_at = _utc_now()
        self.finished_at: datetime | None = None
        self.event_count = 0
        self.model_call_count = 0
        self.total_usage = TokenUsage()
        self.usage_by_call: list[dict[str, int]] = []
        self.tool_calls: dict[str, ToolCallRecord] = {}
        self.reasoning_summaries: dict[str, ReasoningSummaryRecord] = {}
        self.run_id: str | None = None
        self.trace_id: str | None = None
        self.event_status = "running"
        self._lock = threading.Lock()
        self.events_path.write_text("", encoding="utf-8")

    def on_event(self, event: Event) -> None:
        """Persist one event and update aggregate counters."""
        with self._lock:
            payload = cast(dict[str, object], event.model_dump(mode="json", by_alias=False, exclude={"raw_event"}))
            sanitized = cast(dict[str, object], _sanitize(payload))
            with self.events_path.open("a", encoding="utf-8") as event_file:
                event_file.write(json.dumps(sanitized, ensure_ascii=False) + "\n")
            self.event_count += 1

            if isinstance(event, RunStartedEvent):
                self.run_id = event.run_id
                self.trace_id = event.trace_id
            elif isinstance(event, ToolCallStartEvent):
                self.tool_calls[event.tool_call_id] = ToolCallRecord(
                    tool_call_id=event.tool_call_id,
                    name=event.tool_call_name,
                    started_at_ms=event.timestamp,
                )
            elif isinstance(event, ToolCallArgsEvent):
                record = self.tool_calls.get(event.tool_call_id)
                if record is not None:
                    record.arguments_fragments.append(event.delta)
            elif isinstance(event, ToolCallEndEvent):
                record = self.tool_calls.get(event.tool_call_id)
                if record is not None:
                    record.ended_at_ms = event.timestamp
                    record.status = "arguments_complete"
            elif isinstance(event, ToolCallResultEvent):
                record = self.tool_calls.get(event.tool_call_id)
                if record is not None:
                    record.result_at_ms = event.timestamp
                    parsed_result = _parse_json_object(event.content)
                    record.status = "error" if parsed_result is not None and "error" in parsed_result else "completed"
                    record.result_preview = _sanitize_string(event.content, _MAX_RESULT_PREVIEW)
            elif isinstance(event, ThinkingTextMessageStartEvent):
                self.reasoning_summaries[event.thinking_message_id] = ReasoningSummaryRecord(
                    thinking_message_id=event.thinking_message_id,
                    parent_message_id=event.parent_message_id,
                    started_at_ms=event.timestamp,
                )
            elif isinstance(event, ThinkingTextMessageContentEvent):
                record = self.reasoning_summaries.get(event.thinking_message_id)
                if record is not None:
                    record.fragments.append(event.delta)
            elif isinstance(event, ThinkingTextMessageEndEvent):
                record = self.reasoning_summaries.get(event.thinking_message_id)
                if record is not None:
                    record.ended_at_ms = event.timestamp
            elif isinstance(event, UsageUpdateEvent):
                usage = event.usage
                self.total_usage = self.total_usage + usage
                self.usage_by_call.append(usage.to_dict())
            elif isinstance(event, ModelCallFinishedEvent):
                self.model_call_count += 1
            elif isinstance(event, RunErrorEvent):
                self.event_status = "error"
            elif isinstance(event, RunFinishedEvent):
                self.event_status = "completed"

    def finish(
        self,
        status: str | None = None,
        error: str | None = None,
        *,
        finalized: bool = False,
        trajectory_capture: dict[str, object] | None = None,
    ) -> dict[str, object]:
        """Write the final summary. Safe to call after success or failure."""
        with self._lock:
            self.finished_at = _utc_now()
            final_status = status or self.event_status
            duration_ms = int((self.finished_at - self.started_at).total_seconds() * 1000)
            tool_records = [record.to_dict() for record in self.tool_calls.values()]
            reasoning_records = [record.to_dict() for record in self.reasoning_summaries.values()]
            tool_counts: dict[str, int] = {}
            for record in self.tool_calls.values():
                tool_counts[record.name] = tool_counts.get(record.name, 0) + 1
            summary: dict[str, object] = {
                "status": final_status,
                "finalized": finalized,
                "error": error,
                "started_at": _iso_time(self.started_at),
                "finished_at": _iso_time(self.finished_at),
                "duration_ms": duration_ms,
                "input_root": str(self.input_root),
                "output_root": str(self.output_root),
                "model": self.model,
                "provenance": self.provenance,
                "run_metadata_file": "run-metadata.json" if self.provenance else None,
                "run_id": self.run_id,
                "trace_id": self.trace_id,
                "event_count": self.event_count,
                "model_call_count": self.model_call_count,
                "tool_call_count": len(tool_records),
                "tool_counts": tool_counts,
                "tool_calls": tool_records,
                "reasoning_item_count": len(reasoning_records),
                "reasoning_summary_count": sum(bool(record["summary"]) for record in reasoning_records),
                "reasoning_summaries": reasoning_records,
                "token_usage": self.total_usage.to_dict(),
                "token_usage_by_model_call": self.usage_by_call,
                "events_file": self.events_path.name,
                "trajectory_capture": trajectory_capture,
            }
            self.summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            return summary
