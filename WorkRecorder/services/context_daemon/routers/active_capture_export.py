"""Explicit filesystem export routes for active capture recordings."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from packages.active_capture.application.export import RecordingExportError
from packages.contracts import (
    AccessScope,
    ActorRef,
    AuditAction,
    EventStatus,
    ErrorCode,
    RecordingExportRequest,
    RecordingExportResponse,
)

from ..auth import DaemonAuth
from ..container import DaemonContainer
from ..dependencies import route_support
from .active_capture_access import workspace_id_from_request

router = APIRouter()
logger = logging.getLogger(__name__)
_NO_STORE_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


@router.post("/{session_id}/export")
def export_recording(
    session_id: str,
    request: Request,
    body: RecordingExportRequest,
) -> JSONResponse:
    """Materialize a recording into a browsable directory tree after explicit request.

    Args:
        session_id: Active capture recording session identifier.
        request: FastAPI request carrying actor/workspace context.
        body: Typed export request with output root and purpose.

    Returns:
        Response envelope with the recording output directory, or a safe denial.
    """

    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_RAW_ARTIFACT,
        resource_type="active_capture_recording_export",
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
            resource_id=session_id,
            reason="recording export install secret missing",
            message="Recording export requires a local Workbench request.",
        )
    denial = _verify_session_visible(
        container=container,
        request=request,
        request_id=request_id,
        session_id=session_id,
    )
    if isinstance(denial, JSONResponse):
        return denial

    try:
        result = container.recording_exporter.export_session(
            session_id=session_id,
            output_root=Path(body.output_root),
            fallback_mode=body.fallback_mode,
        )
    except RecordingExportError:
        return _not_found(container, request_id=request_id)
    except OSError as error:
        envelope = container.responses.error(
            ErrorCode.INTERNAL_ERROR,
            f"Recording export failed: {error.strerror or 'io error'}",
            request_id=request_id,
        )
        return _json_response(status.HTTP_500_INTERNAL_SERVER_ERROR, envelope.model_dump(mode="json"))
    except Exception:
        logger.exception("recording export failed", extra={"session_id": session_id})
        envelope = container.responses.error(
            ErrorCode.INTERNAL_ERROR,
            "Recording export failed unexpectedly.",
            request_id=request_id,
        )
        return _json_response(status.HTTP_500_INTERNAL_SERVER_ERROR, envelope.model_dump(mode="json"))

    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.DISCLOSURE_EVALUATED,
        resource_type="active_capture_recording_export",
        resource_id=session_id,
        policy_decision_id=decision_id,
        success=True,
        details={
            "session_id": session_id,
            "output_dir": str(result.output_dir),
            "keyframe_dir_count": result.keyframe_dir_count,
            "evidence_file_count": result.evidence_file_count,
            "action_count": result.action_count,
            "video_file_count": result.video_file_count,
            "delivery_mode": "local_directory_export",
            "fallback_mode": body.fallback_mode.value,
            "vm_a11y_record_count": result.vm_a11y_record_count,
            "vm_event_log_count": result.vm_event_log_count,
            "vm_click_log_count": result.vm_click_log_count,
            "fallback_warning": result.fallback_warning,
            "purpose": body.purpose,
        },
    )
    response = RecordingExportResponse(
        session_id=result.session_id,
        output_dir=str(result.output_dir),
        keyframe_dir_count=result.keyframe_dir_count,
        evidence_file_count=result.evidence_file_count,
        action_count=result.action_count,
        video_file_count=result.video_file_count,
        vm_a11y_record_count=result.vm_a11y_record_count,
        vm_event_log_count=result.vm_event_log_count,
        vm_click_log_count=result.vm_click_log_count,
        fallback_warning=result.fallback_warning,
    )
    envelope = container.responses.success(response, request_id=request_id, audit_id=audit_id)
    return _json_response(status.HTTP_200_OK, envelope.model_dump(mode="json", exclude_none=True))


def _verify_session_visible(
    *,
    container: DaemonContainer,
    request: Request,
    request_id: str,
    session_id: str,
) -> None | JSONResponse:
    try:
        view = container.active_capture.view_session(session_id)
    except ValueError:
        return _not_found(container, request_id=request_id)
    workspace_id = workspace_id_from_request(request)
    workspace_mismatch = (
        view.session.workspace_id is not None and workspace_id is not None and view.session.workspace_id != workspace_id
    )
    event_id = view.session.primary_event_id
    event = container.repositories.events.get(event_id) if event_id is not None else None
    if event is None or event.status in {EventStatus.DELETED, EventStatus.RESTRICTED} or workspace_mismatch:
        return _not_found(container, request_id=request_id)
    return None


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
    resource_id: str,
    reason: str,
    message: str,
) -> JSONResponse:
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.DISCLOSURE_EVALUATED,
        resource_type="active_capture_recording_export",
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
