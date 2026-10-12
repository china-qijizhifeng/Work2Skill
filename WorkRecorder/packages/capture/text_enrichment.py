"""Daemon text enrichments for clean page text and canonical text."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from packages.artifacts.vault import ArtifactVaultError, LocalArtifactVault
from packages.contracts import (
    ArtifactRole,
    ArtifactType,
    ContextEvent,
    EnrichmentRecord,
    EvidenceDraft,
    EvidenceKind,
    EvidenceLocator,
    EvidencePayloadRef,
    EvidencePhase,
    EvidenceProvenance,
    EvidenceRecord,
    EvidenceSensitivity,
    EvidenceTrustState,
    ExtractorRef,
    ProviderKind,
    RedactionState,
    SourceType,
)
from packages.contracts.common import JsonScalar
from packages.evidence.redaction import SensitiveTextRedactor
from packages.shared.ids import IdFactory
from packages.shared.time import Clock


@dataclass(frozen=True, slots=True)
class TextDerivation:
    """Draft and provenance inputs for one daemon-owned text enrichment.

    Attributes:
        draft: Evidence draft that will be persisted as an artifact.
        kind: Output evidence kind produced by this enrichment.
        extractor: Extractor identity/version for provenance.
        input_evidence_ids: Parent evidence ids used to derive the text.
        created_at: Timestamp for the enrichment ledger row.
        metadata: Safe scalar diagnostics for the enrichment.
    """

    draft: EvidenceDraft
    kind: EvidenceKind
    extractor: ExtractorRef
    input_evidence_ids: tuple[str, ...]
    created_at: datetime
    metadata: dict[str, str | int | float | bool | None]

    def enrichment_record(
        self,
        *,
        ids: IdFactory,
        event_id: str,
        capture_run_id: str,
        output_evidence_id: str,
    ) -> EnrichmentRecord:
        """Create the auditable enrichment row after the draft is persisted.

        Args:
            ids: Identifier factory for the enrichment id.
            event_id: Event that owns the enrichment.
            capture_run_id: Capture run that produced the enrichment.
            output_evidence_id: Evidence id assigned after draft persistence.

        Returns:
            Enrichment record linking input evidence to the derived text.
        """

        return EnrichmentRecord(
            enrichment_id=ids.new("enr"),
            event_id=event_id,
            capture_run_id=capture_run_id,
            kind=self.kind,
            extractor=self.extractor,
            input_evidence_ids=self.input_evidence_ids,
            output_evidence_ids=(output_evidence_id,),
            status="completed",
            created_at=self.created_at,
            metadata=self.metadata,
        )


class TextEnrichmentService:
    """Build daemon-owned text projections from persisted source evidence."""

    def __init__(self, *, vault: LocalArtifactVault, clock: Clock, redactor: SensitiveTextRedactor) -> None:
        self.vault = vault
        self.clock = clock
        self.redactor = redactor

    def derive_clean_page_text(
        self,
        *,
        event: ContextEvent,
        source_binding_id: str,
        inputs: tuple[EvidenceRecord, ...],
    ) -> TextDerivation | None:
        """Return a clean page text draft from browser page-text source evidence.

        Args:
            event: Event being enriched.
            source_binding_id: Source binding id inherited by derived evidence.
            inputs: Persisted evidence records available for enrichment.

        Returns:
            Clean page text derivation, or ``None`` when no source page text is usable.
        """

        source_records = tuple(
            evidence
            for evidence in inputs
            if evidence.artifact_type == ArtifactType.BROWSER_READABILITY_MARKDOWN
            and evidence.role == ArtifactRole.SOURCE_TEXT
            and evidence.provenance.provider_kind == ProviderKind.SOURCE
            and evidence.payload.storage_uri is not None
        )
        if not source_records:
            return None
        parts: list[str] = []
        input_ids: list[str] = []
        for evidence in source_records:
            source_text = self._read_source_text(evidence)
            if not source_text:
                continue
            redacted = self.redactor.redact(source_text)
            if not redacted:
                continue
            parts.append(redacted)
            input_ids.append(evidence.evidence_id)
        clean_text = "\n\n".join(dict.fromkeys(parts)).strip()
        if not clean_text:
            return None
        now = self.clock.now()
        extractor = ExtractorRef(name="clean_page_text_v1", version="p3_2_v1")
        metadata: dict[str, JsonScalar] = {
            "mode": "daemon_dlp_clean_page_text",
            "source_evidence_count": len(input_ids),
            "text_length": len(clean_text),
            "dlp_version": "local_dlp_v1",
        }
        return TextDerivation(
            draft=EvidenceDraft(
                phase=EvidencePhase.ENRICHED,
                kind=EvidenceKind.CLEAN_PAGE_TEXT,
                artifact_type=ArtifactType.CLEAN_PAGE_TEXT,
                role=ArtifactRole.CLEAN_PAGE_TEXT,
                payload=EvidencePayloadRef(
                    content_type="text/markdown; charset=utf-8",
                    inline_content=clean_text,
                    payload_schema="clean_page_text_v1",
                ),
                locator=EvidenceLocator(
                    source_uri=f"workrecorder://events/{event.event_id}/clean_page_text",
                    source_type=SourceType.WEB,
                ),
                observed_at=now,
                captured_at=now,
                provenance=EvidenceProvenance(
                    provider_key="system.enrichment.clean_page_text",
                    provider_kind=ProviderKind.ENRICHMENT,
                    source_binding_id=source_binding_id,
                    parent_evidence_ids=tuple(input_ids),
                    extractor=extractor,
                ),
                sensitivity=EvidenceSensitivity.INTERNAL,
                trust_state_claim=EvidenceTrustState.DLP_PASSED,
                redaction_state_claim=RedactionState.REDACTED,
                metadata=metadata,
            ),
            kind=EvidenceKind.CLEAN_PAGE_TEXT,
            extractor=extractor,
            input_evidence_ids=tuple(input_ids),
            created_at=now,
            metadata=metadata,
        )

    def derive_canonical_text(
        self,
        *,
        event: ContextEvent,
        source_binding_id: str,
        inputs: tuple[EvidenceRecord, ...],
    ) -> TextDerivation | None:
        """Return sectioned canonical text from DLP-passed derived/source inputs.

        Args:
            event: Event being enriched.
            source_binding_id: Source binding id inherited by derived evidence.
            inputs: Persisted evidence records available for canonicalization.

        Returns:
            Canonical text derivation, or ``None`` when no safe text exists.
        """

        pairs: list[tuple[EvidenceRecord, str]] = []
        for evidence in self._canonical_inputs(inputs):
            if evidence.trust_state == EvidenceTrustState.BLOCKED or evidence.payload.storage_uri is None:
                continue
            text = self._read_text(evidence)
            if not text:
                continue
            redacted = self.redactor.redact(text)
            if redacted:
                pairs.append((evidence, redacted))
        canonical = self._sectioned_canonical_text(pairs)
        if not canonical:
            return None
        now = self.clock.now()
        input_ids = tuple(evidence.evidence_id for evidence, _ in pairs)
        extractor = ExtractorRef(name="canonical_text_v0", version="p3_v1")
        metadata: dict[str, JsonScalar] = {
            "mode": "local_deterministic",
            "input_evidence_count": len(input_ids),
            "text_length": len(canonical),
            "dlp_version": "local_dlp_v1",
            "canonical_sections": "selection,page_text,other_context",
        }
        return TextDerivation(
            draft=EvidenceDraft(
                phase=EvidencePhase.ENRICHED,
                kind=EvidenceKind.CANONICAL_TEXT,
                artifact_type=ArtifactType.CANONICAL_TEXT,
                role=ArtifactRole.CANONICAL_TEXT,
                payload=EvidencePayloadRef(
                    content_type="text/plain; charset=utf-8",
                    inline_content=canonical,
                    payload_schema="canonical_text_v0",
                ),
                locator=EvidenceLocator(
                    source_uri=f"workrecorder://events/{event.event_id}/canonical_text",
                    source_type=SourceType.UNKNOWN,
                ),
                observed_at=now,
                captured_at=now,
                provenance=EvidenceProvenance(
                    provider_key="system.enrichment.canonical_text",
                    provider_kind=ProviderKind.ENRICHMENT,
                    source_binding_id=source_binding_id,
                    parent_evidence_ids=input_ids,
                    extractor=extractor,
                ),
                sensitivity=EvidenceSensitivity.INTERNAL,
                trust_state_claim=EvidenceTrustState.DLP_PASSED,
                redaction_state_claim=RedactionState.REDACTED,
                metadata=metadata,
            ),
            kind=EvidenceKind.CANONICAL_TEXT,
            extractor=extractor,
            input_evidence_ids=input_ids,
            created_at=now,
            metadata=metadata,
        )

    def _canonical_inputs(self, inputs: tuple[EvidenceRecord, ...]) -> tuple[EvidenceRecord, ...]:
        selection = tuple(
            evidence
            for evidence in inputs
            if evidence.role == ArtifactRole.SELECTION_TEXT
            and evidence.provenance.provider_kind == ProviderKind.ENRICHMENT
            and evidence.trust_state == EvidenceTrustState.DLP_PASSED
            and self._selection_text_reliable(evidence)
        )
        ordered = (
            *selection,
            *self._clean_page_inputs(inputs),
        )
        seen: set[str] = set()
        deduped: list[EvidenceRecord] = []
        for evidence in ordered:
            if evidence.evidence_id in seen:
                continue
            seen.add(evidence.evidence_id)
            deduped.append(evidence)
        return tuple(deduped)

    def _selection_text_reliable(self, evidence: EvidenceRecord) -> bool:
        confidence = evidence.metadata.get("confidence")
        if isinstance(confidence, (int, float)):
            return float(confidence) >= 0.62
        return True

    def _clean_page_inputs(self, inputs: tuple[EvidenceRecord, ...]) -> tuple[EvidenceRecord, ...]:
        return tuple(
            evidence
            for evidence in inputs
            if evidence.artifact_type == ArtifactType.CLEAN_PAGE_TEXT
            and evidence.role == ArtifactRole.CLEAN_PAGE_TEXT
            and evidence.provenance.provider_kind == ProviderKind.ENRICHMENT
            and evidence.trust_state == EvidenceTrustState.DLP_PASSED
        )

    def _read_source_text(self, evidence: EvidenceRecord) -> str:
        text = self._read_text(evidence)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return text
        if not isinstance(payload, dict):
            return text
        for key in ("markdown", "plain_text", "text"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return text

    def _read_text(self, evidence: EvidenceRecord) -> str:
        if evidence.payload.storage_uri is None:
            return ""
        try:
            return self.vault.read(evidence.payload.storage_uri).decode("utf-8").strip()
        except (ArtifactVaultError, UnicodeDecodeError):
            return ""

    def _sectioned_canonical_text(self, pairs: list[tuple[EvidenceRecord, str]]) -> str:
        sections: list[str] = []
        labels = {
            ArtifactRole.SELECTION_TEXT: "Selection",
            ArtifactRole.CLEAN_PAGE_TEXT: "Page Text",
            ArtifactRole.SOURCE_TEXT: "Other Context",
        }
        for role in (ArtifactRole.SELECTION_TEXT, ArtifactRole.CLEAN_PAGE_TEXT, ArtifactRole.SOURCE_TEXT):
            parts = [text for evidence, text in pairs if evidence.role == role and text.strip()]
            if parts:
                sections.append(f"## {labels[role]}\n\n" + "\n\n".join(dict.fromkeys(parts)))
        return "\n\n".join(sections).strip()
