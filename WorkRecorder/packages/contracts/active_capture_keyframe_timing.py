"""Typed contracts for evidence-aware keyframe timing decisions."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import Field, model_validator

from .active_capture import ActiveCapturePolicyConfig, KeyframeDiffReport, KeyframeQualityReport, RecordingScope
from .active_capture_demonstration import ActionCoordinates
from .active_capture_metadata import validate_safe_metadata
from .base import ContractModel
from .common import JsonScalar
from .enums import (
    ClickTargetConfidenceBand,
    ClickTargetResolutionStatus,
    HotkeySemantic,
    HumanActionEvidenceRole,
    HumanActionKind,
    KeyframeDropReason,
    KeyframeKeepReason,
    KeyframePriorityBand,
    KeyframeRole,
    KeyframeTriggerKind,
    ProducerInputEventKind,
    ProviderReadinessState,
    RecordingControlKind,
    RedactionState,
    SettleDecisionStatus,
    SettleSampleStatus,
    SettleSignalKind,
    SettleStopReason,
    TextDiffMethod,
    VisualProbeMode,
)


def _validate_timing_metadata(metadata: dict[str, JsonScalar]) -> None:
    validate_safe_metadata(metadata, context="keyframe timing metadata")
    _validate_safe_metric_values(metadata, context="keyframe timing metadata")


_SAFE_FINGERPRINT = re.compile(r"^(fnv64:[0-9a-f]{16}|sha256:[0-9a-f]{64}|phash-[a-z0-9_-]{1,64})$")
_SAFE_SAMPLE_ID = re.compile(r"^[A-Za-z0-9_-]{1,96}$")
_SAFE_PROVIDER_KEY = re.compile(r"^[a-z0-9_.-]{1,64}$")
_SUSPICIOUS_VALUE_FRAGMENTS = (
    "://",
    "/users/",
    "\\users\\",
    "bearer ",
    "secret",
    "token",
    "password",
    "raw",
    "selector",
    "<html",
    "data:image",
    "base64,",
)


def _validate_safe_metric_values(values: dict[str, JsonScalar], *, context: str) -> None:
    for key, value in values.items():
        if isinstance(value, str):
            lowered = value.lower()
            if len(value) > 160 or any(fragment in lowered for fragment in _SUSPICIOUS_VALUE_FRAGMENTS):
                raise ValueError(f"{context} includes forbidden sensitive metadata value for key: {key}")


def _validate_diagnostics(diagnostics: tuple[str, ...], *, context: str) -> None:
    if len(diagnostics) > 8:
        raise ValueError(f"{context} includes too many diagnostics")
    for diagnostic in diagnostics:
        if len(diagnostic) > 160:
            raise ValueError(f"{context} diagnostic is too long")
        lowered = diagnostic.lower()
        if any(fragment in lowered for fragment in _SUSPICIOUS_VALUE_FRAGMENTS):
            raise ValueError(f"{context} diagnostic includes forbidden sensitive value")


def _validate_fingerprint(value: str | None, *, context: str) -> None:
    if value is not None and _SAFE_FINGERPRINT.fullmatch(value.lower()) is None:
        raise ValueError(f"{context} fingerprint must be a safe digest")


def _validate_sample_id(value: str | None, *, context: str) -> None:
    if value is not None and _SAFE_SAMPLE_ID.fullmatch(value) is None:
        raise ValueError(f"{context} sample_id must be a safe identifier")


class KeyframeTimingConfig(ContractModel):
    """Policy knobs for evidence-aware keyframe timing orchestration."""

    before_action_enabled: bool = True
    before_action_freshness_ms: int = Field(default=1_500, ge=0)
    adaptive_settle_enabled: bool = True
    settle_min_delay_ms: int = Field(default=250, ge=0)
    settle_max_wait_ms: int = Field(default=1_500, ge=0)
    settle_poll_interval_ms: int = Field(default=150, ge=1)
    settle_required_stable_samples: int = Field(default=2, ge=1, le=10)
    settle_live_polling_enabled: bool = True
    settle_probe_strategy: VisualProbeMode = VisualProbeMode.HYBRID
    settle_sample_budget: int = Field(default=12, ge=1, le=100)
    settle_visual_diff_enabled: bool = True
    settle_text_diff_enabled: bool = True
    settle_provider_readiness_enabled: bool = True
    settle_timeout_capture_enabled: bool = True
    settle_capture_claim_lease_ms: int = Field(default=30_000, ge=1_000, le=300_000)
    scroll_milestone_enabled: bool = True
    scroll_milestone_screen_fraction: float = Field(default=0.9, ge=0.1, le=5.0)
    scroll_milestone_min_gap_ms: int = Field(default=900, ge=0)
    target_probe_enabled: bool = True
    error_surface_capture_enabled: bool = True
    quality_min_information_gain: float = Field(default=0.12, ge=0.0, le=1.0)
    max_result_frames_per_action: int = Field(default=2, ge=0, le=8)
    policy_version: str = Field(default="active_capture_policy_v2", min_length=1)

    @classmethod
    def from_active_capture_policy(cls, config: ActiveCapturePolicyConfig) -> "KeyframeTimingConfig":
        """Build timing config from the broader active-capture policy."""

        return cls(
            before_action_enabled=config.before_action_keyframes_enabled,
            before_action_freshness_ms=config.before_action_freshness_ms,
            adaptive_settle_enabled=config.adaptive_settle_enabled,
            settle_min_delay_ms=config.adaptive_settle_min_delay_ms,
            settle_max_wait_ms=config.adaptive_settle_max_wait_ms,
            settle_poll_interval_ms=config.adaptive_settle_poll_interval_ms,
            settle_required_stable_samples=config.adaptive_settle_required_stable_samples,
            settle_live_polling_enabled=config.settle_live_polling_enabled,
            settle_probe_strategy=VisualProbeMode(config.settle_probe_strategy),
            settle_sample_budget=config.settle_sample_budget,
            settle_visual_diff_enabled=config.settle_visual_diff_enabled,
            settle_text_diff_enabled=config.settle_text_diff_enabled,
            settle_provider_readiness_enabled=config.settle_provider_readiness_enabled,
            settle_timeout_capture_enabled=config.settle_timeout_capture_enabled,
            settle_capture_claim_lease_ms=config.settle_capture_claim_lease_ms,
            scroll_milestone_enabled=config.scroll_milestone_enabled,
            scroll_milestone_screen_fraction=config.scroll_milestone_screen_fraction,
            scroll_milestone_min_gap_ms=config.scroll_milestone_min_gap_ms,
            target_probe_enabled=config.target_probe_enabled,
            error_surface_capture_enabled=config.error_surface_capture_enabled,
            quality_min_information_gain=config.quality_min_information_gain,
            max_result_frames_per_action=config.max_result_frames_per_action,
            policy_version=config.policy_version,
        )


class AdaptiveSettleWindow(ContractModel):
    """Bounded settle window for one action result keyframe."""

    min_delay_ms: int = Field(ge=0)
    max_wait_ms: int = Field(ge=0)
    poll_interval_ms: int = Field(ge=1)
    required_stable_samples: int = Field(ge=1, le=10)
    execute_after_monotonic_ms: int | None = Field(default=None, ge=0)
    deadline_monotonic_ms: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_window(self) -> "AdaptiveSettleWindow":
        if self.max_wait_ms < self.min_delay_ms:
            raise ValueError("adaptive settle max_wait_ms must be >= min_delay_ms")
        if (
            self.execute_after_monotonic_ms is not None
            and self.deadline_monotonic_ms is not None
            and self.deadline_monotonic_ms < self.execute_after_monotonic_ms
        ):
            raise ValueError("adaptive settle deadline must be >= execute_after_monotonic_ms")
        return self


class KeyframeSignalEnvelope(ContractModel):
    """Typed signal consumed by keyframe timing policies."""

    session_id: str
    signal_id: str
    occurred_at: datetime
    occurred_at_monotonic_ms: int | None = Field(default=None, ge=0)
    action_id: str | None = None
    action_kind: HumanActionKind | None = None
    producer_event_kind: ProducerInputEventKind | None = None
    control_kind: RecordingControlKind | None = None
    trigger_kind: KeyframeTriggerKind | None = None
    hotkey_semantic: HotkeySemantic | None = None
    scroll_delta_y: float | None = None
    scope: RecordingScope | None = None
    coordinates: ActionCoordinates | None = None
    redaction_state: RedactionState = RedactionState.NONE
    click_target_status: ClickTargetResolutionStatus | None = None
    click_target_confidence_band: ClickTargetConfidenceBand | None = None
    last_keyframe_id: str | None = None
    last_keyframe_monotonic_ms: int | None = Field(default=None, ge=0)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata_keys(self) -> "KeyframeSignalEnvelope":
        _validate_timing_metadata(self.metadata)
        return self


class PlannedKeyframeTrigger(ContractModel):
    """One trigger proposed by the timing orchestrator."""

    trigger_kind: KeyframeTriggerKind
    role: KeyframeRole
    priority: KeyframePriorityBand
    keep_reason: KeyframeKeepReason | None = None
    drop_reason: KeyframeDropReason | None = None
    action_id: str | None = None
    action_evidence_role: HumanActionEvidenceRole | None = None
    occurred_at_monotonic_ms: int | None = Field(default=None, ge=0)
    debounce_until_monotonic_ms: int | None = Field(default=None, ge=0)
    settle_window: AdaptiveSettleWindow | None = None
    diff: KeyframeDiffReport | None = None
    quality: KeyframeQualityReport | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata_keys(self) -> "PlannedKeyframeTrigger":
        _validate_timing_metadata(self.metadata)
        if self.action_evidence_role is not None and self.action_id is None:
            raise ValueError("planned keyframe trigger action_evidence_role requires action_id")
        return self


class KeyframeCapturePlan(ContractModel):
    """Complete timing plan for one signal."""

    signal_id: str
    session_id: str
    action_id: str | None = None
    triggers: tuple[PlannedKeyframeTrigger, ...] = Field(default_factory=tuple)
    reused_before_keyframe_id: str | None = None
    needs_review: bool = False
    diagnostics: tuple[str, ...] = Field(default_factory=tuple)
    policy_version: str = Field(default="active_capture_policy_v2", min_length=1)


class KeyframeQualityDecision(ContractModel):
    """Auditable keep/drop decision after quality and information-gain checks."""

    kept: bool
    keep_reason: KeyframeKeepReason | None = None
    drop_reason: KeyframeDropReason | None = None
    information_gain: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    replacement_keyframe_id: str | None = None
    diagnostics: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_reason(self) -> "KeyframeQualityDecision":
        if self.kept and self.keep_reason is None:
            raise ValueError("kept keyframe quality decision requires keep_reason")
        if not self.kept and self.drop_reason is None:
            raise ValueError("dropped keyframe quality decision requires drop_reason")
        return self


class ActionKeyframeLinkView(ContractModel):
    """Safe view of keyframes linked to one action."""

    action_id: str
    before_keyframe_id: str | None = None
    after_keyframe_id: str | None = None
    result_keyframe_id: str | None = None
    target_probe_keyframe_id: str | None = None
    link_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_review: bool = False
    diagnostics: tuple[str, ...] = Field(default_factory=tuple)


class VisualDiffSummary(ContractModel):
    """Safe visual probe metrics observed during adaptive settle polling."""

    enabled: bool = True
    mode: VisualProbeMode = VisualProbeMode.HYBRID
    status: SettleSampleStatus = SettleSampleStatus.OBSERVED
    visual_delta: float | None = Field(default=None, ge=0.0)
    perceptual_hash_distance: float | None = Field(default=None, ge=0.0)
    sample_fingerprint: str | None = None
    diagnostics: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_safe_probe_metrics(self) -> "VisualDiffSummary":
        _validate_fingerprint(self.sample_fingerprint, context="visual diff summary")
        _validate_diagnostics(self.diagnostics, context="visual diff summary")
        return self


class TextDiffSummary(ContractModel):
    """Safe text fingerprint metrics observed during adaptive settle polling."""

    enabled: bool = True
    method: TextDiffMethod = TextDiffMethod.FINGERPRINT
    status: SettleSampleStatus = SettleSampleStatus.OBSERVED
    text_delta: float | None = Field(default=None, ge=0.0)
    text_length: int = Field(default=0, ge=0)
    source_count: int = Field(default=0, ge=0)
    text_fingerprint: str | None = None
    diagnostics: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_safe_probe_metrics(self) -> "TextDiffSummary":
        _validate_fingerprint(self.text_fingerprint, context="text diff summary")
        _validate_diagnostics(self.diagnostics, context="text diff summary")
        return self


class ProviderReadinessSnapshot(ContractModel):
    """Safe provider readiness counters for one settle sample."""

    state: ProviderReadinessState = ProviderReadinessState.UNKNOWN
    completed_provider_count: int = Field(default=0, ge=0)
    pending_provider_count: int = Field(default=0, ge=0)
    failed_provider_count: int = Field(default=0, ge=0)
    unavailable_provider_count: int = Field(default=0, ge=0)
    provider_states: dict[str, ProviderReadinessState] = Field(default_factory=dict)
    diagnostics: tuple[str, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_safe_provider_metrics(self) -> "ProviderReadinessSnapshot":
        if len(self.provider_states) > 16:
            raise ValueError("provider readiness includes too many provider states")
        for key in self.provider_states:
            if _SAFE_PROVIDER_KEY.fullmatch(key) is None:
                raise ValueError("provider readiness provider key must be a safe identifier")
        _validate_diagnostics(self.diagnostics, context="provider readiness")
        return self


class SettlePollingPlan(ContractModel):
    """Durable plan for polling one accepted adaptive-settle candidate."""

    plan_id: str
    candidate_id: str
    session_id: str
    action_id: str | None = None
    trigger_kind: KeyframeTriggerKind
    role: KeyframeRole
    settle_window: AdaptiveSettleWindow
    probe_strategy: VisualProbeMode = VisualProbeMode.HYBRID
    baseline_keyframe_id: str | None = None
    sample_budget: int = Field(default=12, ge=1, le=100)
    timeout_capture_enabled: bool | None = None
    created_at: datetime
    policy_version: str = Field(default="active_capture_policy_v2", min_length=1)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata_keys(self) -> "SettlePollingPlan":
        _validate_timing_metadata(self.metadata)
        return self


class SettleSample(ContractModel):
    """One low-sensitive sample collected while waiting for a result frame."""

    sample_id: str
    plan_id: str
    candidate_id: str
    session_id: str
    sampled_at: datetime
    sampled_at_monotonic_ms: int | None = Field(default=None, ge=0)
    status: SettleSampleStatus
    signal_kind: SettleSignalKind
    visual: VisualDiffSummary | None = None
    text: TextDiffSummary | None = None
    readiness: ProviderReadinessSnapshot | None = None
    diagnostics: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata_keys(self) -> "SettleSample":
        _validate_sample_id(self.sample_id, context="settle sample")
        _validate_diagnostics(self.diagnostics, context="settle sample")
        _validate_timing_metadata(self.metadata)
        return self


class SettleProbeSnapshot(ContractModel):
    """Candidate-neutral native probe snapshot carried by trusted polling requests."""

    sample_id: str | None = None
    sampled_at_monotonic_ms: int | None = Field(default=None, ge=0)
    visual: VisualDiffSummary | None = None
    text: TextDiffSummary | None = None
    readiness: ProviderReadinessSnapshot | None = None
    diagnostics: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata_keys(self) -> "SettleProbeSnapshot":
        _validate_sample_id(self.sample_id, context="settle probe snapshot")
        _validate_diagnostics(self.diagnostics, context="settle probe snapshot")
        _validate_timing_metadata(self.metadata)
        return self


class SettleDecision(ContractModel):
    """Typed decision after evaluating adaptive-settle samples."""

    plan_id: str
    candidate_id: str
    session_id: str
    status: SettleDecisionStatus
    stop_reason: SettleStopReason
    ready_to_capture: bool = False
    capture_after_monotonic_ms: int | None = Field(default=None, ge=0)
    diff: KeyframeDiffReport | None = None
    quality: KeyframeQualityReport | None = None
    stable_sample_count: int = Field(default=0, ge=0)
    sample_count: int = Field(default=0, ge=0)
    needs_review: bool = False
    diagnostics: tuple[str, ...] = Field(default_factory=tuple)


class SettleAuditRecord(ContractModel):
    """Durable audit row for a settle sample/decision without raw material."""

    audit_id: str
    plan_id: str
    candidate_id: str
    session_id: str
    status: SettleDecisionStatus
    stop_reason: SettleStopReason
    sample_count: int = Field(default=0, ge=0)
    decision: SettleDecision
    sample: SettleSample | None = None
    created_at: datetime
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata_keys(self) -> "SettleAuditRecord":
        _validate_timing_metadata(self.metadata)
        return self
