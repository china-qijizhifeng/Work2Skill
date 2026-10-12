"""Keyframe keep/drop policy strategies."""

from __future__ import annotations

from dataclasses import dataclass

from packages.contracts import (
    ActiveCapturePolicyConfig,
    KeyframeCaptureDecision,
    KeyframeDropReason,
    KeyframeKeepReason,
    KeyframeRole,
    KeyframeTriggerKind,
)
from packages.shared.ids import IdFactory
from packages.shared.time import Clock


@dataclass(frozen=True)
class KeyframeCandidate:
    """Policy input for a keyframe candidate.

    Attributes:
        session_id: Active-capture session receiving the candidate.
        event_id: Optional event that produced the candidate.
        role: Semantic role requested for the keyframe.
        trigger_kind: Trigger family that produced the candidate.
        existing_keyframe_count: Current retained keyframe count.
        candidate_id: Stable trigger/candidate identifier.
    """

    session_id: str
    event_id: str | None
    role: KeyframeRole
    trigger_kind: KeyframeTriggerKind
    existing_keyframe_count: int
    candidate_id: str


class KeyframeCapturePolicy:
    """Default keyframe policy with explicit reasons for every decision."""

    def __init__(self, *, config: ActiveCapturePolicyConfig, ids: IdFactory, clock: Clock) -> None:
        self.config = config
        self.ids = ids
        self.clock = clock

    def decide(self, candidate: KeyframeCandidate) -> KeyframeCaptureDecision:
        """Return a keep/drop audit decision for ``candidate``."""

        if not self.config.enabled:
            return self._drop(candidate, KeyframeDropReason.POLICY_DISABLED)
        if candidate.role == KeyframeRole.ANCHOR:
            return self._keep(candidate, KeyframeKeepReason.USER_ANCHOR)
        if candidate.role in {KeyframeRole.START, KeyframeRole.FINAL}:
            return self._keep(candidate, KeyframeKeepReason.REQUIRED_BOUNDARY)
        if candidate.role == KeyframeRole.USER_MARK:
            return self._keep(candidate, KeyframeKeepReason.USER_MARKED)
        if candidate.role in {KeyframeRole.PAUSE_BOUNDARY, KeyframeRole.RESUME_BOUNDARY}:
            return self._keep(candidate, KeyframeKeepReason.PAUSE_RESUME_BOUNDARY)
        if candidate.existing_keyframe_count >= self.config.max_keyframes_per_session:
            return self._drop(candidate, KeyframeDropReason.BUDGET_EXCEEDED)
        if candidate.role == KeyframeRole.BEFORE_ACTION:
            return self._keep(candidate, KeyframeKeepReason.BEFORE_ACTION_CONTEXT)
        if candidate.role == KeyframeRole.RESULT:
            return self._keep(candidate, KeyframeKeepReason.RESULT_OBSERVED)
        if candidate.role == KeyframeRole.ERROR_STATE:
            return self._keep(candidate, KeyframeKeepReason.ERROR_OBSERVED)
        if candidate.role == KeyframeRole.SCROLL_MILESTONE:
            return self._keep(candidate, KeyframeKeepReason.SCROLL_MILESTONE)
        if candidate.role == KeyframeRole.IDLE_ANCHOR:
            return self._keep(candidate, KeyframeKeepReason.IDLE_ANCHOR)
        if candidate.role == KeyframeRole.PROVIDER_COMPLETION:
            return self._keep(candidate, KeyframeKeepReason.PROVIDER_COMPLETION)
        return self._keep(candidate, KeyframeKeepReason.POLICY_ACCEPTED)

    def _keep(self, candidate: KeyframeCandidate, reason: KeyframeKeepReason) -> KeyframeCaptureDecision:
        return KeyframeCaptureDecision(
            decision_id=self.ids.new("kfd"),
            session_id=candidate.session_id,
            event_id=candidate.event_id,
            candidate_id=candidate.candidate_id,
            role=candidate.role,
            trigger_kind=candidate.trigger_kind,
            kept=True,
            keep_reason=reason,
            policy_version=self.config.policy_version,
            metrics={"existing_keyframe_count": candidate.existing_keyframe_count},
            decided_at=self.clock.now(),
        )

    def _drop(self, candidate: KeyframeCandidate, reason: KeyframeDropReason) -> KeyframeCaptureDecision:
        return KeyframeCaptureDecision(
            decision_id=self.ids.new("kfd"),
            session_id=candidate.session_id,
            event_id=candidate.event_id,
            candidate_id=candidate.candidate_id,
            role=candidate.role,
            trigger_kind=candidate.trigger_kind,
            kept=False,
            drop_reason=reason,
            policy_version=self.config.policy_version,
            metrics={"existing_keyframe_count": candidate.existing_keyframe_count},
            decided_at=self.clock.now(),
        )
