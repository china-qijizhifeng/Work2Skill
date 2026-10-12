"""Composable policies for evidence-aware keyframe timing."""

from __future__ import annotations

from dataclasses import dataclass

from packages.contracts import (
    AdaptiveSettleWindow,
    ClickTargetConfidenceBand,
    ClickTargetResolutionStatus,
    HumanActionEvidenceRole,
    HumanActionKind,
    KeyframeCapturePlan,
    KeyframeDiffReport,
    KeyframeDropReason,
    KeyframeKeepReason,
    KeyframePriorityBand,
    KeyframeQualityDecision,
    KeyframeQualityReport,
    KeyframeRole,
    KeyframeSignalEnvelope,
    KeyframeTimingConfig,
    KeyframeTriggerKind,
    PlannedKeyframeTrigger,
    ProducerInputEventKind,
    RecordingControlKind,
    RedactionState,
)
from packages.contracts.common import JsonScalar

_ACTION_KINDS_NEEDING_BEFORE_CONTEXT = {
    HumanActionKind.CLICK,
    HumanActionKind.HOTKEY,
    HumanActionKind.WINDOW_SWITCH,
    HumanActionKind.TAB_SWITCH,
}
_COMMAND_SEMANTIC_ACTIONS = {HumanActionKind.HOTKEY, HumanActionKind.TYPING_PAUSE}
_SENSITIVE_REDACTION_STATES = {RedactionState.BLOCKED, RedactionState.QUARANTINED}


def target_probe_settle_window(
    config: KeyframeTimingConfig, occurred_at_monotonic_ms: int | None
) -> AdaptiveSettleWindow:
    """Build the bounded settle window shared by planned and backfilled target probes.

    Args:
        config: Timing config that owns target-probe settle thresholds.
        occurred_at_monotonic_ms: Monotonic time used to derive execute/deadline bounds.

    Returns:
        Adaptive settle window for the target probe.
    """

    execute_after = (
        occurred_at_monotonic_ms + config.settle_min_delay_ms if occurred_at_monotonic_ms is not None else None
    )
    deadline = occurred_at_monotonic_ms + config.settle_max_wait_ms if occurred_at_monotonic_ms is not None else None
    return AdaptiveSettleWindow(
        min_delay_ms=config.settle_min_delay_ms,
        max_wait_ms=config.settle_max_wait_ms,
        poll_interval_ms=config.settle_poll_interval_ms,
        required_stable_samples=config.settle_required_stable_samples,
        execute_after_monotonic_ms=execute_after,
        deadline_monotonic_ms=deadline,
    )


def target_probe_settle_metadata(config: KeyframeTimingConfig, settle: AdaptiveSettleWindow) -> dict[str, JsonScalar]:
    """Return safe polling metadata for target-disambiguation probes.

    Target probes are support evidence, not user-facing result frames. They can be
    sampled for more context, but timeout capture is explicitly disabled so a
    low-confidence probe cannot create another noisy keyframe by itself.

    Args:
        config: Timing config containing live-polling and provider strategy knobs.
        settle: Settle window to mirror into durable trigger metadata.

    Returns:
        Safe JSON-scalar metadata for a target-probe trigger.
    """

    metadata: dict[str, JsonScalar] = {
        "timing_component": "target_probe",
        "settle_timeout_capture_enabled": False,
        "settle_min_delay_ms": settle.min_delay_ms,
        "settle_max_wait_ms": settle.max_wait_ms,
        "settle_poll_interval_ms": settle.poll_interval_ms,
        "settle_required_stable_samples": settle.required_stable_samples,
    }
    if config.settle_live_polling_enabled:
        metadata["settle_live_polling_state"] = "pending"
        metadata["settle_probe_strategy"] = config.settle_probe_strategy.value
        metadata["settle_sample_budget"] = config.settle_sample_budget
    if settle.execute_after_monotonic_ms is not None:
        metadata["settle_execute_after_monotonic_ms"] = settle.execute_after_monotonic_ms
    if settle.deadline_monotonic_ms is not None:
        metadata["settle_deadline_monotonic_ms"] = settle.deadline_monotonic_ms
    return metadata


