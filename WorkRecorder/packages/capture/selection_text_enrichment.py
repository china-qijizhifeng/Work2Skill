"""Daemon enrichment that turns raw a11y blocks into default selection text."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from packages.artifacts.vault import ArtifactVaultError, LocalArtifactVault
from packages.capture.browser_selection_validation import TRUSTED_A11Y_PROVIDER_KEY, BrowserSelectionEvidenceValidator
from packages.contracts import (
    A11ySnapshot,
    ArtifactType,
    BoundingBox,
    CaptureAttemptRequest,
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
from packages.contracts.enums import ArtifactRole, SelectionTextSourceMethod
from packages.evidence.redaction import SensitiveTextRedactor
from packages.evidence.selection_text import SelectionTextProjectionService
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SelectionTextDerivation:
    """Draft and provenance inputs for one daemon-owned selection projection.

    Attributes:
        draft: Evidence draft that will become the selection-text artifact.
        input_evidence_ids: Parent a11y evidence ids used by the projection.
        projection_metadata: Safe scalar diagnostics from the projection step.
        created_at: Timestamp used for the derived enrichment row.
    """

    draft: EvidenceDraft
    input_evidence_ids: tuple[str, ...]
    projection_metadata: dict[str, str | int | float | bool | None]
    created_at: datetime

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
            Enrichment record linking parent a11y evidence to selection text.
        """

        return EnrichmentRecord(
            enrichment_id=ids.new("enr"),
            event_id=event_id,
            capture_run_id=capture_run_id,
            kind=EvidenceKind.SELECTION_TEXT,
            extractor=ExtractorRef(name="selection_text_from_a11y_blocks_v1", version="p3.1"),
            input_evidence_ids=self.input_evidence_ids,
            output_evidence_ids=(output_evidence_id,),
            status="completed",
            created_at=self.created_at,
            metadata={
                "mode": self.projection_metadata["source_method"],
                "confidence": self.projection_metadata["confidence"],
                "block_count": self.projection_metadata.get("block_count", 0),
                "truncated": self.projection_metadata.get("truncated", False),
            },
        )


