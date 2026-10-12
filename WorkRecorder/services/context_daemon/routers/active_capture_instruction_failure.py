"""Trusted native capture-instruction failure route."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from packages.contracts import AccessScope, AuditAction, ErrorCode, ReportKeyframeCaptureFailureCommand

from ..dependencies import route_support
from ..safe_metadata import safe_public_payload
from .active_capture_post_commit_barrier import drain_active_capture_keyframe_outbox_before_terminal
from .active_capture_route_guard import ActiveCaptureRouteGuard

router = APIRouter()


@router.post("/{session_id}/capture-instructions/failure")
def _report_capture_instruction_failure(session_id: str, body: dict[str, object], request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.CREATE_EVENT,
        resource_type="active_capture_session",
        resource_id=session_id,
        reason="report active capture keyframe instruction failure",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    guard = ActiveCaptureRouteGuard(
        request=request,
        request_id=request_id,
        container=container,
        actor=actor,
        decision_id=decision_id,
    )
    secret_denial = guard.require_trusted_writer(
        session_id=session_id,
        reason="capture_instruction_failure_secret_missing",
        message="Capture instruction failure reports require the local install secret",
    )
    if secret_denial is not None:
        return secret_denial
    native_denial = guard.require_native_capture_authority(
        session_id=session_id,
        reason="capture_instruction_failure_native_secret_missing",
        message="Capture instruction failure reports require trusted local native capture authority",
    )
    if native_denial is not None:
        return native_denial
    try:
        _current_view, denial = guard.require_readable_session(session_id)
        if denial is not None:
            return denial
        command = ReportKeyframeCaptureFailureCommand.model_validate(body)
        barrier = drain_active_capture_keyframe_outbox_before_terminal(
            container=container,
            session_id=session_id,
            candidate_ids=frozenset((command.candidate_id,)),
        )
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
        result = container.active_capture.report_keyframe_capture_failure(
            session_id=session_id,
            command=command,
        )
    except ValidationError as exc:
        return guard.validation_error(message="Invalid capture instruction failure payload", exc=exc)
    except ValueError:
        return guard.domain_error(message="Invalid capture instruction failure request")
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
    envelope = container.responses.success(safe_public_payload(result), request_id=request_id, audit_id=audit_id)
    return JSONResponse(content=envelope.model_dump(mode="json"))