@dataclass(frozen=True)
class ActionBoundaryPolicy:
    """Decide whether an action needs a before-action context frame.

    Attributes:
        config: Timing thresholds that control before-frame reuse and capture.
    """

    config: KeyframeTimingConfig

    def plan(self, signal: KeyframeSignalEnvelope) -> tuple[PlannedKeyframeTrigger, ...]:
        if not self.config.before_action_enabled:
            return ()
        if signal.action_kind not in _ACTION_KINDS_NEEDING_BEFORE_CONTEXT:
            return ()
        if signal.redaction_state in _SENSITIVE_REDACTION_STATES:
            return (
                PlannedKeyframeTrigger(
                    trigger_kind=KeyframeTriggerKind.ACTION_BEFORE,
                    role=KeyframeRole.BEFORE_ACTION,
                    priority=KeyframePriorityBand.NORMAL,
                    drop_reason=KeyframeDropReason.SENSITIVE_SURFACE,
                    action_id=signal.action_id,
                    action_evidence_role=(
                        HumanActionEvidenceRole.BEFORE_KEYFRAME if signal.action_id is not None else None
                    ),
                    metadata={"timing_component": "action_boundary"},
                ),
            )
        if self._has_fresh_before_context(signal):
            return ()
        if signal.metadata.get("native_event_phase") not in {"pre_action", "before_action"}:
            return (
                PlannedKeyframeTrigger(
                    trigger_kind=KeyframeTriggerKind.ACTION_BEFORE,
                    role=KeyframeRole.BEFORE_ACTION,
                    priority=KeyframePriorityBand.NORMAL,
                    drop_reason=KeyframeDropReason.PRE_ACTION_UNAVAILABLE,
                    action_id=signal.action_id,
                    action_evidence_role=(
                        HumanActionEvidenceRole.BEFORE_KEYFRAME if signal.action_id is not None else None
                    ),
                    metadata={"timing_component": "action_boundary"},
                ),
            )
        return (
            PlannedKeyframeTrigger(
                trigger_kind=KeyframeTriggerKind.ACTION_BEFORE,
                role=KeyframeRole.BEFORE_ACTION,
                priority=KeyframePriorityBand.HIGH,
                keep_reason=KeyframeKeepReason.BEFORE_ACTION_CONTEXT,
                action_id=signal.action_id,
                action_evidence_role=HumanActionEvidenceRole.BEFORE_KEYFRAME if signal.action_id is not None else None,
                occurred_at_monotonic_ms=signal.occurred_at_monotonic_ms,
                debounce_until_monotonic_ms=signal.occurred_at_monotonic_ms,
                metadata={
                    "timing_component": "action_boundary",
                },
            ),
        )

    def _has_fresh_before_context(self, signal: KeyframeSignalEnvelope) -> bool:
        if (
            signal.last_keyframe_id is None
            or signal.last_keyframe_monotonic_ms is None
            or signal.occurred_at_monotonic_ms is None
        ):
            return False
        age_ms = signal.occurred_at_monotonic_ms - signal.last_keyframe_monotonic_ms
        return 0 <= age_ms <= self.config.before_action_freshness_ms


