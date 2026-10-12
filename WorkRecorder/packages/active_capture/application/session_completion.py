"""Session completion orchestration for active capture recordings."""

from __future__ import annotations

import logging
from datetime import datetime

from packages.active_capture.application.demonstration_trace import HumanDemonstrationService
from packages.active_capture.application.keyframe_recorder import KeyframeRecorder
from packages.active_capture.application.keyframe_views import bundle_for_session
from packages.active_capture.application.recording_controls import RecordingControlService
from packages.active_capture.application.service_helpers import is_terminal_status
from packages.active_capture.domain.session_completion_policy import TerminalSessionQualityPolicy
from packages.active_capture.domain.session_state import ActiveCaptureSessionStateMachine
from packages.active_capture.domain.timeline_alignment import RecordingTimelineManifestBuilder
from packages.active_capture.ports.video_artifact import PreparedVideoArtifact, VideoArtifactPort
from packages.active_capture.repositories.protocol import ActiveCaptureRepository
from packages.artifacts.vault import ArtifactVaultError, ArtifactVaultTransientError
from packages.contracts import (
    ActiveCaptureSession,
    ActiveCaptureStatus,
    ActiveCaptureWarning,
    ActiveCaptureWarningCode,
    CompleteActiveCaptureSessionCommand,
    RecordingTimelineManifest,
    RecordingVideoSegmentRef,
    StagedVideoArtifactRef,
    VideoArtifactFailureReason,
    VideoArtifactRef,
    VideoArtifactState,
)
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

logger = logging.getLogger(__name__)


