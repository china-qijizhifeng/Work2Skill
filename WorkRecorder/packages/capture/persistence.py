"""Capture persistence for auditable event envelopes."""

from __future__ import annotations

import json
import logging
from typing import Protocol

from packages.artifacts.vault import LocalArtifactVault
from packages.capture.appshot_composer import SystemAppshotComposer
from packages.capture.jobs import CaptureJobPlanner
from packages.capture.persistence_internals import _CapturePersistenceInternals
from packages.capture.selection_text_enrichment import SelectionTextEnrichmentService
from packages.capture.text_enrichment import TextEnrichmentService
from packages.contracts import (
    Artifact,
    CaptureAttemptRequest,
    CapturePostCommitOutboxTask,
    ContextEvent,
    DetectedSurface,
    EnrichmentRecord,
    EventCaptureEnvelope,
    EventStatus,
    EventType,
    EvidenceBundleRecord,
    EvidenceDraft,
    EvidenceKind,
    EvidenceRecord,
    PolicySnapshot,
    ProviderCaptureOutcome,
    ProviderCaptureOutcomeStatus,
    ProviderCommandRun,
    ProviderCommandStatus,
    ProviderEvidenceBundle,
    ProviderKind,
    ProviderRoutePlan,
    ProviderRouteRole,
    SourceBinding,
    SourceRef,
    SourceType,
    TriggerEnvelope,
    UserRef,
)
from packages.contracts.common import JsonScalar
from packages.evidence.policy import EvidencePolicyService
from packages.evidence.redaction import SensitiveTextRedactor
from packages.indexing import IndexingService
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from packages.storage.capture_repository import CaptureRepository
from packages.storage.job_repository import CaptureJobRepository
from packages.storage.ledger_repository import CaptureLedgerRepository

logger = logging.getLogger(__name__)
SYSTEM_APPSHOT_PROVIDER_KEY = "system.appshot"


class CapturePostCommitTaskPlanner(Protocol):
    """Plan durable post-commit tasks without executing handler work."""

    def plan_after_capture_committed(
        self,
        *,
        attempt: CaptureAttemptRequest,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        envelope: EventCaptureEnvelope,
    ) -> tuple[CapturePostCommitOutboxTask, ...]: ...


