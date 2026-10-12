"""Internal artifact and evidence helpers for capture persistence."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from packages.artifacts.vault import LocalArtifactVault
from packages.capture.surface import SurfaceDetectionService
from packages.contracts import (
    Artifact,
    ArtifactRole,
    ArtifactType,
    CaptureAttemptRequest,
    CaptureStrategy,
    ContextEvent,
    DetectedSurface,
    EventCaptureEnvelope,
    EventType,
    EvidenceBundleRecord,
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
    IndexManifest,
    ProviderCaptureOutcome,
    ProviderCaptureOutcomeStatus,
    ProviderCommandStatus,
    ProviderEvidenceBundle,
    ProviderKind,
    ProviderRoute,
    ProviderRoutePlan,
    ProviderRouteRole,
    RedactionState,
    SourceBinding,
    SourceRef,
    SourceType,
)
from packages.evidence.policy import EvidencePolicyService
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

if TYPE_CHECKING:
    from packages.indexing import IndexingService
    from packages.storage.capture_repository import CaptureRepository
    from packages.storage.ledger_repository import CaptureLedgerRepository

logger = logging.getLogger(__name__)


class _CapturePersistenceInternals:
    """Private implementation mixin for artifact, evidence, and manifest persistence."""

    ids: IdFactory
    vault: LocalArtifactVault
    clock: Clock
    evidence_policy: EvidencePolicyService
    indexing: "IndexingService | None"
    ledger: "CaptureLedgerRepository"
    captures: "CaptureRepository"

    def _persist_draft(
        self,
        *,
        attempt: CaptureAttemptRequest,
        event: ContextEvent,
        capture_run_id: str,
        source_binding_id: str,
        draft: EvidenceDraft,
    ) -> tuple[Artifact, EvidenceRecord]:
        artifact_id = self.ids.new("art")
        policy = self.evidence_policy.decide(draft)
        if draft.artifact_type == ArtifactType.SCREENSHOT:
            promoted = self.vault.promote(
                staged_path=Path(attempt.staged_artifact.local_path),
                artifact_id=artifact_id,
                created_at=event.created_at,
            )
        else:
            content = draft.payload.inline_content
            if content is None:
                raise ValueError("provider evidence drafts must include inline content before persistence")
            promoted = self.vault.write_generated(
                artifact_id=artifact_id,
                created_at=event.created_at,
                content=content.encode("utf-8"),
                suffix=self._suffix_for_content_type(draft.payload.content_type),
            )
        payload = draft.payload.model_copy(
            update={
                "storage_uri": promoted.storage_uri,
                "byte_size": promoted.byte_size,
                "sha256": promoted.sha256,
                "inline_content": None,
            }
        )
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
            created_at=event.created_at,
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

    def _trusted_bundle_drafts(
        self,
        *,
        bundle: ProviderEvidenceBundle,
        provider_kind: ProviderKind,
        source_binding_id: str,
    ) -> tuple[EvidenceDraft, ...]:
        """Rewrite provider identity fields with daemon-authenticated command context."""

        drafts: list[EvidenceDraft] = []
        route_id = bundle.diagnostics.get("route_id")
        for draft in bundle.evidence:
            drafts.append(
                draft.model_copy(
                    update={
                        "provenance": draft.provenance.model_copy(
                            update={
                                "provider_key": bundle.provider_key,
                                "provider_kind": provider_kind,
                                "provider_session_id": bundle.provider_session_id,
                                "command_id": bundle.command_id,
                                "route_id": str(route_id) if route_id else draft.provenance.route_id,
                                "source_binding_id": draft.provenance.source_binding_id or source_binding_id,
                            }
                        )
                    }
                )
            )
        return tuple(drafts)

    def _index_text_by_evidence_id(self, evidence_records: tuple[EvidenceRecord, ...]) -> dict[str, str]:
        """Return canonical index text without embedding it into public metadata."""

        index_text: dict[str, str] = {}
        for evidence in evidence_records:
            if not evidence.indexable or evidence.payload.storage_uri is None:
                continue
            try:
                text = self.vault.read(evidence.payload.storage_uri).decode("utf-8").strip()
            except UnicodeDecodeError:
                continue
            if text:
                index_text[evidence.evidence_id] = text
        return index_text

    def _index_manifest(
        self,
        *,
        event_id: str,
        evidence_records: tuple[EvidenceRecord, ...],
        indexable_evidence_ids: tuple[str, ...],
    ) -> IndexManifest:
        indexed = indexable_evidence_ids
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

    def _index_committed_capture(
        self,
        *,
        envelope: EventCaptureEnvelope,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        index_text_by_evidence_id: dict[str, str],
    ) -> None:
        """Refresh search after the ledger commit without failing capture save."""

        if self.indexing is None:
            return
        try:
            receipt = self.indexing.index_capture(
                envelope=envelope,
                event=event,
                artifacts=artifacts,
                index_text_by_evidence_id=index_text_by_evidence_id,
            )
            self.ledger.save_index_receipt(
                event_id=event.event_id,
                capture_run_id=envelope.capture_run_id,
                receipt=receipt,
            )
        except Exception:
            logger.exception(
                "capture indexing failed after ledger commit",
                extra={"event_id": event.event_id, "capture_run_id": envelope.capture_run_id},
            )

    def _provider_routes(
        self, *, route_plan: ProviderRoutePlan, detected_surfaces: tuple[DetectedSurface, ...]
    ) -> tuple[ProviderRoute, ...]:
        routes: list[ProviderRoute] = []
        if route_plan.routes:
            return tuple(
                ProviderRoute(
                    route_id=route.route_id,
                    provider_key=route.provider_key,
                    provider_kind=route.provider_kind,
                    role=route.role,
                    surface_id=route.surface_id,
                    confidence=route.confidence,
                    selected=route.selected,
                    reason=route.reason,
                    target=route.target,
                )
                for route in route_plan.routes
            )
        for index, decision in enumerate(route_plan.decisions):
            selected = decision.provider_key == route_plan.selected_provider_key
            routes.append(
                ProviderRoute(
                    route_id=f"{route_plan.trigger_id}:legacy-route:{index + 1}",
                    provider_key=decision.provider_key,
                    provider_kind=(
                        ProviderKind.SYSTEM_EVIDENCE
                        if decision.provider_key.startswith("system.")
                        else ProviderKind.SOURCE
                    ),
                    role=ProviderRouteRole.PRIMARY_SOURCE if selected else ProviderRouteRole.SECONDARY_SOURCE,
                    surface_id=decision.surface_id,
                    confidence=decision.confidence,
                    selected=selected,
                    reason=decision.reason or decision.status.value,
                )
            )
        if not routes and detected_surfaces:
            surface = detected_surfaces[0]
            routes.append(
                ProviderRoute(
                    route_id=f"{route_plan.trigger_id}:surface-only",
                    provider_key="system.surface_detection",
                    provider_kind=ProviderKind.SYSTEM_EVIDENCE,
                    role=ProviderRouteRole.SYSTEM_EVIDENCE,
                    surface_id=surface.surface_id,
                    confidence=surface.confidence,
                    selected=False,
                    reason="surface_detected",
                )
            )
        return tuple(routes)

    def _fallback_source_binding(
        self,
        *,
        attempt: CaptureAttemptRequest,
        detected_surfaces: tuple[DetectedSurface, ...],
        route_plan: ProviderRoutePlan,
    ) -> SourceBinding:
        surface = next(
            (candidate for candidate in detected_surfaces if candidate.surface_id == route_plan.primary_surface_id),
            None,
        )
        if surface is None:
            surface = detected_surfaces[0] if detected_surfaces else None
        title = (
            surface.title
            if surface is not None and surface.title
            else surface.app_name if surface is not None else "Screen Capture"
        )
        return SourceBinding(
            binding_id=self.ids.new("src"),
            source_ref=SourceRef(
                source_type=SourceType.DESKTOP_WINDOW,
                title=title,
                app_name=surface.app_name if surface is not None else "macOS",
                connector_name="system.surface_detection",
                external_id=(
                    None
                    if attempt.trigger.capture_strategy == CaptureStrategy.OS_WINDOW
                    else str(surface.process_id) if surface is not None and surface.process_id is not None else None
                ),
            ),
            confidence=surface.confidence if surface is not None else 0.5,
            resolved_at=self.clock.now(),
            provider_key="system.surface_detection",
            matched_region=attempt.selection_geometry.selected_region,
        )

    def _merge_source_bindings(
        self, *, primary: SourceBinding, additional: tuple[SourceBinding, ...]
    ) -> tuple[SourceBinding, ...]:
        bindings: list[SourceBinding] = [primary]
        seen = {primary.binding_id}
        for binding in additional:
            if binding.binding_id in seen:
                continue
            bindings.append(binding)
            seen.add(binding.binding_id)
        return tuple(bindings)

    def _event_type_for_attempt(self, *, attempt: CaptureAttemptRequest, binding: SourceBinding) -> EventType:
        if (
            attempt.trigger.capture_strategy == CaptureStrategy.OS_WINDOW
            and SurfaceDetectionService.has_valid_os_window_hint(attempt.window_hints)
        ):
            return EventType.SCREEN_WINDOW_CAPTURED
        return self._event_type_for_source_binding(binding)

    def _event_type_for_source_binding(self, binding: SourceBinding) -> EventType:
        if binding.source_ref.source_type == SourceType.WEB:
            return EventType.WEBPAGE_SELECTION_CAPTURED
        if binding.source_ref.source_type == SourceType.DOCUMENT:
            return EventType.DOCUMENT_SECTION_CAPTURED
        return EventType.SCREEN_REGION_CAPTURED

    def _provider_outcomes_with_evidence(
        self,
        *,
        outcomes: tuple[ProviderCaptureOutcome, ...],
        system_bundles: tuple[ProviderEvidenceBundle, ...],
        evidence_records: tuple[EvidenceRecord, ...],
    ) -> tuple[ProviderCaptureOutcome, ...]:
        evidence_by_command = self._evidence_ids_by_command(evidence_records)
        enriched: list[ProviderCaptureOutcome] = []
        for outcome in outcomes:
            evidence_ids = evidence_by_command.get(outcome.command_id or "", ())
            enriched.append(outcome.model_copy(update={"evidence_ids": evidence_ids}))
        for bundle in system_bundles:
            error_code = bundle.diagnostics.get("error_code") if bundle.diagnostics else None
            error_message = bundle.diagnostics.get("error_message") if bundle.diagnostics else None
            enriched.append(
                ProviderCaptureOutcome(
                    provider_key=bundle.provider_key,
                    provider_kind=ProviderKind.SYSTEM_EVIDENCE,
                    role=ProviderRouteRole.SYSTEM_EVIDENCE,
                    status=self._outcome_status_for_command(bundle.status),
                    reason_code=(
                        str(error_code)
                        if error_code is not None
                        else (str(error_message) if error_message is not None else None)
                    ),
                    command_id=bundle.command_id,
                    provider_session_id=bundle.provider_session_id,
                    evidence_ids=evidence_by_command.get(bundle.command_id, ()),
                    diagnostics=bundle.diagnostics,
                )
            )
        return tuple(enriched)

    def _evidence_bundle_records(
        self,
        *,
        capture_run_id: str,
        evidence_records: tuple[EvidenceRecord, ...],
        app_bundles: tuple[ProviderEvidenceBundle, ...],
        system_bundles: tuple[ProviderEvidenceBundle, ...],
        route_plan: ProviderRoutePlan,
    ) -> tuple[EvidenceBundleRecord, ...]:
        evidence_by_command = self._evidence_ids_by_command(evidence_records)
        route_roles = {route.route_id: route.role for route in route_plan.routes}
        records: list[EvidenceBundleRecord] = []
        bundle_inputs: list[tuple[ProviderEvidenceBundle, ProviderKind, ProviderRouteRole]] = [
            (bundle, ProviderKind.SYSTEM_EVIDENCE, ProviderRouteRole.SYSTEM_EVIDENCE) for bundle in system_bundles
        ]
        for bundle in app_bundles:
            route_id = self._bundle_route_id(bundle)
            role = (
                route_roles.get(route_id, ProviderRouteRole.SECONDARY_SOURCE)
                if route_id is not None
                else ProviderRouteRole.SECONDARY_SOURCE
            )
            bundle_inputs.append((bundle, ProviderKind.SOURCE, role))
        for bundle, provider_kind, role in bundle_inputs:
            records.append(
                EvidenceBundleRecord(
                    bundle_id=self.ids.new("bun"),
                    capture_run_id=capture_run_id,
                    provider_key=bundle.provider_key,
                    provider_kind=provider_kind,
                    evidence_kind=bundle.evidence_kind,
                    status=self._outcome_status_for_command(bundle.status),
                    role=role,
                    route_id=self._bundle_route_id(bundle),
                    source_binding_id=bundle.source_binding.binding_id if bundle.source_binding is not None else None,
                    provider_session_id=bundle.provider_session_id,
                    command_id=bundle.command_id,
                    evidence_ids=evidence_by_command.get(bundle.command_id, ()),
                    completed_at=bundle.completed_at,
                    diagnostics=bundle.diagnostics,
                )
            )
        return tuple(records)

    def _evidence_ids_by_command(self, evidence_records: tuple[EvidenceRecord, ...]) -> dict[str, tuple[str, ...]]:
        grouped: dict[str, list[str]] = {}
        for evidence in evidence_records:
            command_id = evidence.provenance.command_id
            if command_id is None:
                continue
            grouped.setdefault(command_id, []).append(evidence.evidence_id)
        return {command_id: tuple(ids) for command_id, ids in grouped.items()}

    def _outcome_status_for_command(self, status: ProviderCommandStatus) -> ProviderCaptureOutcomeStatus:
        if status == ProviderCommandStatus.SUCCEEDED:
            return ProviderCaptureOutcomeStatus.SUCCEEDED
        if status == ProviderCommandStatus.TIMEOUT:
            return ProviderCaptureOutcomeStatus.TIMEOUT
        if status == ProviderCommandStatus.UNSUPPORTED:
            return ProviderCaptureOutcomeStatus.UNSUPPORTED
        if status == ProviderCommandStatus.SKIPPED:
            return ProviderCaptureOutcomeStatus.SKIPPED
        return ProviderCaptureOutcomeStatus.FAILED

    def _bundle_route_id(self, bundle: ProviderEvidenceBundle) -> str | None:
        route_id = bundle.diagnostics.get("route_id")
        return str(route_id) if route_id else None

    def _write_sidecar(self, *, artifact: Artifact, evidence: EvidenceRecord, envelope: EventCaptureEnvelope) -> None:
        sidecar = {
            "artifact": artifact.model_dump(mode="json"),
            "evidence": evidence.model_dump(mode="json"),
            "capture_run_id": envelope.capture_run_id,
            "event_id": envelope.event_id,
        }
        self.vault.write_sidecar(
            artifact_id=artifact.artifact_id,
            content=json.dumps(sidecar, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        )

    def _suffix_for_content_type(self, content_type: str) -> str:
        if "json" in content_type:
            return ".json"
        if "markdown" in content_type:
            return ".md"
        if "text" in content_type:
            return ".txt"
        if "png" in content_type:
            return ".png"
        return ".bin"

    def _cleanup_sidecars(self, artifact_ids: tuple[str, ...]) -> None:
        for artifact_id in artifact_ids:
            try:
                (self.vault.vault_dir / "manifests" / f"{artifact_id}.json").unlink(missing_ok=True)
            except OSError:
                logger.warning(
                    "failed to remove artifact sidecar after capture rollback",
                    extra={"artifact_id": artifact_id},
                    exc_info=True,
                )

    def discard_unsupported(self, attempt: CaptureAttemptRequest) -> None:
        """Discard staged screenshot for unsupported attempts.

        Args:
            attempt: Capture attempt whose staged screenshot should be removed.
        """

        self.vault.discard_staged_file(Path(attempt.staged_artifact.local_path))

    def find_by_trigger_id(self, trigger_id: str) -> tuple[ContextEvent, tuple[Artifact, ...]] | None:
        """Return existing persisted event and all artifacts for a trigger.

        Args:
            trigger_id: Stable native trigger identifier used for idempotency.

        Returns:
            Existing event and artifacts, or ``None`` when this trigger is new.
        """

        return self.captures.find_artifacts_by_trigger_id(trigger_id)

    def validate_staged_artifact(self, attempt: CaptureAttemptRequest) -> None:
        """Validate staged OS screenshot before provider work.

        Args:
            attempt: Capture attempt containing the staged screenshot path.
        """

        self.vault.validate_staged_file(Path(attempt.staged_artifact.local_path))
