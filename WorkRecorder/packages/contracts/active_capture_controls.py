"""Typed contracts for active-capture recording controls and segments."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from .active_capture import StagedVideoArtifactRef, VideoArtifactPublicSummary, VideoArtifactRef
from .active_capture_metadata import validate_safe_metadata
from .base import ContractModel
from .common import JsonScalar
from .enums import (
    RecordingControlKind,
    RecordingControlSource,
    RecordingSegmentCloseReason,
    RecordingSegmentState,
)


class RecordingControlEvent(ContractModel):
    """Audited control command applied to an active capture recording."""

    control_id: str
    session_id: str
    kind: RecordingControlKind
    source: RecordingControlSource
    occurred_at: datetime
    occurred_at_monotonic_ms: int | None = Field(default=None, ge=0)
    segment_id: str | None = None
    note: str | None = Field(default=None, max_length=500)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata_keys(self) -> "RecordingControlEvent":
        validate_safe_metadata(self.metadata, context="recording control metadata")
        return self


class RecordingPauseInterval(ContractModel):
    """Closed pause interval used when stitching segmented timelines."""

    pause_id: str
    session_id: str
    started_at: datetime
    started_at_monotonic_ms: int | None = Field(default=None, ge=0)
    ended_at: datetime | None = None
    ended_at_monotonic_ms: int | None = Field(default=None, ge=0)
    reason: RecordingControlKind = RecordingControlKind.PAUSE
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_pause_span(self) -> "RecordingPauseInterval":
        if self.ended_at_monotonic_ms is not None and self.started_at_monotonic_ms is not None:
            if self.ended_at_monotonic_ms < self.started_at_monotonic_ms:
                raise ValueError("pause interval end must be >= start")
        validate_safe_metadata(self.metadata, context="recording pause metadata")
        return self


class RecordingPausePublicSummary(ContractModel):
    """Public pause interval without producer metadata."""

    pause_id: str
    session_id: str
    started_at: datetime
    started_at_monotonic_ms: int | None = Field(default=None, ge=0)
    ended_at: datetime | None = None
    ended_at_monotonic_ms: int | None = Field(default=None, ge=0)
    reason: RecordingControlKind = RecordingControlKind.PAUSE


class RecordingVideoSegmentRef(ContractModel):
    """One contiguous recording segment, optionally backed by a video artifact."""

    segment_id: str
    session_id: str
    sequence_index: int = Field(ge=0)
    state: RecordingSegmentState
    started_at: datetime
    ended_at: datetime | None = None
    started_at_monotonic_ms: int | None = Field(default=None, ge=0)
    media_start_monotonic_ms: int | None = Field(default=None, ge=0)
    media_start_wall_time_epoch_ms: int | None = Field(default=None, ge=0)
    ended_at_monotonic_ms: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    close_reason: RecordingSegmentCloseReason | None = None
    staged_video: StagedVideoArtifactRef | None = None
    video: VideoArtifactRef | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_segment_span(self) -> "RecordingVideoSegmentRef":
        if self.ended_at_monotonic_ms is not None and self.started_at_monotonic_ms is not None:
            if self.ended_at_monotonic_ms < self.started_at_monotonic_ms:
                raise ValueError("recording segment end must be >= start")
        if self.media_start_monotonic_ms is not None:
            if self.started_at_monotonic_ms is not None and self.media_start_monotonic_ms < self.started_at_monotonic_ms:
                raise ValueError("recording segment media start must be >= start")
            if self.ended_at_monotonic_ms is not None and self.media_start_monotonic_ms > self.ended_at_monotonic_ms:
                raise ValueError("recording segment media start must be <= end")
        return self


class RecordingSegmentManifest(ContractModel):
    """Session-level manifest for pause/resume segmented recordings."""

    manifest_id: str
    session_id: str
    segments: tuple[RecordingVideoSegmentRef, ...] = Field(default_factory=tuple)
    pause_intervals: tuple[RecordingPauseInterval, ...] = Field(default_factory=tuple)
    control_events: tuple[RecordingControlEvent, ...] = Field(default_factory=tuple)
    total_recorded_duration_ms: int = Field(default=0, ge=0)
    total_paused_duration_ms: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class RecordingControlPublicSummary(ContractModel):
    """Public control event without note or producer metadata."""

    control_id: str
    session_id: str
    kind: RecordingControlKind
    source: RecordingControlSource
    occurred_at: datetime
    occurred_at_monotonic_ms: int | None = Field(default=None, ge=0)
    segment_id: str | None = None


class RecordingVideoSegmentPublicSummary(ContractModel):
    """Public segment metadata without staged paths, hashes, or producer metadata."""

    segment_id: str
    session_id: str
    sequence_index: int = Field(ge=0)
    state: RecordingSegmentState
    started_at: datetime
    ended_at: datetime | None = None
    started_at_monotonic_ms: int | None = Field(default=None, ge=0)
    media_start_monotonic_ms: int | None = Field(default=None, ge=0)
    ended_at_monotonic_ms: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    close_reason: RecordingSegmentCloseReason | None = None
    video: VideoArtifactPublicSummary | None = None


class RecordingSegmentManifestPublicView(ContractModel):
    """Public pause/resume manifest for backend consumers."""

    manifest_id: str
    session_id: str
    segments: tuple[RecordingVideoSegmentPublicSummary, ...] = Field(default_factory=tuple)
    pause_intervals: tuple[RecordingPausePublicSummary, ...] = Field(default_factory=tuple)
    control_events: tuple[RecordingControlPublicSummary, ...] = Field(default_factory=tuple)
    total_recorded_duration_ms: int = Field(default=0, ge=0)
    total_paused_duration_ms: int = Field(default=0, ge=0)
    created_at: datetime
    updated_at: datetime


class ApplyRecordingControlCommand(ContractModel):
    """Command accepted by the daemon for pause/resume/mark/stop controls."""

    kind: RecordingControlKind
    source: RecordingControlSource = RecordingControlSource.API
    occurred_at_monotonic_ms: int | None = Field(default=None, ge=0)
    note: str | None = Field(default=None, max_length=500)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata_keys(self) -> "ApplyRecordingControlCommand":
        validate_safe_metadata(self.metadata, context="recording control command metadata")
        return self


class AttachRecordingSegmentCommand(ContractModel):
    """Command accepted by trusted local producers to attach a segment artifact."""

    segment_id: str
    state: RecordingSegmentState
    started_at_monotonic_ms: int | None = Field(default=None, ge=0)
    media_start_monotonic_ms: int | None = Field(default=None, ge=0)
    media_start_wall_time_epoch_ms: int | None = Field(default=None, ge=0)
    ended_at_monotonic_ms: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    close_reason: RecordingSegmentCloseReason | None = None
    staged_video: StagedVideoArtifactRef | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)