class SessionCompletionService:
    """Finalize active-capture sessions, videos, bundles, and timelines."""

    def __init__(
        self,
        *,
        repository: ActiveCaptureRepository,
        clock: Clock,
        ids: IdFactory,
        state_machine: ActiveCaptureSessionStateMachine,
        recording_controls: RecordingControlService,
        timeline_builder: RecordingTimelineManifestBuilder,
        completion_policy: TerminalSessionQualityPolicy,
        keyframe_recorder: KeyframeRecorder,
        demonstrations: HumanDemonstrationService,
        video_artifacts: VideoArtifactPort | None,
        timeline_alignment_tolerance_ms: int,
    ) -> None:
        self.repository = repository
        self.clock = clock
        self.ids = ids
        self.state_machine = state_machine
        self.recording_controls = recording_controls
        self.timeline_builder = timeline_builder
        self.completion_policy = completion_policy
        self.keyframe_recorder = keyframe_recorder
        self.demonstrations = demonstrations
        self.video_artifacts = video_artifacts
        self.timeline_alignment_tolerance_ms = timeline_alignment_tolerance_ms

    def complete_session(
        self,
        *,
        session: ActiveCaptureSession,
        command: CompleteActiveCaptureSessionCommand,
    ) -> ActiveCaptureSession:
        """Finalize a session and persist its completion graph atomically.

        Args:
            session: Active-capture session to finalize.
            command: Completion command carrying optional staged video refs.

        Returns:
            The final session state persisted in the active-capture ledger.
        """

        now = self.clock.now()
        if is_terminal_status(session.status):
            self._ensure_terminal_graph(session=session, command=command)
            logger.info(
                "active capture complete replay ignored for terminal session",
                extra={"session_id": session.session_id, "status": session.status.value},
            )
            return session
        completion_warnings = list(command.warnings)
        segments: tuple[RecordingVideoSegmentRef, ...] = ()
        try:
            if session.status != ActiveCaptureStatus.FINALIZING:
                session = self.state_machine.transition(session, ActiveCaptureStatus.FINALIZING).model_copy(
                    update={"updated_at": now}
                )
            self._validate_recording_timing_anchor(session=session, command=command)
            self.recording_controls.finalize_live_graph(
                session,
                ended_at_monotonic_ms=(
                    command.recording_timing.ended_at_monotonic_ms if command.recording_timing is not None else None
                ),
            )
            segments = self.repository.list_recording_segments_for_session(session.session_id)
            prepared_video = self._prepare_video_if_present(session=session, command=command)
            video = self._completion_video_ref(prepared_video.ref, segments)
            video_warning = self._warning_for_video_result(command=command, video=video, now=now)
            if video_warning is not None:
                completion_warnings.append(video_warning)
            timeline = self._build_timeline(session=session, video=video, command=command)
        except ArtifactVaultTransientError:
            logger.warning(
                "active capture video promotion failed transiently", extra={"session_id": session.session_id}
            )
            raise
        except ArtifactVaultError as exc:
            logger.warning(
                "active capture session completed with warning",
                extra={"session_id": session.session_id, "warning": str(exc)},
            )
            completion_warnings.append(
                ActiveCaptureWarning(
                    code=ActiveCaptureWarningCode.VIDEO_VALIDATION_FAILED,
                    message=str(exc),
                    created_at=now,
                )
            )
            video = VideoArtifactRef(
                state=VideoArtifactState.FAILED,
                failure_reason=VideoArtifactFailureReason.VALIDATION_FAILED,
                failure_message=str(exc),
            )
            prepared_video = PreparedVideoArtifact(ref=video)
            timeline = self._build_timeline(session=session, video=video, command=command)
        keyframes = self.repository.list_keyframes_for_session(session.session_id)
        quality = self.completion_policy.evaluate(
            session=session,
            keyframes=keyframes,
            video=video,
            warnings=tuple(completion_warnings),
            completed_at=now,
            segments=segments,
        )
        metadata = self._completion_metadata(session=session, command=command)
        user_note = self._completion_user_note(session=session, command=command)
        session = self.state_machine.transition(session, quality.status).model_copy(
            update={
                "ended_at": now,
                "updated_at": now,
                "warnings": (*session.warnings, *quality.warnings),
                "user_note": user_note,
                "metadata": metadata,
            }
        )
        timeline = timeline.model_copy(update={"primary_event_id": session.primary_event_id})
        bundle = bundle_for_session(
            repository=self.repository,
            clock=self.clock,
            ids=self.ids,
            session=session,
            keyframes=keyframes,
        )
        try:
            self.repository.complete_session_graph(
                session=session,
                timeline=timeline,
                bundle=bundle,
                artifacts=(prepared_video.artifact,) if prepared_video.artifact is not None else (),
            )
        except Exception:
            logger.exception(
                "active capture completion graph write failed; discarding prepared recording video",
                extra={"session_id": session.session_id},
            )
            self._discard_prepared_video(prepared_video)
            raise
        self.demonstrations.finalize_trace(session)
        if command.video is not None and prepared_video.artifact is not None and self.video_artifacts is not None:
            self._discard_committed_staged_video(command.video)
        logger.info(
            "active capture session completed",
            extra={"session_id": session.session_id, "status": session.status.value},
        )
        return session

    def _ensure_terminal_graph(
        self,
        *,
        session: ActiveCaptureSession,
        command: CompleteActiveCaptureSessionCommand,
    ) -> None:
        if (
            self.repository.get_timeline_manifest(session.session_id) is not None
            and self.repository.get_bundle_for_session(session.session_id) is not None
        ):
            return
        timeline = self._build_timeline(
            session=session,
            video=VideoArtifactRef(state=VideoArtifactState.NOT_RECORDED),
            command=command,
        )
        bundle = bundle_for_session(
            repository=self.repository,
            clock=self.clock,
            ids=self.ids,
            session=session,
            keyframes=self.repository.list_keyframes_for_session(session.session_id),
        )
        self.repository.complete_session_graph(session=session, timeline=timeline, bundle=bundle)

    def _prepare_video_if_present(
        self,
        *,
        session: ActiveCaptureSession,
        command: CompleteActiveCaptureSessionCommand,
    ) -> PreparedVideoArtifact:
        if command.video is None:
            return PreparedVideoArtifact(ref=VideoArtifactRef(state=VideoArtifactState.NOT_RECORDED))
        if self.video_artifacts is None:
            return PreparedVideoArtifact(
                ref=VideoArtifactRef(
                    state=VideoArtifactState.FAILED,
                    failure_reason=VideoArtifactFailureReason.ADAPTER_MISSING,
                )
            )
        return self.video_artifacts.prepare_staged_video(session=session, staged=command.video)

    def _completion_video_ref(
        self,
        prepared_video: VideoArtifactRef,
        segments: tuple[RecordingVideoSegmentRef, ...],
    ) -> VideoArtifactRef:
        if prepared_video.state != VideoArtifactState.NOT_RECORDED:
            return prepared_video
        available_segment_videos = tuple(
            segment.video
            for segment in segments
            if segment.video is not None
            and segment.video.state == VideoArtifactState.AVAILABLE
            and segment.video.artifact_id is not None
        )
        if available_segment_videos:
            return max(available_segment_videos, key=lambda video: video.duration_ms or 0)
        return prepared_video

    def _completion_metadata(
        self,
        *,
        session: ActiveCaptureSession,
        command: CompleteActiveCaptureSessionCommand,
    ) -> dict[str, str | int | float | bool | None]:
        metadata = dict(session.metadata)
        metadata.update(command.metadata)
        note = (command.user_note or "").strip()
        if note:
            metadata["user_note"] = note
        return metadata

    def _completion_user_note(
        self,
        *,
        session: ActiveCaptureSession,
        command: CompleteActiveCaptureSessionCommand,
    ) -> str | None:
        note = (command.user_note or "").strip()
        if note:
            return note
        return session.user_note

    def _validate_recording_timing_anchor(
        self,
        *,
        session: ActiveCaptureSession,
        command: CompleteActiveCaptureSessionCommand,
    ) -> None:
        if command.recording_timing is None or command.recording_timing.session_id is None:
            return
        if command.recording_timing.session_id != session.session_id:
            raise ValueError("recording timing anchor session does not match active capture session")

    def _discard_committed_staged_video(self, staged: StagedVideoArtifactRef) -> None:
        if self.video_artifacts is None:
            return
        try:
            self.video_artifacts.discard_staged_video(staged)
        except ArtifactVaultError:
            logger.warning("active capture staged video cleanup failed", exc_info=True)

    def _discard_prepared_video(self, prepared: PreparedVideoArtifact) -> None:
        if self.video_artifacts is None:
            return
        self.video_artifacts.discard_prepared_video(prepared)

    def _warning_for_video_result(
        self,
        *,
        command: CompleteActiveCaptureSessionCommand,
        video: VideoArtifactRef,
        now: datetime,
    ) -> ActiveCaptureWarning | None:
        if command.video is None or video.state == VideoArtifactState.AVAILABLE:
            return None
        reason = video.failure_message or (
            video.failure_reason.value if video.failure_reason is not None else video.state.value
        )
        return ActiveCaptureWarning(
            code=ActiveCaptureWarningCode.VIDEO_UNAVAILABLE,
            message=f"Recording video unavailable: {reason}",
            created_at=now,
        )

    def _build_timeline(
        self,
        *,
        session: ActiveCaptureSession,
        video: VideoArtifactRef,
        command: CompleteActiveCaptureSessionCommand,
    ) -> RecordingTimelineManifest:
        return self.timeline_builder.build(
            session_id=session.session_id,
            primary_event_id=session.primary_event_id,
            keyframes=self.repository.list_keyframes_for_session(session.session_id),
            video=video,
            started_at_monotonic_ms=(
                command.recording_timing.started_at_monotonic_ms if command.recording_timing is not None else None
            ),
            ended_at_monotonic_ms=(
                command.recording_timing.ended_at_monotonic_ms if command.recording_timing is not None else None
            ),
            segments=self.repository.list_recording_segments_for_session(session.session_id),
            timeline_alignment_tolerance_ms=self.timeline_alignment_tolerance_ms,
        )
