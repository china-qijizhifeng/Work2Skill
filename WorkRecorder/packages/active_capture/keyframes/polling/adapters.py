"""Default adaptive-settle polling adapters."""

from __future__ import annotations

from packages.contracts import (
    ContextKeyframe,
    KeyframeTriggerCandidate,
    ProviderReadinessSnapshot,
    ProviderReadinessState,
    SettlePollingPlan,
    SettleSample,
    SettleSampleStatus,
    SettleSignalKind,
)
from packages.shared.ids import IdFactory
from packages.shared.time import Clock


class DegradedSettleSampleProvider:
    """Safe null-object sample provider used until native probes are available."""

    def __init__(self, *, ids: IdFactory, clock: Clock) -> None:
        self.ids = ids
        self.clock = clock

    def sample(
        self,
        *,
        plan: SettlePollingPlan,
        candidate: KeyframeTriggerCandidate,
        baseline: ContextKeyframe | None,
        now_monotonic_ms: int | None,
    ) -> SettleSample:
        return SettleSample(
            sample_id=self.ids.new("kfs"),
            plan_id=plan.plan_id,
            candidate_id=candidate.candidate_id,
            session_id=candidate.session_id,
            sampled_at=self.clock.now(),
            sampled_at_monotonic_ms=now_monotonic_ms,
            status=SettleSampleStatus.DEGRADED,
            signal_kind=SettleSignalKind.DEGRADED,
            readiness=ProviderReadinessSnapshot(
                state=ProviderReadinessState.UNAVAILABLE,
                unavailable_provider_count=1,
                diagnostics=("live settle sample provider unavailable; using fixed-delay fallback",),
            ),
            diagnostics=("live settle sample provider unavailable; using fixed-delay fallback",),
            metadata={
                "baseline_keyframe_available": baseline is not None,
                "candidate_trigger_kind": candidate.trigger_kind.value,
            },
        )