@dataclass(frozen=True)
class AdaptiveSettlePolicy:
    """Plan result keyframes with action-specific settle windows.

    Attributes:
        config: Delay, timeout, and stability knobs for adaptive result capture.
    """

    config: KeyframeTimingConfig

    def plan(
        self, signal: KeyframeSignalEnvelope, *, base_trigger: KeyframeTriggerKind | None
    ) -> tuple[PlannedKeyframeTrigger, ...]:
        if signal.action_kind is None:
            return ()
        if signal.redaction_state in _SENSITIVE_REDACTION_STATES:
            return ()
        trigger_kind = self._trigger_kind(signal=signal, base_trigger=base_trigger)
        if trigger_kind is None:
            return ()
        settle = self.window_for(signal) if self.config.adaptive_settle_enabled else None
        keep_reason = self._keep_reason(trigger_kind)
        metadata: dict[str, JsonScalar] = {
            "timing_component": "adaptive_settle" if settle is not None else "fixed_settle",
        }
        if settle is not None:
            if self.config.settle_live_polling_enabled:
                metadata["settle_live_polling_state"] = "pending"
                metadata["settle_probe_strategy"] = self.config.settle_probe_strategy.value
                metadata["settle_sample_budget"] = self.config.settle_sample_budget
                metadata["settle_timeout_capture_enabled"] = self.config.settle_timeout_capture_enabled
            metadata["settle_min_delay_ms"] = settle.min_delay_ms
            metadata["settle_max_wait_ms"] = settle.max_wait_ms
            metadata["settle_poll_interval_ms"] = settle.poll_interval_ms
            metadata["settle_required_stable_samples"] = settle.required_stable_samples
            if settle.execute_after_monotonic_ms is not None:
                metadata["settle_execute_after_monotonic_ms"] = settle.execute_after_monotonic_ms
            if settle.deadline_monotonic_ms is not None:
                metadata["settle_deadline_monotonic_ms"] = settle.deadline_monotonic_ms
        return (
            PlannedKeyframeTrigger(
                trigger_kind=trigger_kind,
                role=self._role_for(trigger_kind),
                priority=self._priority_for(trigger_kind),
                keep_reason=keep_reason,
                action_id=signal.action_id,
                action_evidence_role=HumanActionEvidenceRole.AFTER_KEYFRAME if signal.action_id is not None else None,
                occurred_at_monotonic_ms=signal.occurred_at_monotonic_ms,
                debounce_until_monotonic_ms=settle.execute_after_monotonic_ms if settle is not None else None,
                settle_window=settle,
                metadata=metadata,
            ),
        )

    def window_for(self, signal: KeyframeSignalEnvelope) -> AdaptiveSettleWindow:
        min_delay = self.config.settle_min_delay_ms
        max_wait = self.config.settle_max_wait_ms
        if signal.action_kind in _COMMAND_SEMANTIC_ACTIONS:
            min_delay = max(min_delay, 350)
            max_wait = max(max_wait, 2_000)
        if signal.producer_event_kind in {ProducerInputEventKind.WINDOW_FOCUS, ProducerInputEventKind.TAB_SWITCH}:
            min_delay = max(min_delay, 450)
            max_wait = max(max_wait, 2_500)
        if signal.action_kind == HumanActionKind.SCROLL:
            min_delay = max(min_delay, 300)
            max_wait = max(max_wait, 1_200)
        execute_after = (
            signal.occurred_at_monotonic_ms + min_delay if signal.occurred_at_monotonic_ms is not None else None
        )
        deadline = signal.occurred_at_monotonic_ms + max_wait if signal.occurred_at_monotonic_ms is not None else None
        return AdaptiveSettleWindow(
            min_delay_ms=min_delay,
            max_wait_ms=max_wait,
            poll_interval_ms=self.config.settle_poll_interval_ms,
            required_stable_samples=self.config.settle_required_stable_samples,
            execute_after_monotonic_ms=execute_after,
            deadline_monotonic_ms=deadline,
        )

    def _trigger_kind(
        self,
        *,
        signal: KeyframeSignalEnvelope,
        base_trigger: KeyframeTriggerKind | None,
    ) -> KeyframeTriggerKind | None:
        if signal.action_kind == HumanActionKind.CLICK:
            return base_trigger or KeyframeTriggerKind.CLICK_SETTLE
        if signal.action_kind == HumanActionKind.SCROLL:
            return base_trigger or KeyframeTriggerKind.SCROLL_STOP
        if signal.action_kind == HumanActionKind.HOTKEY:
            return base_trigger or KeyframeTriggerKind.HOTKEY_SETTLE
        if signal.action_kind == HumanActionKind.TYPING_PAUSE:
            if base_trigger in {KeyframeTriggerKind.COMMAND_SUBMITTED, KeyframeTriggerKind.TYPING_SETTLE}:
                return base_trigger
            return None
        if signal.action_kind in {HumanActionKind.WINDOW_SWITCH, HumanActionKind.TAB_SWITCH}:
            return KeyframeTriggerKind.NAVIGATION_COMMITTED
        return base_trigger

    def _role_for(self, trigger_kind: KeyframeTriggerKind) -> KeyframeRole:
        if trigger_kind in {KeyframeTriggerKind.NAVIGATION_COMMITTED, KeyframeTriggerKind.MODAL_STATE_CHANGE}:
            return KeyframeRole.RESULT
        if trigger_kind == KeyframeTriggerKind.SCROLL_MILESTONE:
            return KeyframeRole.SCROLL_MILESTONE
        return KeyframeRole.RESULT

    def _priority_for(self, trigger_kind: KeyframeTriggerKind) -> KeyframePriorityBand:
        if trigger_kind in {
            KeyframeTriggerKind.COMMAND_SUBMITTED,
            KeyframeTriggerKind.NAVIGATION_COMMITTED,
            KeyframeTriggerKind.ERROR_SURFACE_DETECTED,
        }:
            return KeyframePriorityBand.HIGH
        return KeyframePriorityBand.NORMAL

    def _keep_reason(self, trigger_kind: KeyframeTriggerKind) -> KeyframeKeepReason:
        if trigger_kind == KeyframeTriggerKind.COMMAND_SUBMITTED:
            return KeyframeKeepReason.COMMAND_BOUNDARY
        if trigger_kind in {KeyframeTriggerKind.NAVIGATION_COMMITTED, KeyframeTriggerKind.SURFACE_CHANGE}:
            return KeyframeKeepReason.NAVIGATION_BOUNDARY
        return KeyframeKeepReason.RESULT_OBSERVED


