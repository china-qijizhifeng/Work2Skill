"""Application orchestration for evidence-aware keyframe timing."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from packages.active_capture.keyframes.domain.policies import ActionKeyframePlanner
from packages.active_capture.keyframes.ports.protocol import KeyframeTimingReadPort
from packages.contracts import (
    ActionEvidenceLink,
    ActiveCaptureSession,
    ClickTargetConfidenceBand,
    ClickTargetResolutionStatus,
    ContextKeyframe,
    HumanActionEvent,
    HumanActionEvidenceRole,
    KeyframeCapturePlan,
    KeyframeKeepReason,
    KeyframeSignalEnvelope,
    KeyframeTimingConfig,
    KeyframeTriggerKind,
    PlannedKeyframeTrigger,
    ProducerEventEnvelope,
    SubmitKeyframeTriggerCommand,
)
from packages.contracts.common import JsonScalar
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedKeyframeTimingPlan:
    """Prepared trigger commands and action links for one producer event.

    Attributes:
        plan: Full timing plan produced by the policy chain.
        trigger_commands: Write-ready trigger submissions derived from the plan.
        before_action_link: Optional reused keyframe edge for fresh pre-action context.
    """

    plan: KeyframeCapturePlan
    trigger_commands: tuple[SubmitKeyframeTriggerCommand, ...]
    before_action_link: ActionEvidenceLink | None


class KeyframeTimingOrchestrator:
    """Bridge producer/action facts into evidence-aware keyframe trigger commands."""

    def __init__(
        self,
        *,
        repository: KeyframeTimingReadPort,
        ids: IdFactory,
        clock: Clock,
        config: KeyframeTimingConfig,
        planner: ActionKeyframePlanner | None = None,
    ) -> None:
        self.repository = repository
        self.ids = ids
        self.clock = clock
        self.config = config
        self.planner = planner or ActionKeyframePlanner.default(config)

    def prepare_for_producer_event(
        self,
        *,
        session: ActiveCaptureSession,
        event: ProducerEventEnvelope,
        action: HumanActionEvent | None,
        base_trigger: SubmitKeyframeTriggerCommand | None,
        now: datetime,
    ) -> PreparedKeyframeTimingPlan:
        """Prepare timing commands for one producer-derived action.

        The result is intentionally write-free so callers can commit producer
        event, action trace, trigger candidates, and decisions atomically.
        """

        latest = self._latest_keyframe_before(
            session_id=session.session_id,
            occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
        )
        signal = self._signal_from(
            session=session,
            event=event,
            action=action,
            base_trigger=base_trigger,
            latest=latest,
            now=now,
        )
        plan = self.planner.plan(signal=signal, base_trigger=base_trigger.trigger_kind if base_trigger else None)
        commands = tuple(
            self._command_from_plan(
                planned=planned,
                base_trigger=base_trigger,
                event=event,
                session=session,
                plan=plan,
            )
            for planned in plan.triggers
        )
        before_link = self._before_action_link(action=action, plan=plan, latest=latest, now=now)
        logger.info(
            "active capture keyframe timing plan created",
            extra={
                "session_id": session.session_id,
                "producer_event_id": event.producer_event_id,
                "action_id": action.action_id if action is not None else None,
                "trigger_count": len(commands),
                "reused_before_keyframe": bool(plan.reused_before_keyframe_id),
                "needs_review": plan.needs_review,
            },
        )
        return PreparedKeyframeTimingPlan(plan=plan, trigger_commands=commands, before_action_link=before_link)

    def _signal_from(
        self,
        *,
        session: ActiveCaptureSession,
        event: ProducerEventEnvelope,
        action: HumanActionEvent | None,
        base_trigger: SubmitKeyframeTriggerCommand | None,
        latest: ContextKeyframe | None,
        now: datetime,
    ) -> KeyframeSignalEnvelope:
        target_status, confidence_band = self._click_target_hint(event=event)
        metadata = self._safe_timing_metadata(event)
        return KeyframeSignalEnvelope(
            session_id=session.session_id,
            signal_id=event.producer_event_id,
            occurred_at=event.occurred_at or now,
            occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
            action_id=action.action_id if action is not None else None,
            action_kind=action.kind if action is not None else None,
            producer_event_kind=event.event_kind,
            trigger_kind=base_trigger.trigger_kind if base_trigger is not None else None,
            hotkey_semantic=action.hotkey_semantic if action is not None else None,
            scroll_delta_y=action.scroll_delta_y if action is not None else None,
            scope=event.scope or session.scope,
            coordinates=action.coordinates if action is not None else None,
            redaction_state=event.redaction_state,
            click_target_status=target_status,
            click_target_confidence_band=confidence_band,
            last_keyframe_id=latest.keyframe_id if latest is not None else None,
            last_keyframe_monotonic_ms=latest.captured_at_monotonic_ms if latest is not None else None,
            metadata=metadata,
        )

    def _command_from_plan(
        self,
        *,
        planned: PlannedKeyframeTrigger,
        base_trigger: SubmitKeyframeTriggerCommand | None,
        event: ProducerEventEnvelope,
        session: ActiveCaptureSession,
        plan: KeyframeCapturePlan,
    ) -> SubmitKeyframeTriggerCommand:
        base_metadata = base_trigger.metadata if base_trigger is not None else {}
        metadata = {
            **base_metadata,
            **planned.metadata,
            "producer_event_id": event.producer_event_id,
            "timing_plan_signal_id": plan.signal_id,
        }
        return SubmitKeyframeTriggerCommand(
            trigger_kind=planned.trigger_kind,
            role=planned.role,
            priority=planned.priority,
            keep_reason=planned.keep_reason,
            occurred_at_monotonic_ms=planned.occurred_at_monotonic_ms or event.occurred_at_monotonic_ms,
            debounce_until_monotonic_ms=planned.debounce_until_monotonic_ms,
            event_id=base_trigger.event_id if base_trigger is not None else None,
            action_id=planned.action_id,
            action_evidence_role=planned.action_evidence_role,
            scope=(
                base_trigger.scope
                if base_trigger is not None and base_trigger.scope is not None
                else event.scope or session.scope
            ),
            diff=planned.diff,
            quality=planned.quality,
            metadata=metadata,
        )

    def _before_action_link(
        self,
        *,
        action: HumanActionEvent | None,
        plan: KeyframeCapturePlan,
        latest: ContextKeyframe | None,
        now: datetime,
    ) -> ActionEvidenceLink | None:
        if action is None or latest is None or plan.reused_before_keyframe_id != latest.keyframe_id:
            return None
        return ActionEvidenceLink(
            link_id=self.ids.new("ael"),
            action_id=action.action_id,
            role=HumanActionEvidenceRole.BEFORE_KEYFRAME,
            keyframe_id=latest.keyframe_id,
            event_id=latest.event_id,
            evidence_id=latest.screenshot_evidence_id,
            artifact_id=latest.screenshot_artifact_id,
            created_at=now,
            metadata={
                "timing_component": "action_boundary",
                "link_confidence": 0.85,
                "keep_reason": KeyframeKeepReason.BEFORE_ACTION_CONTEXT.value,
            },
        )

    def _latest_keyframe_before(
        self,
        *,
        session_id: str,
        occurred_at_monotonic_ms: int | None,
    ) -> ContextKeyframe | None:
        return self.repository.get_latest_keyframe_before(
            session_id=session_id,
            occurred_at_monotonic_ms=occurred_at_monotonic_ms,
        )

    def _click_target_hint(
        self,
        *,
        event: ProducerEventEnvelope,
    ) -> tuple[ClickTargetResolutionStatus | None, ClickTargetConfidenceBand | None]:
        if event.pointer is None or event.pointer.target is None:
            return None, None
        confidence = event.pointer.target.confidence
        if confidence >= 0.78:
            return ClickTargetResolutionStatus.RESOLVED, ClickTargetConfidenceBand.HIGH
        if confidence >= 0.55:
            return ClickTargetResolutionStatus.LOW_CONFIDENCE, ClickTargetConfidenceBand.MEDIUM
        return ClickTargetResolutionStatus.LOW_CONFIDENCE, ClickTargetConfidenceBand.LOW

    def _safe_timing_metadata(self, event: ProducerEventEnvelope) -> dict[str, JsonScalar]:
        allowed_keys = {"surface_signal_kind", "source_signal", "native_event_phase"}
        safe: dict[str, JsonScalar] = {}
        for key in allowed_keys:
            value = event.metadata.get(key)
            if isinstance(value, str | int | float | bool):
                safe[key] = value
        return safe
