"""Safe delivered-context snapshot building."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel

from packages.contracts import DeliveredContextItem
from packages.safety import safe_public_payload
from packages.shared.ids import IdFactory


class DeliveredPayloadField(StrEnum):
    """Known safe response field names used for delivered snapshot indexing."""

    EVENT_ID = "event_id"
    EVIDENCE_ID = "evidence_id"
    PREVIEW_EVIDENCE_ID = "preview_evidence_id"
    ARTIFACT_ID = "artifact_id"
    CITATION_ID = "citation_id"
    PREVIEW_CITATION_ID = "preview_citation_id"
    TEXT = "text"
    SELECTION_TEXT = "selection_text"
    SELECTION_TEXT_SNIPPET = "selection_text_snippet"
    DISCLOSURE_CLASS = "disclosure_class"
    TEXT_TRUNCATED = "text_truncated"
    SELECTION_TEXT_TRUNCATED = "selection_text_truncated"


class UnsafePayloadField(StrEnum):
    """Response fields that must not be copied into replay snapshots."""

    ACCESS_TOKEN = "access_token"
    AUTHORIZATION = "authorization"
    CONTENT_BASE64 = "content_base64"
    COOKIE = "cookie"
    DIAGNOSTICS_RAW = "diagnostics_raw"
    HTML = "html"
    INLINE_CONTENT = "inline_content"
    LOCAL_PATH = "local_path"
    PASSWORD = "password"
    PAYLOAD_REF = "payload_ref"
    RAW_PAYLOAD = "raw_payload"
    SECRET = "secret"
    SESSION_STORAGE = "session_storage"
    STORAGE_URI = "storage_uri"
    TOKEN = "token"
    VAULT_PATH = "vault_path"


class DeliveredSnapshotBuilder:
    """Build replay-safe payloads and item indexes.

    Attributes:
        ids: Identifier generator used for delivered item ids.
    """

    def __init__(self, ids: IdFactory) -> None:
        """Create a snapshot builder.

        Args:
            ids: Identifier generator for delivered context items.
        """

        self.ids = ids

    def safe_payload(self, payload: object) -> dict[str, object]:
        """Strip fields that must never be duplicated into replay snapshots.

        Args:
            payload: Daemon response payload before replay persistence.

        Returns:
            JSON-like dictionary safe to store in the agent-run ledger.
        """

        dumped = safe_public_payload(self.to_jsonable(payload))
        sanitized = self._strip_unsafe(dumped)
        return sanitized if isinstance(sanitized, dict) else {"value": sanitized}

    def items_for_payload(self, *, snapshot_id: str, payload: object) -> tuple[DeliveredContextItem, ...]:
        """Index delivered event/evidence/artifact/citation references.

        Args:
            snapshot_id: Snapshot id that owns the delivered items.
            payload: Safe payload persisted for replay.

        Returns:
            Item rows that make replay queries searchable and auditable.
        """

        items: list[DeliveredContextItem] = []

        def _visit(value: object, path: str) -> None:
            if isinstance(value, dict):
                event_id = self._str(value.get(DeliveredPayloadField.EVENT_ID))
                evidence_id = self._str(
                    value.get(DeliveredPayloadField.EVIDENCE_ID) or value.get(DeliveredPayloadField.PREVIEW_EVIDENCE_ID)
                )
                artifact_id = self._str(value.get(DeliveredPayloadField.ARTIFACT_ID))
                citation_id = self._str(
                    value.get(DeliveredPayloadField.CITATION_ID) or value.get(DeliveredPayloadField.PREVIEW_CITATION_ID)
                )
                text = (
                    value.get(DeliveredPayloadField.TEXT)
                    or value.get(DeliveredPayloadField.SELECTION_TEXT)
                    or value.get(DeliveredPayloadField.SELECTION_TEXT_SNIPPET)
                )
                if event_id or evidence_id or artifact_id or citation_id:
                    items.append(
                        DeliveredContextItem(
                            item_id=self.ids.new("dci"),
                            snapshot_id=snapshot_id,
                            event_id=event_id,
                            evidence_id=evidence_id,
                            artifact_id=artifact_id,
                            citation_id=citation_id,
                            field_path=path or "$",
                            disclosure_class=self._str(value.get(DeliveredPayloadField.DISCLOSURE_CLASS)),
                            text_hash=self.hash_text(text) if isinstance(text, str) and text else None,
                            byte_size=len(self.json_bytes(value)),
                            truncated=bool(
                                value.get(DeliveredPayloadField.TEXT_TRUNCATED)
                                or value.get(DeliveredPayloadField.SELECTION_TEXT_TRUNCATED)
                            ),
                        )
                    )
                for key, nested in value.items():
                    _visit(nested, f"{path}.{key}" if path else str(key))
            elif isinstance(value, list):
                for index, nested in enumerate(value):
                    _visit(nested, f"{path}[{index}]")

        _visit(payload, "")
        return tuple(items)

    def hash_text(self, value: str | None) -> str:
        """Hash text without storing a duplicate raw copy.

        Args:
            value: Text to hash.

        Returns:
            Hex SHA-256 digest.
        """

        return hashlib.sha256((value or "").encode("utf-8")).hexdigest()

    def hash_json(self, value: object) -> str:
        """Hash a JSON-like payload in stable key order.

        Args:
            value: JSON-like payload.

        Returns:
            Hex SHA-256 digest of the serialized payload.
        """

        return hashlib.sha256(self.json_bytes(value)).hexdigest()

    def json_bytes(self, value: object) -> bytes:
        """Serialize a JSON-like payload using stable options.

        Args:
            value: Payload to serialize.

        Returns:
            UTF-8 encoded JSON bytes.
        """

        return json.dumps(self.to_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )

    def to_jsonable(self, payload: object) -> object:
        """Convert contract models and simple objects into JSON-like data.

        Args:
            payload: Contract model or JSON-serializable value.

        Returns:
            JSON-compatible object.
        """

        if isinstance(payload, BaseModel):
            return payload.model_dump(mode="json")
        return json.loads(json.dumps(payload, default=str))

    def _strip_unsafe(self, value: object) -> object:
        deny_keys = {field.value for field in UnsafePayloadField}
        deny_fragments = ("cookie", "password", "secret", "token", "authorization", "storage_uri", "vault")
        if isinstance(value, dict):
            clean: dict[str, object] = {}
            for key, nested in value.items():
                normalized = key.lower()
                if normalized in deny_keys or any(fragment in normalized for fragment in deny_fragments):
                    continue
                clean[key] = self._strip_unsafe(nested)
            return clean
        if isinstance(value, list):
            return [self._strip_unsafe(item) for item in value if not (isinstance(item, str) and item in deny_keys)]
        if isinstance(value, str):
            return self._sanitize_string(value)
        return value

    def _sanitize_string(self, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
        if parsed.scheme in {"file", "local-artifact", "vault"}:
            return "[redacted-uri]"
        if value.startswith(("/", "~/")):
            return "[redacted-path]"
        return value

    def _str(self, value: object) -> str | None:
        return value if isinstance(value, str) and value else None
