"""Safe metadata views for public daemon, share, and replay responses."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import cast
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel

STORAGE_URI_KEYS = {
    "storage_uri",
    "inline_content",
    "bundle_url",
    "bundle_path",
    "local_path",
    "storage_path",
    "vault_path",
    "raw_path",
}
URL_KEYS = {"origin", "source_uri", "target_url", "url", "sanitized_url"}
SHARE_URL_KEYS = {"external_url", "provider_url", "copyable_url", "copied_link"}
SECRET_ADJACENT_KEYS = {
    "access_token",
    "api_key",
    "auth_token",
    "authorization",
    "app_secret",
    "bearer_token",
    "client_secret",
    "csrf_token",
    "cookie",
    "install_secret",
    "native_capture_secret",
    "password",
    "provider_registration_secret",
    "refresh_token",
    "secret",
    "session_cookie",
    "tenant_access_token",
    "token",
    "token_hash",
}
PUBLIC_IDENTITY_KEYS = {
    "actual_process_id",
    "actual_window_id",
    "display_id",
    "external_id",
    "frame",
    "local_path",
    "native_window_id",
    "process_id",
    "provider_context_id",
    "provider_session_id",
    "screen_rect",
    "window_id",
}
OS_WINDOW_EVENT_TYPES = {"screen.window.captured"}
OS_WINDOW_STRATEGIES = {"os_window"}
OS_WINDOW_PRIVATE_KEYS = PUBLIC_IDENTITY_KEYS | {
    "bundle_id",
    "detected_surfaces",
    "matched_region",
    "os_window_bundle_id",
    "os_window_display_id",
    "os_window_frame_height",
    "os_window_frame_space",
    "os_window_frame_width",
    "os_window_frame_x",
    "os_window_frame_y",
    "os_window_process_id",
    "os_window_window_id",
    "pixel_region",
    "primary_bundle_id",
    "primary_process_id",
    "primary_window_id",
    "command_id",
    "source_binding_id",
    "binding_id",
    "provider_routes",
    "provider_outcomes",
    "source_bindings",
    "selection",
    "selected_region",
    "selection_height",
    "selection_width",
    "selection_x",
    "selection_y",
    "selection_geometry",
    "target_provider_session_id",
    "target_tab_id",
    "target_window_id",
    "window",
    "viewport",
}


def _normalize_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


NORMALIZED_STORAGE_URI_KEYS = {_normalize_key(key) for key in STORAGE_URI_KEYS}
NORMALIZED_URL_KEYS = {_normalize_key(key) for key in URL_KEYS}
NORMALIZED_SHARE_URL_KEYS = {_normalize_key(key) for key in SHARE_URL_KEYS}
NORMALIZED_SECRET_ADJACENT_KEYS = {_normalize_key(key) for key in SECRET_ADJACENT_KEYS}
NORMALIZED_PUBLIC_IDENTITY_KEYS = {_normalize_key(key) for key in PUBLIC_IDENTITY_KEYS}
NORMALIZED_OS_WINDOW_PRIVATE_KEYS = {_normalize_key(key) for key in OS_WINDOW_PRIVATE_KEYS}
NORMALIZED_PRIVATE_KEY_PREFIXES = (
    NORMALIZED_STORAGE_URI_KEYS | NORMALIZED_SECRET_ADJACENT_KEYS | NORMALIZED_PUBLIC_IDENTITY_KEYS
)
SENSITIVE_URI_RE = re.compile(r"\b(?:file|local-artifact|vault)://\S+")
HTTP_URI_RE = re.compile(r"\bhttps?://[^\s,;)}]+", re.IGNORECASE)
LOCAL_PATH_RE = re.compile(r"(?<![\w/])(?:/users|/private|/tmp|/var/folders)/\S+", re.IGNORECASE)
AUTHORIZATION_BEARER_VALUE_RE = re.compile(r"(?i)\bauthorization\s*[:=]\s*bearer\s+[^\s,;)}\]]+")
BARE_BEARER_VALUE_RE = re.compile(r"(?i)\bbearer\s+[^\s,;)}\]]+")
SECRET_VALUE_RE = re.compile(
    r"(?i)\b(?:"
    r"access[_\-\s]?token|"
    r"api[_\-\s]?key|"
    r"app[_\-\s]?secret|"
    r"auth[_\-\s]?token|"
    r"bearer[_\-\s]?token|"
    r"client[_\-\s]?secret|"
    r"csrf[_\-\s]?token|"
    r"install[_\-\s]?secret|"
    r"native[_\-\s]?capture[_\-\s]?secret|"
    r"password|"
    r"provider[_\-\s]?registration[_\-\s]?secret|"
    r"refresh[_\-\s]?token|"
    r"secret|"
    r"tenant[_\-\s]?access[_\-\s]?token|"
    r"token"
    r")\s*[:=]\s*(?!redacted\b)[^\s,;)}\]]+"
)


def safe_public_payload(value: object, *, _os_window_context: bool = False) -> object:
    """Return a JSON-like object with raw handles and local identity removed.

    Args:
        value: Contract model or JSON-like payload that may contain internal
            identity, local path, raw artifact, or token-adjacent values.
        _os_window_context: Whether OS-window-specific private fields should be
            stripped even if the payload does not self-identify as OS_WINDOW.

    Returns:
        A JSON-like payload with public-safe values and sensitive fields nulled
        or redacted.
    """

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return _safe_dict(cast(Mapping[object, object], value), os_window_context=_os_window_context)
    if isinstance(value, (list, tuple)):
        return [safe_public_payload(item, _os_window_context=_os_window_context) for item in value]
    if isinstance(value, str):
        return _sanitize_string_value(value)
    return value


def _safe_dict(payload: Mapping[object, object], *, os_window_context: bool) -> dict[str, object]:
    safe: dict[str, object] = {}
    os_window_context = os_window_context or _is_os_window_payload(payload)
    for index, (key, value) in enumerate(payload.items(), start=1):
        key_text = str(key)
        normalized_key = _normalize_key(key_text)
        public_key = _safe_public_key(key_text, normalized_key, index)
        if os_window_context and normalized_key in NORMALIZED_OS_WINDOW_PRIVATE_KEYS:
            safe[public_key] = None
            continue
        if normalized_key in NORMALIZED_PUBLIC_IDENTITY_KEYS:
            safe[public_key] = None
            continue
        if normalized_key in NORMALIZED_STORAGE_URI_KEYS:
            safe[public_key] = None
            continue
        if normalized_key in NORMALIZED_SECRET_ADJACENT_KEYS:
            safe[public_key] = None
            continue
        if normalized_key in NORMALIZED_URL_KEYS | NORMALIZED_SHARE_URL_KEYS and isinstance(value, str):
            safe[public_key] = _sanitize_url_like(value, os_window_context=os_window_context)
            continue
        if isinstance(value, str):
            safe[public_key] = _sanitize_string_value(value)
            continue
        safe[public_key] = safe_public_payload(value, _os_window_context=os_window_context)
    return safe


def _is_os_window_payload(payload: Mapping[object, object]) -> bool:
    event_type = payload.get("event_type")
    if isinstance(event_type, str) and event_type in OS_WINDOW_EVENT_TYPES:
        return True
    capture_strategy = payload.get("capture_strategy")
    if isinstance(capture_strategy, str) and capture_strategy in OS_WINDOW_STRATEGIES:
        return True
    trigger = payload.get("trigger")
    if isinstance(trigger, Mapping):
        strategy = trigger.get("capture_strategy")
        if isinstance(strategy, str) and strategy in OS_WINDOW_STRATEGIES:
            return True
    return False


def _sanitize_url_like(value: str, *, os_window_context: bool = False) -> str:
    try:
        parts = urlsplit(value)
    except ValueError:
        return "[url:redacted]"
    if not parts.scheme:
        return _sanitize_string_value(value)
    if parts.scheme in {"file", "local-artifact", "vault"}:
        return "[uri:redacted]"
    if os_window_context and parts.scheme == "macos" and parts.netloc in {"a11y"}:
        return urlunsplit((parts.scheme, parts.netloc, "/[redacted]", "", ""))
    return urlunsplit((parts.scheme, _safe_netloc(parts), parts.path, "", ""))


def _sanitize_string_value(value: str) -> str:
    redacted = value
    redacted = SENSITIVE_URI_RE.sub("[uri:redacted]", redacted)
    redacted = HTTP_URI_RE.sub(_sanitize_embedded_http_uri, redacted)
    redacted = LOCAL_PATH_RE.sub("[path:redacted]", redacted)
    redacted = AUTHORIZATION_BEARER_VALUE_RE.sub("[secret:redacted]", redacted)
    redacted = BARE_BEARER_VALUE_RE.sub("[secret:redacted]", redacted)
    redacted = SECRET_VALUE_RE.sub("[secret:redacted]", redacted)
    return redacted


def _sanitize_embedded_http_uri(match: re.Match[str]) -> str:
    raw_uri = match.group(0)
    try:
        parts = urlsplit(raw_uri)
    except ValueError:
        return "[url:redacted]"
    if parts.query or parts.fragment:
        return urlunsplit((parts.scheme, _safe_netloc(parts), parts.path, "", ""))
    return raw_uri


def _safe_public_key(key_text: str, normalized_key: str, index: int) -> str:
    if _sanitize_string_value(key_text) != key_text:
        return f"redacted_key_{index}"
    if _looks_like_sensitive_key_instance(normalized_key):
        return f"redacted_key_{index}"
    return key_text


def _looks_like_sensitive_key_instance(normalized_key: str) -> bool:
    return any(
        normalized_key.startswith(prefix) and normalized_key != prefix for prefix in NORMALIZED_PRIVATE_KEY_PREFIXES
    )


def _safe_netloc(parts: object) -> str:
    host = getattr(parts, "hostname", None) or ""
    try:
        port = getattr(parts, "port", None)
    except ValueError:
        port = None
    return f"{host}:{port}" if port is not None else host
