"""Typed contracts for user-triggered active context capture.

The active capture contracts describe sessions, keyframes, video artifact
metadata, and timeline manifests without exposing raw screenshot or video
bytes. They are intentionally strict because these models cross daemon,
storage, CLI, and future native-client boundaries.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import ClassVar

from pydantic import Field, model_validator

from .active_capture_metadata import validate_safe_metadata
from .base import ContractModel
from .common import ActorRef, BoundingBox, JsonScalar
from .enums import (
    ActiveCaptureMode,
    ActiveCaptureStatus,
    ActiveCaptureWarningCode,
    KeyframeBundleStatus,
    KeyframeDropReason,
    KeyframeEvidenceRole,
    KeyframeKeepReason,
    KeyframePriorityBand,
    KeyframeRole,
    KeyframeTriggerCandidateStatus,
    KeyframeTriggerKind,
    NativeCaptureTimingAuthority,
    NativeTimingClock,
    RecordingScopeKind,
    RecordingVideoContentType,
    SettleDecisionStatus,
    SettleStopReason,
    TimelineAlignmentConfidence,
    TimelineAlignmentStatus,
    VideoArtifactFailureReason,
    VideoArtifactState,
)

_ACTIVE_CAPTURE_BINDING_METADATA_KEYS = frozenset(
    {
        "settle_live_polling_state",
        "settle_decision_status",
        "settle_stop_reason",
        "settle_sample_count",
        "settle_stable_sample_count",
        "settle_needs_review",
        "settle_capture_claim_id",
        "settle_capture_claim_expires_monotonic_ms",
    }
)
_ACTIVE_CAPTURE_BINDING_STATE_VALUES = frozenset({"pending", "observing", "ready", "capturing", "closed"})
_ACTIVE_CAPTURE_CLAIM_ID = re.compile(r"^[A-Za-z0-9_-]{1,96}$")


class ActiveCapturePolicyConfig(ContractModel):
    """Runtime policy knobs for active capture backend services."""

    enabled: bool = True
    auto_anchor_screenshots: bool = True
    short_observation_window_ms: int = Field(default=5_000, ge=0)
    max_session_duration_ms: int = Field(default=10 * 60 * 1000, ge=1_000)
    max_keyframes_per_session: int = Field(default=64, ge=1, le=512)
    scope_lost_grace_ms: int = Field(default=3_000, ge=0)
    video_enabled: bool = True
    video_max_bytes: int = Field(default=250 * 1024 * 1024, ge=1)
    timeline_alignment_tolerance_ms: int = Field(default=500, ge=0)
    pause_resume_enabled: bool = True
    action_trace_enabled: bool = True
    record_action_coordinates: bool = True
    max_action_events_per_session: int = Field(default=20_000, ge=1, le=100_000)
    min_keyframe_gap_ms: int = Field(default=500, ge=0)
    click_settle_delay_ms: int = Field(default=300, ge=0)
    scroll_stop_delay_ms: int = Field(default=400, ge=0)
    hotkey_settle_delay_ms: int = Field(default=250, ge=0)
    typing_pause_delay_ms: int = Field(default=500, ge=0)
    typing_milestone_keyframes_enabled: bool = True
    typing_milestone_min_chars: int = Field(default=8, ge=1, le=10_000)
    typing_milestone_min_events: int = Field(default=8, ge=1, le=10_000)
    typing_milestone_coalesce_window_ms: int = Field(default=12_000, ge=0, le=120_000)
    idle_anchor_interval_ms: int = Field(default=30_000, ge=1_000)
    visual_diff_threshold: float = Field(default=0.06, ge=0.0, le=1.0)
    text_diff_threshold: float = Field(default=0.12, ge=0.0, le=1.0)
    before_action_keyframes_enabled: bool = True
    before_action_freshness_ms: int = Field(default=1_500, ge=0)
    adaptive_settle_enabled: bool = True
    adaptive_settle_min_delay_ms: int = Field(default=250, ge=0)
    adaptive_settle_max_wait_ms: int = Field(default=1_500, ge=0)
    adaptive_settle_poll_interval_ms: int = Field(default=150, ge=1)
    adaptive_settle_required_stable_samples: int = Field(default=2, ge=1, le=10)
    settle_live_polling_enabled: bool = True
    settle_probe_strategy: str = Field(default="hybrid", min_length=1)
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
    max_pending_trigger_candidates: int = Field(default=128, ge=1, le=10_000)
    max_producer_events_per_session: int = Field(default=30_000, ge=1, le=200_000)
    click_target_resolver_enabled: bool = True
    click_target_high_confidence_threshold: float = Field(default=0.78, ge=0.0, le=1.0)
    click_target_review_confidence_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    click_target_max_candidates: int = Field(default=8, ge=1, le=32)
    click_target_max_safe_label_chars: int = Field(default=80, ge=8, le=200)
    policy_version: str = Field(default="active_capture_policy_v1", min_length=1)


class RecordingScope(ContractModel):
    """Resolved local capture scope for a recording session."""

    kind: RecordingScopeKind
    display_id: str | None = None
    scale_factor: float | None = Field(default=None, gt=0.0)
    window_id: str | None = None
    process_id: int | None = None
    bundle_id: str | None = None
    app_name: str | None = None
    title: str | None = None
    bounds: BoundingBox | None = None
    selection_region: BoundingBox | None = None
    scope_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    occlusion_estimate: float | None = Field(default=None, ge=0.0, le=1.0)
    resolved_at: datetime | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_actionable_scope(self) -> "RecordingScope":
        """Reject scopes that would silently match unrelated screenshots."""

        if self.kind == RecordingScopeKind.WINDOW:
            has_window_identity = bool(self.window_id or self.process_id or self.bundle_id)
            if not has_window_identity:
                raise ValueError("window recording scope requires window_id, process_id, or bundle_id")
            if self.bounds is None:
                raise ValueError("window recording scope requires bounds")
        if self.kind == RecordingScopeKind.REGION:
            if self.display_id is None:
                raise ValueError("region recording scope requires display_id")
            if self.selection_region is None:
                raise ValueError("region recording scope requires selection_region")
        if self.kind == RecordingScopeKind.CURRENT_APP and not (self.process_id or self.bundle_id):
            raise ValueError("current_app recording scope requires process_id or bundle_id")
        return self


class ActiveCaptureWarning(ContractModel):
    """Structured warning that does not make the session unusable."""

    code: ActiveCaptureWarningCode
    message: str
    created_at: datetime
    details: dict[str, JsonScalar] = Field(default_factory=dict)


class ActiveCaptureSession(ContractModel):
    """Backend-owned active capture session state."""

    session_id: str
    mode: ActiveCaptureMode
    status: ActiveCaptureStatus
    actor: ActorRef | None = None
    workspace_id: str | None = None
    primary_event_id: str | None = None
    scope: RecordingScope | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    warnings: tuple[ActiveCaptureWarning, ...] = Field(default_factory=tuple)
    policy_version: str = Field(default="active_capture_policy_v1", min_length=1)
    user_note: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class ActiveCaptureBinding(ContractModel):
    """Optional capture-attempt binding to an active capture session."""

    AUTO_SESSION_ID: ClassVar[str] = "auto"

    session_id: str = Field(min_length=1)
    role: KeyframeRole
    trigger_kind: KeyframeTriggerKind
    keep_reason: KeyframeKeepReason | None = None
    candidate_id: str | None = Field(default=None, min_length=1)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_binding_metadata(self) -> "ActiveCaptureBinding":
        validate_safe_metadata(self.metadata, context="active capture binding metadata")
        forbidden = sorted(set(self.metadata) - _ACTIVE_CAPTURE_BINDING_METADATA_KEYS)
        if forbidden:
            raise ValueError("active capture binding metadata contains unsupported keys")
        _validate_active_capture_binding_metadata_values(self.metadata)
        return self

    @property
    def is_auto_session(self) -> bool:
        """Whether this binding asks the daemon to create an anchor-only session."""

        return self.session_id == self.AUTO_SESSION_ID


def _validate_active_capture_binding_metadata_values(metadata: dict[str, JsonScalar]) -> None:
    state = metadata.get("settle_live_polling_state")
    if state is not None and state not in _ACTIVE_CAPTURE_BINDING_STATE_VALUES:
        raise ValueError("active capture binding metadata has invalid settle_live_polling_state")
    decision = metadata.get("settle_decision_status")
    if decision is not None and decision not in {item.value for item in SettleDecisionStatus}:
        raise ValueError("active capture binding metadata has invalid settle_decision_status")
    stop_reason = metadata.get("settle_stop_reason")
    if stop_reason is not None and stop_reason not in {item.value for item in SettleStopReason}:
        raise ValueError("active capture binding metadata has invalid settle_stop_reason")
    needs_review = metadata.get("settle_needs_review")
    if needs_review is not None and not isinstance(needs_review, bool):
        raise ValueError("active capture binding metadata settle_needs_review must be boolean")
    claim_id = metadata.get("settle_capture_claim_id")
    if claim_id is not None and (not isinstance(claim_id, str) or _ACTIVE_CAPTURE_CLAIM_ID.fullmatch(claim_id) is None):
        raise ValueError("active capture binding metadata has invalid settle_capture_claim_id")
    for key in (
        "settle_sample_count",
        "settle_stable_sample_count",
        "settle_capture_claim_expires_monotonic_ms",
    ):
        value = metadata.get(key)
        if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
            raise ValueError(f"active capture binding metadata {key} must be a non-negative integer")


class NativeCaptureTimingReceipt(ContractModel):
    """Trusted local timing emitted by an installed native capture producer."""

    authority: NativeCaptureTimingAuthority
    captured_at_monotonic_ms: int = Field(ge=0)
    source_clock: NativeTimingClock = NativeTimingClock.SYSTEM_UPTIME_MS
    recorded_at_wall_time: datetime | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class RecordingTimingAnchor(ContractModel):
    """Trusted recording clock span emitted by a local native video producer."""

    authority: NativeCaptureTimingAuthority
    session_id: str | None = Field(default=None, min_length=1)
    recording_id: str | None = Field(default=None, min_length=1)
    source_clock: NativeTimingClock = NativeTimingClock.SYSTEM_UPTIME_MS
    started_at_monotonic_ms: int = Field(ge=0)
    ended_at_monotonic_ms: int = Field(ge=0)
    started_at_wall_time: datetime | None = None
    ended_at_wall_time: datetime | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_monotonic_span(self) -> "RecordingTimingAnchor":
        if self.ended_at_monotonic_ms < self.started_at_monotonic_ms:
            raise ValueError("recording timing anchor end must be >= start")
        return self


class KeyframeQualityReport(ContractModel):
    """Small quality report for a persisted keyframe."""

    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    text_chars: int = Field(default=0, ge=0)
    screenshot_available: bool = False
    system_appshot_available: bool = False
    diagnostics: tuple[str, ...] = Field(default_factory=tuple)
    metrics: dict[str, JsonScalar] = Field(default_factory=dict)


class KeyframeDiffReport(ContractModel):
    """Policy input describing how different a candidate frame is."""

    previous_keyframe_id: str | None = None
    visual_delta: float | None = Field(default=None, ge=0.0)
    text_delta: float | None = Field(default=None, ge=0.0)
    changed: bool | None = None
    metrics: dict[str, JsonScalar] = Field(default_factory=dict)


class ContextKeyframe(ContractModel):
    """A kept keyframe that links existing event/evidence ledger rows."""

    keyframe_id: str
    session_id: str
    event_id: str
    capture_run_id: str
    role: KeyframeRole
    trigger_kind: KeyframeTriggerKind
    keep_reason: KeyframeKeepReason
    captured_at: datetime
    sequence_index: int = Field(ge=0)
    scope: RecordingScope | None = None
    screenshot_artifact_id: str | None = None
    screenshot_evidence_id: str | None = None
    system_appshot_evidence_id: str | None = None
    quality: KeyframeQualityReport = Field(default_factory=KeyframeQualityReport)
    diff: KeyframeDiffReport | None = None
    captured_at_monotonic_ms: int | None = Field(default=None, ge=0)
    media_time_ms: int | None = Field(default=None, ge=0)
    policy_version: str = Field(default="active_capture_policy_v1", min_length=1)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class KeyframeEvidenceLink(ContractModel):
    """Typed relation between one keyframe and one evidence record."""

    link_id: str
    keyframe_id: str
    event_id: str
    evidence_id: str
    artifact_id: str | None = None
    role: KeyframeEvidenceRole
    provider_key: str | None = None
    created_at: datetime
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class KeyframeInspectSummary(ContractModel):
    """Safe keyframe summary returned by explicit event inspection."""

    keyframe_id: str
    session_id: str
    role: KeyframeRole
    trigger_kind: KeyframeTriggerKind
    captured_at: datetime
    sequence_index: int = Field(ge=0)
    screenshot_artifact_id: str | None = None
    screenshot_evidence_id: str | None = None
    system_appshot_evidence_id: str | None = None
    media_time_ms: int | None = Field(default=None, ge=0)
    evidence_count: int = Field(default=0, ge=0)
    quality: KeyframeQualityReport = Field(default_factory=KeyframeQualityReport)


class KeyframeCaptureDecision(ContractModel):
    """Audit row for kept and dropped keyframe candidates."""

    decision_id: str
    session_id: str
    event_id: str | None = None
    candidate_id: str
    role: KeyframeRole
    trigger_kind: KeyframeTriggerKind
    kept: bool
    keep_reason: KeyframeKeepReason | None = None
    drop_reason: KeyframeDropReason | None = None
    kept_keyframe_id: str | None = None
    policy_version: str = Field(default="active_capture_policy_v1", min_length=1)
    metrics: dict[str, JsonScalar] = Field(default_factory=dict)
    decided_at: datetime


class KeyframeContextBundle(ContractModel):
    """Session-level keyframe bundle summary."""

    bundle_id: str
    session_id: str
    primary_event_id: str | None = None
    status: KeyframeBundleStatus
    anchor_keyframe_id: str | None = None
    keyframe_count: int = Field(default=0, ge=0)
    summary_evidence_id: str | None = None
    created_at: datetime
    updated_at: datetime
    warnings: tuple[ActiveCaptureWarning, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class StagedVideoArtifactRef(ContractModel):
    """Reference to a staged local video artifact awaiting vault promotion."""

    local_path: str = Field(min_length=1)
    content_type: RecordingVideoContentType = RecordingVideoContentType.MP4
    filename: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class VideoArtifactRef(ContractModel):
    """Safe metadata for a recording video artifact."""

    artifact_id: str | None = None
    state: VideoArtifactState
    content_type: RecordingVideoContentType | None = None
    byte_size: int | None = Field(default=None, ge=0)
    sha256: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    failure_reason: VideoArtifactFailureReason | None = None
    failure_message: str | None = Field(default=None, max_length=500)
    created_at: datetime | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class VideoArtifactPublicSummary(ContractModel):
    """Public recording video summary without raw hash or producer metadata."""

    artifact_id: str | None = None
    state: VideoArtifactState
    content_type: RecordingVideoContentType | None = None
    byte_size: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    failure_reason: VideoArtifactFailureReason | None = None
    failure_message: str | None = Field(default=None, max_length=500)
    created_at: datetime | None = None


class TimelineKeyframeEntry(ContractModel):
    """One keyframe aligned onto the session timeline."""

    keyframe_id: str
    role: KeyframeRole
    trigger_kind: KeyframeTriggerKind
    sequence_index: int = Field(ge=0)
    captured_at_wall_time: datetime
    captured_at_monotonic_ms: int | None = Field(default=None, ge=0)
    media_time_ms: int | None = Field(default=None, ge=0)
    video_artifact_id: str | None = None
    nearest_video_segment_id: str | None = None
    alignment_confidence: TimelineAlignmentConfidence
    alignment_status: TimelineAlignmentStatus = TimelineAlignmentStatus.MISSING_CLOCK
    evidence_bundle_id: str | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class RecordingTimelineManifest(ContractModel):
    """Timeline manifest aligning keyframes, wall clock, and video media time."""

    manifest_id: str
    session_id: str
    primary_event_id: str | None = None
    video: VideoArtifactRef = Field(default_factory=lambda: VideoArtifactRef(state=VideoArtifactState.NOT_RECORDED))
    clock_origin_wall_time: datetime
    clock_origin_monotonic_ms: int | None = Field(default=None, ge=0)
    started_at_monotonic_ms: int | None = Field(default=None, ge=0)
    ended_at_monotonic_ms: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    alignment_error_ms: int | None = Field(default=None, ge=0)
    entries: tuple[TimelineKeyframeEntry, ...] = Field(default_factory=tuple)
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class TimelinePublicEntry(ContractModel):
    """Public keyframe timeline entry without internal artifact graph ids."""

    keyframe_id: str
    role: KeyframeRole
    trigger_kind: KeyframeTriggerKind
    sequence_index: int = Field(ge=0)
    captured_at_wall_time: datetime
    captured_at_monotonic_ms: int | None = Field(default=None, ge=0)
    media_time_ms: int | None = Field(default=None, ge=0)
    nearest_video_segment_id: str | None = None
    alignment_confidence: TimelineAlignmentConfidence
    alignment_status: TimelineAlignmentStatus = TimelineAlignmentStatus.MISSING_CLOCK


class RecordingTimelinePublicSummary(ContractModel):
    """Public timeline summary for active capture APIs."""

    manifest_id: str
    session_id: str
    primary_event_id: str | None = None
    video: VideoArtifactPublicSummary = Field(
        default_factory=lambda: VideoArtifactPublicSummary(state=VideoArtifactState.NOT_RECORDED)
    )
    clock_origin_wall_time: datetime
    started_at_monotonic_ms: int | None = Field(default=None, ge=0)
    ended_at_monotonic_ms: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    entries: tuple[TimelinePublicEntry, ...] = Field(default_factory=tuple)


class CreateActiveCaptureSessionCommand(ContractModel):
    """Command accepted by the daemon to create a backend session."""

    mode: ActiveCaptureMode = ActiveCaptureMode.RECORDING_SESSION
    workspace_id: str | None = None
    scope: RecordingScope | None = None
    start_recording: bool = True
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class CompleteActiveCaptureSessionCommand(ContractModel):
    """Command accepted by the daemon to finalize a backend session."""

    warnings: tuple[ActiveCaptureWarning, ...] = Field(default_factory=tuple)
    video: StagedVideoArtifactRef | None = None
    recording_timing: RecordingTimingAnchor | None = None
    user_note: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class CancelActiveCaptureSessionCommand(ContractModel):
    """Command accepted by the daemon to cancel a backend session."""

    reason: str | None = Field(default=None, max_length=240)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class ActiveCaptureControlTriggerCandidateSummary(ContractModel):
    """Public trigger candidate summary returned by recording control calls."""

    candidate_id: str
    status: KeyframeTriggerCandidateStatus
    trigger_kind: KeyframeTriggerKind
    role: KeyframeRole
    priority: KeyframePriorityBand
    debounce_until_monotonic_ms: int | None = Field(default=None, ge=0)
    keyframe_id: str | None = None
    event_id: str | None = None
    drop_reason: KeyframeDropReason | None = None
    diagnostics: tuple[str, ...] = Field(default_factory=tuple)


class ActiveCaptureControlCaptureInstruction(ContractModel):
    """Capture instruction returned by recording control calls."""

    candidate_id: str
    session_id: str
    role: KeyframeRole
    trigger_kind: KeyframeTriggerKind
    binding: ActiveCaptureBinding
    execute_after_monotonic_ms: int | None = Field(default=None, ge=0)


class ActiveCaptureControlTriggerSubmission(ContractModel):
    """Control-response trigger submission without importing trigger contracts."""

    candidate: ActiveCaptureControlTriggerCandidateSummary
    capture_instruction: ActiveCaptureControlCaptureInstruction | None = None


class ActiveCaptureSessionView(ContractModel):
    """Backend API response for one active capture session."""

    session: ActiveCaptureSession
    bundle: KeyframeContextBundle | None = None
    keyframes: tuple[ContextKeyframe, ...] = Field(default_factory=tuple)
    timeline: RecordingTimelineManifest | None = None
    video: VideoArtifactRef | None = None
    control_trigger: ActiveCaptureControlTriggerSubmission | None = None


class ActiveCaptureSessionPublicSummary(ContractModel):
    """Public session summary without scope/window/process metadata."""

    session_id: str
    mode: ActiveCaptureMode
    status: ActiveCaptureStatus
    primary_event_id: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    warnings: tuple[ActiveCaptureWarning, ...] = Field(default_factory=tuple)
    user_note: str | None = Field(default=None, max_length=1000)


class ActiveCapturePublicView(ContractModel):
    """Safe API projection for active capture sessions."""

    session: ActiveCaptureSessionPublicSummary
    bundle: KeyframeContextBundle | None = None
    keyframes: tuple[KeyframeInspectSummary, ...] = Field(default_factory=tuple)
    timeline: RecordingTimelinePublicSummary | None = None
    video: VideoArtifactPublicSummary | None = None
    control_trigger: ActiveCaptureControlTriggerSubmission | None = None