class CapturePersistenceService(_CapturePersistenceInternals):
    """Persist accepted capture attempts as auditable envelopes."""

    def __init__(
        self,
        *,
        captures: CaptureRepository,
        jobs: CaptureJobRepository,
        ledger: CaptureLedgerRepository,
        vault: LocalArtifactVault,
        ids: IdFactory,
        clock: Clock,
        evidence_policy: EvidencePolicyService | None = None,
        indexing: IndexingService | None = None,
        post_commit_task_planner: CapturePostCommitTaskPlanner | None = None,
    ) -> None:
        self.captures = captures
        self.jobs = jobs
        self.ledger = ledger
        self.vault = vault
        self.ids = ids
        self.clock = clock
        self.evidence_policy = evidence_policy or EvidencePolicyService()
        self.indexing = indexing
        self.text_redactor = SensitiveTextRedactor()
        self.appshot_composer = SystemAppshotComposer(vault=vault)
        self.job_planner = CaptureJobPlanner(ids=ids)
        self.selection_text_enrichment = SelectionTextEnrichmentService(
            vault=vault,
            clock=clock,
            redactor=self.text_redactor,
        )
        self.text_enrichment = TextEnrichmentService(
            vault=vault,
            clock=clock,
            redactor=self.text_redactor,
        )
        self.post_commit_task_planner = post_commit_task_planner

    def save_accepted(
        self,
        *,
        attempt: CaptureAttemptRequest,
        app_bundles: tuple[ProviderEvidenceBundle, ...],
        system_bundles: tuple[ProviderEvidenceBundle, ...],
        provider_outcomes: tuple[ProviderCaptureOutcome, ...],
        route_plan: ProviderRoutePlan,
        detected_surfaces: tuple[DetectedSurface, ...],
        command_runs: tuple[ProviderCommandRun, ...],
        primary_source_binding: SourceBinding | None = None,
        source_bindings: tuple[SourceBinding, ...] = (),
        policy_decision_id: str | None = None,
    ) -> tuple[ContextEvent, tuple[Artifact, ...], EventCaptureEnvelope]:
        """Persist one accepted capture run atomically.

        Args:
            attempt: Validated attempt from the native shell.
            app_bundles: Optional app/source evidence bundles.
            system_bundles: System evidence bundles collected for this attempt.
            provider_outcomes: Capture outcomes for selected/skipped app routes.
            route_plan: Provider route diagnostics.
            detected_surfaces: Surface detection result.
            command_runs: Provider command diagnostics.
            primary_source_binding: Optional primary source binding from a successful provider.
            source_bindings: Additional source bindings from secondary providers.
            policy_decision_id: Optional create-event policy decision.

        Returns:
            Persisted event, artifacts, and canonical event capture envelope.

        Raises:
            RuntimeError: Existing idempotent capture rows are missing their envelope.
            ValueError: Accepted provider evidence does not contain a source binding.
        """

        return self._save_accepted_impl(
            attempt=attempt,
            app_bundles=app_bundles,
            system_bundles=system_bundles,
            provider_outcomes=provider_outcomes,
            route_plan=route_plan,
            detected_surfaces=detected_surfaces,
            command_runs=command_runs,
            primary_source_binding=primary_source_binding,
            source_bindings=source_bindings,
            policy_decision_id=policy_decision_id,
        )

    def _save_accepted_impl(
        self,
        *,
        attempt: CaptureAttemptRequest,
        app_bundles: tuple[ProviderEvidenceBundle, ...],
        system_bundles: tuple[ProviderEvidenceBundle, ...],
        provider_outcomes: tuple[ProviderCaptureOutcome, ...],
        route_plan: ProviderRoutePlan,
        detected_surfaces: tuple[DetectedSurface, ...],
        command_runs: tuple[ProviderCommandRun, ...],
        primary_source_binding: SourceBinding | None = None,
        source_bindings: tuple[SourceBinding, ...] = (),
        policy_decision_id: str | None = None,
    ) -> tuple[ContextEvent, tuple[Artifact, ...], EventCaptureEnvelope]:
        """Persist one accepted capture run atomically.

        Args:
            attempt: Validated attempt from the native shell.
            app_bundles: Optional app/source evidence bundles.
            system_bundles: System evidence bundles collected for this attempt.
            provider_outcomes: Capture outcomes for selected/skipped app routes.
            route_plan: Provider route diagnostics.
            detected_surfaces: Surface detection result.
            command_runs: Provider command diagnostics.
            primary_source_binding: Optional primary source binding from a successful provider.
            source_bindings: Additional source bindings from secondary providers.
            policy_decision_id: Optional create-event policy decision.

        Returns:
            Persisted event, artifacts, and canonical event capture envelope.

        Raises:
            RuntimeError: Existing idempotent capture rows are missing their envelope.
        """

        existing = self.find_by_trigger_id(attempt.trigger.trigger_id)
        if existing is not None:
            event, existing_artifacts = existing
            envelope = self.ledger.get_envelope_by_event_id(event.event_id)
            if envelope is None:
                raise RuntimeError("existing capture is missing its auditable envelope")
            self._ensure_existing_index(event=event, artifacts=existing_artifacts, envelope=envelope)
            return event, existing_artifacts, envelope
        now = self.clock.now()
        event_id = self.ids.new("evt")
        capture_run_id = self.ids.new("run")
        source_binding = primary_source_binding or self._fallback_source_binding(
            attempt=attempt,
            detected_surfaces=detected_surfaces,
            route_plan=route_plan,
        )
        all_source_bindings = self._merge_source_bindings(
            primary=source_binding,
            additional=(
                *source_bindings,
                *(bundle.source_binding for bundle in app_bundles if bundle.source_binding is not None),
            ),
        )
        event_type = self._event_type_for_attempt(attempt=attempt, binding=source_binding)
        trigger = _trigger_with_active_capture_candidate(attempt)
        event = ContextEvent(
            event_id=event_id,
            event_type=event_type,
            trigger=trigger.model_copy(update={"intent_text": attempt.intent_text or trigger.intent_text}),
            source_binding=source_binding,
            status=EventStatus.PENDING_ENRICHMENT,
            intent_text=attempt.intent_text or trigger.intent_text,
            created_at=now,
            updated_at=now,
            user=UserRef.from_actor(attempt.actor),
        )
        artifacts: list[Artifact] = []
        evidence_records: list[EvidenceRecord] = []
        enrichment_records: list[EnrichmentRecord] = []
        sidecar_artifact_ids: list[str] = []
        try:
            all_drafts: list[EvidenceDraft] = []
            appshot_drafts: list[EvidenceDraft] = []
            for bundle in system_bundles:
                trusted_system_drafts = self._trusted_bundle_drafts(
                    bundle=bundle,
                    provider_kind=ProviderKind.SYSTEM_EVIDENCE,
                    source_binding_id=source_binding.binding_id,
                )
                for draft in trusted_system_drafts:
                    if draft.kind == EvidenceKind.SYSTEM_APPSHOT:
                        appshot_drafts.append(draft)
                    else:
                        all_drafts.append(draft)
            for bundle in app_bundles:
                all_drafts.extend(
                    self._trusted_bundle_drafts(
                        bundle=bundle,
                        provider_kind=ProviderKind.SOURCE,
                        source_binding_id=(bundle.source_binding or source_binding).binding_id,
                    )
                )
            for draft in all_drafts:
                artifact, evidence = self._persist_draft(
                    attempt=attempt,
                    event=event,
                    capture_run_id=capture_run_id,
                    source_binding_id=source_binding.binding_id,
                    draft=draft,
                )
                artifacts.append(artifact)
                evidence_records.append(evidence)
            for draft in appshot_drafts:
                appshot_draft = self.appshot_composer.enrich(
                    draft=draft,
                    evidence_records=tuple(evidence_records),
                    artifacts=tuple(artifacts),
                    system_bundles=system_bundles,
                )
                artifact, evidence = self._persist_draft(
                    attempt=attempt,
                    event=event,
                    capture_run_id=capture_run_id,
                    source_binding_id=source_binding.binding_id,
                    draft=appshot_draft,
                )
                artifacts.append(artifact)
                evidence_records.append(evidence)
            selection_derivation = self.selection_text_enrichment.derive(
                attempt=attempt,
                event=event,
                capture_run_id=capture_run_id,
                source_binding_id=source_binding.binding_id,
                inputs=tuple(evidence_records),
            )
            if selection_derivation is not None:
                selection_artifact, selection_evidence = self._persist_draft(
                    attempt=attempt,
                    event=event,
                    capture_run_id=capture_run_id,
                    source_binding_id=source_binding.binding_id,
                    draft=selection_derivation.draft,
                )
                artifacts.append(selection_artifact)
                evidence_records.append(selection_evidence)
                selection_enrichment = selection_derivation.enrichment_record(
                    ids=self.ids,
                    event_id=event.event_id,
                    capture_run_id=capture_run_id,
                    output_evidence_id=selection_evidence.evidence_id,
                )
                enrichment_records.append(selection_enrichment)
            clean_page_derivation = self.text_enrichment.derive_clean_page_text(
                event=event,
                source_binding_id=source_binding.binding_id,
                inputs=tuple(evidence_records),
            )
            if clean_page_derivation is not None:
                clean_artifact, clean_evidence = self._persist_draft(
                    attempt=attempt,
                    event=event,
                    capture_run_id=capture_run_id,
                    source_binding_id=source_binding.binding_id,
                    draft=clean_page_derivation.draft,
                )
                artifacts.append(clean_artifact)
                evidence_records.append(clean_evidence)
                enrichment_records.append(
                    clean_page_derivation.enrichment_record(
                        ids=self.ids,
                        event_id=event.event_id,
                        capture_run_id=capture_run_id,
                        output_evidence_id=clean_evidence.evidence_id,
                    )
                )
            canonical_derivation = self.text_enrichment.derive_canonical_text(
                event=event,
                source_binding_id=source_binding.binding_id,
                inputs=tuple(evidence_records),
            )
            if canonical_derivation is not None:
                canonical_artifact, canonical_evidence = self._persist_draft(
                    attempt=attempt,
                    event=event,
                    capture_run_id=capture_run_id,
                    source_binding_id=source_binding.binding_id,
                    draft=canonical_derivation.draft,
                )
                artifacts.append(canonical_artifact)
                evidence_records.append(canonical_evidence)
                enrichment_records.append(
                    canonical_derivation.enrichment_record(
                        ids=self.ids,
                        event_id=event.event_id,
                        capture_run_id=capture_run_id,
                        output_evidence_id=canonical_evidence.evidence_id,
                    )
                )
            jobs = self.job_planner.jobs_for_event(event.event_id, now=now)
            saved_event = event.model_copy(update={"status": EventStatus.AGENT_READY, "updated_at": now})
            saved_artifacts = tuple(artifacts)
            index_text = self._index_text_by_evidence_id(tuple(evidence_records))
            index_manifest = self._index_manifest(
                event_id=event.event_id,
                evidence_records=tuple(evidence_records),
                indexable_evidence_ids=tuple(index_text),
            )
            enriched_outcomes = self._provider_outcomes_with_evidence(
                outcomes=provider_outcomes,
                system_bundles=system_bundles,
                evidence_records=tuple(evidence_records),
            )
            evidence_bundles = self._evidence_bundle_records(
                capture_run_id=capture_run_id,
                evidence_records=tuple(evidence_records),
                app_bundles=app_bundles,
                system_bundles=system_bundles,
                route_plan=route_plan,
            )
            system_appshot_evidence_id = next(
                (
                    evidence.evidence_id
                    for evidence in evidence_records
                    if evidence.kind == EvidenceKind.SYSTEM_APPSHOT
                    and evidence.provenance.provider_key == SYSTEM_APPSHOT_PROVIDER_KEY
                ),
                None,
            )
            envelope = EventCaptureEnvelope(
                capture_run_id=capture_run_id,
                capture_revision=f"appshot:{attempt.trigger.trigger_id}",
                event_id=event.event_id,
                event_type=event_type,
                trigger=trigger,
                selection_geometry=attempt.selection_geometry,
                detected_surfaces=detected_surfaces,
                route_plan=route_plan,
                provider_routes=self._provider_routes(route_plan=route_plan, detected_surfaces=detected_surfaces),
                provider_command_runs=command_runs,
                provider_outcomes=enriched_outcomes,
                source_bindings=all_source_bindings,
                evidence_bundles=evidence_bundles,
                system_appshot_evidence_id=system_appshot_evidence_id,
                system_evidence_bundle_ids=tuple(
                    bundle.bundle_id
                    for bundle in evidence_bundles
                    if bundle.provider_kind == ProviderKind.SYSTEM_EVIDENCE
                ),
                system_evidence_ids=tuple(
                    evidence.evidence_id
                    for evidence in evidence_records
                    if evidence.provenance.provider_kind == ProviderKind.SYSTEM_EVIDENCE
                ),
                app_evidence_ids=tuple(
                    evidence.evidence_id
                    for evidence in evidence_records
                    if evidence.provenance.provider_kind == ProviderKind.SOURCE
                ),
                enrichment_records=tuple(enrichment_records),
                evidence_records=tuple(evidence_records),
                artifact_ids=tuple(artifact.artifact_id for artifact in artifacts),
                index_manifest=index_manifest,
                policy_snapshot=PolicySnapshot(
                    create_event_decision_id=policy_decision_id,
                    artifact_policy_version="artifact_policy_v2",
                ),
                context_event=saved_event,
                jobs=jobs,
                created_at=now,
                updated_at=now,
            )
            for artifact, evidence in zip(saved_artifacts, evidence_records, strict=False):
                self._write_sidecar(artifact=artifact, evidence=evidence, envelope=envelope)
                sidecar_artifact_ids.append(artifact.artifact_id)
            post_commit_tasks = self._plan_post_commit_tasks(
                attempt=attempt,
                event=saved_event,
                artifacts=saved_artifacts,
                envelope=envelope,
            )
            self.ledger.save_full_capture(
                attempt=attempt,
                envelope=envelope,
                event=saved_event,
                artifacts=saved_artifacts,
                jobs=jobs,
                index_text_by_evidence_id=index_text,
                post_commit_tasks=post_commit_tasks,
            )
            self._index_committed_capture(
                envelope=envelope,
                event=saved_event,
                artifacts=saved_artifacts,
                index_text_by_evidence_id=index_text,
            )
            return saved_event, saved_artifacts, envelope
        except Exception:
            logger.exception(
                "capture transaction failed after artifact writes",
                extra={"trigger_id": attempt.trigger.trigger_id, "artifact_count": len(artifacts)},
            )
            self._cleanup_sidecars(tuple(sidecar_artifact_ids))
            raise

    def _plan_post_commit_tasks(
        self,
        *,
        attempt: CaptureAttemptRequest,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        envelope: EventCaptureEnvelope,
    ) -> tuple[CapturePostCommitOutboxTask, ...]:
        if self.post_commit_task_planner is None:
            return ()
        try:
            return self.post_commit_task_planner.plan_after_capture_committed(
                attempt=attempt,
                event=event,
                artifacts=artifacts,
                envelope=envelope,
            )
        except Exception:
            logger.exception(
                "capture post-commit outbox planning failed",
                extra={"trigger_id": attempt.trigger.trigger_id, "event_id": event.event_id},
            )
            return ()

    def _ensure_existing_index(
        self,
        *,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        envelope: EventCaptureEnvelope,
    ) -> None:
        """Repair idempotent capture retries that predate an index receipt."""

        if self.indexing is None:
            return
        index_text = self._index_text_by_evidence_id(envelope.evidence_records)
        receipt = self.indexing.index_capture(
            envelope=envelope,
            event=event,
            artifacts=artifacts,
            index_text_by_evidence_id=index_text,
        )
        self.ledger.save_index_receipt(
            event_id=event.event_id,
            capture_run_id=envelope.capture_run_id,
            receipt=receipt,
        )

    def record_unsupported(
        self,
        *,
        attempt: CaptureAttemptRequest,
        route_plan: ProviderRoutePlan,
        detected_surfaces: tuple[DetectedSurface, ...],
        unsupported_reason: object,
        command_runs: tuple[ProviderCommandRun, ...] = (),
    ) -> None:
        """Persist diagnostics for an attempt that does not create an event.

        Args:
            attempt: Capture attempt rejected by routing or policy.
            route_plan: Provider route diagnostics that explain the rejection.
            detected_surfaces: Surfaces detected under the selected region.
            unsupported_reason: Typed reason or value to store in diagnostics.
            command_runs: Provider command attempts made before rejection.
        """

        now = self.clock.now()
        payload = {
            "schema_version": 1,
            "capture_run_id": self.ids.new("run"),
            "trigger": attempt.trigger.model_dump(mode="json"),
            "selection_geometry": attempt.selection_geometry.model_dump(mode="json"),
            "detected_surfaces": [surface.model_dump(mode="json") for surface in detected_surfaces],
            "route_plan": route_plan.model_dump(mode="json"),
            "provider_command_runs": [command.model_dump(mode="json") for command in command_runs],
            "unsupported_reason": str(getattr(unsupported_reason, "value", unsupported_reason)),
            "created_at": now.isoformat(),
        }
        self.ledger.save_unsupported_attempt(
            attempt=attempt,
            capture_run_id=str(payload["capture_run_id"]),
            status="unsupported",
            envelope_payload=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            created_at=now.isoformat(),
        )


def _trigger_with_active_capture_candidate(attempt: CaptureAttemptRequest) -> TriggerEnvelope:
    candidate_id = attempt.active_capture.candidate_id if attempt.active_capture is not None else None
    if not isinstance(candidate_id, str) or not candidate_id:
        return attempt.trigger
    if attempt.trigger.metadata.get("active_capture_candidate_id") == candidate_id:
        return attempt.trigger
    metadata: dict[str, JsonScalar] = dict(attempt.trigger.metadata)
    metadata["active_capture_candidate_id"] = candidate_id
    return attempt.trigger.model_copy(update={"metadata": metadata})
