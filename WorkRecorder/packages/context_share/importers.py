"""Import helpers for WorkRecorder share packages and Feishu Drive links."""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
from dataclasses import dataclass
from typing import Callable, Protocol, cast
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError

from packages.artifacts.vault import MAX_GENERATED_ARTIFACT_BYTES
from packages.contracts import (
    EventSourceContributionView,
    ReadableEvidenceView,
    SearchResultCard,
    ShareImportSourceKind,
    SystemAppshotSnapshot,
    UserRef,
)
from packages.integrations.feishu import FeishuIntegrationError

from .package import verify_share_import_manifest

MAX_SHARE_HTML_BYTES = 15 * 1024 * 1024
MAX_SHARE_SCREENSHOT_BYTES = MAX_GENERATED_ARTIFACT_BYTES
MAX_SAFE_CONTEXT_JSON_BYTES = MAX_GENERATED_ARTIFACT_BYTES
FEISHU_FILE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{8,160}$")
ALLOWED_SAFE_CONTEXT_KEYS = {
    "share_id",
    "event_id",
    "scope",
    "created_by",
    "user",
    "captured_at",
    "summary_card",
    "source_contributions",
    "system_appshot",
    "canonical_text",
    "clean_page_text",
    "visual_ocr_text",
    "readable_evidence",
    "hidden_materials",
    "available_fields",
    "policy",
}
FORBIDDEN_VALUE_MARKERS = (
    "local-artifact://",
    "vault://",
    "file://",
    "/Users/",
    "/private/",
    "/tmp/",
    "/var/folders/",
)
FORBIDDEN_PAYLOAD_KEYS = {
    "raw_artifact_refs",
    "raw_dom",
    "raw_a11y_tree",
    "vault_path",
    "storage_uri",
    "storage_path",
    "local_path",
    "raw_path",
    "bundle_path",
    "bundle_url",
    "inline_content",
    "cookies",
    "cookie",
    "localstorage",
    "sessionstorage",
}


class ShareImportError(RuntimeError):
    """Sanitized share import failure that is safe to return to UI surfaces."""

    def __init__(self, message: str, *, code: str, source_kind: ShareImportSourceKind) -> None:
        super().__init__(message)
        self.code = code
        self.source_kind = source_kind


@dataclass(frozen=True)
class ImportedSharePackage:
    """Parsed, integrity-checked WorkRecorder share payload.

    Attributes:
        source_kind: Source classifier for the imported package.
        share_id: Stable WorkRecorder share id from the manifest.
        original_event_id: Event id from the source machine.
        revision: Share package revision number.
        safe_context: Agent-visible context payload after sanitization.
        screenshot_png: Optional full screenshot bytes from the package.
        manifest: Import manifest embedded in the HTML.
        package_hash: SHA-256 of the downloaded HTML bytes.
        provider_url: Sanitized provider URL used to fetch the package.
    """

    source_kind: ShareImportSourceKind
    share_id: str
    original_event_id: str
    revision: int
    safe_context: dict[str, object]
    screenshot_png: bytes | None
    manifest: dict[str, object]
    package_hash: str
    provider_url: str | None = None


class FeishuDriveDownloader(Protocol):
    """Small protocol used by the importer and tests."""

    def download_file(self, *, file_token: str) -> bytes:
        """Download the share HTML bytes for one Feishu file token.

        Args:
            file_token: Feishu file token parsed from a tenant URL.

        Returns:
            Self-contained WorkRecorder share HTML bytes.
        """
        ...


class ShareSourceClassifier:
    """Classify share references without doing network or storage work."""

    def classify(self, value: str) -> ShareImportSourceKind:
        """Classify a user-provided share link or share id.

        Args:
            value: Raw input from CLI, Workbench, or API.

        Returns:
            Source kind used by the import service to select an importer.
        """

        text = value.strip()
        if text.startswith("workrecorder://share/") or text.startswith("shr_"):
            return ShareImportSourceKind.LOCAL_REFERENCE
        if _feishu_file_token(text):
            return ShareImportSourceKind.FEISHU_DRIVE_URL
        return ShareImportSourceKind.UNKNOWN


