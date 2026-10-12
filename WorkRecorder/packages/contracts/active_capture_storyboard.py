"""Safe storyboard and card projections for active capture recordings."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .active_capture_click_targets import ClickTargetPublicView
from .active_capture_projection import ProjectionTruncationSummary
from .base import ContractModel
from .common import JsonScalar
from .enums import (
    ActiveCaptureStatus,
    HumanActionKind,
    KeyframeRole,
    KeyframeTriggerKind,
    RecordingAvailableField,
    RecordingControlKind,
    RecordingHiddenMaterial,
    RecordingStoryboardItemKind,
    VideoArtifactState,
)


class RecordingCardSummary(ContractModel):
    """Safe card summary for a recording session; no raw media paths."""

    session_id: str
    primary_event_id: str | None = None
    status: ActiveCaptureStatus
    app_name: str | None = None
    title: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    keyframe_count: int = Field(default=0, ge=0)
    action_count: int = Field(default=0, ge=0)
    video_state: VideoArtifactState = VideoArtifactState.NOT_RECORDED
    available_fields: tuple[RecordingAvailableField, ...] = Field(default_factory=tuple)
    hidden_materials: tuple[RecordingHiddenMaterial, ...] = Field(default_factory=tuple)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class StoryboardKeyframeItem(ContractModel):
    """Safe timeline item for one keyframe."""

    item_id: str
    kind: RecordingStoryboardItemKind = RecordingStoryboardItemKind.KEYFRAME
    keyframe_id: str
    role: KeyframeRole
    trigger_kind: KeyframeTriggerKind
    sequence_index: int = Field(ge=0)
    captured_at: datetime
    media_time_ms: int | None = Field(default=None, ge=0)
    caption: str | None = Field(default=None, max_length=500)
    screenshot_artifact_id: str | None = None
    evidence_count: int = Field(default=0, ge=0)


class StoryboardActionItem(ContractModel):
    """Safe timeline item for one human action."""

    item_id: str
    kind: RecordingStoryboardItemKind = RecordingStoryboardItemKind.ACTION
    action_id: str
    action_kind: HumanActionKind
    sequence_index: int = Field(ge=0)
    occurred_at: datetime
    media_time_ms: int | None = Field(default=None, ge=0)
    caption: str | None = Field(default=None, max_length=500)
    evidence_keyframe_ids: tuple[str, ...] = Field(default_factory=tuple)
    target: ClickTargetPublicView | None = None
    # Legacy compatibility field. New callers should consume ``target``.
    target_label: str | None = Field(default=None, max_length=500)


class StoryboardControlItem(ContractModel):
    """Safe timeline item for one recording control."""

    item_id: str
    kind: RecordingStoryboardItemKind = RecordingStoryboardItemKind.CONTROL
    control_id: str
    control_kind: RecordingControlKind
    occurred_at: datetime
    media_time_ms: int | None = Field(default=None, ge=0)
    caption: str | None = Field(default=None, max_length=500)


RecordingStoryboardItem = StoryboardKeyframeItem | StoryboardActionItem | StoryboardControlItem


class RecordingStoryboardProjection(ContractModel):
    """Explicit backend projection for future UI/agent storyboard views."""

    session_id: str
    card: RecordingCardSummary
    items: tuple[RecordingStoryboardItem, ...] = Field(default_factory=tuple)
    projection: ProjectionTruncationSummary = Field(default_factory=ProjectionTruncationSummary)
    generated_at: datetime
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)
