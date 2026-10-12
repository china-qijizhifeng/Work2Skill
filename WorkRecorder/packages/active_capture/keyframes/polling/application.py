"""Application services for adaptive-settle live polling."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from packages.active_capture.application.recording_projection import RecordingPublicProjector
from packages.active_capture.keyframes.polling.adapters import DegradedSettleSampleProvider
from packages.active_capture.keyframes.polling.domain import SettleStabilityStateMachine
from packages.active_capture.keyframes.polling.ports import SettlePollingRepository, SettleSampleProvider
from packages.contracts import (
    ActiveCaptureSession,
    AdaptiveSettleWindow,
    ContextKeyframe,
    KeyframeCaptureInstruction,
    KeyframeDropReason,
    KeyframeQualityReport,
    KeyframeTimingConfig,
    KeyframeTriggerCandidate,
    KeyframeTriggerCandidateStatus,
    PendingKeyframeCaptureInstructionsResponse,
    PollKeyframeCaptureInstructionsCommand,
    SettleAuditRecord,
    SettleDecision,
    SettleDecisionStatus,
    SettlePollingPlan,
    SettleProbeSnapshot,
    SettleSample,
    SettleSampleStatus,
    SettleSignalKind,
    SettleStopReason,
    TextDiffSummary,
    VisualDiffSummary,
    VisualProbeMode,
)
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

logger = logging.getLogger(__name__)

_PENDING_STATES = {"pending", "observing"}
_READY_STATES = {"ready"}
_CLAIMED_STATE = "capturing"


@dataclass(frozen=True)
class SettleCandidateClaimer:
    """Select pending adaptive-settle candidates without widening ingest ports.

    Attributes:
        repository: Narrow polling repository used to batch-read active trigger candidates.
    """

    repository: SettlePollingRepository

    def candidates(self, *, session_id: str, limit: int, now_monotonic_ms: int) -> tuple[KeyframeTriggerCandidate, ...]:
        active = self.repository.list_active_trigger_candidates_for_session(session_id, limit=max(limit * 4, 32))
        return tuple(
            candidate
            for candidate in active
            if self._claimable(candidate=candidate, now_monotonic_ms=now_monotonic_ms) and candidate.keyframe_id is None
        )[:limit]

    def _claimable(self, *, candidate: KeyframeTriggerCandidate, now_monotonic_ms: int) -> bool:
        state = candidate.metadata.get("settle_live_polling_state")
        if state in {*_PENDING_STATES, *_READY_STATES}:
            return True
        if state != _CLAIMED_STATE:
            return False
        expires = candidate.metadata.get("settle_capture_claim_expires_monotonic_ms")
        return isinstance(expires, int | float) and int(expires) <= now_monotonic_ms


class SettleFinalizer:
    """Apply settle decisions to trigger candidates."""

    def __init__(
        self,
        *,
        repository: SettlePollingRepository,
        ids: IdFactory,
        projector: RecordingPublicProjector,
        capture_claim_lease_ms: int,
    ) -> None:
        self.repository = repository
        self.ids = ids
        self.projector = projector
        self.capture_claim_lease_ms = capture_claim_lease_ms

    def finalize(
        self,
        *,
        candidate: KeyframeTriggerCandidate,
        decision: SettleDecision,
        now_monotonic_ms: int,
    ) -> KeyframeTriggerCandidate:
        metadata = candidate.metadata | {
            "settle_live_polling_state": self._state_for_decision(decision),
            "settle_decision_status": decision.status.value,
            "settle_stop_reason": decision.stop_reason.value,
            "settle_sample_count": decision.sample_count,
            "settle_stable_sample_count": decision.stable_sample_count,
            "settle_needs_review": decision.needs_review,
        }
        update: dict[str, object] = {
            "metadata": metadata,
            "diagnostics": tuple(dict.fromkeys((*candidate.diagnostics, *decision.diagnostics))),
        }
        if decision.ready_to_capture:
            update["diff"] = decision.diff
            update["quality"] = decision.quality or KeyframeQualityReport(
                confidence=0.5,
                diagnostics=("settle polling decision did not include quality",),
            )
            update["debounce_until_monotonic_ms"] = decision.capture_after_monotonic_ms
        elif decision.status in {SettleDecisionStatus.SUPPRESSED, SettleDecisionStatus.FAILED}:
            update["status"] = KeyframeTriggerCandidateStatus.DROPPED
            update["drop_reason"] = self._drop_reason(decision.stop_reason)
            update["keep_reason"] = None
        saved = self.repository.save_settle_candidate_decision(
            candidate=candidate.model_copy(update=update),
            now_monotonic_ms=now_monotonic_ms,
        )
        logger.info(
            "active capture settle candidate finalized",
            extra={
                "session_id": saved.session_id,
                "candidate_id": saved.candidate_id,
                "settle_status": decision.status.value,
                "stop_reason": decision.stop_reason.value,
            },
        )
        return saved

    def instruction_for(self, candidate: KeyframeTriggerCandidate) -> KeyframeCaptureInstruction | None:
        return self.projector.capture_instruction_for_candidate(candidate, allow_claimed=True)

    def claim_for_capture(
        self, *, candidate: KeyframeTriggerCandidate, now_monotonic_ms: int
    ) -> KeyframeTriggerCandidate | None:
        claim_id = self.ids.new("stlc")
        return self.repository.claim_settle_candidate_for_capture(
            candidate_id=candidate.candidate_id,
            claim_id=claim_id,
            now_monotonic_ms=now_monotonic_ms,
            lease_ms=self.capture_claim_lease_ms,
        )

    def drop_expired_capture_claim(
        self, *, candidate: KeyframeTriggerCandidate, now_monotonic_ms: int
    ) -> KeyframeTriggerCandidate:
        diagnostics = tuple(
            dict.fromkeys((*candidate.diagnostics, "capture instruction claim expired before keyframe commit"))
        )
        metadata = candidate.metadata | {
            "settle_live_polling_state": "closed",
            "settle_stop_reason": SettleStopReason.TIMEOUT.value,
            "settle_decision_status": SettleDecisionStatus.FAILED.value,
            "settle_needs_review": True,
        }
        dropped = candidate.model_copy(
            update={
                "status": KeyframeTriggerCandidateStatus.DROPPED,
                "drop_reason": KeyframeDropReason.ADAPTIVE_TIMEOUT,
                "keep_reason": None,
                "metadata": metadata,
                "diagnostics": diagnostics,
            }
        )
        saved = self.repository.save_settle_candidate_decision(
            candidate=dropped,
            now_monotonic_ms=now_monotonic_ms,
        )
        logger.warning(
            "active capture settle capture claim expired",
            extra={"session_id": saved.session_id, "candidate_id": saved.candidate_id},
        )
        return saved

    def _state_for_decision(self, decision: SettleDecision) -> str:
        if decision.ready_to_capture:
            return "ready"
        if decision.status == SettleDecisionStatus.OBSERVING:
            return "observing"
        return "closed"

    def _drop_reason(self, reason: SettleStopReason) -> KeyframeDropReason:
        match reason:
            case SettleStopReason.BUDGET_EXCEEDED:
                return KeyframeDropReason.BUDGET_EXCEEDED
            case SettleStopReason.SENSITIVE_SURFACE:
                return KeyframeDropReason.SENSITIVE_SURFACE
            case SettleStopReason.SCOPE_LOST:
                return KeyframeDropReason.SCOPE_LOST
            case SettleStopReason.TIMEOUT:
                return KeyframeDropReason.ADAPTIVE_TIMEOUT
            case _:
                return KeyframeDropReason.LOW_INFORMATION_GAIN


class AdaptiveSettlePollingService:
    """Poll accepted adaptive-settle candidates and release capture instructions."""

    def __init__(
        self,
        *,
        repository: SettlePollingRepository,
        ids: IdFactory,
        clock: Clock,
        config: KeyframeTimingConfig,
        sample_provider: SettleSampleProvider | None = None,
        projector: RecordingPublicProjector | None = None,
        state_machine: SettleStabilityStateMachine | None = None,
    ) -> None:
        self.repository = repository
        self.ids = ids
        self.clock = clock
        self.config = config
        self.sample_provider = sample_provider or DegradedSettleSampleProvider(ids=ids, clock=clock)
        self.projector = projector or RecordingPublicProjector()
        self.claimer = SettleCandidateClaimer(repository=repository)
        self.finalizer = SettleFinalizer(
            repository=repository,
            ids=ids,
            projector=self.projector,
            capture_claim_lease_ms=config.settle_capture_claim_lease_ms,
        )
        self.state_machine = state_machine or SettleStabilityStateMachine.default(config)

    def poll_session(
        self,
        *,
        session: ActiveCaptureSession,
        command: PollKeyframeCaptureInstructionsCommand,
    ) -> PendingKeyframeCaptureInstructionsResponse:
        if not self.config.settle_live_polling_enabled:
            return PendingKeyframeCaptureInstructionsResponse()
        now_monotonic_ms = command.now_monotonic_ms
        ready: list[KeyframeCaptureInstruction] = []
        observed = 0
        probe_required = 0
        for candidate in self.claimer.candidates(
            session_id=session.session_id, limit=command.limit, now_monotonic_ms=now_monotonic_ms
        ):
            observed += 1
            if candidate.metadata.get("settle_live_polling_state") == _CLAIMED_STATE:
                self.finalizer.drop_expired_capture_claim(candidate=candidate, now_monotonic_ms=now_monotonic_ms)
                continue
            if candidate.metadata.get("settle_live_polling_state") in {*_READY_STATES, _CLAIMED_STATE}:
                claimed = self.finalizer.claim_for_capture(candidate=candidate, now_monotonic_ms=now_monotonic_ms)
                if claimed is not None and (instruction := self.finalizer.instruction_for(claimed)):
                    ready.append(instruction)
                continue
            plan = self._plan_from_candidate(candidate=candidate, now=self.clock.now())
            baseline = self._baseline_keyframe(plan)
            samples = self._existing_samples(candidate.candidate_id)
            new_sample: SettleSample | None = None
            due_for_sample = self._is_due_for_sample(plan=plan, samples=samples, now_monotonic_ms=now_monotonic_ms)
            if due_for_sample:
                probe_required += 1
                new_sample = self._sample_from_probe_snapshot(
                    command.probe_snapshot,
                    plan=plan,
                    candidate=candidate,
                    prior_samples=samples,
                )
                if new_sample is None and command.allow_degraded_sample:
                    new_sample = self.sample_provider.sample(
                        plan=plan,
                        candidate=candidate,
                        baseline=baseline,
                        now_monotonic_ms=now_monotonic_ms,
                    )
                if new_sample is not None:
                    samples = (*samples, new_sample)
            decision = self.state_machine.decide(plan=plan, samples=samples, now_monotonic_ms=now_monotonic_ms)
            self._audit(plan=plan, sample=new_sample, decision=decision)
            saved = self.finalizer.finalize(candidate=candidate, decision=decision, now_monotonic_ms=now_monotonic_ms)
            if decision.ready_to_capture and (instruction := self.finalizer.instruction_for(saved)) is not None:
                claimed = self.finalizer.claim_for_capture(candidate=saved, now_monotonic_ms=now_monotonic_ms)
                if claimed is not None and (instruction := self.finalizer.instruction_for(claimed)):
                    ready.append(instruction)
        return PendingKeyframeCaptureInstructionsResponse(
            instructions=tuple(ready),
            observed_candidate_count=observed,
            ready_candidate_count=len(ready),
            probe_required_candidate_count=probe_required,
        )

    def _plan_from_candidate(self, *, candidate: KeyframeTriggerCandidate, now: datetime) -> SettlePollingPlan:
        min_delay = int(candidate.metadata.get("settle_min_delay_ms") or self.config.settle_min_delay_ms)
        max_wait = int(candidate.metadata.get("settle_max_wait_ms") or self.config.settle_max_wait_ms)
        execute_after = candidate.metadata.get("settle_execute_after_monotonic_ms")
        deadline = candidate.metadata.get("settle_deadline_monotonic_ms")
        window = AdaptiveSettleWindow(
            min_delay_ms=min_delay,
            max_wait_ms=max_wait,
            poll_interval_ms=int(
                candidate.metadata.get("settle_poll_interval_ms") or self.config.settle_poll_interval_ms
            ),
            required_stable_samples=int(
                candidate.metadata.get("settle_required_stable_samples") or self.config.settle_required_stable_samples
            ),
            execute_after_monotonic_ms=(
                int(execute_after) if isinstance(execute_after, int | float) else candidate.debounce_until_monotonic_ms
            ),
            deadline_monotonic_ms=(
                int(deadline)
                if isinstance(deadline, int | float)
                else (
                    candidate.occurred_at_monotonic_ms + max_wait
                    if candidate.occurred_at_monotonic_ms is not None
                    else None
                )
            ),
        )
        strategy_value = str(candidate.metadata.get("settle_probe_strategy") or self.config.settle_probe_strategy.value)
        try:
            probe_strategy = VisualProbeMode(strategy_value)
        except ValueError:
            probe_strategy = self.config.settle_probe_strategy
        timeout_capture = candidate.metadata.get("settle_timeout_capture_enabled")
        return SettlePollingPlan(
            plan_id=str(candidate.metadata.get("settle_polling_plan_id") or f"stlp_{candidate.candidate_id}"),
            candidate_id=candidate.candidate_id,
            session_id=candidate.session_id,
            action_id=candidate.action_id,
            trigger_kind=candidate.trigger_kind,
            role=candidate.role,
            settle_window=window,
            probe_strategy=probe_strategy,
            baseline_keyframe_id=str(candidate.metadata.get("baseline_keyframe_id") or "") or None,
            sample_budget=int(candidate.metadata.get("settle_sample_budget") or self.config.settle_sample_budget),
            timeout_capture_enabled=timeout_capture if isinstance(timeout_capture, bool) else None,
            created_at=now,
            policy_version=candidate.policy_version,
        )

    def _baseline_keyframe(self, plan: SettlePollingPlan) -> ContextKeyframe | None:
        if plan.baseline_keyframe_id is not None:
            return self.repository.get_keyframe(plan.baseline_keyframe_id)
        return self.repository.get_latest_keyframe_before(
            session_id=plan.session_id,
            occurred_at_monotonic_ms=plan.settle_window.execute_after_monotonic_ms,
        )

    def _existing_samples(self, candidate_id: str) -> tuple[SettleSample, ...]:
        samples: list[SettleSample] = []
        seen: set[str] = set()
        for record in self.repository.list_settle_audits_for_candidate(candidate_id):
            if record.sample is None or record.sample.sample_id in seen:
                continue
            seen.add(record.sample.sample_id)
            samples.append(record.sample)
        return tuple(samples)

    def _sample_from_probe_snapshot(
        self,
        snapshot: SettleProbeSnapshot | None,
        *,
        plan: SettlePollingPlan,
        candidate: KeyframeTriggerCandidate,
        prior_samples: tuple[SettleSample, ...],
    ) -> SettleSample | None:
        if snapshot is None:
            return None
        snapshot = self._filtered_probe_snapshot(snapshot=snapshot, plan=plan)
        if snapshot is None:
            return None
        latest = prior_samples[-1] if prior_samples else None
        status = self._status_from_snapshot(snapshot=snapshot, previous=latest)
        signal_kind = self._signal_kind_for_snapshot(snapshot)
        return SettleSample(
            sample_id=snapshot.sample_id or self.ids.new("kfs"),
            plan_id=plan.plan_id,
            candidate_id=candidate.candidate_id,
            session_id=candidate.session_id,
            sampled_at=self.clock.now(),
            sampled_at_monotonic_ms=snapshot.sampled_at_monotonic_ms,
            status=status,
            signal_kind=signal_kind,
            visual=self._visual_with_status(snapshot=snapshot, previous=latest, status=status),
            text=self._text_with_status(snapshot=snapshot, previous=latest, status=status),
            readiness=snapshot.readiness,
            diagnostics=snapshot.diagnostics,
            metadata=snapshot.metadata | {"sample_origin": "native_probe_snapshot"},
        )

    def _filtered_probe_snapshot(
        self, *, snapshot: SettleProbeSnapshot, plan: SettlePollingPlan
    ) -> SettleProbeSnapshot | None:
        visual_allowed = self.config.settle_visual_diff_enabled and plan.probe_strategy in {
            VisualProbeMode.HYBRID,
            VisualProbeMode.VISUAL_PROBE_ONLY,
        }
        text_allowed = self.config.settle_text_diff_enabled and plan.probe_strategy in {
            VisualProbeMode.HYBRID,
            VisualProbeMode.TEXT_PROVIDER_ONLY,
        }
        readiness_allowed = self.config.settle_provider_readiness_enabled and plan.probe_strategy in {
            VisualProbeMode.HYBRID,
            VisualProbeMode.TEXT_PROVIDER_ONLY,
        }
        visual = snapshot.visual if visual_allowed else None
        text = snapshot.text if text_allowed else None
        readiness = snapshot.readiness if readiness_allowed else None
        if visual is None and text is None and readiness is None:
            return None
        return snapshot.model_copy(update={"visual": visual, "text": text, "readiness": readiness})

    def _status_from_snapshot(
        self, *, snapshot: SettleProbeSnapshot, previous: SettleSample | None
    ) -> SettleSampleStatus:
        visual_status = self._fingerprint_status(
            current=snapshot.visual.sample_fingerprint if snapshot.visual is not None else None,
            previous=(
                previous.visual.sample_fingerprint if previous is not None and previous.visual is not None else None
            ),
        )
        text_status = self._fingerprint_status(
            current=snapshot.text.text_fingerprint if snapshot.text is not None else None,
            previous=previous.text.text_fingerprint if previous is not None and previous.text is not None else None,
        )
        if SettleSampleStatus.CHANGED in {visual_status, text_status}:
            return SettleSampleStatus.CHANGED
        if SettleSampleStatus.STABLE in {visual_status, text_status}:
            return SettleSampleStatus.STABLE
        if snapshot.visual is not None or snapshot.text is not None:
            return SettleSampleStatus.OBSERVED
        if snapshot.readiness is not None:
            return SettleSampleStatus.OBSERVED
        return SettleSampleStatus.DEGRADED

    def _fingerprint_status(self, *, current: str | None, previous: str | None) -> SettleSampleStatus:
        if not current:
            return SettleSampleStatus.OBSERVED
        if previous is None:
            return SettleSampleStatus.OBSERVED
        if current == previous:
            return SettleSampleStatus.STABLE
        return SettleSampleStatus.CHANGED

    def _signal_kind_for_snapshot(self, snapshot: SettleProbeSnapshot) -> SettleSignalKind:
        if snapshot.visual is not None:
            return SettleSignalKind.VISUAL
        if snapshot.text is not None:
            return SettleSignalKind.TEXT
        if snapshot.readiness is not None:
            return SettleSignalKind.PROVIDER_READINESS
        return SettleSignalKind.DEGRADED

    def _visual_with_status(
        self,
        *,
        snapshot: SettleProbeSnapshot,
        previous: SettleSample | None,
        status: SettleSampleStatus,
    ) -> VisualDiffSummary | None:
        visual = snapshot.visual
        if visual is None:
            return None
        previous_fingerprint = (
            previous.visual.sample_fingerprint if previous is not None and previous.visual is not None else None
        )
        current_fingerprint = visual.sample_fingerprint
        visual_delta = visual.visual_delta
        if current_fingerprint and previous_fingerprint:
            visual_delta = 0.0 if current_fingerprint == previous_fingerprint else (visual_delta or 1.0)
        return visual.model_copy(update={"status": status, "visual_delta": visual_delta})

    def _text_with_status(
        self,
        *,
        snapshot: SettleProbeSnapshot,
        previous: SettleSample | None,
        status: SettleSampleStatus,
    ) -> TextDiffSummary | None:
        text = snapshot.text
        if text is None:
            return None
        previous_fingerprint = (
            previous.text.text_fingerprint if previous is not None and previous.text is not None else None
        )
        current_fingerprint = text.text_fingerprint
        text_delta = text.text_delta
        if current_fingerprint and previous_fingerprint:
            text_delta = 0.0 if current_fingerprint == previous_fingerprint else (text_delta or 1.0)
        return text.model_copy(update={"status": status, "text_delta": text_delta})

    def _is_due_for_sample(
        self,
        *,
        plan: SettlePollingPlan,
        samples: tuple[SettleSample, ...],
        now_monotonic_ms: int | None,
    ) -> bool:
        if len(samples) >= min(self.config.settle_sample_budget, plan.sample_budget):
            return False
        if now_monotonic_ms is not None and now_monotonic_ms < (plan.settle_window.execute_after_monotonic_ms or 0):
            return False
        if not samples:
            return True
        latest = samples[-1].sampled_at_monotonic_ms
        return (
            latest is None
            or now_monotonic_ms is None
            or now_monotonic_ms - latest >= plan.settle_window.poll_interval_ms
        )

    def _audit(
        self,
        *,
        plan: SettlePollingPlan,
        sample: SettleSample | None,
        decision: SettleDecision,
    ) -> None:
        self.repository.save_settle_audit(
            SettleAuditRecord(
                audit_id=self.ids.new("stla"),
                plan_id=plan.plan_id,
                candidate_id=plan.candidate_id,
                session_id=plan.session_id,
                status=decision.status,
                stop_reason=decision.stop_reason,
                sample_count=decision.sample_count,
                decision=decision,
                sample=sample,
                created_at=self.clock.now(),
                metadata={"policy_version": plan.policy_version},
            )
        )
