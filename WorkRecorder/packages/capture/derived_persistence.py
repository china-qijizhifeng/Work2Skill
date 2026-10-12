"""Persistence service for asynchronous derived evidence."""

from __future__ import annotations

from packages.artifacts.vault import ArtifactVaultError, LocalArtifactVault
from packages.contracts import (
    Artifact,
    ContextEvent,
    EnrichmentRecord,
    EventCaptureEnvelope,
    EvidenceDraft,
    EvidencePayloadRef,
    EvidenceRecord,
    EvidenceTrustState,
    IndexManifest,
)
from packages.evidence.policy import EvidencePolicyService
from packages.indexing import IndexingService
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from packages.storage.artifact_repository import ArtifactRepository
from packages.storage.ledger_repository import CaptureLedgerRepository


class DerivedEvidencePersistenceService:
    """Append asynchronous enrichment evidence to an existing event ledger."""

    def __init__(
        self,
        *,
        ledger: CaptureLedgerRepository,
        artifacts: ArtifactRepository,
        vault: LocalArtifactVault,
        ids: IdFactory,
        clock: Clock,
        evidence_policy: EvidencePolicyService,
        indexing: IndexingService | None,
    ) -> None:
        """Create a derived persistence service."""

        self.ledger = ledger
        self.artifacts = artifacts
        self.vault = vault
        self.ids = ids
        self.clock = clock
        self.evidence_policy = evidence_policy
        self.indexing = indexing

    def append(
        self,
        *,
        event: ContextEvent,
        capture_run_id: str,
        source_binding_id: str,
        draft: EvidenceDraft,
        enrichment: EnrichmentRecord,
    ) -> tuple[Artifact, EvidenceRecord, EventCaptureEnvelope]:
        """Persist one derived evidence artifact and refresh the index.

        Args:
            event: Existing context event that receives derived evidence.
            capture_run_id: Capture run owning the event ledger.
            source_binding_id: Source binding to stamp when the draft omits one.
            draft: Derived evidence artifact to promote into the vault.
            enrichment: Enrichment ledger entry describing the producer.

        Returns:
            Persisted artifact, persisted evidence record, and updated envelope.
        """

        persisted, envelope = self.append_many(
            event=event,
            capture_run_id=capture_run_id,
            source_binding_id=source_binding_id,
            drafts=(draft,),
            enrichment=enrichment,
        )
        artifact, evidence = persisted[0]
        return artifact, evidence, envelope

    def append_many(
        self,
        *,
        event: ContextEvent,
        capture_run_id: str,
        source_binding_id: str,
        drafts: tuple[EvidenceDraft, ...],
        enrichment: EnrichmentRecord,
    ) -> tuple[tuple[tuple[Artifact, EvidenceRecord], ...], EventCaptureEnvelope]:
        """Persist multiple derived artifacts as one enrichment transaction.

        Args:
            event: Existing context event that receives derived evidence.
            capture_run_id: Capture run owning the event ledger.
            source_binding_id: Source binding to stamp when drafts omit one.
            drafts: Non-empty derived evidence drafts to persist atomically.
            enrichment: Enrichment ledger entry describing the producer.

        Returns:
            Tuple of persisted artifact/evidence pairs and the updated envelope.

        Raises:
            ValueError: Raised when no drafts are provided.
            RuntimeError: Raised when the original capture envelope is missing.
        """

        if not drafts:
            raise ValueError("append_many requires at least one derived evidence draft")
        persisted = tuple(
            self._persist_draft(
                event=event,
                capture_run_id=capture_run_id,
                source_binding_id=source_binding_id,
                draft=draft,
            )
            for draft in drafts
        )
        artifacts = tuple(item[0] for item in persisted)
        evidence_records = tuple(item[1] for item in persisted)
        output_enrichment = enrichment.model_copy(
            update={"output_evidence_ids": tuple(evidence.evidence_id for evidence in evidence_records)}
        )
        envelope = self.ledger.get_envelope_by_event_id(event.event_id)
        if envelope is None:
            raise RuntimeError("missing envelope for derived evidence append")
        all_evidence = (*envelope.evidence_records, *evidence_records)
        index_text = self._index_text_by_evidence_id(all_evidence)
        index_manifest = self._index_manifest(
            event_id=event.event_id, evidence_records=all_evidence, index_text=index_text
        )
        updated_event = event.model_copy(update={"updated_at": self.clock.now()})
        updated_envelope = self.ledger.append_enrichment(
            event=updated_event,
            artifacts=artifacts,
            evidence_records=evidence_records,
            enrichment_records=(output_enrichment,),
            index_manifest=index_manifest,
            index_text_by_evidence_id=index_text,
        )
        if self.indexing is not None:
            artifacts_for_index = tuple(self._artifacts_for_envelope(updated_envelope, artifacts))
            self.indexing.index_capture(
                envelope=updated_envelope,
                event=updated_event,
                artifacts=artifacts_for_index,
                index_text_by_evidence_id=index_text,
            )
        return persisted, updated_envelope

    def _persist_draft(
        self,
        *,
        event: ContextEvent,
        capture_run_id: str,
        source_binding_id: str,
        draft: EvidenceDraft,
    ) -> tuple[Artifact, EvidenceRecord]:
        artifact_id = self.ids.new("art")
        content = draft.payload.inline_content
        if content is None:
            raise ValueError("derived evidence requires inline content")
        promoted = self.vault.write_generated(
            artifact_id=artifact_id,
            created_at=event.updated_at,
            content=content.encode("utf-8"),
            suffix=self._suffix_for_content_type(draft.payload.content_type),
        )
        payload = EvidencePayloadRef(
            content_type=draft.payload.content_type,
            storage_uri=promoted.storage_uri,
            byte_size=promoted.byte_size,
            sha256=promoted.sha256,
            payload_schema=draft.payload.payload_schema,
            payload_version=draft.payload.payload_version,
        )
        policy = self.evidence_policy.decide(draft)
        evidence_id = self.ids.new("evd")
        evidence = EvidenceRecord(
            evidence_id=evidence_id,
            event_id=event.event_id,
            capture_run_id=capture_run_id,
            phase=draft.phase,
            kind=draft.kind,
            artifact_id=artifact_id,
            artifact_type=draft.artifact_type,
            role=draft.role,
            payload=payload,
            locator=draft.locator,
            observed_at=draft.observed_at,
            captured_at=draft.captured_at,
            ingested_at=self.clock.now(),
            provenance=draft.provenance.model_copy(
                update={"source_binding_id": draft.provenance.source_binding_id or source_binding_id}
            ),
            sensitivity=draft.sensitivity,
            trust_state=policy.trust_state,
            ingest_state=policy.ingest_state,
            redaction_state=policy.redaction_state,
            allowed_scopes=policy.allowed_scopes,
            indexable=policy.indexable,
            metadata=draft.metadata,
        )
        artifact = Artifact(
            artifact_id=artifact_id,
            event_id=event.event_id,
            artifact_type=draft.artifact_type,
            role=draft.role,
            storage_uri=promoted.storage_uri,
            redaction_state=policy.redaction_state,
            allowed_scopes=policy.allowed_scopes,
            content_type=draft.payload.content_type,
            byte_size=promoted.byte_size,
            sha256=promoted.sha256,
            ingest_state=policy.ingest_state,
            metadata=draft.metadata,
            created_at=self.clock.now(),
            evidence_id=evidence_id,
            capture_run_id=capture_run_id,
            provider_key=evidence.provenance.provider_key,
            provider_session_id=evidence.provenance.provider_session_id,
            command_id=evidence.provenance.command_id,
            evidence_kind=evidence.kind,
            source_uri=evidence.locator.source_uri,
            observed_at=evidence.observed_at,
            extractor_name=evidence.provenance.extractor.name,
            extractor_version=evidence.provenance.extractor.version,
        )
        return artifact, evidence

    def _index_text_by_evidence_id(self, evidence_records: tuple[EvidenceRecord, ...]) -> dict[str, str]:
        text: dict[str, str] = {}
        for evidence in evidence_records:
            if not evidence.indexable or evidence.payload.storage_uri is None:
                continue
            try:
                content = self.vault.read(evidence.payload.storage_uri).decode("utf-8").strip()
            except (ArtifactVaultError, UnicodeDecodeError):
                continue
            if content:
                text[evidence.evidence_id] = content
        return text

    def _index_manifest(
        self, *, event_id: str, evidence_records: tuple[EvidenceRecord, ...], index_text: dict[str, str]
    ) -> IndexManifest:
        indexed = tuple(index_text)
        return IndexManifest(
            event_id=event_id,
            indexed_evidence_ids=indexed,
            canonical_document_ids=tuple(f"doc_{evidence_id}" for evidence_id in indexed),
            document_chunk_ids=tuple(f"chk_{evidence_id}_0" for evidence_id in indexed),
            blocked_evidence_ids=tuple(
                evidence.evidence_id
                for evidence in evidence_records
                if evidence.trust_state == EvidenceTrustState.BLOCKED
            ),
        )

    def _artifacts_for_envelope(
        self, envelope: EventCaptureEnvelope, new_artifacts: tuple[Artifact, ...]
    ) -> tuple[Artifact, ...]:
        new_by_id = {artifact.artifact_id: artifact for artifact in new_artifacts}
        artifacts = []
        for artifact_id in envelope.artifact_ids:
            if artifact_id in new_by_id:
                artifacts.append(new_by_id[artifact_id])
                continue
            existing = self.artifacts.get(artifact_id)
            if existing is not None:
                artifacts.append(existing)
        return tuple(artifacts)

    def _suffix_for_content_type(self, content_type: str) -> str:
        if "json" in content_type:
            return ".json"
        if "markdown" in content_type:
            return ".md"
        if "text" in content_type:
            return ".txt"
        return ".bin"
