"""Pure adaptive-settle polling policies."""

from __future__ import annotations

from dataclasses import dataclass

from packages.contracts import (
    KeyframeDiffReport,
    KeyframeQualityReport,
    KeyframeTimingConfig,
    KeyframeTriggerKind,
    ProviderReadinessState,
    SettleDecision,
    SettleDecisionStatus,
    SettlePollingPlan,
    SettleSample,
    SettleSampleStatus,
    SettleStopReason,
)

_LOW_VALUE_TIMEOUT_SUPPRESSED_TRIGGERS = {
    KeyframeTriggerKind.TYPING_SETTLE,
    KeyframeTriggerKind.TARGET_RESOLUTION_PROBE,
}


@dataclass(frozen=True)
class SampleBudgetPolicy:
    """Bound the amount of polling work spent on one candidate.

    Attributes:
        config: Keyframe timing policy containing the global polling sample budget.
    """

    config: KeyframeTimingConfig

    def exceeded(self, *, sample_count: int, plan: SettlePollingPlan) -> bool:
        return sample_count >= min(self.config.settle_sample_budget, plan.sample_budget)


@dataclass(frozen=True)
class DiffFusionPolicy:
    """Combine visual and text metrics into one safe diff report.

    Attributes:
        config: Keyframe timing policy containing information-gain thresholds.
    """

    config: KeyframeTimingConfig

    def diff_for_samples(self, samples: tuple[SettleSample, ...]) -> KeyframeDiffReport | None:
        visual_values = [
            sample.visual.visual_delta
            for sample in samples
            if sample.visual is not None and sample.visual.visual_delta is not None
        ]
        text_values = [
            sample.text.text_delta
            for sample in samples
            if sample.text is not None and sample.text.text_delta is not None
        ]
        if not visual_values and not text_values:
            return None
        visual_delta = max(visual_values) if visual_values else None
        text_delta = max(text_values) if text_values else None
        changed = (
            (visual_delta is not None and visual_delta >= self.config.quality_min_information_gain)
            or (text_delta is not None and text_delta >= self.config.quality_min_information_gain)
            or any(sample.status == SettleSampleStatus.CHANGED for sample in samples)
        )
        return KeyframeDiffReport(
            visual_delta=visual_delta,
            text_delta=text_delta,
            changed=changed,
            metrics={
                "settle_sample_count": len(samples),
                "max_visual_delta": visual_delta or 0.0,
                "max_text_delta": text_delta or 0.0,
            },
        )

    def quality_for_samples(self, samples: tuple[SettleSample, ...]) -> KeyframeQualityReport:
        text_chars = max((sample.text.text_length for sample in samples if sample.text is not None), default=0)
        provider_ready = any(
            sample.readiness is not None and sample.readiness.state == ProviderReadinessState.READY
            for sample in samples
        )
        confidence = 0.75 if provider_ready else 0.55
        if any(sample.status == SettleSampleStatus.DEGRADED for sample in samples):
            confidence = min(confidence, 0.45)
        return KeyframeQualityReport(
            confidence=confidence,
            text_chars=text_chars,
            screenshot_available=True,
            system_appshot_available=provider_ready,
            diagnostics=tuple(dict.fromkeys(diagnostic for sample in samples for diagnostic in sample.diagnostics)),
            metrics={
                "settle_sample_count": len(samples),
                "provider_ready": provider_ready,
            },
        )


