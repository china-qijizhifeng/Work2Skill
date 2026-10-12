"""Materialize imported share packages into events, artifacts, and manifests."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from pydantic import ValidationError

from packages.artifacts.vault import LocalArtifactVault
from packages.contracts import (
    AccessScope,
    ActorRef,
    Artifact,
    ArtifactIngestState,
    ArtifactRole,
    ArtifactType,
    BoundingBox,
    CaptureStrategy,
    ContextEvent,
    EventStatus,
    EventType,
    EvidenceKind,
    IdentityProvider,
    RedactionState,
    ShareImportRequest,
    SharePackageManifest,
    SourceBinding,
    SourceRef,
    SourceType,
    TriggerEnvelope,
    TriggerType,
    UserRef,
)
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

from .importers import ImportedSharePackage


class ShareImportMaterializer:
    """Build local ledger objects from a validated imported share package."""

    def __init__(self, *, vault: LocalArtifactVault, ids: IdFactory, clock: Clock) -> None:
        self.vault = vault
        self.ids = ids
        self.clock = clock

    def event_from_package(
        self,
        *,
        package: ImportedSharePackage,
        actor: ActorRef,
        request: ShareImportRequest,
    ) -> ContextEvent:
        """Create a local imported event from safe package metadata."""

        card = _dict(package.safe_context.get("summary_card"))
        source = _dict(card.get("source"))
        captured_at = _datetime(card.get("captured_at") or package.safe_context.get("captured_at"), self.clock.now())
        title = _string(source.get("title")) or "WorkRecorder 分享上下文"
        app_name = _string(source.get("app_name")) or "WorkRecorder Share"
        sanitized_url = _sanitize_optional_url(_string(source.get("sanitized_url")))
        origin = _sanitize_origin(_string(source.get("origin")) or _origin_from_url(sanitized_url))
        selection = _selection_from_payload(card.get("selection_bbox"))
        trigger = TriggerEnvelope(
            trigger_id=self.ids.new("trg_imp"),
            trigger_type=TriggerType.MANUAL_SHARE_IMPORT,
            capture_strategy=CaptureStrategy.OS_REGION,
            actor=actor,
            occurred_at=captured_at,
            selection=selection,
            intent_text=_string(card.get("user_note")) or None,
            metadata={
                "source_share_id": package.share_id,
                "original_event_id": package.original_event_id,
                "share_revision": package.revision,
                "share_source_kind": package.source_kind.value,
            },
        )
        source_binding = SourceBinding(
            binding_id=self.ids.new("src_imp"),
            source_ref=SourceRef(
                source_type=SourceType.IMPORTED_CONTEXT,
                title=title,
                app_name=app_name,
                url=sanitized_url or None,
                origin=origin or None,
                connector_name="WorkRecorder Share",
                external_id=package.share_id,
                version=str(package.revision),
            ),
            confidence=1.0,
            resolved_at=self.clock.now(),
            provider_key="context_share.import",
        )
        return ContextEvent(
            event_id=self.ids.new("evt"),
            event_type=EventType.IMPORTED_CONTEXT.value,
            trigger=trigger,
            source_binding=source_binding,
            status=EventStatus.AGENT_READY,
            intent_text=_string(card.get("user_note")) or None,
            created_at=self.clock.now(),
            updated_at=self.clock.now(),
            user=UserRef(
                user_id=actor.actor_id,
                display_name=actor.display_name,
                identity_provider=IdentityProvider.LOCAL,
            ),
        )

    def artifacts_from_package(self, *, package: ImportedSharePackage, event_id: str) -> list[Artifact]:
        """Create safe artifact records for the imported event."""

        safe_context = package.safe_context
        card = _dict(safe_context.get("summary_card"))
        artifacts: list[Artifact] = []
        if package.screenshot_png:
            artifacts.append(
                self._write_artifact(
                    event_id=event_id,
                    artifact_type=ArtifactType.SCREENSHOT,
                    role=ArtifactRole.VISUAL_EVIDENCE,
                    content=package.screenshot_png,
                    suffix=".png",
                    content_type="image/png",
                    allowed_scopes=(AccessScope.READ_METADATA,),
                    ingest_state=ArtifactIngestState.QUARANTINED,
                    evidence_kind=EvidenceKind.SCREENSHOT,
                    metadata={"source_share_id": package.share_id, "revision": package.revision},
                )
            )
        text_specs = (
            (
                "selection_text",
                _string(card.get("selection_text") or card.get("selection_text_snippet")),
                ArtifactType.A11Y_SELECTION_TEXT,
                ArtifactRole.SELECTION_TEXT,
                EvidenceKind.SELECTION_TEXT,
            ),
            (
                "canonical_text",
                _string(safe_context.get("canonical_text")),
                ArtifactType.CANONICAL_TEXT,
                ArtifactRole.CANONICAL_TEXT,
                EvidenceKind.CANONICAL_TEXT,
            ),
            (
                "clean_page_text",
                _string(safe_context.get("clean_page_text")),
                ArtifactType.CLEAN_PAGE_TEXT,
                ArtifactRole.CLEAN_PAGE_TEXT,
                EvidenceKind.CLEAN_PAGE_TEXT,
            ),
            (
                "visual_ocr_text",
                _string(safe_context.get("visual_ocr_text")),
                ArtifactType.VISUAL_OCR_TEXT,
                ArtifactRole.VISUAL_OCR_TEXT,
                EvidenceKind.VISUAL_OCR_TEXT,
            ),
        )
        for field_name, text, artifact_type, role, evidence_kind in text_specs:
            if not text.strip():
                continue
            artifacts.append(
                self._write_artifact(
                    event_id=event_id,
                    artifact_type=artifact_type,
                    role=role,
                    content=text.encode("utf-8"),
                    suffix=".txt",
                    content_type="text/plain; charset=utf-8",
                    allowed_scopes=(AccessScope.READ_METADATA, AccessScope.READ_TEXT),
                    ingest_state=ArtifactIngestState.DLP_PASSED,
                    evidence_kind=evidence_kind,
                    metadata={"source_share_id": package.share_id, "revision": package.revision, "field": field_name},
                )
            )
        return artifacts

    def manifest_from_import(
        self,
        *,
        package: ImportedSharePackage,
        event_id: str,
        screenshot_sha: str | None,
    ) -> SharePackageManifest:
        """Create local manifest metadata for a downloaded package."""

        now = self.clock.now()
        safe_json = json.dumps(package.safe_context, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
        manifest_json = json.dumps(package.manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return SharePackageManifest(
            share_id=package.share_id,
            event_id=event_id,
            revision=package.revision,
            html_filename=f"imported-{package.share_id}-r{package.revision}.html",
            json_filename=f"imported-{package.share_id}-r{package.revision}.json",
            screenshot_filename=f"imported-{package.share_id}-r{package.revision}.png" if screenshot_sha else None,
            manifest_filename=f"imported-{package.share_id}-r{package.revision}-manifest.json",
            html_sha256=package.package_hash,
            json_sha256=hashlib.sha256(safe_json).hexdigest(),
            manifest_sha256=hashlib.sha256(manifest_json).hexdigest(),
            screenshot_sha256=screenshot_sha,
            created_at=now,
        )

    def _write_artifact(
        self,
        *,
        event_id: str,
        artifact_type: ArtifactType,
        role: ArtifactRole,
        content: bytes,
        suffix: str,
        content_type: str,
        allowed_scopes: tuple[AccessScope, ...],
        ingest_state: ArtifactIngestState,
        evidence_kind: EvidenceKind,
        metadata: dict[str, object],
    ) -> Artifact:
        artifact_id = self.ids.new("art")
        promoted = self.vault.write_generated(
            artifact_id=artifact_id,
            created_at=self.clock.now(),
            content=content,
            suffix=suffix,
        )
        return Artifact(
            artifact_id=artifact_id,
            event_id=event_id,
            artifact_type=artifact_type,
            role=role,
            storage_uri=promoted.storage_uri,
            redaction_state=RedactionState.REDACTED,
            allowed_scopes=allowed_scopes,
            content_type=content_type,
            byte_size=promoted.byte_size,
            sha256=promoted.sha256,
            ingest_state=ingest_state,
            metadata={
                key: value
                for key, value in metadata.items()
                if isinstance(value, (str, int, float, bool)) or value is None
            },
            created_at=self.clock.now(),
            evidence_id=self.ids.new("evd"),
            provider_key="context_share.import",
            evidence_kind=evidence_kind,
            source_uri=f"workrecorder://share/{metadata.get('source_share_id')}",
            observed_at=self.clock.now(),
            extractor_name="workrecorder_share_import",
            extractor_version="v1",
        )


def _selection_from_payload(value: object) -> BoundingBox | None:
    if not isinstance(value, dict):
        return None
    try:
        return BoundingBox.model_validate(value)
    except ValidationError:
        return None


def _sanitize_optional_url(value: str) -> str:
    if not value:
        return ""
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme, _safe_netloc(parts), parts.path, "", ""))


def _sanitize_origin(value: str) -> str:
    parts = urlsplit(value.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme, _safe_netloc(parts), "", "", ""))


def _origin_from_url(value: str) -> str:
    if not value:
        return ""
    parts = urlsplit(value)
    if not parts.scheme or not parts.netloc:
        return ""
    return urlunsplit((parts.scheme, _safe_netloc(parts), "", "", ""))


def _safe_netloc(parts: object) -> str:
    host = getattr(parts, "hostname", None) or ""
    try:
        port = getattr(parts, "port", None)
    except ValueError:
        port = None
    return f"{host}:{port}" if port is not None else host


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _datetime(value: object, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    return fallback
