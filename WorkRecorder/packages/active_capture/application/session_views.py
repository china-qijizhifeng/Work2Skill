"""Session view helpers for the ActiveCaptureService facade."""

from __future__ import annotations

from packages.active_capture.application.keyframe_views import (
    sanitize_bundle_for_keyframes,
    sanitize_timeline_for_keyframes,
)
from packages.active_capture.repositories.protocol import ActiveCaptureRepository
from packages.contracts import ActiveCaptureSession, ActiveCaptureSessionView


def build_session_view(
    *,
    repository: ActiveCaptureRepository,
    session: ActiveCaptureSession,
) -> ActiveCaptureSessionView:
    """Return the current backend view for a session.

    Args:
        repository: Active-capture repository used to load graph pieces.
        session: Session being projected.

    Returns:
        Session view with sanitized keyframe bundle and timeline refs.
    """

    keyframes = repository.list_keyframes_for_session(session.session_id)
    timeline = repository.get_timeline_manifest(session.session_id)
    bundle = sanitize_bundle_for_keyframes(
        bundle=repository.get_bundle_for_session(session.session_id),
        keyframes=keyframes,
    )
    timeline = sanitize_timeline_for_keyframes(timeline=timeline, keyframes=keyframes)
    return ActiveCaptureSessionView(
        session=session,
        bundle=bundle,
        keyframes=keyframes,
        timeline=timeline,
        video=timeline.video if timeline is not None else None,
    )


def filter_session_view_for_visible_events(
    *,
    view: ActiveCaptureSessionView,
    visible_event_ids: set[str],
) -> ActiveCaptureSessionView:
    """Return a session view with keyframes/timeline entries limited to visible events.

    Args:
        view: Existing unfiltered session view.
        visible_event_ids: Event ids visible to the caller.

    Returns:
        A view with hidden event references removed.
    """

    visible_keyframes = tuple(keyframe for keyframe in view.keyframes if keyframe.event_id in visible_event_ids)
    if visible_keyframes == view.keyframes:
        return view
    visible_keyframe_ids = {keyframe.keyframe_id for keyframe in visible_keyframes}
    bundle = sanitize_bundle_for_keyframes(bundle=view.bundle, keyframes=visible_keyframes)
    timeline = view.timeline
    if timeline is not None:
        timeline = timeline.model_copy(
            update={"entries": tuple(entry for entry in timeline.entries if entry.keyframe_id in visible_keyframe_ids)}
        )
    return view.model_copy(update={"bundle": bundle, "keyframes": visible_keyframes, "timeline": timeline})