@dataclass(frozen=True)
class ScrollMilestonePolicy:
    """Keep representative scroll milestones without flooding the timeline.

    Attributes:
        config: Screen-fraction and minimum-gap knobs for scroll milestone capture.
    """

    config: KeyframeTimingConfig

    def plan(self, signal: KeyframeSignalEnvelope) -> tuple[PlannedKeyframeTrigger, ...]:
        if not self.config.scroll_milestone_enabled or signal.action_kind != HumanActionKind.SCROLL:
            return ()
        if signal.scroll_delta_y is None:
            return ()
        reference_height = 800.0
        if signal.scope is not None and signal.scope.selection_region is not None:
            reference_height = max(1.0, float(signal.scope.selection_region.height))
        elif signal.scope is not None and signal.scope.bounds is not None:
            reference_height = max(1.0, float(signal.scope.bounds.height))
        if abs(signal.scroll_delta_y) < reference_height * self.config.scroll_milestone_screen_fraction:
            return ()
        return (
            PlannedKeyframeTrigger(
                trigger_kind=KeyframeTriggerKind.SCROLL_MILESTONE,
                role=KeyframeRole.SCROLL_MILESTONE,
                priority=KeyframePriorityBand.NORMAL,
                keep_reason=KeyframeKeepReason.SCROLL_MILESTONE,
                occurred_at_monotonic_ms=signal.occurred_at_monotonic_ms,
                debounce_until_monotonic_ms=(
                    signal.occurred_at_monotonic_ms + self.config.scroll_milestone_min_gap_ms
                    if signal.occurred_at_monotonic_ms is not None
                    else None
                ),
                metadata={
                    "timing_component": "scroll_milestone",
                    "scroll_delta_bucket": self._bucket(abs(signal.scroll_delta_y)),
                },
                action_id=signal.action_id,
                action_evidence_role=HumanActionEvidenceRole.AFTER_KEYFRAME if signal.action_id is not None else None,
            ),
        )

    def _bucket(self, value: float) -> int:
        return min(10, max(1, int(value // 250) + 1))


@dataclass(frozen=True)
class SurfaceChangePolicy:
    """Promote focus, tab, and modal changes into navigation boundary frames.

    Attributes:
        config: Settle timing used after surface boundaries are observed.
    """

    config: KeyframeTimingConfig

    def plan(self, signal: KeyframeSignalEnvelope) -> tuple[PlannedKeyframeTrigger, ...]:
        if signal.producer_event_kind not in {ProducerInputEventKind.WINDOW_FOCUS, ProducerInputEventKind.TAB_SWITCH}:
            return ()
        return (
            PlannedKeyframeTrigger(
                trigger_kind=KeyframeTriggerKind.NAVIGATION_COMMITTED,
                role=KeyframeRole.RESULT,
                priority=KeyframePriorityBand.HIGH,
                keep_reason=KeyframeKeepReason.NAVIGATION_BOUNDARY,
                action_id=signal.action_id,
                action_evidence_role=HumanActionEvidenceRole.AFTER_KEYFRAME if signal.action_id is not None else None,
                occurred_at_monotonic_ms=signal.occurred_at_monotonic_ms,
                debounce_until_monotonic_ms=(
                    signal.occurred_at_monotonic_ms + self.config.settle_min_delay_ms
                    if signal.occurred_at_monotonic_ms is not None
                    else None
                ),
                metadata={
                    "timing_component": "surface_change",
                },
            ),
        )


@dataclass(frozen=True)
class ErrorSurfacePolicy:
    """Capture safe error, warning, alert, and toast surfaces.

    Attributes:
        config: Feature flag and policy version for safe error-surface capture.
    """

    config: KeyframeTimingConfig

    def plan(self, signal: KeyframeSignalEnvelope) -> tuple[PlannedKeyframeTrigger, ...]:
        if not self.config.error_surface_capture_enabled:
            return ()
        surface_kind = signal.metadata.get("surface_signal_kind")
        if surface_kind not in {"alert", "error_banner", "permission_warning", "toast", "warning"}:
            return ()
        if signal.redaction_state in _SENSITIVE_REDACTION_STATES:
            return (
                PlannedKeyframeTrigger(
                    trigger_kind=KeyframeTriggerKind.ERROR_SURFACE_DETECTED,
                    role=KeyframeRole.ERROR_STATE,
                    priority=KeyframePriorityBand.HIGH,
                    drop_reason=KeyframeDropReason.SENSITIVE_SURFACE,
                    action_id=signal.action_id,
                    action_evidence_role=(
                        HumanActionEvidenceRole.RESULT_EVIDENCE if signal.action_id is not None else None
                    ),
                    metadata={"timing_component": "error_surface"},
                ),
            )
        return (
            PlannedKeyframeTrigger(
                trigger_kind=KeyframeTriggerKind.ERROR_SURFACE_DETECTED,
                role=KeyframeRole.ERROR_STATE,
                priority=KeyframePriorityBand.HIGH,
                keep_reason=KeyframeKeepReason.ERROR_OBSERVED,
                action_id=signal.action_id,
                action_evidence_role=HumanActionEvidenceRole.RESULT_EVIDENCE if signal.action_id is not None else None,
                occurred_at_monotonic_ms=signal.occurred_at_monotonic_ms,
                debounce_until_monotonic_ms=signal.occurred_at_monotonic_ms,
                metadata={
                    "surface_signal_kind": str(surface_kind),
                    "timing_component": "error_surface",
                },
            ),
        )


@dataclass(frozen=True)
class TargetProbePolicy:
    """Plan a probe frame when click target resolution is weak.

    Attributes:
        config: Feature flag and settle timing for target disambiguation probes.
    """

    config: KeyframeTimingConfig

    def plan(self, signal: KeyframeSignalEnvelope) -> tuple[PlannedKeyframeTrigger, ...]:
        if not self.config.target_probe_enabled or signal.action_kind != HumanActionKind.CLICK:
            return ()
        if signal.click_target_status not in {
            ClickTargetResolutionStatus.PENDING,
            ClickTargetResolutionStatus.AMBIGUOUS,
            ClickTargetResolutionStatus.LOW_CONFIDENCE,
        } and signal.click_target_confidence_band not in {
            ClickTargetConfidenceBand.LOW,
            ClickTargetConfidenceBand.UNAVAILABLE,
        }:
            return ()
        settle = target_probe_settle_window(self.config, signal.occurred_at_monotonic_ms)
        return (
            PlannedKeyframeTrigger(
                trigger_kind=KeyframeTriggerKind.TARGET_RESOLUTION_PROBE,
                role=KeyframeRole.RESULT,
                priority=KeyframePriorityBand.NORMAL,
                keep_reason=KeyframeKeepReason.TARGET_DISAMBIGUATION,
                action_id=signal.action_id,
                action_evidence_role=HumanActionEvidenceRole.TARGET_EVIDENCE if signal.action_id is not None else None,
                occurred_at_monotonic_ms=signal.occurred_at_monotonic_ms,
                debounce_until_monotonic_ms=settle.execute_after_monotonic_ms,
                settle_window=settle,
                metadata=target_probe_settle_metadata(self.config, settle),
            ),
        )


@dataclass(frozen=True)
class QualityKeepDropPolicy:
    """Decide whether a candidate has enough information gain to keep.

    Attributes:
        config: Quality thresholds and policy version for keep/drop decisions.
    """

    config: KeyframeTimingConfig

    def decide(
        self,
        *,
        trigger_kind: KeyframeTriggerKind,
        priority: KeyframePriorityBand,
        diff: KeyframeDiffReport | None,
        quality: KeyframeQualityReport | None,
    ) -> KeyframeQualityDecision:
        if priority == KeyframePriorityBand.REQUIRED:
            return KeyframeQualityDecision(
                kept=True,
                keep_reason=KeyframeKeepReason.REQUIRED_BOUNDARY,
                information_gain=1.0,
                confidence=1.0,
            )
        information_gain = self._information_gain(diff=diff, quality=quality)
        if trigger_kind == KeyframeTriggerKind.ERROR_SURFACE_DETECTED:
            return KeyframeQualityDecision(
                kept=True,
                keep_reason=KeyframeKeepReason.ERROR_OBSERVED,
                information_gain=max(information_gain, self.config.quality_min_information_gain),
                confidence=quality.confidence if quality is not None else 0.7,
            )
        if information_gain < self.config.quality_min_information_gain:
            return KeyframeQualityDecision(
                kept=False,
                drop_reason=KeyframeDropReason.LOW_INFORMATION_GAIN,
                information_gain=information_gain,
                confidence=quality.confidence if quality is not None else 0.0,
                diagnostics=("candidate below quality_min_information_gain",),
            )
        return KeyframeQualityDecision(
            kept=True,
            keep_reason=KeyframeKeepReason.ADAPTIVE_STABILITY,
            information_gain=information_gain,
            confidence=quality.confidence if quality is not None else information_gain,
        )

    def _information_gain(
        self,
        *,
        diff: KeyframeDiffReport | None,
        quality: KeyframeQualityReport | None,
    ) -> float:
        values: list[float] = []
        if diff is not None:
            if diff.visual_delta is not None:
                values.append(min(1.0, diff.visual_delta))
            if diff.text_delta is not None:
                values.append(min(1.0, diff.text_delta))
            if diff.changed:
                values.append(self.config.quality_min_information_gain)
        if quality is not None:
            if quality.screenshot_available or quality.system_appshot_available:
                values.append(0.08)
            if quality.text_chars > 0:
                values.append(min(0.25, quality.text_chars / 2_000))
            values.append(min(1.0, max(0.0, quality.confidence)) * 0.25)
        return max(values, default=0.0)


@dataclass(frozen=True)
class ActionKeyframePlanner:
    """Chain keyframe timing policies into a single capture plan.

    Attributes:
        action_boundary: Strategy for before-action context frames.
        adaptive_settle: Strategy for action result timing windows.
        scroll_milestone: Strategy for representative long-scroll frames.
        surface_change: Strategy for navigation and focus boundary frames.
        error_surface: Strategy for safe warning, alert, and toast frames.
        target_probe: Strategy for click target disambiguation frames.
        config: Shared keyframe timing configuration.
    """

    action_boundary: ActionBoundaryPolicy
    adaptive_settle: AdaptiveSettlePolicy
    scroll_milestone: ScrollMilestonePolicy
    surface_change: SurfaceChangePolicy
    error_surface: ErrorSurfacePolicy
    target_probe: TargetProbePolicy
    config: KeyframeTimingConfig

    @classmethod
    def default(cls, config: KeyframeTimingConfig) -> "ActionKeyframePlanner":
        return cls(
            action_boundary=ActionBoundaryPolicy(config),
            adaptive_settle=AdaptiveSettlePolicy(config),
            scroll_milestone=ScrollMilestonePolicy(config),
            surface_change=SurfaceChangePolicy(config),
            error_surface=ErrorSurfacePolicy(config),
            target_probe=TargetProbePolicy(config),
            config=config,
        )

    def plan(
        self,
        *,
        signal: KeyframeSignalEnvelope,
        base_trigger: KeyframeTriggerKind | None,
    ) -> KeyframeCapturePlan:
        triggers: list[PlannedKeyframeTrigger] = []
        triggers.extend(self.action_boundary.plan(signal))
        triggers.extend(self.scroll_milestone.plan(signal))
        triggers.extend(self.surface_change.plan(signal))
        triggers.extend(self.adaptive_settle.plan(signal, base_trigger=base_trigger))
        triggers.extend(self.target_probe.plan(signal))
        triggers.extend(self.error_surface.plan(signal))
        visible_triggers = self._dedupe(tuple(trigger for trigger in triggers if trigger.drop_reason is None))
        dropped_triggers = tuple(trigger for trigger in triggers if trigger.drop_reason is not None)
        diagnostics = tuple(
            dict.fromkeys(
                (
                    *(
                        f"dropped:{trigger.trigger_kind.value}:{trigger.drop_reason.value}"
                        for trigger in dropped_triggers
                        if trigger.drop_reason
                    ),
                    *(f"planned:{trigger.trigger_kind.value}" for trigger in visible_triggers),
                )
            )
        )
        return KeyframeCapturePlan(
            signal_id=signal.signal_id,
            session_id=signal.session_id,
            action_id=signal.action_id,
            triggers=visible_triggers,
            reused_before_keyframe_id=self._reused_before_keyframe(signal),
            needs_review=signal.redaction_state in _SENSITIVE_REDACTION_STATES or bool(dropped_triggers),
            diagnostics=diagnostics,
            policy_version=self.config.policy_version,
        )

    def _reused_before_keyframe(self, signal: KeyframeSignalEnvelope) -> str | None:
        if self.action_boundary._has_fresh_before_context(signal):
            return signal.last_keyframe_id
        return None

    def _dedupe(self, triggers: tuple[PlannedKeyframeTrigger, ...]) -> tuple[PlannedKeyframeTrigger, ...]:
        seen: set[tuple[KeyframeTriggerKind, KeyframeRole, str | None]] = set()
        deduped: list[PlannedKeyframeTrigger] = []
        for trigger in triggers:
            key = (trigger.trigger_kind, trigger.role, trigger.action_id)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(trigger)
        return tuple(deduped)
