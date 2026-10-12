"""Event-driven keyframe trigger scheduling for active capture."""

from __future__ import annotations

import logging

from packages.active_capture.application.service_helpers import is_terminal_status
from packages.active_capture.keyframes.domain.policies import QualityKeepDropPolicy
from packages.active_capture.repositories.protocol import ActiveCaptureRepository
from packages.contracts import (
    ActiveCapturePolicyConfig,
    ActiveCaptureSession,
    HumanActionEvidenceRole,
    KeyframeDropReason,
    KeyframeKeepReason,
    KeyframePriorityBand,
    KeyframeQualityDecision,
    KeyframeRole,
    KeyframeTimingConfig,
    KeyframeTriggerCandidate,
    KeyframeTriggerCandidateStatus,
    KeyframeTriggerKind,
    SubmitKeyframeTriggerCommand,
    TriggerDebouncePolicy,
)
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

logger = logging.getLogger(__name__)


class KeyframeTriggerScheduler:
    """Debounce, classify, and persist keyframe trigger candidates."""

    def __init__(
        self,
        *,
        repository: ActiveCaptureRepository,
        ids: IdFactory,
        clock: Clock,
        config: ActiveCapturePolicyConfig,
    ) -> None:
        self.repository = repository
        self.ids = ids
        self.clock = clock
        self.config = config
        self.quality_policy = QualityKeepDropPolicy(KeyframeTimingConfig.from_active_capture_policy(config))

    def policy(self) -> TriggerDebouncePolicy:
        """Return the currently configured trigger policy as a typed contract."""

        return TriggerDebouncePolicy(
            min_keyframe_gap_ms=self.config.min_keyframe_gap_ms,
            click_settle_delay_ms=self.config.click_settle_delay_ms,
            scroll_stop_delay_ms=self.config.scroll_stop_delay_ms,
            typing_pause_delay_ms=self.config.typing_pause_delay_ms,
            idle_anchor_interval_ms=self.config.idle_anchor_interval_ms,
            visual_diff_threshold=self.config.visual_diff_threshold,
            text_diff_threshold=self.config.text_diff_threshold,
            max_pending_candidates=self.config.max_pending_trigger_candidates,
        )

    def submit(
        self,
        *,
        session: ActiveCaptureSession,
        command: SubmitKeyframeTriggerCommand,
    ) -> KeyframeTriggerCandidate:
        """Submit one event-driven keyframe trigger candidate."""

        if is_terminal_status(session.status):
            raise ValueError("cannot submit keyframe trigger for terminal active capture session")
        candidate = self.prepare_candidate(
            session=session,
            command=command,
            existing=self._candidate_context(session.session_id),
            pending_action_ids=frozenset(),
        )
        saved = self.repository.save_trigger_candidate(candidate)
        logger.info(
            "active capture trigger candidate submitted",
            extra={
                "session_id": session.session_id,
                "candidate_id": saved.candidate_id,
                "trigger_kind": saved.trigger_kind.value,
                "status": saved.status.value,
            },
        )
        return saved

    def prepare_candidate(
        self,
        *,
        session: ActiveCaptureSession,
        command: SubmitKeyframeTriggerCommand,
        existing: tuple[KeyframeTriggerCandidate, ...],
        pending_action_ids: frozenset[str] = frozenset(),
    ) -> KeyframeTriggerCandidate:
        """Build a trigger candidate without committing it."""

        policy = self.policy()
        role = command.role or self._default_role(command.trigger_kind)
        priority = command.priority or self._default_priority(command.trigger_kind)
        self._validate_action_binding(session=session, command=command, pending_action_ids=pending_action_ids)
        now = self.clock.now()
        status = KeyframeTriggerCandidateStatus.RECEIVED
        keep_reason = command.keep_reason or self._default_keep_reason(command.trigger_kind)
        drop_reason: KeyframeDropReason | None = None
        diagnostics: tuple[str, ...] = ()
        if (
            priority != KeyframePriorityBand.REQUIRED
            and self._active_candidate_count(existing) >= policy.max_pending_candidates
        ):
            status = KeyframeTriggerCandidateStatus.DROPPED
            drop_reason = KeyframeDropReason.BUDGET_EXCEEDED
            diagnostics = ("trigger candidate budget exceeded",)
        elif priority != KeyframePriorityBand.REQUIRED and self._too_soon(existing, command, policy):
            status = KeyframeTriggerCandidateStatus.DEBOUNCED
            drop_reason = KeyframeDropReason.TOO_SOON
            diagnostics = ("debounced by min_keyframe_gap_ms",)
        elif priority != KeyframePriorityBand.REQUIRED and self._action_result_budget_exceeded(existing, command):
            status = KeyframeTriggerCandidateStatus.DROPPED
            drop_reason = KeyframeDropReason.BUDGET_EXCEEDED
            diagnostics = ("action result keyframe budget exceeded",)
        elif self._below_diff_threshold(command, policy):
            status = KeyframeTriggerCandidateStatus.DROPPED
            drop_reason = KeyframeDropReason.LOW_DELTA
            diagnostics = ("candidate diff below configured threshold",)
        elif (
            priority != KeyframePriorityBand.REQUIRED
            and (quality_decision := self._quality_drop_decision(command, priority)) is not None
        ):
            status = KeyframeTriggerCandidateStatus.DROPPED
            drop_reason = quality_decision.drop_reason
            diagnostics = quality_decision.diagnostics
        else:
            status = KeyframeTriggerCandidateStatus.ACCEPTED
        candidate = KeyframeTriggerCandidate(
            candidate_id=self.ids.new("kfc"),
            session_id=session.session_id,
            trigger_kind=command.trigger_kind,
            role=role,
            priority=priority,
            status=status,
            occurred_at=now,
            occurred_at_monotonic_ms=command.occurred_at_monotonic_ms,
            event_id=command.event_id,
            action_id=command.action_id,
            action_evidence_role=command.action_evidence_role,
            keep_reason=keep_reason if status == KeyframeTriggerCandidateStatus.ACCEPTED else None,
            drop_reason=drop_reason,
            scope=command.scope or session.scope,
            diff=command.diff,
            quality=command.quality,
            debounce_until_monotonic_ms=self._debounce_until(command, policy),
            policy_version=self.config.policy_version,
            diagnostics=diagnostics,
            metadata=command.metadata,
        )
        return candidate

    def _candidate_context(self, session_id: str) -> tuple[KeyframeTriggerCandidate, ...]:
        return self.repository.list_recent_trigger_candidates_for_session(
            session_id,
            statuses=(
                KeyframeTriggerCandidateStatus.RECEIVED,
                KeyframeTriggerCandidateStatus.ACCEPTED,
                KeyframeTriggerCandidateStatus.CAPTURED,
            ),
            limit=max(self.config.max_pending_trigger_candidates * 4, 128),
        )

    def _validate_action_binding(
        self,
        *,
        session: ActiveCaptureSession,
        command: SubmitKeyframeTriggerCommand,
        pending_action_ids: frozenset[str],
    ) -> None:
        if command.action_id is None:
            if command.action_evidence_role is not None:
                raise ValueError("action_evidence_role requires action_id")
            return
        if command.action_id in pending_action_ids:
            return
        action = self.repository.get_human_action(command.action_id)
        if action is None or action.session_id != session.session_id:
            raise ValueError("keyframe trigger action_id does not belong to active capture session")

    def mark_captured(self, *, candidate_id: str, keyframe_id: str, event_id: str | None = None) -> None:
        """Mark a previously accepted candidate as captured by a keyframe."""

        candidate = self.repository.get_trigger_candidate(candidate_id)
        if candidate is None or candidate.status != KeyframeTriggerCandidateStatus.ACCEPTED:
            return
        self.repository.save_trigger_candidate(
            candidate.model_copy(
                update={
                    "status": KeyframeTriggerCandidateStatus.CAPTURED,
                    "keyframe_id": keyframe_id,
                    "event_id": event_id or candidate.event_id,
                }
            )
        )

    def mark_dropped(
        self,
        *,
        candidate_id: str,
        reason: KeyframeDropReason,
        event_id: str | None = None,
        diagnostic: str | None = None,
    ) -> None:
        """Mark a previously accepted candidate as terminally dropped."""

        candidate = self.repository.get_trigger_candidate(candidate_id)
        if candidate is None or candidate.status == KeyframeTriggerCandidateStatus.CAPTURED:
            return
        diagnostics = candidate.diagnostics
        if diagnostic:
            diagnostics = (*diagnostics, diagnostic)
        self.repository.save_trigger_candidate(
            candidate.model_copy(
                update={
                    "status": KeyframeTriggerCandidateStatus.DROPPED,
                    "drop_reason": reason,
                    "keep_reason": None,
                    "event_id": event_id or candidate.event_id,
                    "diagnostics": tuple(dict.fromkeys(diagnostics)),
                }
            )
        )

    def _active_candidate_count(self, existing: tuple[KeyframeTriggerCandidate, ...]) -> int:
        active_statuses = {
            KeyframeTriggerCandidateStatus.RECEIVED,
            KeyframeTriggerCandidateStatus.ACCEPTED,
        }
        return sum(1 for candidate in existing if candidate.status in active_statuses)

    def _action_result_budget_exceeded(
        self,
        existing: tuple[KeyframeTriggerCandidate, ...],
        command: SubmitKeyframeTriggerCommand,
    ) -> bool:
        if command.action_id is None or command.action_evidence_role not in {
            HumanActionEvidenceRole.AFTER_KEYFRAME,
            HumanActionEvidenceRole.RESULT_EVIDENCE,
            HumanActionEvidenceRole.TARGET_EVIDENCE,
        }:
            return False
        active_statuses = {
            KeyframeTriggerCandidateStatus.RECEIVED,
            KeyframeTriggerCandidateStatus.ACCEPTED,
            KeyframeTriggerCandidateStatus.CAPTURED,
        }
        count = sum(
            1
            for candidate in existing
            if candidate.action_id == command.action_id
            and candidate.action_evidence_role
            in {
                HumanActionEvidenceRole.AFTER_KEYFRAME,
                HumanActionEvidenceRole.RESULT_EVIDENCE,
                HumanActionEvidenceRole.TARGET_EVIDENCE,
            }
            and candidate.status in active_statuses
        )
        return count >= self.config.max_result_frames_per_action

    def _too_soon(
        self,
        existing: tuple[KeyframeTriggerCandidate, ...],
        command: SubmitKeyframeTriggerCommand,
        policy: TriggerDebouncePolicy,
    ) -> bool:
        if command.occurred_at_monotonic_ms is None:
            return False
        accepted = (
            item
            for item in existing
            if item.occurred_at_monotonic_ms is not None
            and item.status
            in {
                KeyframeTriggerCandidateStatus.ACCEPTED,
                KeyframeTriggerCandidateStatus.CAPTURED,
            }
        )
        latest = max(accepted, key=lambda item: item.occurred_at_monotonic_ms or 0, default=None)
        if latest is None or latest.occurred_at_monotonic_ms is None:
            return False
        command_plan_id = command.metadata.get("timing_plan_signal_id")
        latest_plan_id = latest.metadata.get("timing_plan_signal_id")
        if (
            isinstance(command_plan_id, str)
            and command_plan_id
            and isinstance(latest_plan_id, str)
            and command_plan_id == latest_plan_id
        ):
            return False
        return command.occurred_at_monotonic_ms - latest.occurred_at_monotonic_ms < policy.min_keyframe_gap_ms

    def _below_diff_threshold(self, command: SubmitKeyframeTriggerCommand, policy: TriggerDebouncePolicy) -> bool:
        if command.trigger_kind == KeyframeTriggerKind.VISUAL_CHANGE and command.diff is not None:
            return (command.diff.visual_delta or 0.0) < policy.visual_diff_threshold
        if command.trigger_kind == KeyframeTriggerKind.TEXT_CHANGE and command.diff is not None:
            return (command.diff.text_delta or 0.0) < policy.text_diff_threshold
        return False

    def _quality_drop_decision(
        self,
        command: SubmitKeyframeTriggerCommand,
        priority: KeyframePriorityBand,
    ) -> KeyframeQualityDecision | None:
        if command.diff is None and command.quality is None:
            return None
        decision = self.quality_policy.decide(
            trigger_kind=command.trigger_kind,
            priority=priority,
            diff=command.diff,
            quality=command.quality,
        )
        return None if decision.kept else decision

    def _debounce_until(
        self,
        command: SubmitKeyframeTriggerCommand,
        policy: TriggerDebouncePolicy,
    ) -> int | None:
        if command.debounce_until_monotonic_ms is not None:
            return command.debounce_until_monotonic_ms
        if command.occurred_at_monotonic_ms is None:
            return None
        if command.trigger_kind == KeyframeTriggerKind.CLICK_SETTLE:
            return command.occurred_at_monotonic_ms + policy.click_settle_delay_ms
        if command.trigger_kind == KeyframeTriggerKind.SCROLL_STOP:
            return command.occurred_at_monotonic_ms + policy.scroll_stop_delay_ms
        if command.trigger_kind == KeyframeTriggerKind.HOTKEY_SETTLE:
            return command.occurred_at_monotonic_ms + self.config.hotkey_settle_delay_ms
        if command.trigger_kind == KeyframeTriggerKind.TYPING_SETTLE:
            return command.occurred_at_monotonic_ms
        if command.trigger_kind == KeyframeTriggerKind.COMMAND_SUBMITTED:
            return command.occurred_at_monotonic_ms + self.config.hotkey_settle_delay_ms
        if command.trigger_kind in {
            KeyframeTriggerKind.ACTION_BEFORE,
            KeyframeTriggerKind.ERROR_SURFACE_DETECTED,
            KeyframeTriggerKind.PAUSE_BOUNDARY,
            KeyframeTriggerKind.RESUME_BOUNDARY,
        }:
            return command.occurred_at_monotonic_ms
        if command.trigger_kind in {
            KeyframeTriggerKind.ACTION_RESULT_SETTLE,
            KeyframeTriggerKind.NAVIGATION_COMMITTED,
            KeyframeTriggerKind.MODAL_STATE_CHANGE,
            KeyframeTriggerKind.TARGET_RESOLUTION_PROBE,
        }:
            return command.occurred_at_monotonic_ms + self.config.adaptive_settle_min_delay_ms
        if command.trigger_kind == KeyframeTriggerKind.SCROLL_MILESTONE:
            return command.occurred_at_monotonic_ms + self.config.scroll_milestone_min_gap_ms
        return command.occurred_at_monotonic_ms + policy.min_keyframe_gap_ms

    def _default_role(self, trigger_kind: KeyframeTriggerKind) -> KeyframeRole:
        match trigger_kind:
            case KeyframeTriggerKind.RECORDING_START:
                return KeyframeRole.START
            case KeyframeTriggerKind.RECORDING_STOP | KeyframeTriggerKind.SESSION_COMPLETE:
                return KeyframeRole.FINAL
            case KeyframeTriggerKind.ACTION_BEFORE:
                return KeyframeRole.BEFORE_ACTION
            case KeyframeTriggerKind.PAUSE_BOUNDARY:
                return KeyframeRole.PAUSE_BOUNDARY
            case KeyframeTriggerKind.RESUME_BOUNDARY:
                return KeyframeRole.RESUME_BOUNDARY
            case KeyframeTriggerKind.ERROR_SURFACE_DETECTED:
                return KeyframeRole.ERROR_STATE
            case KeyframeTriggerKind.SCROLL_MILESTONE:
                return KeyframeRole.SCROLL_MILESTONE
            case KeyframeTriggerKind.USER_MARK:
                return KeyframeRole.USER_MARK
            case KeyframeTriggerKind.IDLE_FALLBACK:
                return KeyframeRole.IDLE_ANCHOR
            case KeyframeTriggerKind.PROVIDER_COMPLETED | KeyframeTriggerKind.PROVIDER_COMPLETION:
                return KeyframeRole.PROVIDER_COMPLETION
            case (
                KeyframeTriggerKind.STABILITY_SETTLE
                | KeyframeTriggerKind.CLICK_SETTLE
                | KeyframeTriggerKind.HOTKEY_SETTLE
                | KeyframeTriggerKind.TYPING_SETTLE
            ):
                return KeyframeRole.SETTLE
            case (
                KeyframeTriggerKind.ACTION_RESULT_SETTLE
                | KeyframeTriggerKind.COMMAND_SUBMITTED
                | KeyframeTriggerKind.NAVIGATION_COMMITTED
                | KeyframeTriggerKind.MODAL_STATE_CHANGE
                | KeyframeTriggerKind.TARGET_RESOLUTION_PROBE
            ):
                return KeyframeRole.RESULT
            case _:
                return KeyframeRole.CHANGE

    def _default_priority(self, trigger_kind: KeyframeTriggerKind) -> KeyframePriorityBand:
        match trigger_kind:
            case (
                KeyframeTriggerKind.RECORDING_START
                | KeyframeTriggerKind.RECORDING_STOP
                | KeyframeTriggerKind.USER_MARK
                | KeyframeTriggerKind.SESSION_COMPLETE
                | KeyframeTriggerKind.PAUSE_BOUNDARY
                | KeyframeTriggerKind.RESUME_BOUNDARY
            ):
                return KeyframePriorityBand.REQUIRED
            case (
                KeyframeTriggerKind.ACTION_BEFORE
                | KeyframeTriggerKind.ACTION_RESULT_SETTLE
                | KeyframeTriggerKind.NAVIGATION_COMMITTED
                | KeyframeTriggerKind.MODAL_STATE_CHANGE
                | KeyframeTriggerKind.TITLE_URL_CHANGE
                | KeyframeTriggerKind.CLICK_SETTLE
                | KeyframeTriggerKind.SCROLL_STOP
                | KeyframeTriggerKind.SCROLL_MILESTONE
                | KeyframeTriggerKind.TARGET_RESOLUTION_PROBE
                | KeyframeTriggerKind.HOTKEY_SETTLE
                | KeyframeTriggerKind.TYPING_SETTLE
                | KeyframeTriggerKind.COMMAND_SUBMITTED
                | KeyframeTriggerKind.FOCUS_CHANGE
                | KeyframeTriggerKind.ERROR_SURFACE_DETECTED
                | KeyframeTriggerKind.PROVIDER_COMPLETED
                | KeyframeTriggerKind.PROVIDER_COMPLETION
                | KeyframeTriggerKind.OCR_COMPLETED
            ):
                return KeyframePriorityBand.HIGH
            case KeyframeTriggerKind.IDLE_FALLBACK:
                return KeyframePriorityBand.IDLE
            case _:
                return KeyframePriorityBand.NORMAL

    def _default_keep_reason(self, trigger_kind: KeyframeTriggerKind) -> KeyframeKeepReason:
        match trigger_kind:
            case KeyframeTriggerKind.USER_MARK:
                return KeyframeKeepReason.USER_MARKED
            case KeyframeTriggerKind.RECORDING_START | KeyframeTriggerKind.RECORDING_STOP:
                return KeyframeKeepReason.REQUIRED_BOUNDARY
            case KeyframeTriggerKind.ACTION_BEFORE:
                return KeyframeKeepReason.BEFORE_ACTION_CONTEXT
            case KeyframeTriggerKind.ACTION_RESULT_SETTLE | KeyframeTriggerKind.CLICK_SETTLE:
                return KeyframeKeepReason.RESULT_OBSERVED
            case KeyframeTriggerKind.COMMAND_SUBMITTED:
                return KeyframeKeepReason.COMMAND_BOUNDARY
            case KeyframeTriggerKind.NAVIGATION_COMMITTED | KeyframeTriggerKind.MODAL_STATE_CHANGE:
                return KeyframeKeepReason.NAVIGATION_BOUNDARY
            case KeyframeTriggerKind.SCROLL_MILESTONE:
                return KeyframeKeepReason.SCROLL_MILESTONE
            case KeyframeTriggerKind.TARGET_RESOLUTION_PROBE:
                return KeyframeKeepReason.TARGET_DISAMBIGUATION
            case KeyframeTriggerKind.ERROR_SURFACE_DETECTED:
                return KeyframeKeepReason.ERROR_OBSERVED
            case KeyframeTriggerKind.PAUSE_BOUNDARY | KeyframeTriggerKind.RESUME_BOUNDARY:
                return KeyframeKeepReason.PAUSE_RESUME_BOUNDARY
            case KeyframeTriggerKind.PROVIDER_COMPLETED | KeyframeTriggerKind.PROVIDER_COMPLETION:
                return KeyframeKeepReason.PROVIDER_EVIDENCE_ADDED
            case KeyframeTriggerKind.OCR_COMPLETED:
                return KeyframeKeepReason.QUALITY_IMPROVED
            case KeyframeTriggerKind.VISUAL_CHANGE:
                return KeyframeKeepReason.VISUAL_DELTA
            case KeyframeTriggerKind.TEXT_CHANGE:
                return KeyframeKeepReason.TEXT_DELTA
            case (
                KeyframeTriggerKind.SURFACE_CHANGE
                | KeyframeTriggerKind.TITLE_URL_CHANGE
                | KeyframeTriggerKind.FOCUS_CHANGE
            ):
                return KeyframeKeepReason.PRIMARY_SURFACE_CHANGED
            case KeyframeTriggerKind.IDLE_FALLBACK:
                return KeyframeKeepReason.IDLE_ANCHOR
            case _:
                return KeyframeKeepReason.POLICY_ACCEPTED
