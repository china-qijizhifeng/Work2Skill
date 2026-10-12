"""Ports for adaptive-settle polling adapters."""

from __future__ import annotations

from typing import Protocol

from packages.contracts import (
    ContextKeyframe,
    KeyframeTriggerCandidate,
    SettleAuditRecord,
    SettlePollingPlan,
    SettleSample,
)


class SettleSampleProvider(Protocol):
    """Collect one safe sample for a pending adaptive-settle candidate."""

    def sample(
        self,
        *,
        plan: SettlePollingPlan,
        candidate: KeyframeTriggerCandidate,
        baseline: ContextKeyframe | None,
        now_monotonic_ms: int | None,
    ) -> SettleSample: ...


class TimingAuditRepository(Protocol):
    """Persistence boundary for settle polling samples and decisions."""

    def save_settle_audit(self, record: SettleAuditRecord) -> SettleAuditRecord: ...

    def list_settle_audits_for_candidate(self, candidate_id: str) -> tuple[SettleAuditRecord, ...]: ...


class SettlePollingRepository(TimingAuditRepository, Protocol):
    """Narrow aggregate port used only by the settle polling service."""

    def list_active_trigger_candidates_for_session(
        self, session_id: str, *, limit: int | None = None
    ) -> tuple[KeyframeTriggerCandidate, ...]: ...

    def save_trigger_candidate(self, candidate: KeyframeTriggerCandidate) -> KeyframeTriggerCandidate: ...

    def save_settle_candidate_decision(
        self, *, candidate: KeyframeTriggerCandidate, now_monotonic_ms: int
    ) -> KeyframeTriggerCandidate: ...

    def claim_settle_candidate_for_capture(
        self, *, candidate_id: str, claim_id: str, now_monotonic_ms: int, lease_ms: int
    ) -> KeyframeTriggerCandidate | None: ...

    def get_keyframe(self, keyframe_id: str) -> ContextKeyframe | None: ...

    def get_latest_keyframe_before(
        self, *, session_id: str, occurred_at_monotonic_ms: int | None
    ) -> ContextKeyframe | None: ...
