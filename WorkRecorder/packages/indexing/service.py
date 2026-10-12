"""Index write and search orchestration services."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime

from packages.artifacts.vault import LocalArtifactVault
from packages.contracts import (
    AccessScope,
    AgentVisibleField,
    Artifact,
    ArtifactIngestState,
    ArtifactType,
    ContextEvent,
    DisclosureClass,
    EventCaptureEnvelope,
    EvidenceKind,
    EvidenceSensitivity,
    IndexPolicyDecisionStatus,
    RedactionState,
)
from packages.disclosure.views import sanitized_url
from packages.indexing.contracts import IndexDocument, IndexFieldKind, IndexReceipt, IndexWriteBatch
from packages.indexing.registry import IndexBackendRegistry
from packages.indexing.safety import (
    IndexableTextSource,
    SafeIndexProjection,
    SafeIndexProjectionBatch,
    SafeIndexProjectionService,
)
from packages.shared.ids import IdFactory
from packages.storage.index_policy_audit_repository import IndexPolicyAuditRepository

logger = logging.getLogger(__name__)


class IndexingService:
    """Build daemon-owned searchable projections and write them to index backends."""

    def __init__(
        self,
        *,
        registry: IndexBackendRegistry,
        vault: LocalArtifactVault,
        safe_projection: SafeIndexProjectionService | None = None,
        policy_audit: IndexPolicyAuditRepository | None = None,
    ) -> None:
        self.registry = registry
        self.vault = vault
        self.safe_projection = safe_projection or SafeIndexProjectionService(ids=IdFactory())
        self.policy_audit = policy_audit

    def index_capture(
        self,
        *,
        envelope: EventCaptureEnvelope,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        index_text_by_evidence_id: dict[str, str],
    ) -> IndexReceipt:
        """Index one accepted capture using only daemon-approved projections.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        batch = self.safe_batch_for_capture(
            envelope=envelope,
            event=event,
            artifacts=artifacts,
            index_text_by_evidence_id=index_text_by_evidence_id,
        )
        receipt = self.index_safe_projection(batch)
        logger.info(
            "capture projections indexed",
            extra={
                "event_id": event.event_id,
                "capture_run_id": envelope.capture_run_id,
                "backend": receipt.backend,
                "indexed_count": receipt.indexed_count,
                "skipped_count": receipt.skipped_count,
                "degraded": receipt.degraded,
            },
        )
        return receipt

    def index_safe_projection(self, batch: SafeIndexProjectionBatch) -> IndexReceipt:
        """Index text only after a typed policy-before-index projection.

        Args:
            batch: Projection batch returned by SafeIndexProjectionService.

        Returns:
            Backend receipt for the safe write.
        """

        documents = tuple(
            self._safe_document(projection)
            for projection in batch.projections
            if projection.text.strip() and projection.decision.status != IndexPolicyDecisionStatus.SUPPRESSED
        )
        if self.policy_audit is not None:
            self.policy_audit.save_batch_pending(batch)
        try:
            receipt = self.registry.default().upsert(
                IndexWriteBatch(
                    capture_run_id=batch.capture_run_id,
                    event_id=batch.event_id,
                    documents=documents,
                    replace_event=batch.replace_event,
                    replace_chunk_prefixes=batch.replace_chunk_prefixes,
                )
            )
        except Exception:
            logger.exception("safe projection index backend write failed", extra={"event_id": batch.event_id})
            if self.policy_audit is not None:
                self.policy_audit.mark_batch_failed(batch)
            raise
        if self.policy_audit is not None:
            self.policy_audit.mark_batch_indexed(batch)
        logger.info(
            "safe projections indexed",
            extra={
                "event_id": batch.event_id,
                "backend": receipt.backend,
                "indexed_count": receipt.indexed_count,
                "suppressed_count": batch.audit.suppressed_count,
                "replace_event": batch.replace_event,
            },
        )
        return receipt

    def batch_for_capture(
        self,
        *,
        envelope: EventCaptureEnvelope,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        index_text_by_evidence_id: dict[str, str],
    ) -> IndexWriteBatch:
        """Return index documents for one capture without mutating storage.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        safe_batch = self.safe_batch_for_capture(
            envelope=envelope,
            event=event,
            artifacts=artifacts,
            index_text_by_evidence_id=index_text_by_evidence_id,
        )
        documents = tuple(
            self._safe_document(projection)
            for projection in safe_batch.projections
            if projection.text.strip() and projection.decision.status != IndexPolicyDecisionStatus.SUPPRESSED
        )
        return IndexWriteBatch(
            capture_run_id=envelope.capture_run_id,
            event_id=event.event_id,
            documents=documents,
            replace_event=True,
        )

    def safe_batch_for_capture(
        self,
        *,
        envelope: EventCaptureEnvelope,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        index_text_by_evidence_id: dict[str, str],
    ) -> SafeIndexProjectionBatch:
        """Return policy-approved index projections for one capture."""

        sources: list[IndexableTextSource] = []
        source = event.source_binding.source_ref
        workspace_id = self._workspace_id(envelope)
        base_metadata: dict[str, object] = {
            "event_type": event.event_type,
            "source_binding_id": event.source_binding.binding_id,
            "trigger_id": event.trigger.trigger_id,
            "workspace_id": workspace_id,
        }
        safe_metadata = " ".join(
            item
            for item in (
                source.title,
                source.app_name or "",
                source.origin or "",
                sanitized_url(source.url) or "",
                event.event_type,
            )
            if item
        ).strip()
        if safe_metadata:
            sources.append(
                IndexableTextSource(
                    event=event,
                    field_kind=IndexFieldKind.SAFE_METADATA,
                    text=safe_metadata,
                    captured_at=event.trigger.occurred_at,
                    disclosure_class=DisclosureClass.SAFE_METADATA,
                    workspace_id=workspace_id,
                    agent_visible_fields=(AgentVisibleField.SAFE_METADATA,),
                    metadata={
                        **self._scalar_metadata(base_metadata),
                        "index_document_key": "safe_metadata",
                    },
                )
            )
        note = (event.intent_text or event.trigger.intent_text or "").strip()
        if note:
            sources.append(
                IndexableTextSource(
                    event=event,
                    field_kind=IndexFieldKind.USER_NOTE,
                    text=note,
                    captured_at=event.trigger.occurred_at,
                    disclosure_class=DisclosureClass.SAFE_METADATA,
                    workspace_id=workspace_id,
                    agent_visible_fields=(AgentVisibleField.USER_NOTE,),
                    metadata={
                        **self._scalar_metadata(base_metadata),
                        "index_document_key": IndexFieldKind.USER_NOTE.value,
                    },
                )
            )
        artifact_by_evidence_id = {
            artifact.evidence_id: artifact for artifact in artifacts if artifact.evidence_id is not None
        }
        evidence_by_id = {evidence.evidence_id: evidence for evidence in envelope.evidence_records}
        for evidence_id, text in index_text_by_evidence_id.items():
            evidence = evidence_by_id.get(evidence_id)
            artifact = artifact_by_evidence_id.get(evidence_id)
            if evidence is None or artifact is None or not self._indexable_artifact(artifact):
                continue
            field_kind = self._field_kind(evidence.kind, artifact.artifact_type)
            if field_kind is None:
                continue
            sources.append(
                IndexableTextSource(
                    event=event,
                    field_kind=field_kind,
                    text=text,
                    captured_at=event.trigger.occurred_at,
                    evidence_id=evidence_id,
                    artifact_id=artifact.artifact_id,
                    provider_key=evidence.provenance.provider_key,
                    source_uri=self._safe_source_uri(evidence.locator.source_uri),
                    observed_at=evidence.observed_at,
                    extractor_name=evidence.provenance.extractor.name,
                    extractor_version=evidence.provenance.extractor.version,
                    evidence_kind=evidence.kind,
                    artifact_type=artifact.artifact_type,
                    sensitivity=evidence.sensitivity,
                    disclosure_class=self._disclosure_class(field_kind),
                    redaction_state=artifact.redaction_state,
                    workspace_id=workspace_id,
                    agent_visible_fields=(self._agent_field_kind(field_kind),),
                    metadata={
                        **self._scalar_metadata(base_metadata),
                        "index_document_key": evidence_id,
                    },
                )
            )
        return self.safe_projection.project(
            capture_run_id=envelope.capture_run_id,
            event_id=event.event_id,
            sources=tuple(sources),
            replace_event=True,
        )

    def delete_event(self, event_id: str) -> IndexReceipt:
        """Delete one event from the default backend.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        return self.registry.default().delete_event(event_id)

    def index_imported_event(self, *, event: ContextEvent, artifacts: tuple[Artifact, ...]) -> IndexReceipt:
        """Index one imported share using only safe imported projections.

        Imported events do not have a capture envelope. They still need to be
        searchable by the same agent-facing fields, so this method writes a
        small audited batch with safe metadata, user note, and redacted text
        artifacts only.
        """

        source = event.source_binding.source_ref
        metadata: dict[str, object] = {
            "event_type": event.event_type,
            "source_binding_id": event.source_binding.binding_id,
            "trigger_id": event.trigger.trigger_id,
            "imported_share_id": event.trigger.metadata.get("source_share_id"),
            "original_event_id": event.trigger.metadata.get("original_event_id"),
        }
        scalar_metadata = self._scalar_metadata(metadata)
        sources: list[IndexableTextSource] = []
        safe_metadata = " ".join(
            item
            for item in (
                source.title,
                source.app_name or "",
                source.origin or "",
                sanitized_url(source.url) or "",
                event.event_type,
            )
            if item
        ).strip()
        if safe_metadata:
            sources.append(
                IndexableTextSource(
                    event=event,
                    field_kind=IndexFieldKind.SAFE_METADATA,
                    text=safe_metadata,
                    captured_at=event.trigger.occurred_at,
                    disclosure_class=DisclosureClass.SAFE_METADATA,
                    metadata=scalar_metadata,
                )
            )
        note = (event.intent_text or event.trigger.intent_text or "").strip()
        if note:
            sources.append(
                IndexableTextSource(
                    event=event,
                    field_kind=IndexFieldKind.USER_NOTE,
                    text=note,
                    captured_at=event.trigger.occurred_at,
                    disclosure_class=DisclosureClass.SAFE_METADATA,
                    metadata=scalar_metadata,
                )
            )
        for artifact in artifacts:
            if not self._indexable_artifact(artifact) or not artifact.storage_uri:
                continue
            field_kind = self._field_kind(artifact.evidence_kind or EvidenceKind.SELECTION_TEXT, artifact.artifact_type)
            if field_kind is None:
                continue
            try:
                raw_text = self.vault.read(artifact.storage_uri).decode("utf-8", errors="replace").strip()
            except Exception:
                logger.warning(
                    "imported artifact could not be read for indexing", extra={"artifact_id": artifact.artifact_id}
                )
                continue
            if not raw_text:
                continue
            sources.append(
                IndexableTextSource(
                    event=event,
                    field_kind=field_kind,
                    text=raw_text,
                    captured_at=event.trigger.occurred_at,
                    evidence_id=artifact.evidence_id,
                    artifact_id=artifact.artifact_id,
                    provider_key=artifact.provider_key,
                    source_uri=artifact.source_uri,
                    observed_at=artifact.observed_at,
                    extractor_name=artifact.extractor_name,
                    extractor_version=artifact.extractor_version,
                    artifact_type=artifact.artifact_type,
                    redaction_state=artifact.redaction_state,
                    evidence_kind=artifact.evidence_kind,
                    disclosure_class=self._disclosure_class(field_kind),
                    metadata=scalar_metadata,
                )
            )
        batch = self.safe_projection.project(event_id=event.event_id, sources=tuple(sources))
        return self.index_safe_projection(batch)

    def _safe_document(self, projection: SafeIndexProjection) -> IndexDocument:
        source = projection.source
        event = source.event
        source_ref = event.source_binding.source_ref
        configured_base_id = source.metadata.get("index_document_key")
        base_id = (
            configured_base_id
            if isinstance(configured_base_id, str) and configured_base_id
            else source.evidence_id or source.artifact_id or source.field_kind.value
        )
        user = event.user
        metadata = {
            key: value
            for key, value in {
                **source.metadata,
                "index_policy_decision_id": projection.decision.decision_id,
                "index_policy_status": projection.decision.status.value,
                "index_suppression_reason": projection.decision.suppression_reason.value,
                "sensitive_surface_type": projection.decision.sensitive_surface_type.value,
                "agent_visible_fields": ",".join(field.value for field in projection.decision.agent_visible_fields),
                "user_identity_provider": user.identity_provider.value if user else None,
                "user_tenant_key": user.tenant_key if user else None,
                "user_feishu_open_id": user.feishu_open_id if user else None,
            }.items()
            if isinstance(value, (str, int, float, bool)) or value is None
        }
        return IndexDocument(
            document_id=f"idxdoc_{event.event_id}_{base_id}",
            chunk_id=f"idxchk_{event.event_id}_{base_id}_0",
            event_id=event.event_id,
            evidence_id=source.evidence_id,
            artifact_id=source.artifact_id,
            provider_key=source.provider_key or event.source_binding.provider_key,
            source_uri=self._safe_source_uri(source.source_uri) or sanitized_url(source_ref.url),
            captured_at=source.captured_at,
            observed_at=source.observed_at,
            extractor_name=source.extractor_name,
            extractor_version=source.extractor_version,
            policy_version=projection.decision.policy_version,
            disclosure_class=source.disclosure_class,
            evidence_kind=source.evidence_kind,
            artifact_type=source.artifact_type,
            sensitivity=source.sensitivity,
            redaction_state=projection.decision.redaction_state,
            event_status=source.event_status,
            field_kind=source.field_kind,
            text=projection.text,
            text_hash=self._hash(projection.text),
            title=source_ref.title,
            app_name=source_ref.app_name,
            origin=sanitized_url(source_ref.origin),
            sanitized_url=sanitized_url(source_ref.url),
            source_type=source_ref.source_type.value,
            workspace_id=source.workspace_id,
            user_id=user.user_id if user else event.trigger.actor.actor_id,
            user_display_name=(user.display_name if user and user.display_name else event.trigger.actor.display_name),
            metadata=metadata,
        )

    def _field_kind(self, evidence_kind: EvidenceKind, artifact_type: ArtifactType) -> IndexFieldKind | None:
        if evidence_kind == EvidenceKind.SELECTION_TEXT or artifact_type in {
            ArtifactType.A11Y_SELECTION_TEXT,
            ArtifactType.DOM_SELECTION_TEXT,
        }:
            return IndexFieldKind.SELECTION_TEXT
        if evidence_kind == EvidenceKind.VISUAL_OCR_TEXT or artifact_type == ArtifactType.VISUAL_OCR_TEXT:
            return IndexFieldKind.VISUAL_OCR_TEXT
        if evidence_kind == EvidenceKind.CLEAN_PAGE_TEXT or artifact_type == ArtifactType.CLEAN_PAGE_TEXT:
            return IndexFieldKind.CLEAN_PAGE_TEXT
        if evidence_kind == EvidenceKind.CANONICAL_TEXT or artifact_type == ArtifactType.CANONICAL_TEXT:
            return IndexFieldKind.CANONICAL_TEXT
        return None

    def _disclosure_class(self, field_kind: IndexFieldKind) -> DisclosureClass:
        if field_kind == IndexFieldKind.SELECTION_TEXT:
            return DisclosureClass.SELECTION_BOUND_TEXT
        if field_kind == IndexFieldKind.VISUAL_OCR_TEXT:
            return DisclosureClass.VISUAL_OCR_TEXT
        if field_kind == IndexFieldKind.CLEAN_PAGE_TEXT:
            return DisclosureClass.CLEAN_PAGE_TEXT
        if field_kind == IndexFieldKind.CANONICAL_TEXT:
            return DisclosureClass.REDACTED_CANONICAL
        return DisclosureClass.SAFE_METADATA

    def _indexable_artifact(self, artifact: Artifact) -> bool:
        return (
            AccessScope.READ_TEXT in artifact.allowed_scopes
            and artifact.ingest_state in {ArtifactIngestState.DLP_PASSED, ArtifactIngestState.INDEXED}
            and artifact.redaction_state not in {RedactionState.BLOCKED, RedactionState.QUARANTINED}
            and artifact.artifact_type
            in {
                ArtifactType.A11Y_SELECTION_TEXT,
                ArtifactType.DOM_SELECTION_TEXT,
                ArtifactType.VISUAL_OCR_TEXT,
                ArtifactType.CANONICAL_TEXT,
                ArtifactType.CLEAN_PAGE_TEXT,
            }
        )

    def _workspace_id(self, envelope: EventCaptureEnvelope) -> str | None:
        for evidence in envelope.evidence_records:
            value = evidence.metadata.get("workspace_id")
            if isinstance(value, str) and value:
                return value
        return None

    def _hash(self, text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _safe_source_uri(self, value: str | None) -> str | None:
        if not value:
            return None
        sanitized = sanitized_url(value)
        if sanitized and sanitized != value:
            return sanitized
        if value.startswith(("http://", "https://", "workrecorder://", "macos://")):
            return sanitized or value
        return None

    def _scalar_metadata(self, metadata: dict[str, object]) -> dict[str, str | int | float | bool | None]:
        return {
            key: value for key, value in metadata.items() if isinstance(value, (str, int, float, bool)) or value is None
        }

    def _agent_field_kind(self, field_kind: IndexFieldKind) -> AgentVisibleField:
        mapping = {
            IndexFieldKind.SAFE_METADATA: AgentVisibleField.SAFE_METADATA,
            IndexFieldKind.USER_NOTE: AgentVisibleField.USER_NOTE,
            IndexFieldKind.SELECTION_TEXT: AgentVisibleField.SELECTION_TEXT,
            IndexFieldKind.VISUAL_OCR_TEXT: AgentVisibleField.VISUAL_OCR_TEXT,
            IndexFieldKind.CANONICAL_TEXT: AgentVisibleField.CANONICAL_TEXT,
            IndexFieldKind.CLEAN_PAGE_TEXT: AgentVisibleField.CLEAN_PAGE_TEXT,
            IndexFieldKind.ACTIVE_CAPTURE_SUMMARY: AgentVisibleField.ACTIVE_CAPTURE_SUMMARY,
            IndexFieldKind.RECORDING_TIMELINE: AgentVisibleField.RECORDING_TIMELINE,
            IndexFieldKind.HUMAN_DEMO_SUMMARY: AgentVisibleField.HUMAN_DEMO_SUMMARY,
        }
        return mapping.get(field_kind, AgentVisibleField.SAFE_METADATA)
