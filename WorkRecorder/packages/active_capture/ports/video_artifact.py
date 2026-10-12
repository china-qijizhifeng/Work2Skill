"""Ports for optional recording video artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from packages.contracts import ActiveCaptureSession, Artifact, RecordingVideoSegmentRef, VideoArtifactRef
from packages.contracts.active_capture import StagedVideoArtifactRef


@dataclass(frozen=True)
class PreparedVideoArtifact:
    """Prepared recording video metadata not yet committed to the public ledger.

    Attributes:
        ref: Active-capture video reference to persist with the session graph.
        artifact: Optional artifact row prepared for atomic ledger insertion.
    """

    ref: VideoArtifactRef
    artifact: Artifact | None = None


class VideoArtifactPort(Protocol):
    """Promote or reject a staged video artifact for an active capture session."""

    def prepare_staged_video(
        self,
        *,
        session: ActiveCaptureSession,
        staged: StagedVideoArtifactRef,
    ) -> PreparedVideoArtifact: ...

    def prepare_staged_segment_video(
        self,
        *,
        session: ActiveCaptureSession,
        segment: RecordingVideoSegmentRef,
        staged: StagedVideoArtifactRef,
    ) -> PreparedVideoArtifact: ...

    def discard_prepared_video(self, prepared: PreparedVideoArtifact) -> None: ...

    def discard_staged_video(self, staged: StagedVideoArtifactRef) -> None: ...