class SharePackageParser:
    """Parse self-contained WorkRecorder share HTML packages."""

    def __init__(self, *, signature_secret_provider: Callable[[], str | None] | None = None) -> None:
        self.signature_secret_provider = signature_secret_provider

    def parse_html(
        self,
        *,
        html_bytes: bytes,
        source_kind: ShareImportSourceKind,
        provider_url: str | None = None,
    ) -> ImportedSharePackage:
        """Parse and validate a WorkRecorder HTML share package.

        Args:
            html_bytes: Downloaded or local HTML bytes.
            source_kind: Source kind for policy and error reporting.
            provider_url: Optional sanitized external URL for provenance.

        Returns:
            Parsed safe payload and optional screenshot bytes.

        Raises:
            ShareImportError: If the package is malformed, oversized, or
                contains raw/private fields that WorkRecorder never imports.
        """

        if not html_bytes or len(html_bytes) > MAX_SHARE_HTML_BYTES:
            raise ShareImportError(
                "分享文件大小不符合要求。",
                code="invalid_size",
                source_kind=source_kind,
            )
        html_text = html_bytes.decode("utf-8", errors="replace")
        safe_context = self._safe_context(html_text, source_kind=source_kind)
        manifest = self._manifest(html_text, safe_context=safe_context)
        if source_kind == ShareImportSourceKind.FEISHU_DRIVE_URL:
            if manifest.get("schema_version") != "workrecorder_share_html_v1":
                raise ShareImportError(
                    "分享文件版本不受支持，已停止导入。",
                    code="unsupported_schema",
                    source_kind=source_kind,
                )
        share_id = _string(manifest.get("share_id") or safe_context.get("share_id"))
        event_id = _string(manifest.get("event_id") or safe_context.get("event_id"))
        revision = _int(manifest.get("revision"), default=1)
        self._assert_manifest_identity(
            manifest=manifest,
            safe_context=safe_context,
            share_id=share_id,
            event_id=event_id,
            revision=revision,
            source_kind=source_kind,
        )
        if not share_id or not event_id:
            raise ShareImportError(
                "这不是有效的 WorkRecorder 分享文件。",
                code="missing_identity",
                source_kind=source_kind,
            )
        safe_json = json.dumps(safe_context, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        expected_json_hash = _string(manifest.get("json_sha256"))
        if source_kind == ShareImportSourceKind.FEISHU_DRIVE_URL and not expected_json_hash:
            raise ShareImportError(
                "分享文件缺少完整性校验信息。",
                code="json_hash_missing",
                source_kind=source_kind,
            )
        if expected_json_hash and hashlib.sha256(safe_json).hexdigest() != expected_json_hash:
            raise ShareImportError(
                "分享文件校验失败，内容可能已被修改。",
                code="json_hash_mismatch",
                source_kind=source_kind,
            )
        safe_context = self._normalize_safe_context(
            _sanitize_safe_context_urls(safe_context),
            source_kind=source_kind,
        )
        screenshot_png = self._screenshot(html_text, source_kind=source_kind)
        expected_screenshot_hash = _string(manifest.get("screenshot_sha256"))
        if expected_screenshot_hash and screenshot_png is None:
            raise ShareImportError(
                "分享截图缺失，已停止导入。",
                code="screenshot_missing",
                source_kind=source_kind,
            )
        if screenshot_png is not None and not expected_screenshot_hash:
            raise ShareImportError(
                "分享截图缺少完整性校验信息。",
                code="screenshot_hash_missing",
                source_kind=source_kind,
            )
        if screenshot_png is not None and expected_screenshot_hash:
            if hashlib.sha256(screenshot_png).hexdigest() != expected_screenshot_hash:
                raise ShareImportError(
                    "分享截图校验失败，内容可能已被修改。",
                    code="screenshot_hash_mismatch",
                    source_kind=source_kind,
                )
        if source_kind == ShareImportSourceKind.FEISHU_DRIVE_URL:
            self._assert_signature(manifest, source_kind=source_kind)
        return ImportedSharePackage(
            source_kind=source_kind,
            share_id=share_id,
            original_event_id=event_id,
            revision=revision,
            safe_context=safe_context,
            screenshot_png=screenshot_png,
            manifest=manifest,
            package_hash=hashlib.sha256(html_bytes).hexdigest(),
            provider_url=provider_url,
        )

    def _safe_context(self, html_text: str, *, source_kind: ShareImportSourceKind) -> dict[str, object]:
        script = _script_json(html_text, "workrecorder-safe-context")
        if script is None:
            script = _legacy_safe_context(html_text)
        if script is None:
            raise ShareImportError(
                "分享文件缺少可导入的上下文数据。",
                code="safe_context_missing",
                source_kind=source_kind,
            )
        try:
            payload = json.loads(script)
        except json.JSONDecodeError as exc:
            raise ShareImportError(
                "分享上下文格式无效。",
                code="safe_context_malformed",
                source_kind=source_kind,
            ) from exc
        if not isinstance(payload, dict):
            raise ShareImportError(
                "分享上下文格式无效。",
                code="safe_context_not_object",
                source_kind=source_kind,
            )
        if len(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")) > MAX_SAFE_CONTEXT_JSON_BYTES:
            raise ShareImportError(
                "分享上下文过大，已停止导入。",
                code="safe_context_too_large",
                source_kind=source_kind,
            )
        self._assert_safe_payload(payload, source_kind=source_kind)
        return payload

    def _assert_safe_payload(self, payload: dict[str, object], *, source_kind: ShareImportSourceKind) -> None:
        unexpected = sorted(set(payload) - ALLOWED_SAFE_CONTEXT_KEYS)
        if unexpected:
            raise ShareImportError(
                "分享上下文包含 WorkRecorder 不会导入的原始字段。",
                code="safe_context_unexpected_fields",
                source_kind=source_kind,
            )
        serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
        for marker in FORBIDDEN_VALUE_MARKERS:
            if marker.lower() in serialized:
                raise ShareImportError(
                    "分享上下文包含原始材料引用，已停止导入。",
                    code="safe_context_forbidden_raw",
                    source_kind=source_kind,
                )
        forbidden_key = _first_forbidden_key(payload)
        if forbidden_key is not None:
            raise ShareImportError(
                "分享上下文包含 WorkRecorder 不会导入的原始字段。",
                code="safe_context_forbidden_raw",
                source_kind=source_kind,
            )

    def _manifest(self, html_text: str, *, safe_context: dict[str, object]) -> dict[str, object]:
        script = _script_json(html_text, "workrecorder-import-manifest")
        if script is not None:
            try:
                payload = json.loads(script)
                if isinstance(payload, dict):
                    return payload
            except json.JSONDecodeError:
                return {}
        return {
            "share_id": safe_context.get("share_id"),
            "event_id": safe_context.get("event_id"),
            "revision": 1,
        }

    def _screenshot(self, html_text: str, *, source_kind: ShareImportSourceKind) -> bytes | None:
        match = re.search(r'src=["\']data:image/png;base64,([^"\']+)["\']', html_text, flags=re.IGNORECASE)
        if match is None:
            return None
        try:
            data = base64.b64decode(match.group(1), validate=True)
        except ValueError as exc:
            raise ShareImportError(
                "分享截图格式无效。",
                code="screenshot_malformed",
                source_kind=source_kind,
            ) from exc
        if len(data) > MAX_SHARE_SCREENSHOT_BYTES:
            raise ShareImportError(
                "分享截图过大，已停止导入。",
                code="screenshot_too_large",
                source_kind=source_kind,
            )
        return data

    def _assert_manifest_identity(
        self,
        *,
        manifest: dict[str, object],
        safe_context: dict[str, object],
        share_id: str,
        event_id: str,
        revision: int,
        source_kind: ShareImportSourceKind,
    ) -> None:
        safe_share_id = _string(safe_context.get("share_id"))
        safe_event_id = _string(safe_context.get("event_id"))
        safe_revision = _int(safe_context.get("revision"), default=revision)
        manifest_revision = _int(manifest.get("revision"), default=revision)
        if safe_share_id and share_id and safe_share_id != share_id:
            raise ShareImportError("分享文件身份校验失败。", code="identity_mismatch", source_kind=source_kind)
        if safe_event_id and event_id and safe_event_id != event_id:
            raise ShareImportError("分享文件身份校验失败。", code="identity_mismatch", source_kind=source_kind)
        if safe_context.get("revision") is not None and safe_revision != manifest_revision:
            raise ShareImportError("分享文件版本校验失败。", code="identity_mismatch", source_kind=source_kind)

    def _assert_signature(self, manifest: dict[str, object], *, source_kind: ShareImportSourceKind) -> None:
        secret = self.signature_secret_provider() if self.signature_secret_provider is not None else None
        if not secret:
            raise ShareImportError(
                "WorkRecorder 尚未配置分享签名校验，无法安全导入飞书链接。",
                code="signature_verification_unconfigured",
                source_kind=source_kind,
            )
        if not isinstance(manifest.get("package_signature"), str):
            raise ShareImportError(
                "分享文件缺少可信签名，已停止导入。",
                code="signature_missing",
                source_kind=source_kind,
            )
        if not verify_share_import_manifest(manifest, secret=secret):
            raise ShareImportError(
                "分享文件签名校验失败，内容可能已被替换。",
                code="signature_mismatch",
                source_kind=source_kind,
            )

    def _normalize_safe_context(
        self, payload: dict[str, object], *, source_kind: ShareImportSourceKind
    ) -> dict[str, object]:
        normalized: dict[str, object] = {}
        for key in ("share_id", "event_id", "scope", "captured_at"):
            if isinstance(payload.get(key), str):
                normalized[key] = payload[key]
        for key in ("created_by", "user"):
            user = _safe_user_ref(payload.get(key))
            if user:
                normalized[key] = user
        card = _safe_summary_card(payload.get("summary_card"))
        if card:
            normalized["summary_card"] = card
        for key in ("canonical_text", "clean_page_text", "visual_ocr_text"):
            if isinstance(payload.get(key), str):
                normalized[key] = payload[key]
        hidden = _safe_string_list(payload.get("hidden_materials"))
        if hidden:
            normalized["hidden_materials"] = hidden
        fields = _safe_string_list(payload.get("available_fields"))
        if fields:
            normalized["available_fields"] = fields
        policy = _safe_policy(payload.get("policy"))
        if policy:
            normalized["policy"] = policy
        contributions = _safe_source_contributions(payload.get("source_contributions"), source_kind=source_kind)
        if contributions:
            normalized["source_contributions"] = contributions
        appshot = _safe_system_appshot(payload.get("system_appshot"), source_kind=source_kind)
        if appshot:
            normalized["system_appshot"] = appshot
        readable = _safe_readable_evidence(payload.get("readable_evidence"), source_kind=source_kind)
        if readable:
            normalized["readable_evidence"] = readable
        return normalized


class FeishuDriveShareImporter:
    """Download a WorkRecorder share HTML file from Feishu Drive."""

    def __init__(self, *, drive: FeishuDriveDownloader, parser: SharePackageParser) -> None:
        self.drive = drive
        self.parser = parser

    def import_url(self, value: str) -> ImportedSharePackage:
        """Download and parse one Feishu file URL.

        Args:
            value: User-pasted Feishu file URL.

        Returns:
            Parsed package ready for local import.
        """

        file_token = _feishu_file_token(value)
        if not file_token:
            raise ShareImportError(
                "这不是可识别的飞书文件链接。",
                code="unsupported_feishu_url",
                source_kind=ShareImportSourceKind.FEISHU_DRIVE_URL,
            )
        try:
            content = self.drive.download_file(file_token=file_token)
        except FeishuIntegrationError as exc:
            source_kind = ShareImportSourceKind.FEISHU_DRIVE_URL
            raise ShareImportError(_feishu_user_message(exc), code=exc.code, source_kind=source_kind) from exc
        return self.parser.parse_html(
            html_bytes=content,
            source_kind=ShareImportSourceKind.FEISHU_DRIVE_URL,
            provider_url=_sanitize_url(value),
        )


def _script_json(html_text: str, element_id: str) -> str | None:
    pattern = rf"<script[^>]*id=[\"']{re.escape(element_id)}[\"'][^>]*>(.*?)</script>"
    match = re.search(pattern, html_text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None


def _legacy_safe_context(html_text: str) -> str | None:
    matches = re.findall(r"<pre[^>]*>(.*?)</pre>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not matches:
        return None
    for candidate in reversed(matches):
        unescaped = html.unescape(str(candidate)).strip()
        if '"summary_card"' in unescaped and '"event_id"' in unescaped:
            return unescaped
    return None


def _feishu_file_token(value: str) -> str | None:
    parsed = urlsplit(value.strip())
    if parsed.scheme != "https":
        return None
    host = (parsed.hostname or "").lower()
    if not _is_allowed_feishu_host(host):
        return None
    parts = [part for part in parsed.path.split("/") if part]
    for index, part in enumerate(parts[:-1]):
        if part == "file" and FEISHU_FILE_TOKEN_RE.fullmatch(parts[index + 1]):
            return parts[index + 1]
    return None


def _is_allowed_feishu_host(host: str) -> bool:
    return (
        host == "feishu.cn" or host.endswith(".feishu.cn") or host == "larksuite.com" or host.endswith(".larksuite.com")
    )


def _first_forbidden_key(value: object) -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if isinstance(key, str) and key.lower() in FORBIDDEN_PAYLOAD_KEYS:
                return key
            found = _first_forbidden_key(nested)
            if found is not None:
                return found
    if isinstance(value, list):
        for nested in value:
            found = _first_forbidden_key(nested)
            if found is not None:
                return found
    return None


def _sanitize_safe_context_urls(value: dict[str, object]) -> dict[str, object]:
    return cast(dict[str, object], _sanitize_value_urls(value)) if isinstance(value, dict) else {}


def _sanitize_value_urls(value: object) -> object:
    if isinstance(value, dict):
        return {key: _sanitize_url_value(key, nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_sanitize_value_urls(item) for item in value]
    return value


def _sanitize_url_value(key: str, value: object) -> object:
    if isinstance(value, (dict, list)):
        return _sanitize_value_urls(value)
    if not isinstance(value, str):
        return value
    normalized_key = key.lower()
    if normalized_key in {"sanitized_url", "url", "provider_url"}:
        return _strip_query_hash(value)
    if normalized_key == "origin":
        return _origin_only(value)
    return value


def _safe_summary_card(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    try:
        validated = SearchResultCard.model_validate(value)
        return cast(dict[str, object], validated.model_dump(mode="json"))
    except (TypeError, ValueError, ValidationError):
        pass
    allowed_scalars = {
        "event_id",
        "event_type",
        "captured_at",
        "user_note",
        "user_note_truncated",
        "selection_text",
        "selection_text_snippet",
        "selection_text_truncated",
        "canonical_text_snippet",
        "canonical_text_truncated",
        "preview_evidence_id",
        "preview_citation_id",
        "preview_confidence",
        "match_reason",
        "provider_diagnostics_count",
        "source_kind",
        "disclosure_view",
        "disclosure_policy_version",
    }
    card = {key: nested for key, nested in value.items() if key in allowed_scalars and _is_json_scalar(nested)}
    source = value.get("source")
    if isinstance(source, dict):
        source_payload = {
            key: _sanitize_url(str(nested)) if key in {"sanitized_url", "origin"} else str(nested)
            for key, nested in source.items()
            if key in {"app_name", "title", "origin", "sanitized_url"} and isinstance(nested, (str, int, float, bool))
        }
        if source_payload:
            card["source"] = source_payload
    bbox = value.get("selection_bbox")
    if isinstance(bbox, dict):
        card["selection_bbox"] = {
            key: nested
            for key, nested in bbox.items()
            if key in {"x", "y", "width", "height", "coordinate_space"} and _is_json_scalar(nested)
        }
    for key in ("hidden_artifacts", "provider_contributions"):
        items = _safe_string_list(value.get(key))
        if items:
            card[key] = items
    return card


def _safe_user_ref(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    try:
        return cast(dict[str, object], UserRef.model_validate(value).model_dump(mode="json"))
    except (TypeError, ValueError, ValidationError):
        return {
            key: nested
            for key, nested in value.items()
            if key in {"user_id", "display_name", "identity_provider", "feishu_open_id", "tenant_key", "email_hash"}
            and _is_json_scalar(nested)
        }


def _safe_policy(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {
        key: nested
        for key, nested in value.items()
        if key
        in {
            "disclosure_policy_version",
            "redaction_policy_version",
            "raw_dom_uploaded",
            "raw_a11y_tree_uploaded",
            "url_query_hash_uploaded",
        }
        and _is_json_scalar(nested)
    }


def _safe_source_contributions(value: object, *, source_kind: ShareImportSourceKind) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, object]] = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        try:
            rows.append(
                cast(dict[str, object], EventSourceContributionView.model_validate(item).model_dump(mode="json"))
            )
        except Exception as exc:
            raise ShareImportError(
                "分享来源信息格式无效。",
                code="source_contributions_invalid",
                source_kind=source_kind,
            ) from exc
    return rows


def _safe_system_appshot(value: object, *, source_kind: ShareImportSourceKind) -> dict[str, object]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ShareImportError("系统底片格式无效。", code="system_appshot_invalid", source_kind=source_kind)
    try:
        return cast(dict[str, object], SystemAppshotSnapshot.model_validate(value).model_dump(mode="json"))
    except Exception as exc:
        raise ShareImportError("系统底片格式无效。", code="system_appshot_invalid", source_kind=source_kind) from exc


def _safe_readable_evidence(value: object, *, source_kind: ShareImportSourceKind) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, object]] = []
    for item in value[:40]:
        if not isinstance(item, dict):
            continue
        try:
            rows.append(cast(dict[str, object], ReadableEvidenceView.model_validate(item).model_dump(mode="json")))
        except Exception as exc:
            raise ShareImportError(
                "可读证据格式无效。",
                code="readable_evidence_invalid",
                source_kind=source_kind,
            ) from exc
    return rows


def _safe_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item)[:240] for item in value[:80] if isinstance(item, (str, int, float, bool))]


def _is_json_scalar(value: object) -> bool:
    return isinstance(value, (str, int, float, bool)) or value is None


def _strip_query_hash(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, _safe_netloc(parsed), parsed.path, "", ""))


def _origin_only(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return urlunsplit((parsed.scheme, _safe_netloc(parsed), "", "", ""))


def _sanitize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if not parsed.scheme:
        return value.strip()
    return urlunsplit((parsed.scheme, _safe_netloc(parsed), parsed.path, "", ""))


def _safe_netloc(parsed: object) -> str:
    if not hasattr(parsed, "hostname"):
        return ""
    host = getattr(parsed, "hostname") or ""
    try:
        port = getattr(parsed, "port") or None
    except ValueError:
        port = None
    return f"{host}:{port}" if port is not None else host


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _int(value: object, *, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return default


def _feishu_user_message(error: FeishuIntegrationError) -> str:
    if error.code in {"config_missing", "secret_missing"}:
        return "飞书导入尚未配置应用权限，无法读取这个链接。"
    if error.code.startswith("download_http_403") or error.code in {
        "feishu_99991663",
        "feishu_99991672",
        "feishu_1061004",
    }:
        return "没有权限读取这个飞书分享文件。请确认它来自同一组织，并且 WorkRecorder 应用有文件读取权限。"
    if error.code.startswith("download_http_404"):
        return "没有找到这个飞书分享文件，可能已被删除或撤销。"
    return "飞书分享文件读取失败，请稍后重试或检查应用权限。"
