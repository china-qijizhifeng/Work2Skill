"""Terminal quality policy for active capture sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from packages.contracts import (
    ActiveCaptureMode,
    ActiveCapturePolicyConfig,
    ActiveCaptureSession,
    ActiveCaptureStatus,
    ActiveCaptureWarning,
    ActiveCaptureWarningCode,
    ContextKeyframe,
    KeyframeRole,
    RecordingVideoSegmentRef,
    VideoArtifactRef,
    VideoArtifactState,
)


@dataclass(frozen=True)
class TerminalSessionQualityDecision:
    """Result of evaluating whether a completed graph is usable.

    Attributes:
        status: Final lifecycle state chosen for the session.
        warnings: Non-fatal completion warnings retained on the session.
    """

    status: ActiveCaptureStatus
    warnings: tuple[ActiveCaptureWarning, ...]


class TerminalSessionQualityPolicy:
    """Decide final session state from persisted evidence, video, and policy."""

    def __init__(self, *, config: ActiveCapturePolicyConfig) -> None:
        self.config = config

    def evaluate(
        self,
        *,
        session: ActiveCaptureSession,
        keyframes: tuple[ContextKeyframe, ...],
        video: VideoArtifactRef,
        warnings: tuple[ActiveCaptureWarning, ...],
        completed_at: datetime,
        segments: tuple[RecordingVideoSegmentRef, ...] = (),
    ) -> TerminalSessionQualityDecision:
        """Return a fail-closed final state for the completed session graph."""

        completion_warnings = list(warnings)
        video_available = video.state == VideoArtifactState.AVAILABLE or self._has_available_segment_video(segments)
        if session.started_at is not None:
            duration_ms = int((completed_at - session.started_at).total_seconds() * 1000)
            if duration_ms > self.config.max_session_duration_ms:
                completion_warnings.append(
                    ActiveCaptureWarning(
                        code=ActiveCaptureWarningCode.TIMELINE_ALIGNMENT_ESTIMATED,
                        message="Active capture exceeded the configured maximum session duration",
                        created_at=completed_at,
                        details={
                            "duration_ms": duration_ms,
                            "max_session_duration_ms": self.config.max_session_duration_ms,
                        },
                    )
                )
        if not keyframes and not video_available:
            completion_warnings.append(
                ActiveCaptureWarning(
                    code=ActiveCaptureWarningCode.KEYFRAME_CAPTURE_FAILED,
                    message="Active capture completed without usable keyframes or recording video",
                    created_at=completed_at,
                )
            )
            return TerminalSessionQualityDecision(
                status=ActiveCaptureStatus.FAILED,
                warnings=tuple(completion_warnings),
            )
        if session.mode == ActiveCaptureMode.RECORDING_SESSION:
            missing_boundary_roles = self._missing_boundary_roles(keyframes)
            if missing_boundary_roles:
                completion_warnings.append(
                    ActiveCaptureWarning(
                        code=ActiveCaptureWarningCode.KEYFRAME_CAPTURE_FAILED,
                        message="Active capture completed without all recording boundary keyframes",
                        created_at=completed_at,
                        details={"missing_roles": ",".join(role.value for role in missing_boundary_roles)},
                    )
                )
        final_status = (
            ActiveCaptureStatus.COMPLETED_WITH_WARNINGS if completion_warnings else ActiveCaptureStatus.COMPLETED
        )
        return TerminalSessionQualityDecision(status=final_status, warnings=tuple(completion_warnings))

    def _missing_boundary_roles(self, keyframes: tuple[ContextKeyframe, ...]) -> tuple[KeyframeRole, ...]:
        roles = {keyframe.role for keyframe in keyframes}
        missing: list[KeyframeRole] = []
        for role in (KeyframeRole.START, KeyframeRole.FINAL):
            if role not in roles:
                missing.append(role)
        return tuple(missing)

    def _has_available_segment_video(self, segments: tuple[RecordingVideoSegmentRef, ...]) -> bool:
        return any(
            segment.video is not None and segment.video.state == VideoArtifactState.AVAILABLE for segment in segments
        )
