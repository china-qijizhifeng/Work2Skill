"""Agent-safe inspect contracts for active capture recordings."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from .active_capture_click_targets import ClickTargetPublicView
from .active_capture_input_events import KeyChord, TypingSessionAggregateView
from .active_capture_projection import ProjectionTruncationSummary
from .base import ContractModel
from .common import BoundingBox, JsonScalar, TextRange
from .enums import (
    ActiveCaptureCitationKind,
    ActiveCaptureMode,
    ActiveCaptureStatus,
    AgentVisibleField,
    ArtifactType,
    CoordinateSpace,
    DisclosureClass,
    HotkeySemantic,
    HumanActionKind,
    KeyframeRole,
    KeyframeTriggerKind,
    ProducerDecisionReason,
    ProducerDecisionStatus,
    RecordingAvailableField,
    RecordingControlKind,
    RecordingExportFallbackMode,
    RecordingHiddenMaterial,
    RecordingStoryboardItemKind,
    RecordingTimelineStepFoldReason,
    RecordingTimelineStepVisibilityClass,
    RedactionState,
    SkillReadinessState,
    VideoArtifactState,
)


class SkillReadinessSummary(ContractModel):
    """Session or step readiness for later skill distillation."""

    state: SkillReadinessState
    reasons: tuple[str, ...] = Field(default_factory=tuple)
    review_item_count: int = Field(default=0, ge=0)
    blocked_item_count: int = Field(default=0, ge=0)
    missing_evidence: tuple[str, ...] = Field(default_factory=tuple)


class ActiveCaptureCitationTarget(ContractModel):
    """Typed citation target embedded in the agent-run citation ledger."""

    kind: ActiveCaptureCitationKind
    session_id: str
    event_id: str
    keyframe_id: str | None = None
    action_id: str | None = None
    timeline_step_id: str | None = None
    evidence_id: str | None = None
    artifact_id: str | None = None
    text_range: TextRange | None = None
    bbox: BoundingBox | None = None
    coordinate_space: CoordinateSpace = CoordinateSpace.SCREEN_PX
    media_time_ms: int | None = Field(default=None, ge=0)
    field_path: str = Field(default="active_capture", min_length=1, max_length=240)


class ActiveCaptureCitationRef(ContractModel):
    """Citation ref returned in active-capture inspect views before/after attachment."""

    target: ActiveCaptureCitationTarget
    citation_id: str | None = None
    label: str | None = Field(default=None, max_length=240)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class RecordingSafeTextBlock(ContractModel):
    """Bounded redacted text block attached to a keyframe or action citation."""

    block_id: str
    source_field: AgentVisibleField
    event_id: str
    keyframe_id: str | None = None
    evidence_id: str | None = None
    artifact_id: str | None = None
    artifact_type: ArtifactType | None = None
    disclosure_class: DisclosureClass
    text: str = Field(max_length=64_000)
    text_truncated: bool = False
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    redaction_state: RedactionState = RedactionState.REDACTED
    citations: tuple[ActiveCaptureCitationRef, ...] = Field(default_factory=tuple)


class RecordingVideoInspectRef(ContractModel):
    """Safe video reference for inspect; never includes raw paths or hashes."""

    artifact_id: str | None = None
    state: VideoArtifactState
    content_type: str | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    byte_size: int | None = Field(default=None, ge=0)
    alignment_error_ms: int | None = Field(default=None, ge=0)


class RecordingVideoPlaybackRequest(ContractModel):
    """Explicit local playback request for a user-opened recording video."""

    event_id: str = Field(min_length=1)
    artifact_id: str = Field(min_length=1)
    purpose: str = Field(default="workbench_user_play_recording", min_length=1, max_length=160)


class RecordingVideoPlaybackResponse(ContractModel):
    """Explicit local playback payload for a user-opened recording video."""

    session_id: str
    event_id: str
    artifact_id: str
    content_type: str
    byte_size: int = Field(ge=0)
    playback_file_path: str | None = Field(default=None, min_length=1)
    content_base64: str | None = None

    @model_validator(mode="after")
    def require_local_or_legacy_payload(self) -> RecordingVideoPlaybackResponse:
        if not self.playback_file_path and not self.content_base64:
            raise ValueError("recording playback response requires a local file path or legacy content payload")
        return self


class RecordingExportRequest(ContractModel):
    """Explicit local request to materialize a recording into a directory tree."""

    output_root: str = Field(min_length=1, max_length=4096)
    purpose: str = Field(default="workbench_user_export_recording", min_length=1, max_length=160)
    fallback_mode: RecordingExportFallbackMode = RecordingExportFallbackMode.NORMAL


class RecordingExportResponse(ContractModel):
    """Result of materializing a recording into a per-recording directory tree."""

    session_id: str
    output_dir: str = Field(min_length=1)
    keyframe_dir_count: int = Field(ge=0)
    evidence_file_count: int = Field(ge=0)
    action_count: int = Field(ge=0)
    video_file_count: int = Field(ge=0)
    vm_a11y_record_count: int = Field(default=0, ge=0)
    vm_event_log_count: int = Field(default=0, ge=0)
    vm_click_log_count: int = Field(default=0, ge=0)
    fallback_warning: str | None = None


class RecordingActionSummaryView(ContractModel):
    """Safe action details useful for later skill distillation."""

    action_id: str
    action_kind: HumanActionKind
    hotkey_semantic: HotkeySemantic | None = None
    key_chord: KeyChord | None = None
    typing_summary: TypingSessionAggregateView | None = None
    target: ClickTargetPublicView | None = None
    producer_decision_status: ProducerDecisionStatus | None = None
    producer_decision_reason: ProducerDecisionReason | None = None
    before_keyframe_ids: tuple[str, ...] = Field(default_factory=tuple)
    after_keyframe_ids: tuple[str, ...] = Field(default_factory=tuple)
    target_evidence_keyframe_ids: tuple[str, ...] = Field(default_factory=tuple)
    result_keyframe_id: str | None = None


class RecordingTimelineStepView(ContractModel):
    """One ordered active-capture timeline step for agents."""

    step_id: str
    kind: RecordingStoryboardItemKind
    occurred_at: datetime
    media_time_ms: int | None = Field(default=None, ge=0)
    sequence_index: int | None = Field(default=None, ge=0)
    keyframe_id: str | None = None
    keyframe_event_id: str | None = None
    visibility_class: RecordingTimelineStepVisibilityClass = RecordingTimelineStepVisibilityClass.VISIBLE
    fold_reason: RecordingTimelineStepFoldReason | None = None
    safe_text_ref_ids: tuple[str, ...] = Field(default_factory=tuple)
    action_id: str | None = None
    control_id: str | None = None
    keyframe_role: KeyframeRole | None = None
    trigger_kind: KeyframeTriggerKind | None = None
    action_kind: HumanActionKind | None = None
    action_summary: RecordingActionSummaryView | None = None
    control_kind: RecordingControlKind | None = None
    safe_caption: str = Field(min_length=1, max_length=500)
    needs_review: bool = False
    readiness: SkillReadinessSummary
    citations: tuple[ActiveCaptureCitationRef, ...] = Field(default_factory=tuple)


class RecordingTimelineInspectView(ContractModel):
    """Agent-facing ordered recording timeline."""

    session_id: str
    duration_ms: int | None = Field(default=None, ge=0)
    alignment_error_ms: int | None = Field(default=None, ge=0)
    steps: tuple[RecordingTimelineStepView, ...] = Field(default_factory=tuple)


class ActiveCaptureInspectView(ContractModel):
    """Agent-safe active capture section embedded in event inspection."""

    session_id: str
    mode: ActiveCaptureMode
    primary_event_id: str | None = None
    status: ActiveCaptureStatus
    started_at: datetime | None = None
    ended_at: datetime | None = None
    user_note: str | None = Field(default=None, max_length=1000)
    available_fields: tuple[RecordingAvailableField, ...] = Field(default_factory=tuple)
    hidden_materials: tuple[RecordingHiddenMaterial, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    timeline: RecordingTimelineInspectView | None = None
    safe_text_blocks: tuple[RecordingSafeTextBlock, ...] = Field(default_factory=tuple)
    video_ref: RecordingVideoInspectRef | None = None
    citations: tuple[ActiveCaptureCitationRef, ...] = Field(default_factory=tuple)
    skill_readiness: SkillReadinessSummary
    projection: ProjectionTruncationSummary = Field(default_factory=ProjectionTruncationSummary)
    generated_at: datetime
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)
