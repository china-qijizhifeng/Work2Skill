"""Post-resolution target probe trigger submission."""

from __future__ import annotations

import logging

from packages.active_capture.application.keyframe_triggers import KeyframeTriggerScheduler
from packages.active_capture.keyframes.domain.policies import target_probe_settle_metadata, target_probe_settle_window
from packages.contracts import (
    ActiveCapturePolicyConfig,
    ActiveCaptureSession,
    ContextKeyframe,
    HumanActionEvidenceRole,
    KeyframeKeepReason,
    KeyframePriorityBand,
    KeyframeRole,
    KeyframeTimingConfig,
    KeyframeTriggerKind,
    SubmitKeyframeTriggerCommand,
)

logger = logging.getLogger(__name__)


class TargetProbeBackfillService:
    """Submit a target-disambiguation keyframe after click resolution remains uncertain."""

    def __init__(self, *, config: ActiveCapturePolicyConfig, trigger_scheduler: KeyframeTriggerScheduler) -> None:
        self.config = config
        self.trigger_scheduler = trigger_scheduler

    def submit_if_needed(
        self,
        *,
        session: ActiveCaptureSession,
        action_id: str,
        keyframe: ContextKeyframe,
        needs_review: bool,
    ) -> None:
        if not self.config.target_probe_enabled or not needs_review:
            return
        try:
            timing_config = KeyframeTimingConfig.from_active_capture_policy(self.config)
            settle_window = target_probe_settle_window(timing_config, keyframe.captured_at_monotonic_ms)
            metadata = target_probe_settle_metadata(timing_config, settle_window)
            self.trigger_scheduler.submit(
                session=session,
                command=SubmitKeyframeTriggerCommand(
                    trigger_kind=KeyframeTriggerKind.TARGET_RESOLUTION_PROBE,
                    role=KeyframeRole.RESULT,
                    priority=KeyframePriorityBand.NORMAL,
                    keep_reason=KeyframeKeepReason.TARGET_DISAMBIGUATION,
                    occurred_at_monotonic_ms=keyframe.captured_at_monotonic_ms,
                    debounce_until_monotonic_ms=settle_window.execute_after_monotonic_ms,
                    event_id=keyframe.event_id,
                    action_id=action_id,
                    action_evidence_role=HumanActionEvidenceRole.TARGET_EVIDENCE,
                    scope=session.scope,
                    metadata=metadata,
                ),
            )
        except ValueError:
            logger.info(
                "active capture target probe suppressed",
                extra={"session_id": session.session_id, "action_id": action_id},
            )
