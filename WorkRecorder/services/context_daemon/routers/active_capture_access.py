"""Access helpers shared by active-capture daemon routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Request

from packages.contracts import (
    ActiveCaptureSession,
    ActiveCaptureSessionView,
    ActorRef,
    ClickTargetPublicView,
    ContextKeyframe,
    EventStatus,
    HumanActionKind,
    HumanActionTargetKind,
    RecordingStoryboardProjection,
    SkillDistillationInputView,
    SkillDistillationTargetView,
    StoryboardActionItem,
)

if TYPE_CHECKING:
    from ..container import DaemonContainer

_LOCAL_ACTIVE_CAPTURE_READER_ACTORS = frozenset({"workrecorder-workbench"})


def _session_identity_read_allowed(
    container: "DaemonContainer",
    session: ActiveCaptureSession,
    *,
    actor: ActorRef,
    request: Request,
) -> bool:
    """Allow the local Workbench to read native-capture sessions in the same workspace."""

    effective_actor_id = actor.actor_id
    if actor.actor_id in _LOCAL_ACTIVE_CAPTURE_READER_ACTORS and session.actor is not None:
        effective_actor_id = session.actor.actor_id
    return container.active_capture.can_access_session(
        session=session,
        actor_id=effective_actor_id,
        workspace_id=workspace_id_from_request(request),
    )


def session_read_allowed(
    container: "DaemonContainer",
    view: ActiveCaptureSessionView,
    *,
    actor: ActorRef,
    request: Request,
) -> bool:
    """Return whether a caller can read one active-capture session view.

    Args:
        container: Daemon dependency container with repositories and services.
        view: Active-capture view being protected.
        actor: Authenticated caller identity.
        request: FastAPI request carrying the optional workspace header.

    Returns:
        True when actor, workspace, and primary event visibility all match.
    """

    return _session_primary_event_allows_read(
        container, view.session.primary_event_id
    ) and _session_identity_read_allowed(
        container,
        view.session,
        actor=actor,
        request=request,
    )


def session_metadata_read_allowed(
    container: "DaemonContainer",
    session: ActiveCaptureSession,
    *,
    actor: ActorRef,
    request: Request,
) -> bool:
    """Return whether a caller can read safe metadata for one active-capture session."""

    return _session_primary_event_allows_read(
        container, session.primary_event_id
    ) and _session_identity_read_allowed(
        container,
        session,
        actor=actor,
        request=request,
    )


def searched_recording_metadata_read_allowed(
    container: "DaemonContainer",
    session: ActiveCaptureSession,
    *,
    actor: ActorRef,
    request: Request,
    query: str,
) -> bool:
    """Allow a matching soft-deleted recording card to appear in an explicit note search."""

    if not _session_identity_read_allowed(
        container,
        session,
        actor=actor,
        request=request,
    ):
        return False
    if _session_primary_event_allows_read(container, session.primary_event_id):
        return True
    normalized_query = query.strip().casefold()
    if not normalized_query or not session.user_note:
        return False
    event = (
        container.repositories.events.get_including_deleted(session.primary_event_id)
        if session.primary_event_id
        else None
    )
    return (
        event is not None
        and event.status == EventStatus.DELETED
        and normalized_query in session.user_note.casefold()
    )


def workspace_id_from_request(request: Request) -> str | None:
    """Read the trusted workspace header from a daemon request.

    Args:
        request: FastAPI request carrying headers from the local client.

    Returns:
        Trimmed workspace id, or None when the header is absent or blank.
    """

    workspace_id = request.headers.get("x-workrecorder-workspace-id")
    if workspace_id is None or not workspace_id.strip():
        return None
    return workspace_id.strip()


def filter_session_view_for_visible_events(
    container: "DaemonContainer", view: ActiveCaptureSessionView
) -> ActiveCaptureSessionView:
    """Remove keyframes whose backing events are no longer visible.

    Args:
        container: Daemon dependency container with event repositories.
        view: Active-capture graph returned by the application service.

    Returns:
        A sanitized view that future public projection can safely expose.
    """

    candidate_event_ids = tuple(dict.fromkeys(keyframe.event_id for keyframe in view.keyframes))
    visible_event_ids = {
        event.event_id
        for event in container.repositories.events.list_by_ids(candidate_event_ids)
        if event.status not in {EventStatus.DELETED, EventStatus.RESTRICTED}
    }
    return container.active_capture.filter_view_for_visible_events(
        view=view,
        visible_event_ids=visible_event_ids,
    )


def filter_storyboard_for_visible_keyframes(
    projection: RecordingStoryboardProjection,
    *,
    session_has_keyframes: bool,
    visible_keyframe_ids: set[str],
) -> RecordingStoryboardProjection:
    """Remove storyboard rows whose keyframe evidence is no longer visible.

    Args:
        projection: UI-oriented storyboard projection produced by active capture.
        session_has_keyframes: Whether the underlying session has any keyframes.
        visible_keyframe_ids: Keyframe ids backed by events the caller may read.

    Returns:
        A storyboard projection with hidden keyframes and unverifiable action rows removed.
    """

    items = []
    action_count = 0
    for item in projection.items:
        keyframe_id = getattr(item, "keyframe_id", None)
        if isinstance(keyframe_id, str) and keyframe_id not in visible_keyframe_ids:
            continue
        if isinstance(item, StoryboardActionItem):
            sanitized_item = _sanitize_storyboard_action_item(
                item,
                session_has_keyframes=session_has_keyframes,
                visible_keyframe_ids=visible_keyframe_ids,
            )
            if sanitized_item is None:
                continue
            item = sanitized_item
            action_count += 1
        items.append(item)
    card = projection.card.model_copy(
        update={
            "keyframe_count": sum(1 for item in items if getattr(item, "keyframe_id", None) is not None),
            "action_count": action_count,
        }
    )
    return projection.model_copy(update={"card": card, "items": tuple(items)})


def _sanitize_storyboard_action_item(
    item: StoryboardActionItem,
    *,
    session_has_keyframes: bool,
    visible_keyframe_ids: set[str],
) -> StoryboardActionItem | None:
    """Drop any legacy or hidden target labels from storyboard action rows.

    The action row itself is low-sensitive once the graph visibility projection has
    run. The semantic target is optional and must always come from the structured,
    sanitized public target view rather than legacy ``target_label`` strings.
    """

    evidence_keyframe_ids = tuple(
        keyframe_id for keyframe_id in item.evidence_keyframe_ids if keyframe_id in visible_keyframe_ids
    )
    if session_has_keyframes and not evidence_keyframe_ids:
        return None
    target = _sanitize_resolved_public_target(
        item.target,
        visible_keyframe_ids=visible_keyframe_ids,
    )
    return item.model_copy(
        update={
            "caption": _safe_storyboard_action_caption(item, target=target),
            "evidence_keyframe_ids": evidence_keyframe_ids,
            "target": target,
            "target_label": target.display_label if target is not None else None,
        }
    )


def _safe_storyboard_action_caption(
    item: StoryboardActionItem,
    *,
    target: ClickTargetPublicView | None,
) -> str | None:
    """Recompute target-derived captions after route visibility filtering."""

    if item.action_kind != HumanActionKind.CLICK:
        return item.caption
    if target is None:
        return "点击（目标待确认）"
    if target.needs_review:
        return f"点击（{target.display_label}）"
    return f"点击「{target.display_label}」"


def filter_skill_input_for_visible_keyframes(
    container: "DaemonContainer",
    projection: SkillDistillationInputView,
    *,
    session_has_keyframes: bool,
    visible_keyframes: tuple[ContextKeyframe, ...],
) -> SkillDistillationInputView:
    """Remove skill-input steps whose supporting keyframes are not visible.

    Args:
        projection: Skill-distillation input projection produced by active capture.
        session_has_keyframes: Whether the underlying session has any keyframes.
        visible_keyframes: Keyframes backed by events the caller may read.

    Returns:
        A skill input projection that only cites visible keyframes.
    """

    visible_keyframe_ids = {keyframe.keyframe_id for keyframe in visible_keyframes}
    visible_evidence_ids = {
        evidence_id
        for keyframe in visible_keyframes
        for evidence_id in (keyframe.screenshot_evidence_id, keyframe.system_appshot_evidence_id)
        if evidence_id is not None
    }
    visible_artifact_ids = {
        keyframe.screenshot_artifact_id for keyframe in visible_keyframes if keyframe.screenshot_artifact_id is not None
    }
    for link in container.repositories.active_capture.list_evidence_links_for_session(projection.session_id):
        if link.keyframe_id not in visible_keyframe_ids:
            continue
        visible_evidence_ids.add(link.evidence_id)
        if link.artifact_id is not None:
            visible_artifact_ids.add(link.artifact_id)
    steps = []
    for step in projection.steps:
        if session_has_keyframes and not step.evidence_keyframe_ids:
            if step.action_kind not in _SAFE_UNLINKED_SKILL_ACTION_KINDS:
                continue
            steps.append(
                step.model_copy(
                    update={
                        "needs_review": True,
                        "target": _sanitize_skill_target(
                            step.target,
                            visible_keyframe_ids=visible_keyframe_ids,
                            visible_evidence_ids=visible_evidence_ids,
                            visible_artifact_ids=visible_artifact_ids,
                        ),
                    }
                )
            )
            continue
        evidence_keyframe_ids = tuple(
            keyframe_id for keyframe_id in step.evidence_keyframe_ids if keyframe_id in visible_keyframe_ids
        )
        if step.evidence_keyframe_ids and not evidence_keyframe_ids:
            continue
        steps.append(
            step.model_copy(
                update={
                    "evidence_keyframe_ids": evidence_keyframe_ids,
                    "target": _sanitize_skill_target(
                        step.target,
                        visible_keyframe_ids=visible_keyframe_ids,
                        visible_evidence_ids=visible_evidence_ids,
                        visible_artifact_ids=visible_artifact_ids,
                    ),
                }
            )
        )
    return projection.model_copy(update={"steps": tuple(steps)})


_SAFE_UNLINKED_SKILL_ACTION_KINDS = frozenset(
    {
        HumanActionKind.HOTKEY,
        HumanActionKind.KEY_DOWN,
        HumanActionKind.KEY_UP,
        HumanActionKind.TYPING_PAUSE,
    }
)


def _sanitize_skill_target(
    target: SkillDistillationTargetView | None,
    *,
    visible_keyframe_ids: set[str],
    visible_evidence_ids: set[str],
    visible_artifact_ids: set[str],
) -> SkillDistillationTargetView | None:
    if target is None:
        return None
    resolved_target = _sanitize_resolved_skill_target(
        target.resolved_target,
        visible_keyframe_ids=visible_keyframe_ids,
    )
    if target.keyframe_id is None:
        return target.model_copy(
            update={
                "evidence_id": None,
                "artifact_id": None,
                "resolved_target": resolved_target,
            }
        )
    if target.keyframe_id not in visible_keyframe_ids:
        return target.model_copy(
            update={
                "target_kind": HumanActionTargetKind.UNKNOWN,
                "keyframe_id": None,
                "evidence_id": None,
                "artifact_id": None,
                "resolved_target": None,
                "confidence": 0.0,
                "has_coordinates": False,
            }
        )
    updates: dict[str, object] = {"resolved_target": resolved_target}
    if target.evidence_id is not None and target.evidence_id not in visible_evidence_ids:
        updates["evidence_id"] = None
    if target.artifact_id is not None and target.artifact_id not in visible_artifact_ids:
        updates["artifact_id"] = None
    if updates:
        return target.model_copy(update=updates)
    return target


def _sanitize_resolved_skill_target(
    target: ClickTargetPublicView | None,
    *,
    visible_keyframe_ids: set[str],
) -> ClickTargetPublicView | None:
    return _sanitize_resolved_public_target(target, visible_keyframe_ids=visible_keyframe_ids)


def _sanitize_resolved_public_target(
    target: ClickTargetPublicView | None,
    *,
    visible_keyframe_ids: set[str],
) -> ClickTargetPublicView | None:
    if target is None:
        return None
    evidence_keyframe_ids = tuple(
        keyframe_id for keyframe_id in target.evidence_keyframe_ids if keyframe_id in visible_keyframe_ids
    )
    if target.evidence_keyframe_ids and not evidence_keyframe_ids:
        return None
    if len(evidence_keyframe_ids) != len(target.evidence_keyframe_ids):
        return target.model_copy(update={"evidence_keyframe_ids": evidence_keyframe_ids, "needs_review": True})
    return target


def _session_primary_event_allows_read(container: "DaemonContainer", event_id: str | None) -> bool:
    if event_id is None:
        return True
    event = container.repositories.events.get(event_id)
    return event is not None and event.status not in {EventStatus.DELETED, EventStatus.RESTRICTED}
