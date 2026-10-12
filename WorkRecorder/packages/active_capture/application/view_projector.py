"""Safe API projections for active capture session graphs."""

from __future__ import annotations

from packages.active_capture.repositories.protocol import ActiveCaptureRepository
from packages.contracts import (
    ActiveCapturePublicView,
    ActiveCaptureSessionPublicSummary,
    ActiveCaptureSessionView,
    KeyframeInspectSummary,
    RecordingTimelineManifest,
    RecordingTimelinePublicSummary,
    TimelinePublicEntry,
    VideoArtifactPublicSummary,
    VideoArtifactRef,
)


class ActiveCaptureViewProjector:
    """Convert internal active-capture graphs into public API views."""

    def __init__(self, *, repository: ActiveCaptureRepository) -> None:
        self.repository = repository

    def to_public_view(self, view: ActiveCaptureSessionView) -> ActiveCapturePublicView:
        evidence_count_by_keyframe: dict[str, int] = {}
        for link in self.repository.list_evidence_links_for_session(view.session.session_id):
            evidence_count_by_keyframe[link.keyframe_id] = evidence_count_by_keyframe.get(link.keyframe_id, 0) + 1
        summaries = tuple(
            KeyframeInspectSummary(
                keyframe_id=keyframe.keyframe_id,
                session_id=keyframe.session_id,
                role=keyframe.role,
                trigger_kind=keyframe.trigger_kind,
                captured_at=keyframe.captured_at,
                sequence_index=keyframe.sequence_index,
                screenshot_artifact_id=keyframe.screenshot_artifact_id,
                screenshot_evidence_id=keyframe.screenshot_evidence_id,
                system_appshot_evidence_id=keyframe.system_appshot_evidence_id,
                media_time_ms=keyframe.media_time_ms,
                evidence_count=evidence_count_by_keyframe.get(keyframe.keyframe_id, 0),
                quality=keyframe.quality,
            )
            for keyframe in view.keyframes
        )
        return ActiveCapturePublicView(
            session=ActiveCaptureSessionPublicSummary(
                session_id=view.session.session_id,
                mode=view.session.mode,
                status=view.session.status,
                primary_event_id=view.session.primary_event_id,
                started_at=view.session.started_at,
                ended_at=view.session.ended_at,
                created_at=view.session.created_at,
                updated_at=view.session.updated_at,
                warnings=view.session.warnings,
                user_note=view.session.user_note,
            ),
            bundle=view.bundle,
            keyframes=summaries,
            timeline=self._timeline_summary(view.timeline),
            video=self._video_summary(view.video),
            control_trigger=view.control_trigger,
        )

    def _timeline_summary(
        self,
        timeline: RecordingTimelineManifest | None,
    ) -> RecordingTimelinePublicSummary | None:
        if timeline is None:
            return None
        return RecordingTimelinePublicSummary(
            manifest_id=timeline.manifest_id,
            session_id=timeline.session_id,
            primary_event_id=timeline.primary_event_id,
            video=self._video_summary(timeline.video) or VideoArtifactPublicSummary(state=timeline.video.state),
            clock_origin_wall_time=timeline.clock_origin_wall_time,
            started_at_monotonic_ms=timeline.started_at_monotonic_ms,
            ended_at_monotonic_ms=timeline.ended_at_monotonic_ms,
            duration_ms=timeline.duration_ms,
            entries=tuple(
                TimelinePublicEntry(
                    keyframe_id=entry.keyframe_id,
                    role=entry.role,
                    trigger_kind=entry.trigger_kind,
                    sequence_index=entry.sequence_index,
                    captured_at_wall_time=entry.captured_at_wall_time,
                    captured_at_monotonic_ms=entry.captured_at_monotonic_ms,
                    media_time_ms=entry.media_time_ms,
                    nearest_video_segment_id=entry.nearest_video_segment_id,
                    alignment_confidence=entry.alignment_confidence,
                    alignment_status=entry.alignment_status,
                )
                for entry in timeline.entries
            ),
        )

    def _video_summary(self, video: VideoArtifactRef | None) -> VideoArtifactPublicSummary | None:
        if video is None:
            return None
        return VideoArtifactPublicSummary(
            artifact_id=video.artifact_id,
            state=video.state,
            content_type=video.content_type,
            byte_size=video.byte_size,
            duration_ms=video.duration_ms,
            failure_reason=video.failure_reason,
            failure_message=video.failure_message,
            created_at=video.created_at,
        )
