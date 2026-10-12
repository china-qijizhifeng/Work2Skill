"""Explicit playback routes for active capture recordings."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from packages.artifacts.vault import ArtifactVaultError
from packages.contracts import (
    AccessScope,
    ActiveCaptureMode,
    ActiveCaptureSessionView,
    ActorRef,
    Artifact,
    ArtifactType,
    AuditAction,
    ContextEvent,
    ErrorCode,
    EventStatus,
    RecordingVideoPlaybackRequest,
    RecordingVideoPlaybackResponse,
    VideoArtifactRef,
    VideoArtifactState,
)

from ..auth import DaemonAuth
from ..container import DaemonContainer
from ..dependencies import route_support
from .active_capture_access import workspace_id_from_request

router = APIRouter()
_NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.post("/{session_id}/video/playback")
def play_recording_video(
    session_id: str,
    request: Request,
    body: RecordingVideoPlaybackRequest,
) -> JSONResponse:
    """Return a trusted local video handoff after an explicit playback request.

    Args:
        session_id: Active capture recording session identifier.
        request: FastAPI request carrying actor/workspace context.
        body: Typed playback request with event, artifact, and purpose.

    Returns:
        Response envelope with a vault-owned local file path, or a safe denial envelope.
    """

    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_RAW_ARTIFACT,
        resource_type="active_capture_recording_video",
        resource_id=session_id,
        reason=body.purpose,
    )
    if not isinstance(auth_result, tuple):
        return _json_response(status.HTTP_403_FORBIDDEN, auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    if not DaemonAuth().install_secret_matches(request, container):
        return _policy_denied(
            container,
            request=request,
            request_id=request_id,
            actor=actor,
            decision_id=decision_id,
            resource_type="active_capture_recording_video",
            resource_id=session_id,
            reason="recording video playback install secret missing",
            message="Recording video playback requires a local Workbench request.",
        )
    visible = _load_visible_session(
        container=container,
        request=request,
        request_id=request_id,
        session_id=session_id,
        event_id=body.event_id,
    )
    if isinstance(visible, JSONResponse):
        return visible
    view, event = visible
    video = _require_available_video(
        container=container,
        request=request,
        request_id=request_id,
        view=view,
        event_id=event.event_id,
        artifact_id=body.artifact_id,
        actor=actor,
        decision_id=decision_id,
    )
    if isinstance(video, JSONResponse):
        return video
    artifact = _require_recording_artifact(
        container=container,
        request=request,
        request_id=request_id,
        video=video,
        event_id=event.event_id,
        actor=actor,
        decision_id=decision_id,
    )
    if isinstance(artifact, JSONResponse):
        return artifact
    video_path = _resolve_recording_video_path(
        container=container, request_id=request_id, storage_uri=artifact.storage_uri
    )
    if isinstance(video_path, JSONResponse):
        return video_path
    byte_size = video_path.stat().st_size
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.DISCLOSURE_EVALUATED,
        resource_type="artifact",
        resource_id=artifact.artifact_id,
        policy_decision_id=decision_id,
        success=True,
        details={
            "artifact_type": artifact.artifact_type.value,
            "event_id": event.event_id,
            "session_id": session_id,
            "delivered_byte_count": byte_size,
            "delivery_mode": "local_file_handoff",
            "purpose": body.purpose,
        },
    )
    response = RecordingVideoPlaybackResponse(
        session_id=session_id,
        event_id=event.event_id,
        artifact_id=artifact.artifact_id,
        content_type=artifact.content_type or "video/mp4",
        byte_size=byte_size,
        playback_file_path=str(video_path),
    )
    envelope = container.responses.success(response, request_id=request_id, audit_id=audit_id)
    return _json_response(status.HTTP_200_OK, envelope.model_dump(mode="json", exclude_none=True))


def _load_visible_session(
    *,
    container: DaemonContainer,
    request: Request,
    request_id: str,
    session_id: str,
    event_id: str,
) -> tuple[ActiveCaptureSessionView, ContextEvent] | JSONResponse:
    try:
        view = container.active_capture.view_session(session_id)
    except ValueError:
        return _not_found(container, request_id=request_id)
    event = container.repositories.events.get(event_id)
    workspace_id = workspace_id_from_request(request)
    workspace_mismatch = (
        view.session.workspace_id is not None and workspace_id is not None and view.session.workspace_id != workspace_id
    )
    if event is None or event.status in {EventStatus.DELETED, EventStatus.RESTRICTED} or workspace_mismatch:
        return _not_found(container, request_id=request_id)
    return view, event


def _require_available_video(
    *,
    container: DaemonContainer,
    request: Request,
    request_id: str,
    view: ActiveCaptureSessionView,
    event_id: str,
    actor: ActorRef,
    decision_id: str,
    artifact_id: str,
) -> VideoArtifactRef | JSONResponse:
    video = view.timeline.video if view.timeline is not None else view.video
    if (
        view.session.mode != ActiveCaptureMode.RECORDING_SESSION
        or view.session.primary_event_id != event_id
        or video is None
        or video.state != VideoArtifactState.AVAILABLE
        or video.artifact_id is None
        or artifact_id != video.artifact_id
    ):
        return _policy_denied(
            container,
            request=request,
            request_id=request_id,
            actor=actor,
            decision_id=decision_id,
            resource_type="active_capture_recording_video",
            resource_id=view.session.session_id,
            reason="recording video playback precondition failed",
            message="Recording video playback is unavailable for this session.",
        )
    return video


def _require_recording_artifact(
    *,
    container: DaemonContainer,
    request: Request,
    request_id: str,
    video: VideoArtifactRef,
    event_id: str,
    actor: ActorRef,
    decision_id: str,
) -> Artifact | JSONResponse:
    if video.artifact_id is None:
        return _policy_denied(
            container,
            request=request,
            request_id=request_id,
            actor=actor,
            decision_id=decision_id,
            resource_type="artifact",
            resource_id="missing",
            reason="recording video artifact id missing",
            message="Recording video playback is unavailable for this artifact.",
        )
    artifact = container.repositories.artifacts.get(video.artifact_id)
    if (
        artifact is None
        or artifact.event_id != event_id
        or artifact.artifact_type != ArtifactType.RECORDING_VIDEO
        or artifact.storage_uri is None
    ):
        return _policy_denied(
            container,
            request=request,
            request_id=request_id,
            actor=actor,
            decision_id=decision_id,
            resource_type="artifact",
            resource_id=video.artifact_id,
            reason="recording video artifact mismatch",
            message="Recording video playback is unavailable for this artifact.",
        )
    return artifact


def _resolve_recording_video_path(
    *,
    container: DaemonContainer,
    request_id: str,
    storage_uri: str,
) -> Path | JSONResponse:
    try:
        return container.vault.resolve_local_path(storage_uri)
    except ArtifactVaultError:
        envelope = container.responses.error(
            ErrorCode.NOT_FOUND,
            "Recording video file not found.",
            request_id=request_id,
        )
        return _json_response(status.HTTP_404_NOT_FOUND, envelope.model_dump(mode="json"))


def _not_found(container: DaemonContainer, *, request_id: str) -> JSONResponse:
    envelope = container.responses.error(ErrorCode.NOT_FOUND, "Active capture session not found", request_id=request_id)
    return _json_response(status.HTTP_404_NOT_FOUND, envelope.model_dump(mode="json"))


def _policy_denied(
    container: DaemonContainer,
    *,
    request: Request,
    request_id: str,
    actor: ActorRef,
    decision_id: str,
    resource_type: str,
    resource_id: str,
    reason: str,
    message: str,
) -> JSONResponse:
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.DISCLOSURE_EVALUATED,
        resource_type=resource_type,
        resource_id=resource_id,
        policy_decision_id=decision_id,
        success=False,
        details={"reason": reason},
    )
    envelope = container.responses.error(
        ErrorCode.POLICY_DENIED,
        message,
        request_id=request_id,
        audit_id=audit_id,
    )
    return _json_response(status.HTTP_403_FORBIDDEN, envelope.model_dump(mode="json"))


def _json_response(status_code: int, content: object) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=content, headers=_NO_STORE_HEADERS)