@dataclass
class SettleStabilityStateMachine:
    """Evaluate safe samples and decide whether final capture is due.

    Attributes:
        config: Keyframe timing policy for settle windows and timeout behavior.
        budget: Strategy that decides whether sampling work is exhausted.
        fusion: Strategy that converts safe samples into diff and quality summaries.
    """

    config: KeyframeTimingConfig
    budget: SampleBudgetPolicy
    fusion: DiffFusionPolicy

    @classmethod
    def default(cls, config: KeyframeTimingConfig) -> "SettleStabilityStateMachine":
        return cls(config=config, budget=SampleBudgetPolicy(config), fusion=DiffFusionPolicy(config))

    def decide(
        self,
        *,
        plan: SettlePollingPlan,
        samples: tuple[SettleSample, ...],
        now_monotonic_ms: int | None,
    ) -> SettleDecision:
        sample_count = len(samples)
        latest = samples[-1] if samples else None
        if now_monotonic_ms is not None and now_monotonic_ms < (plan.settle_window.execute_after_monotonic_ms or 0):
            return self._observing(plan, SettleStopReason.NOT_DUE, sample_count=sample_count)
        if latest is not None and latest.status == SettleSampleStatus.SUPPRESSED:
            return self._suppressed(plan, SettleStopReason.SENSITIVE_SURFACE, sample_count=sample_count)
        if latest is not None and latest.status == SettleSampleStatus.FAILED:
            return self._timeout(plan, samples, stop_reason=SettleStopReason.SAMPLE_FAILED)
        if latest is not None and latest.status == SettleSampleStatus.DEGRADED:
            return self._ready(
                plan,
                samples,
                stop_reason=SettleStopReason.PROVIDER_UNAVAILABLE,
                needs_review=True,
            )
        if self._provider_ready(samples):
            return self._ready(plan, samples, stop_reason=SettleStopReason.PROVIDER_READY)
        if self._stable_after_meaningful_change(plan=plan, samples=samples):
            return self._ready(plan, samples, stop_reason=SettleStopReason.STABLE_AFTER_CHANGE)
        if self.budget.exceeded(sample_count=sample_count, plan=plan):
            return self._timeout(plan, samples, stop_reason=SettleStopReason.BUDGET_EXCEEDED)
        if (
            now_monotonic_ms is not None
            and plan.settle_window.deadline_monotonic_ms is not None
            and now_monotonic_ms >= plan.settle_window.deadline_monotonic_ms
        ):
            if self._should_suppress_low_value_timeout(plan=plan, samples=samples):
                return self._suppressed(plan, SettleStopReason.TIMEOUT, sample_count=sample_count)
            return self._timeout(plan, samples, stop_reason=SettleStopReason.TIMEOUT)
        return self._observing(plan, SettleStopReason.NOT_DUE, sample_count=sample_count)

    def _stable_after_meaningful_change(self, *, plan: SettlePollingPlan, samples: tuple[SettleSample, ...]) -> bool:
        if not samples:
            return False
        has_change = any(sample.status == SettleSampleStatus.CHANGED for sample in samples)
        if not has_change:
            has_change = any(
                (
                    sample.visual is not None
                    and sample.visual.visual_delta is not None
                    and sample.visual.visual_delta >= self.config.quality_min_information_gain
                )
                or (
                    sample.text is not None
                    and sample.text.text_delta is not None
                    and sample.text.text_delta >= self.config.quality_min_information_gain
                )
                for sample in samples
            )
        if not has_change:
            return False
        stable_count = self._trailing_status_count(samples, SettleSampleStatus.STABLE)
        return stable_count >= plan.settle_window.required_stable_samples

    def _provider_ready(self, samples: tuple[SettleSample, ...]) -> bool:
        latest = samples[-1] if samples else None
        return (
            latest is not None
            and latest.readiness is not None
            and latest.readiness.state == ProviderReadinessState.READY
        )

    def _should_suppress_low_value_timeout(self, *, plan: SettlePollingPlan, samples: tuple[SettleSample, ...]) -> bool:
        if plan.timeout_capture_enabled is True:
            return False
        if plan.timeout_capture_enabled is False:
            return True
        return plan.trigger_kind in _LOW_VALUE_TIMEOUT_SUPPRESSED_TRIGGERS

    def _trailing_status_count(self, samples: tuple[SettleSample, ...], status: SettleSampleStatus) -> int:
        count = 0
        for sample in reversed(samples):
            if sample.status != status:
                break
            count += 1
        return count

    def _observing(
        self, plan: SettlePollingPlan, stop_reason: SettleStopReason, *, sample_count: int
    ) -> SettleDecision:
        return SettleDecision(
            plan_id=plan.plan_id,
            candidate_id=plan.candidate_id,
            session_id=plan.session_id,
            status=SettleDecisionStatus.OBSERVING,
            stop_reason=stop_reason,
            sample_count=sample_count,
            diagnostics=("settle polling still observing",),
        )

    def _ready(
        self,
        plan: SettlePollingPlan,
        samples: tuple[SettleSample, ...],
        *,
        stop_reason: SettleStopReason,
        needs_review: bool = False,
    ) -> SettleDecision:
        return SettleDecision(
            plan_id=plan.plan_id,
            candidate_id=plan.candidate_id,
            session_id=plan.session_id,
            status=SettleDecisionStatus.READY_TO_CAPTURE,
            stop_reason=stop_reason,
            ready_to_capture=True,
            capture_after_monotonic_ms=(samples[-1].sampled_at_monotonic_ms if samples else None),
            diff=self.fusion.diff_for_samples(samples),
            quality=self.fusion.quality_for_samples(samples),
            stable_sample_count=self._trailing_status_count(samples, SettleSampleStatus.STABLE),
            sample_count=len(samples),
            needs_review=needs_review,
            diagnostics=("settle polling finalized capture instruction",),
        )

    def _timeout(
        self, plan: SettlePollingPlan, samples: tuple[SettleSample, ...], *, stop_reason: SettleStopReason
    ) -> SettleDecision:
        timeout_capture_enabled = (
            self.config.settle_timeout_capture_enabled
            if plan.timeout_capture_enabled is None
            else plan.timeout_capture_enabled
        )
        if timeout_capture_enabled:
            return SettleDecision(
                plan_id=plan.plan_id,
                candidate_id=plan.candidate_id,
                session_id=plan.session_id,
                status=SettleDecisionStatus.TIMEOUT_CAPTURE,
                stop_reason=stop_reason,
                ready_to_capture=True,
                capture_after_monotonic_ms=plan.settle_window.deadline_monotonic_ms,
                diff=self.fusion.diff_for_samples(samples),
                quality=self.fusion.quality_for_samples(samples),
                stable_sample_count=self._trailing_status_count(samples, SettleSampleStatus.STABLE),
                sample_count=len(samples),
                needs_review=True,
                diagnostics=("settle polling timed out; capturing best available result",),
            )
        return self._suppressed(plan, stop_reason, sample_count=len(samples))

    def _suppressed(
        self, plan: SettlePollingPlan, stop_reason: SettleStopReason, *, sample_count: int
    ) -> SettleDecision:
        return SettleDecision(
            plan_id=plan.plan_id,
            candidate_id=plan.candidate_id,
            session_id=plan.session_id,
            status=SettleDecisionStatus.SUPPRESSED,
            stop_reason=stop_reason,
            sample_count=sample_count,
            needs_review=True,
            diagnostics=("settle polling suppressed candidate",),
        )
