"""Shared helpers for macOS recording release evidence generation."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Sequence, TypeAlias, cast

REPO_ROOT = Path(__file__).resolve().parents[1]
JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]

_SECRET_PATTERNS = (
    # Saved credentials may predate the current product prefix.
    re.compile(r"\b[a-z][a-z0-9]*_(?:native_|provider_)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]+", re.IGNORECASE),
    re.compile(r"storage_uri['\"]?\s*[:=]\s*['\"][^'\"]+['\"]", re.IGNORECASE),
    re.compile(r"/var/folders/[^\s'\",)]+"),
    re.compile(r"/usr/local/\.OCular/[^\s'\",)]+"),
)
_URI_KEY_PATTERN = re.compile(r"(?:^|_)(?:uri|url|path|file|storage)(?:$|_)", re.IGNORECASE)
_RAW_DIAGNOSTIC_KEY_PATTERN = re.compile(r"(?:^|_)(?:stdout|stderr|html|raw|raw_text|fixture)(?:$|_)", re.IGNORECASE)
_RAW_DIAGNOSTIC_VALUE_PATTERN = re.compile(
    r"(?:<\s*(?:html|body|form|input|script)\b|SHOULD_NOT_LEAK_|type=[\"']?password|password)",
    re.IGNORECASE,
)
_SENSITIVE_URI_SCHEMES = (
    "file://",
    "local-artifact://",
    "vault://",
    "s3://",
    "gs://",
)


def _redact_text(text: str) -> str:
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    redacted = redacted.replace(str(REPO_ROOT), "[REPO_ROOT]")
    redacted = redacted.replace(str(Path.home()), "[LOCAL_HOME]")
    home_name = Path.home().name
    if home_name:
        redacted = re.sub(rf"\b{re.escape(home_name)}\b", "[LOCAL_USER]", redacted)
    return redacted


def _sanitize_json(value: JsonValue, *, key: str | None = None) -> JsonValue:
    if isinstance(value, str):
        return _sanitize_string_value(value, key=key)
    if isinstance(value, list):
        return [_sanitize_json(item, key=key) for item in value]
    if isinstance(value, dict):
        return {item_key: _sanitize_json(item, key=item_key) for item_key, item in value.items()}
    return value


def _sanitize_string_value(value: str, *, key: str | None) -> str:
    if key and _URI_KEY_PATTERN.search(key):
        if value.startswith(_SENSITIVE_URI_SCHEMES) or value.startswith("/") or str(Path.home()) in value:
            return "[REDACTED_URI]"
    if key and _RAW_DIAGNOSTIC_KEY_PATTERN.search(key) and _RAW_DIAGNOSTIC_VALUE_PATTERN.search(value):
        return "[REDACTED_DIAGNOSTIC_TEXT]"
    return _redact_text(value)


def _redact_file(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    if path.suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            pass
        else:
            path.write_text(
                json.dumps(_sanitize_json(cast(JsonValue, payload)), ensure_ascii=False, indent=2, sort_keys=True)
                + "\n",
                encoding="utf-8",
            )
            return
    path.write_text(_redact_text(text), encoding="utf-8")


def _redact_release_artifacts(output_dir: Path) -> None:
    for path in output_dir.rglob("*"):
        if path.suffix not in {".json", ".log", ".md"}:
            continue
        _redact_file(path)


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return _redact_text(str(path))


def _display_command(command: Sequence[str]) -> str:
    return " ".join(_display_command_arg(arg) for arg in command)


def _display_command_arg(arg: str) -> str:
    if arg == sys.executable:
        return "python"
    return _display_path(Path(arg)) if "/" in arg else _redact_text(arg)


def _dedupe_strings(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _write_json(path: Path, payload: JsonValue) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sanitized = _sanitize_json(payload)
    path.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
