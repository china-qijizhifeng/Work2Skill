"""Helpers for mapping monotonic event clocks onto recording media time."""

from __future__ import annotations

from packages.contracts import RecordingVideoSegmentRef


def media_time_from_recording_segments(
    *,
    occurred_at_monotonic_ms: int | None,
    segments: tuple[RecordingVideoSegmentRef, ...],
    require_media_start: bool = True,
) -> int | None:
    """Return stitched video-relative media time for a monotonic event.

    ``started_at_monotonic_ms`` is when the native recording session/segment was
    requested. ``media_start_monotonic_ms`` is when video time 0 actually begins
    (normally the first captured frame). For user-visible replay and exported
    keylogs we must use the latter; otherwise input logs drift by the startup
    latency between "start recording" and the first frame.
    """

    if occurred_at_monotonic_ms is None:
        return None
    stitched_offset_ms = 0
    for segment in sorted(segments, key=lambda item: (item.sequence_index, item.started_at)):
        if segment.started_at_monotonic_ms is None:
            continue
        has_media_start = segment.media_start_monotonic_ms is not None
        media_start_ms = segment.media_start_monotonic_ms or segment.started_at_monotonic_ms
        segment_end_ms = segment.ended_at_monotonic_ms
        segment_duration_ms = _segment_media_duration_ms(
            segment,
            media_start_ms=media_start_ms,
            segment_end_ms=segment_end_ms,
        )
        if segment_end_ms is None and segment_duration_ms is not None:
            segment_end_ms = media_start_ms + segment_duration_ms
        if segment_end_ms is None and occurred_at_monotonic_ms >= segment.started_at_monotonic_ms:
            segment_end_ms = occurred_at_monotonic_ms
        if segment_end_ms is None:
            continue
        if segment.started_at_monotonic_ms <= occurred_at_monotonic_ms <= segment_end_ms:
            if require_media_start and not has_media_start:
                return None
            segment_media_ms = max(0, occurred_at_monotonic_ms - media_start_ms)
            if segment_duration_ms is not None:
                segment_media_ms = min(segment_media_ms, segment_duration_ms)
            return stitched_offset_ms + segment_media_ms
        if segment_duration_ms is not None:
            stitched_offset_ms += segment_duration_ms
    return None


def recording_media_origin_monotonic_ms(
    *, segments: tuple[RecordingVideoSegmentRef, ...], fallback: int | None = None
) -> int | None:
    """Return the monotonic instant that should correspond to video media time 0."""

    for segment in sorted(segments, key=lambda item: (item.sequence_index, item.started_at)):
        if segment.media_start_monotonic_ms is not None:
            return segment.media_start_monotonic_ms
    return fallback


def _segment_media_duration_ms(
    segment: RecordingVideoSegmentRef,
    *,
    media_start_ms: int,
    segment_end_ms: int | None,
) -> int | None:
    if segment.video is not None and segment.video.duration_ms is not None:
        return segment.video.duration_ms
    if segment.duration_ms is not None:
        return segment.duration_ms
    if segment_end_ms is not None:
        return max(0, segment_end_ms - media_start_ms)
    return None
