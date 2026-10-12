"""Null video artifact adapter used when video capture is disabled."""

from __future__ import annotations

from packages.active_capture.ports.video_artifact import PreparedVideoArtifact
from packages.contracts import (
    ActiveCaptureSession,
    RecordingVideoSegmentRef,
    VideoArtifactFailureReason,
    VideoArtifactRef,
    VideoArtifactState,
)
from packages.contracts.active_capture import StagedVideoArtifactRef


class NullVideoArtifactAdapter:
    """Return a locked unavailable video ref without touching raw media."""

    def prepare_staged_video(
        self,
        *,
        session: ActiveCaptureSession,
        staged: StagedVideoArtifactRef,
    ) -> PreparedVideoArtifact:
        del session, staged
        return PreparedVideoArtifact(
            ref=VideoArtifactRef(
                state=VideoArtifactState.FAILED,
                failure_reason=VideoArtifactFailureReason.PROMOTION_DISABLED,
            )
        )

    def prepare_staged_segment_video(
        self,
        *,
        session: ActiveCaptureSession,
        segment: RecordingVideoSegmentRef,
        staged: StagedVideoArtifactRef,
    ) -> PreparedVideoArtifact:
        del session, segment, staged
        return PreparedVideoArtifact(
            ref=VideoArtifactRef(
                state=VideoArtifactState.FAILED,
                failure_reason=VideoArtifactFailureReason.PROMOTION_DISABLED,
            )
        )

    def discard_prepared_video(self, prepared: PreparedVideoArtifact) -> None:
        del prepared

    def discard_staged_video(self, staged: StagedVideoArtifactRef) -> None:
        del staged