class SelectionTextEnrichmentService:
    """Build daemon-owned `selection_text` evidence from persisted a11y trees."""

    def __init__(
        self,
        *,
        vault: LocalArtifactVault,
        clock: Clock,
        redactor: SensitiveTextRedactor,
    ) -> None:
        self.vault = vault
        self.clock = clock
        self.projector = SelectionTextProjectionService(redactor=redactor)
        self.browser = BrowserSelectionEvidenceValidator(vault=vault, projector=self.projector)

    def derive(
        self,
        *,
        attempt: CaptureAttemptRequest,
        event: ContextEvent,
        capture_run_id: str,
        source_binding_id: str,
        inputs: tuple[EvidenceRecord, ...],
    ) -> SelectionTextDerivation | None:
        """Return a selection text evidence draft when a usable a11y tree exists.

        Args:
            attempt: Capture attempt containing the selected bbox.
            event: Event being persisted.
            capture_run_id: Capture run id for provenance.
            source_binding_id: Source binding id inherited by derived evidence.
            inputs: Persisted evidence records available for enrichment.

        Returns:
            Selection-text derivation, or ``None`` when no reliable a11y text exists.
        """

        browser_derivation = self._browser_region_derivation(
            attempt=attempt,
            event=event,
            capture_run_id=capture_run_id,
            source_binding_id=source_binding_id,
            inputs=inputs,
        )
        if browser_derivation is not None:
            return browser_derivation

        a11y_tree, snapshot = self._trusted_snapshot(attempt=attempt, event=event, inputs=inputs)
        if a11y_tree is None or snapshot is None:
            return None
        projection = self.projector.project(snapshot)
        if not projection.text.strip():
            logger.info(
                "selection text projection produced no readable text event_id=%s source_blocks=%s overbroad_parent_only=%s",
                event.event_id,
                projection.source_block_count,
                projection.overbroad_parent_only,
                extra={
                    "event_id": event.event_id,
                    "source_block_count": projection.source_block_count,
                    "overbroad_parent_only": projection.overbroad_parent_only,
                },
            )
            return None
        if self.browser.is_web_source(event) and self.browser.looks_like_browser_ui_noise(projection.text):
            logger.info(
                "a11y selection text looks like browser UI noise and will not be promoted event_id=%s",
                event.event_id,
                extra={"event_id": event.event_id, "source_method": projection.source_method.value},
            )
            return None
        coverage = self._matching_coverage(inputs=inputs, a11y_tree=a11y_tree)
        now = self.clock.now()
        parent_evidence_ids = [a11y_tree.evidence_id]
        if coverage is not None:
            parent_evidence_ids.append(coverage.evidence_id)
        input_artifact_ids = (a11y_tree.artifact_id,) if a11y_tree.artifact_id is not None else ()
        selection = attempt.selection_geometry.selected_region
        metadata: dict[str, str | int | float | bool | None] = {
            "source_method": projection.source_method.value,
            "text_length": len(projection.text),
            "source_block_count": projection.source_block_count,
            "block_count": projection.block_count,
            "confidence": projection.confidence,
            "truncated": projection.truncated,
            "truncation_reason": projection.truncation_reason,
            "overbroad_parent_only": projection.overbroad_parent_only,
            "redaction_version": projection.redaction_version,
        }
        return SelectionTextDerivation(
            draft=EvidenceDraft(
                phase=EvidencePhase.ENRICHED,
                kind=EvidenceKind.SELECTION_TEXT,
                artifact_type=ArtifactType.A11Y_SELECTION_TEXT,
                role=ArtifactRole.SELECTION_TEXT,
                payload=EvidencePayloadRef(
                    content_type="text/plain; charset=utf-8",
                    inline_content=projection.text,
                    payload_schema="a11y_selection_text_v1",
                ),
                locator=EvidenceLocator(
                    source_uri=f"workrecorder://events/{event.event_id}/selection_text/a11y",
                    source_type=SourceType.DESKTOP_WINDOW,
                    coordinate_space=selection.coordinate_space.value,
                    bbox=selection,
                ),
                observed_at=a11y_tree.observed_at,
                captured_at=now,
                provenance=EvidenceProvenance(
                    provider_key="system.enrichment.selection_text",
                    provider_kind=ProviderKind.ENRICHMENT,
                    source_binding_id=source_binding_id,
                    parent_evidence_ids=tuple(parent_evidence_ids),
                    input_artifact_ids=input_artifact_ids,
                    extractor=ExtractorRef(name="selection_text_from_a11y_blocks_v1", version="p3.1"),
                ),
                sensitivity=EvidenceSensitivity.INTERNAL,
                trust_state_claim=EvidenceTrustState.DLP_PASSED,
                redaction_state_claim=RedactionState.REDACTED,
                metadata=metadata,
            ),
            input_evidence_ids=tuple(parent_evidence_ids),
            projection_metadata=metadata,
            created_at=now,
        )

    def _browser_region_derivation(
        self,
        *,
        attempt: CaptureAttemptRequest,
        event: ContextEvent,
        capture_run_id: str,
        source_binding_id: str,
        inputs: tuple[EvidenceRecord, ...],
    ) -> SelectionTextDerivation | None:
        selected = self.browser.selected_text(inputs=inputs, source_binding_id=source_binding_id)
        if selected is None:
            return None
        selected_text = self.browser.read_text(selected)
        if not selected_text:
            return None
        redacted = self.projector.redactor.redact(selected_text)
        if not redacted:
            return None
        selection_map, map_confidence = self.browser.selection_map(
            inputs=inputs,
            selected=selected,
            selected_text=selected_text,
            attempt=attempt,
            source_binding_id=source_binding_id,
        )
        if selection_map is None:
            return None
        page_support_count = self.browser.page_support_count(
            inputs=inputs,
            selected=selected,
            selected_text=selected_text,
            source_binding_id=source_binding_id,
        )
        if page_support_count <= 0:
            logger.info(
                "browser selection text was not supported by page evidence event_id=%s evidence_id=%s",
                event.event_id,
                selected.evidence_id,
                extra={"event_id": event.event_id, "evidence_id": selected.evidence_id},
            )
            return None
        system_evidence_supported = self.browser.supported_by_system_evidence(
            inputs=inputs,
            selected_text=selected_text,
            attempt=attempt,
            event=event,
        )
        if not system_evidence_supported:
            logger.info(
                "browser selection text was not supported by independent system evidence event_id=%s evidence_id=%s page_support_count=%s",
                event.event_id,
                selected.evidence_id,
                page_support_count,
                extra={
                    "event_id": event.event_id,
                    "evidence_id": selected.evidence_id,
                    "page_support_count": page_support_count,
                },
            )
            return None
        selected_confidence = self.browser.float_metadata(selected, "selection_confidence", default=0.72)
        confidence = min(selected_confidence, map_confidence)
        if confidence < 0.62:
            logger.info(
                "browser selection text was too weak for promotion event_id=%s evidence_id=%s confidence=%s",
                event.event_id,
                selected.evidence_id,
                confidence,
                extra={"event_id": event.event_id, "evidence_id": selected.evidence_id, "confidence": confidence},
            )
            return None
        now = self.clock.now()
        selection = attempt.selection_geometry.selected_region
        parent_ids = [selected.evidence_id]
        parent_ids.append(selection_map.evidence_id)
        input_artifact_ids = tuple(
            evidence.artifact_id for evidence in (selected, selection_map) if evidence.artifact_id is not None
        )
        metadata: dict[str, str | int | float | bool | None] = {
            "source_method": SelectionTextSourceMethod.WEB_DOM_PROJECTION.value,
            "confidence": round(confidence, 3),
            "source_evidence_count": len(parent_ids),
            "source_evidence_id": selected.evidence_id,
            "selection_map_evidence_id": selection_map.evidence_id,
            "page_support_count": page_support_count,
            "system_evidence_supported": system_evidence_supported,
            "text_length": len(redacted),
            "redaction_version": "local_dlp_v1",
            "included_in_canonical": confidence >= 0.62,
        }
        return SelectionTextDerivation(
            draft=EvidenceDraft(
                phase=EvidencePhase.ENRICHED,
                kind=EvidenceKind.SELECTION_TEXT,
                artifact_type=ArtifactType.DOM_SELECTION_TEXT,
                role=ArtifactRole.SELECTION_TEXT,
                payload=EvidencePayloadRef(
                    content_type="text/plain; charset=utf-8",
                    inline_content=redacted,
                    payload_schema="dom_selection_text_v1",
                ),
                locator=EvidenceLocator(
                    source_uri=f"workrecorder://events/{event.event_id}/selection_text/dom",
                    source_type=SourceType.WEB,
                    coordinate_space=selection.coordinate_space.value,
                    bbox=selection,
                ),
                observed_at=selected.observed_at,
                captured_at=now,
                provenance=EvidenceProvenance(
                    provider_key="system.enrichment.selection_text",
                    provider_kind=ProviderKind.ENRICHMENT,
                    source_binding_id=source_binding_id,
                    parent_evidence_ids=tuple(parent_ids),
                    input_artifact_ids=input_artifact_ids,
                    extractor=ExtractorRef(name="selection_text_from_browser_dom_region_v1", version="p3.3"),
                ),
                sensitivity=EvidenceSensitivity.INTERNAL,
                trust_state_claim=EvidenceTrustState.DLP_PASSED,
                redaction_state_claim=RedactionState.REDACTED,
                metadata=metadata,
            ),
            input_evidence_ids=tuple(parent_ids),
            projection_metadata=metadata,
            created_at=now,
        )

    def _trusted_snapshot(
        self,
        *,
        attempt: CaptureAttemptRequest,
        event: ContextEvent,
        inputs: tuple[EvidenceRecord, ...],
    ) -> tuple[EvidenceRecord | None, A11ySnapshot | None]:
        for a11y_tree in (evidence for evidence in inputs if self._is_trusted_a11y_tree(evidence)):
            assert a11y_tree.payload.storage_uri is not None
            try:
                snapshot = A11ySnapshot.model_validate_json(self.vault.read(a11y_tree.payload.storage_uri))
            except Exception:
                logger.exception(
                    "failed to parse trusted a11y snapshot for selection text event_id=%s evidence_id=%s",
                    event.event_id,
                    a11y_tree.evidence_id,
                    extra={"event_id": event.event_id, "evidence_id": a11y_tree.evidence_id},
                )
                continue
            if not self._selection_matches(snapshot.selection, attempt.selection_geometry.selected_region):
                logger.warning(
                    "trusted a11y snapshot selection mismatch event_id=%s evidence_id=%s",
                    event.event_id,
                    a11y_tree.evidence_id,
                    extra={"event_id": event.event_id, "evidence_id": a11y_tree.evidence_id},
                )
                continue
            return a11y_tree, snapshot
        return None, None

    def _is_trusted_a11y_tree(self, evidence: EvidenceRecord) -> bool:
        return (
            evidence.artifact_type == ArtifactType.A11Y_TREE
            and evidence.role == ArtifactRole.UI_STRUCTURE
            and evidence.provenance.provider_key == TRUSTED_A11Y_PROVIDER_KEY
            and evidence.provenance.provider_kind == ProviderKind.SYSTEM_EVIDENCE
            and evidence.payload.payload_schema == "a11y_snapshot"
            and evidence.payload.storage_uri is not None
        )

    def _matching_coverage(
        self, *, inputs: tuple[EvidenceRecord, ...], a11y_tree: EvidenceRecord
    ) -> EvidenceRecord | None:
        return next(
            (
                evidence
                for evidence in inputs
                if evidence.artifact_type == ArtifactType.A11Y_COVERAGE
                and evidence.provenance.provider_key == TRUSTED_A11Y_PROVIDER_KEY
                and evidence.provenance.provider_kind == ProviderKind.SYSTEM_EVIDENCE
                and evidence.provenance.command_id == a11y_tree.provenance.command_id
                and evidence.provenance.provider_session_id == a11y_tree.provenance.provider_session_id
            ),
            None,
        )

    def _selection_matches(self, left: BoundingBox, right: BoundingBox) -> bool:
        return all(
            getattr(left, field) == getattr(right, field) for field in ("x", "y", "width", "height", "coordinate_space")
        )
