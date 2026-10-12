"""Timeline manifest construction and media-time alignment."""

from __future__ import annotations

from dataclasses import dataclass

from packages.contracts import (
    ContextKeyframe,
    RecordingTimelineManifest,
    RecordingVideoSegmentRef,
    TimelineAlignmentConfidence,
    TimelineAlignmentStatus,
    TimelineKeyframeEntry,
    VideoArtifactRef,
    VideoArtifactState,
)
from packages.contracts.common import JsonScalar
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

from .media_time import recording_media_origin_monotonic_ms


@dataclass(frozen=True)
class TimelineAlignmentDecision:
    """Typed result of mapping a keyframe timestamp to video media time.

    Attributes:
        media_time_ms: Segment-relative or recording-relative media timestamp.
        confidence: Confidence assigned to the mapping.
        status: Machine-readable alignment reason.
        metadata: Small scalar diagnostics for audit and tests.
    """

    media_time_ms: int | None
    confidence: TimelineAlignmentConfidence
    status: TimelineAlignmentStatus
    metadata: dict[str, JsonScalar]


class RecordingTimelineManifestBuilder:
    """Build manifests from typed keyframes without inferring from DB order."""

    def __init__(self, *, ids: IdFactory, clock: Clock) -> None:
        self.ids = ids
        self.clock = clock

    def build(
        self,
        *,
        session_id: str,
        primary_event_id: str | None,
        keyframes: tuple[ContextKeyframe, ...],
        video: VideoArtifactRef | None = None,
        clock_origin_monotonic_ms: int | None = None,
        started_at_monotonic_ms: int | None = None,
        ended_at_monotonic_ms: int | None = None,
        segments: tuple[RecordingVideoSegmentRef, ...] = (),
        timeline_alignment_tolerance_ms: int = 0,
    ) -> RecordingTimelineManifest:
        """Create a manifest using monotonic timestamps already present on frames."""

        now = self.clock.now()
        ordered = tuple(sorted(keyframes, key=lambda item: (item.sequence_index, item.captured_at)))
        origin_wall_time = ordered[0].captured_at if ordered else now
        ordered_segments = tuple(sorted(segments, key=lambda item: (item.sequence_index, item.started_at)))
        origin_monotonic = clock_origin_monotonic_ms or recording_media_origin_monotonic_ms(
            segments=ordered_segments,
            fallback=started_at_monotonic_ms,
        )
        if origin_monotonic is None:
            origin_monotonic = next(
                (item.captured_at_monotonic_ms for item in ordered if item.captured_at_monotonic_ms is not None),
                None,
            )
        start_mono = started_at_monotonic_ms or origin_monotonic
        video_duration_ms = video.duration_ms if video is not None else None
        entries = tuple(
            self._entry(
                keyframe=keyframe,
                video_artifact_id=video.artifact_id if video is not None else None,
                started_at_monotonic_ms=start_mono,
                video_duration_ms=video_duration_ms,
                segments=ordered_segments,
                timeline_alignment_tolerance_ms=timeline_alignment_tolerance_ms,
            )
            for keyframe in ordered
        )
        duration_ms = None
        if started_at_monotonic_ms is not None and ended_at_monotonic_ms is not None:
            duration_ms = max(0, ended_at_monotonic_ms - started_at_monotonic_ms)
        elif video is not None:
            duration_ms = video.duration_ms
        return RecordingTimelineManifest(
            manifest_id=self.ids.new("tlm"),
            session_id=session_id,
            primary_event_id=primary_event_id,
            video=video or VideoArtifactRef(state=VideoArtifactState.NOT_RECORDED),
            clock_origin_wall_time=origin_wall_time,
            clock_origin_monotonic_ms=origin_monotonic,
            started_at_monotonic_ms=started_at_monotonic_ms,
            ended_at_monotonic_ms=ended_at_monotonic_ms,
            duration_ms=duration_ms,
            alignment_error_ms=None if video is not None else 0,
            entries=entries,
            created_at=now,
            updated_at=now,
        )

    def _entry(
        self,
        *,
        keyframe: ContextKeyframe,
        video_artifact_id: str | None,
        started_at_monotonic_ms: int | None,
        video_duration_ms: int | None,
        segments: tuple[RecordingVideoSegmentRef, ...],
        timeline_alignment_tolerance_ms: int,
    ) -> TimelineKeyframeEntry:
        decision = self._align_media_time(
            keyframe=keyframe,
            started_at_monotonic_ms=started_at_monotonic_ms,
            video_duration_ms=video_duration_ms,
            segments=segments,
            tolerance_ms=timeline_alignment_tolerance_ms,
        )
        segment_id = decision.metadata.get("segment_id")
        return TimelineKeyframeEntry(
            keyframe_id=keyframe.keyframe_id,
            role=keyframe.role,
            trigger_kind=keyframe.trigger_kind,
            sequence_index=keyframe.sequence_index,
            captured_at_wall_time=keyframe.captured_at,
            captured_at_monotonic_ms=keyframe.captured_at_monotonic_ms,
            media_time_ms=decision.media_time_ms,
            video_artifact_id=video_artifact_id,
            nearest_video_segment_id=segment_id if isinstance(segment_id, str) else None,
            alignment_confidence=decision.confidence,
            alignment_status=decision.status,
            metadata=decision.metadata,
        )

    def _align_media_time(
        self,
        *,
        keyframe: ContextKeyframe,
        started_at_monotonic_ms: int | None,
        video_duration_ms: int | None,
        segments: tuple[RecordingVideoSegmentRef, ...],
        tolerance_ms: int,
    ) -> TimelineAlignmentDecision:
        if keyframe.captured_at_monotonic_ms is not None and segments:
            has_usable_segment_clock = any(item.started_at_monotonic_ms is not None for item in segments)
            has_complete_segment_clock = has_usable_segment_clock and all(
                item.started_at_monotonic_ms is not None
                and (item.ended_at_monotonic_ms is not None or item.duration_ms is not None)
                for item in segments
            )
            if has_complete_segment_clock:
                return self._align_from_recording_segments(
                    captured_at_monotonic_ms=keyframe.captured_at_monotonic_ms,
                    segments=segments,
                    video_duration_ms=video_duration_ms,
                    tolerance_ms=tolerance_ms,
                )
        if keyframe.captured_at_monotonic_ms is not None and started_at_monotonic_ms is not None:
            return self._align_from_monotonic_clock(
                captured_at_monotonic_ms=keyframe.captured_at_monotonic_ms,
                started_at_monotonic_ms=started_at_monotonic_ms,
                video_duration_ms=video_duration_ms,
                tolerance_ms=tolerance_ms,
            )
        if keyframe.media_time_ms is not None:
            return self._align_from_client_media_hint(
                media_time_ms=keyframe.media_time_ms,
                video_duration_ms=video_duration_ms,
                tolerance_ms=tolerance_ms,
            )
        return TimelineAlignmentDecision(
            media_time_ms=None,
            confidence=TimelineAlignmentConfidence.UNAVAILABLE,
            status=TimelineAlignmentStatus.MISSING_CLOCK,
            metadata={},
        )

    def _align_from_recording_segments(
        self,
        *,
        captured_at_monotonic_ms: int,
        segments: tuple[RecordingVideoSegmentRef, ...],
        video_duration_ms: int | None,
        tolerance_ms: int,
    ) -> TimelineAlignmentDecision:
        stitched_offset_ms = 0
        for segment in segments:
            if segment.started_at_monotonic_ms is None:
                continue
            segment_end_ms = segment.ended_at_monotonic_ms
            if segment_end_ms is None and segment.duration_ms is not None:
                segment_end_ms = self._segment_media_start_monotonic_ms(segment) + segment.duration_ms
            if segment_end_ms is None:
                continue
            media_start_ms = self._segment_media_start_monotonic_ms(segment)
            segment_clock_span_ms = max(0, segment_end_ms - media_start_ms)
            segment_duration_ms = self._segment_media_duration_ms(segment, fallback_duration_ms=segment_clock_span_ms)
            if (
                segment.started_at_monotonic_ms - tolerance_ms
                <= captured_at_monotonic_ms
                <= segment_end_ms + tolerance_ms
            ):
                segment_media_ms = max(0, captured_at_monotonic_ms - media_start_ms)
                segment_media_ms = min(segment_media_ms, segment_duration_ms)
                media_time_ms = stitched_offset_ms + segment_media_ms
                bounded = self._bound_to_video_duration(
                    media_time_ms=media_time_ms,
                    video_duration_ms=video_duration_ms,
                    tolerance_ms=tolerance_ms,
                    metadata={
                        "segment_id": segment.segment_id,
                        "segment_sequence_index": segment.sequence_index,
                        "segment_media_start_monotonic_ms": media_start_ms,
                    },
                )
                if bounded is not None:
                    return bounded
                return TimelineAlignmentDecision(
                    media_time_ms=media_time_ms,
                    confidence=TimelineAlignmentConfidence.EXACT,
                    status=TimelineAlignmentStatus.ALIGNED,
                    metadata={
                        "segment_id": segment.segment_id,
                        "segment_sequence_index": segment.sequence_index,
                        "segment_media_start_monotonic_ms": media_start_ms,
                    },
                )
            stitched_offset_ms += segment_duration_ms
        return TimelineAlignmentDecision(
            media_time_ms=None,
            confidence=TimelineAlignmentConfidence.UNAVAILABLE,
            status=TimelineAlignmentStatus.OUTSIDE_VIDEO_DURATION,
            metadata={"segment_count": len(segments)},
        )

    @staticmethod
    def _segment_media_duration_ms(segment: RecordingVideoSegmentRef, *, fallback_duration_ms: int) -> int:
        if segment.video is not None and segment.video.duration_ms is not None:
            return segment.video.duration_ms
        if segment.duration_ms is not None:
            return segment.duration_ms
        return fallback_duration_ms

    @staticmethod
    def _segment_media_start_monotonic_ms(segment: RecordingVideoSegmentRef) -> int:
        if segment.media_start_monotonic_ms is not None:
            return segment.media_start_monotonic_ms
        if segment.started_at_monotonic_ms is not None:
            return segment.started_at_monotonic_ms
        return 0

    @staticmethod
    def _bound_to_video_duration(
        *,
        media_time_ms: int,
        video_duration_ms: int | None,
        tolerance_ms: int,
        metadata: dict[str, JsonScalar],
    ) -> TimelineAlignmentDecision | None:
        if video_duration_ms is None or media_time_ms <= video_duration_ms:
            return None
        alignment_error_ms = media_time_ms - video_duration_ms
        if alignment_error_ms <= tolerance_ms:
            bounded_metadata = {
                **metadata,
                "alignment_adjustment_ms": alignment_error_ms,
                "video_duration_ms": video_duration_ms,
            }
            return TimelineAlignmentDecision(
                media_time_ms=video_duration_ms,
                confidence=TimelineAlignmentConfidence.EXACT,
                status=TimelineAlignmentStatus.ALIGNED,
                metadata=bounded_metadata,
            )
        return TimelineAlignmentDecision(
            media_time_ms=None,
            confidence=TimelineAlignmentConfidence.UNAVAILABLE,
            status=TimelineAlignmentStatus.OUTSIDE_VIDEO_DURATION,
            metadata={
                **metadata,
                "alignment_error_ms": alignment_error_ms,
                "video_duration_ms": video_duration_ms,
            },
        )

    def _align_from_monotonic_clock(
        self,
        *,
        captured_at_monotonic_ms: int,
        started_at_monotonic_ms: int,
        video_duration_ms: int | None,
        tolerance_ms: int,
    ) -> TimelineAlignmentDecision:
        raw_media_time_ms = captured_at_monotonic_ms - started_at_monotonic_ms
        if raw_media_time_ms < -tolerance_ms:
            return TimelineAlignmentDecision(
                media_time_ms=None,
                confidence=TimelineAlignmentConfidence.UNAVAILABLE,
                status=TimelineAlignmentStatus.BEFORE_VIDEO_START,
                metadata={"alignment_error_ms": abs(raw_media_time_ms)},
            )
        media_time_ms = max(0, raw_media_time_ms)
        if video_duration_ms is not None and media_time_ms > video_duration_ms + tolerance_ms:
            return TimelineAlignmentDecision(
                media_time_ms=None,
                confidence=TimelineAlignmentConfidence.UNAVAILABLE,
                status=TimelineAlignmentStatus.OUTSIDE_VIDEO_DURATION,
                metadata={
                    "alignment_error_ms": raw_media_time_ms - video_duration_ms,
                    "video_duration_ms": video_duration_ms,
                },
            )
        return TimelineAlignmentDecision(
            media_time_ms=media_time_ms,
            confidence=TimelineAlignmentConfidence.ESTIMATED,
            status=TimelineAlignmentStatus.ALIGNED,
            metadata={},
        )

    def _align_from_client_media_hint(
        self,
        *,
        media_time_ms: int,
        video_duration_ms: int | None,
        tolerance_ms: int,
    ) -> TimelineAlignmentDecision:
        if video_duration_ms is not None and media_time_ms > video_duration_ms + tolerance_ms:
            return TimelineAlignmentDecision(
                media_time_ms=None,
                confidence=TimelineAlignmentConfidence.UNAVAILABLE,
                status=TimelineAlignmentStatus.OUTSIDE_VIDEO_DURATION,
                metadata={"video_duration_ms": video_duration_ms},
            )
        return TimelineAlignmentDecision(
            media_time_ms=media_time_ms,
            confidence=TimelineAlignmentConfidence.ESTIMATED,
            status=TimelineAlignmentStatus.CLIENT_MEDIA_HINT,
            metadata={},
        )
