"""Read-side helpers for active-capture keyframe projections."""

from __future__ import annotations

from packages.active_capture.repositories.protocol import ActiveCaptureKeyframeRepository
from packages.contracts import (
    ActiveCaptureSession,
    ActiveCaptureStatus,
    ContextKeyframe,
    KeyframeBundleStatus,
    KeyframeContextBundle,
    KeyframeInspectSummary,
    KeyframeRole,
    RecordingTimelineManifest,
)
from packages.shared.ids import IdFactory
from packages.shared.time import Clock


def inspect_summaries_for_event(
    *,
    repository: ActiveCaptureKeyframeRepository,
    event_id: str,
) -> tuple[KeyframeInspectSummary, ...]:
    """Return safe keyframe summaries for explicit event inspection.

    Args:
        repository: Active-capture read repository.
        event_id: Context event whose keyframes should be summarized.

    Returns:
        Public keyframe summaries without raw artifact bytes.
    """

    summaries: list[KeyframeInspectSummary] = []
    for keyframe in repository.list_keyframes_for_event(event_id):
        summaries.append(
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
                evidence_count=len(repository.list_evidence_links_for_keyframe(keyframe.keyframe_id)),
                quality=keyframe.quality,
            )
        )
    return tuple(summaries)


def refresh_bundle(
    *,
    repository: ActiveCaptureKeyframeRepository,
    clock: Clock,
    ids: IdFactory,
    session: ActiveCaptureSession,
) -> KeyframeContextBundle:
    """Refresh and persist the derived keyframe bundle for a session.

    Args:
        repository: Active-capture keyframe repository.
        clock: Clock used for bundle timestamps.
        ids: Identifier generator for new bundles.
        session: Session whose bundle should be rebuilt.

    Returns:
        Persisted bundle snapshot.
    """

    existing = repository.get_bundle_for_session(session.session_id)
    bundle = bundle_for_session(
        repository=repository,
        clock=clock,
        ids=ids,
        session=session,
        keyframes=repository.list_keyframes_for_session(session.session_id),
    )
    return repository.save_bundle(
        bundle.model_copy(update={"created_at": existing.created_at if existing else clock.now()})
    )


def bundle_for_session(
    *,
    repository: ActiveCaptureKeyframeRepository,
    clock: Clock,
    ids: IdFactory,
    session: ActiveCaptureSession,
    keyframes: tuple[ContextKeyframe, ...],
) -> KeyframeContextBundle:
    """Build the bundle aggregate for a session.

    Args:
        repository: Active-capture keyframe repository.
        clock: Clock used for timestamps.
        ids: Identifier generator for new bundles.
        session: Session that owns the keyframes.
        keyframes: Retained keyframes to summarize.

    Returns:
        Bundle aggregate with anchor and readiness status.
    """

    now = clock.now()
    existing = repository.get_bundle_for_session(session.session_id)
    anchor = next((item for item in keyframes if item.role == KeyframeRole.ANCHOR), keyframes[0] if keyframes else None)
    status = KeyframeBundleStatus.ANCHOR_ONLY if len(keyframes) <= 1 else KeyframeBundleStatus.READY
    if session.status == ActiveCaptureStatus.COMPLETED_WITH_WARNINGS:
        status = KeyframeBundleStatus.COMPLETED_WITH_WARNINGS
    if session.status == ActiveCaptureStatus.FAILED:
        status = KeyframeBundleStatus.FAILED
    return KeyframeContextBundle(
        bundle_id=existing.bundle_id if existing is not None else ids.new("kfb"),
        session_id=session.session_id,
        primary_event_id=session.primary_event_id,
        status=status,
        anchor_keyframe_id=anchor.keyframe_id if anchor is not None else None,
        keyframe_count=len(keyframes),
        created_at=existing.created_at if existing is not None else now,
        updated_at=now,
        warnings=session.warnings,
    )


def sanitize_bundle_for_keyframes(
    *,
    bundle: KeyframeContextBundle | None,
    keyframes: tuple[ContextKeyframe, ...],
) -> KeyframeContextBundle | None:
    """Drop bundle refs that point outside the supplied visible keyframes.

    Args:
        bundle: Bundle aggregate to sanitize.
        keyframes: Visible keyframes allowed in the response.

    Returns:
        Sanitized bundle, or None when no bundle exists.
    """

    if bundle is None:
        return None
    keyframe_ids = {item.keyframe_id for item in keyframes}
    anchor_keyframe_id = bundle.anchor_keyframe_id if bundle.anchor_keyframe_id in keyframe_ids else None
    return bundle.model_copy(update={"anchor_keyframe_id": anchor_keyframe_id, "keyframe_count": len(keyframes)})


def sanitize_timeline_for_keyframes(
    *,
    timeline: RecordingTimelineManifest | None,
    keyframes: tuple[ContextKeyframe, ...],
) -> RecordingTimelineManifest | None:
    """Drop timeline entries that point outside the visible keyframes.

    Args:
        timeline: Timeline aggregate to sanitize.
        keyframes: Visible keyframes allowed in the response.

    Returns:
        Sanitized timeline, or None when absent.
    """

    if timeline is None:
        return None
    keyframe_ids = {item.keyframe_id for item in keyframes}
    return timeline.model_copy(
        update={"entries": tuple(entry for entry in timeline.entries if entry.keyframe_id in keyframe_ids)}
    )
