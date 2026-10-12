"""Completion and cancellation routes for active capture sessions."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from packages.artifacts.vault import ArtifactVaultError, ArtifactVaultTransientError
from packages.contracts import (
    AccessScope,
    ActiveCaptureSessionView,
    ActorRef,
    AuditAction,
    CancelActiveCaptureSessionCommand,
    CompleteActiveCaptureSessionCommand,
    ErrorCode,
    EventInspectSection,
)

from ..auth import DaemonAuth
from ..dependencies import route_support
from ..safe_metadata import safe_public_payload
from .active_capture_access import filter_session_view_for_visible_events, session_read_allowed
from .active_capture_post_commit_barrier import drain_active_capture_keyframe_outbox_before_terminal
from .validation_errors import safe_validation_error_details

if TYPE_CHECKING:
    from ..container import DaemonContainer

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/{session_id}/complete")
def _complete_session(session_id: str, body: dict[str, object], request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.CREATE_EVENT,
        resource_type="active_capture_session",
        resource_id=session_id,
        reason="complete active capture backend session",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    try:
        current_view = container.active_capture.view_session(session_id)
        if not session_read_allowed(container, current_view, actor=actor, request=request):
            envelope = container.responses.error(
                ErrorCode.NOT_FOUND, "Active capture session not found", request_id=request_id
            )
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
        command = CompleteActiveCaptureSessionCommand.model_validate(body)
        if not DaemonAuth().install_secret_matches(request, container):
            audit_id = route_support.audit_action(
                request=request,
                request_id=request_id,
                actor=actor,
                action=AuditAction.CAPTURE_ATTEMPTED,
                resource_type="active_capture_session",
                resource_id=session_id,
                policy_decision_id=decision_id,
                success=False,
                details={"reason": "recording_completion_secret_missing"},
            )
            envelope = container.responses.error(
                ErrorCode.POLICY_DENIED,
                "Recording completion requires the local install secret",
                request_id=request_id,
                audit_id=audit_id,
            )
            return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=envelope.model_dump(mode="json"))
        barrier = drain_active_capture_keyframe_outbox_before_terminal(container=container, session_id=session_id)
        if barrier.blocked:
            envelope = container.responses.error(
                ErrorCode.INTERNAL_ERROR,
                "Recording keyframes are still being processed",
                request_id=request_id,
                details={
                    "retryable": True,
                    "pending_event_count": len(barrier.blocked_event_ids),
                },
            )
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=envelope.model_dump(mode="json")
            )
        view = container.active_capture.complete_session(session_id=session_id, command=command)
        _index_active_capture_safe_projection(container=container, view=view, actor=actor)
    except ValidationError as exc:
        envelope = container.responses.error(
            ErrorCode.VALIDATION_ERROR,
            "Invalid active capture completion payload",
            request_id=request_id,
            details=safe_validation_error_details(exc),
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=envelope.model_dump(mode="json"))
    except ArtifactVaultTransientError:
        envelope = container.responses.error(
            ErrorCode.INTERNAL_ERROR,
            "Recording artifact is temporarily unavailable",
            request_id=request_id,
            details={"retryable": True},
        )
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=envelope.model_dump(mode="json"))
    except (ValueError, ArtifactVaultError):
        envelope = container.responses.error(
            ErrorCode.VALIDATION_ERROR,
            "Invalid active capture completion request",
            request_id=request_id,
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=envelope.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.CAPTURE_ATTEMPTED,
        resource_type="active_capture_session",
        resource_id=session_id,
        policy_decision_id=decision_id,
        success=True,
    )
    envelope = container.responses.success(
        safe_public_payload(
            container.active_capture.to_public_view(filter_session_view_for_visible_events(container, view))
        ),
        request_id=request_id,
        audit_id=audit_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.post("/{session_id}/cancel")
def _cancel_session(session_id: str, body: dict[str, object], request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.CREATE_EVENT,
        resource_type="active_capture_session",
        resource_id=session_id,
        reason="cancel active capture backend session",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    try:
        current_view = container.active_capture.view_session(session_id)
        if not session_read_allowed(container, current_view, actor=actor, request=request):
            envelope = container.responses.error(
                ErrorCode.NOT_FOUND, "Active capture session not found", request_id=request_id
            )
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
        if not DaemonAuth().install_secret_matches(request, container):
            audit_id = route_support.audit_action(
                request=request,
                request_id=request_id,
                actor=actor,
                action=AuditAction.CAPTURE_ATTEMPTED,
                resource_type="active_capture_session",
                resource_id=session_id,
                policy_decision_id=decision_id,
                success=False,
                details={"reason": "recording_cancel_secret_missing"},
            )
            envelope = container.responses.error(
                ErrorCode.POLICY_DENIED,
                "Recording cancellation requires the local install secret",
                request_id=request_id,
                audit_id=audit_id,
            )
            return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=envelope.model_dump(mode="json"))
        command = CancelActiveCaptureSessionCommand.model_validate(body)
        view = container.active_capture.cancel_session(session_id=session_id, reason=command.reason)
    except ValidationError as exc:
        envelope = container.responses.error(
            ErrorCode.VALIDATION_ERROR,
            "Invalid active capture cancel payload",
            request_id=request_id,
            details=safe_validation_error_details(exc),
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=envelope.model_dump(mode="json"))
    except ValueError:
        envelope = container.responses.error(
            ErrorCode.NOT_FOUND, "Active capture session not found", request_id=request_id
        )
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.CAPTURE_ATTEMPTED,
        resource_type="active_capture_session",
        resource_id=session_id,
        policy_decision_id=decision_id,
        success=True,
    )
    envelope = container.responses.success(
        safe_public_payload(
            container.active_capture.to_public_view(filter_session_view_for_visible_events(container, view))
        ),
        request_id=request_id,
        audit_id=audit_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


def _completion_requires_local_install_secret(command: CompleteActiveCaptureSessionCommand) -> bool:
    return command.video is not None or command.recording_timing is not None


def _index_active_capture_safe_projection(
    *,
    container: "DaemonContainer",
    view: ActiveCaptureSessionView,
    actor: ActorRef,
) -> None:
    primary_event_id = view.session.primary_event_id
    if primary_event_id is None:
        return
    try:
        inspect = container.active_capture_inspect.build_for_event(
            event_id=primary_event_id,
            actor=actor,
            purpose="active_capture_completion_index",
            requested_sections=(
                EventInspectSection.ACTIVE_CAPTURE_SUMMARY,
                EventInspectSection.RECORDING_TIMELINE,
                EventInspectSection.SELECTION_TEXT,
                EventInspectSection.VISUAL_OCR_TEXT,
                EventInspectSection.CANONICAL,
                EventInspectSection.CLEAN_PAGE_TEXT,
                EventInspectSection.EVIDENCE_REFS,
            ),
        )
        if inspect is None:
            return
        batch = container.active_capture_inspect.index_projection_for_inspect(inspect, actor=actor)
        if batch is not None:
            container.indexing.index_safe_projection(batch)
    except Exception:
        logger.warning(
            "active capture safe index projection failed",
            extra={"event_id": primary_event_id},
            exc_info=True,
        )
