"""Headless backend routes for active capture sessions."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from packages.artifacts.vault import ArtifactVaultTransientError
from packages.contracts import (
    AccessScope,
    ApplyRecordingControlCommand,
    AttachRecordingSegmentCommand,
    AuditAction,
    CreateActiveCaptureSessionCommand,
    ErrorCode,
    PollKeyframeCaptureInstructionsCommand,
    RecordHumanActionCommand,
    RecordProducerInputBatchCommand,
    RecordProducerInputEventCommand,
    SearchResponse,
    SubmitKeyframeTriggerCommand,
)

from ..dependencies import route_support
from ..safe_metadata import safe_public_payload
from .active_capture_access import (
    filter_session_view_for_visible_events,
    filter_skill_input_for_visible_keyframes,
    filter_storyboard_for_visible_keyframes,
    searched_recording_metadata_read_allowed,
    session_metadata_read_allowed,
    session_read_allowed,
    workspace_id_from_request,
)
from .active_capture_completion import router as completion_router
from .active_capture_export import router as export_router
from .active_capture_instruction_failure import router as instruction_failure_router
from .active_capture_playback import router as playback_router
from .active_capture_route_guard import ActiveCaptureRouteGuard
from .validation_errors import safe_validation_error_details

router = APIRouter(prefix="/v1/active-captures", tags=["active-captures"])
logger = logging.getLogger(__name__)


@router.post("/sessions")
def _create_session(body: dict[str, object], request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.CREATE_EVENT,
        resource_type="active_capture_session",
        reason="create active capture backend session",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    try:
        command = CreateActiveCaptureSessionCommand.model_validate(body)
        workspace_id = workspace_id_from_request(request)
        if command.workspace_id is not None and command.workspace_id != workspace_id:
            envelope = container.responses.error(
                ErrorCode.VALIDATION_ERROR,
                "Active capture workspace must match the request workspace",
                request_id=request_id,
            )
            return JSONResponse(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=envelope.model_dump(mode="json")
            )
        if workspace_id is not None:
            command = command.model_copy(update={"workspace_id": workspace_id})
        view = container.active_capture.create_session(
            command=command,
            actor_id=actor.actor_id,
            actor_display_name=actor.display_name,
        )
    except ValidationError as exc:
        envelope = container.responses.error(
            ErrorCode.VALIDATION_ERROR,
            "Invalid active capture session payload",
            request_id=request_id,
            details=safe_validation_error_details(exc),
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=envelope.model_dump(mode="json"))
    except ValueError:
        envelope = container.responses.error(
            ErrorCode.VALIDATION_ERROR,
            "Invalid active capture session request",
            request_id=request_id,
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=envelope.model_dump(mode="json"))
    except Exception:
        logger.exception("failed to create active capture session", extra={"request_id": request_id})
        audit_id = route_support.audit_action(
            request=request,
            request_id=request_id,
            actor=actor,
            action=AuditAction.CAPTURE_ATTEMPTED,
            resource_type="active_capture_session",
            resource_id=None,
            policy_decision_id=decision_id,
            success=False,
        )
        envelope = container.responses.error(
            ErrorCode.INTERNAL_ERROR,
            "Failed to create active capture session",
            request_id=request_id,
            audit_id=audit_id,
        )
        return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=envelope.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.CAPTURE_ATTEMPTED,
        resource_type="active_capture_session",
        resource_id=view.session.session_id,
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


@router.get("/recordings")
def _list_recordings(
    request: Request,
    limit: int = Query(1000, ge=1, le=5000),
    query: str = Query("", max_length=1000),
) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_TEXT,
        resource_type="active_capture_recording_library",
        reason="list active capture recording sessions",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    cards = container.active_capture.recording_session_cards(
        limit=limit,
        include=lambda session: (
            searched_recording_metadata_read_allowed(
                container,
                session,
                actor=actor,
                request=request,
                query=query,
            )
            if query.strip()
            else session_metadata_read_allowed(
                container,
                session,
                actor=actor,
                request=request,
            )
        ),
    )
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_READ,
        resource_type="active_capture_recording_library",
        resource_id=None,
        policy_decision_id=decision_id,
        success=True,
        details={"result_count": len(cards)},
    )
    response = SearchResponse(events=(), results=cards, degraded=False, backend="active_capture_sessions")
    envelope = container.responses.success(response, request_id=request_id, audit_id=audit_id)
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/{session_id}")
def _get_session(session_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="active_capture_session",
        resource_id=session_id,
        reason="read active capture backend session",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    try:
        view = container.active_capture.view_session(session_id)
    except ValueError:
        envelope = container.responses.error(
            ErrorCode.NOT_FOUND, "Active capture session not found", request_id=request_id
        )
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    if not session_read_allowed(container, view, actor=actor, request=request):
        envelope = container.responses.error(
            ErrorCode.NOT_FOUND, "Active capture session not found", request_id=request_id
        )
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_READ,
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


@router.post("/{session_id}/controls")
def _apply_control(session_id: str, body: dict[str, object], request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.CREATE_EVENT,
        resource_type="active_capture_session",
        resource_id=session_id,
        reason="apply active capture recording control",
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
        reason="recording_control_secret_missing",
        message="Recording controls require the local install secret",
    )
    if secret_denial is not None:
        return secret_denial
    try:
        current_view = container.active_capture.view_session(session_id)
        if not session_read_allowed(container, current_view, actor=actor, request=request):
            envelope = container.responses.error(
                ErrorCode.NOT_FOUND, "Active capture session not found", request_id=request_id
            )
            return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
        command = ApplyRecordingControlCommand.model_validate(body)
        view = container.active_capture.apply_recording_control(session_id=session_id, command=command)
    except ValidationError as exc:
        envelope = container.responses.error(
            ErrorCode.VALIDATION_ERROR,
            "Invalid active capture control payload",
            request_id=request_id,
            details=safe_validation_error_details(exc),
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=envelope.model_dump(mode="json"))
    except ValueError:
        envelope = container.responses.error(
            ErrorCode.VALIDATION_ERROR,
            "Invalid active capture control request",
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


@router.post("/{session_id}/segments")
def _attach_segment(session_id: str, body: dict[str, object], request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.CREATE_EVENT,
        resource_type="active_capture_session",
        resource_id=session_id,
        reason="attach active capture recording segment",
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
        reason="recording_segment_secret_missing",
        message="Recording segment updates require the local install secret",
    )
    if secret_denial is not None:
        return secret_denial
    try:
        _current_view, denial = guard.require_readable_session(session_id)
        if denial is not None:
            return denial
        segment = container.active_capture.attach_recording_segment(
            session_id=session_id,
            command=AttachRecordingSegmentCommand.model_validate(body),
        )
    except ValidationError as exc:
        return guard.validation_error(message="Invalid active capture segment payload", exc=exc)
    except ArtifactVaultTransientError:
        envelope = container.responses.error(
            ErrorCode.INTERNAL_ERROR,
            "Recording segment artifact is temporarily unavailable",
            request_id=request_id,
            details={"retryable": True},
        )
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=envelope.model_dump(mode="json"))
    except ValueError:
        return guard.domain_error(message="Invalid active capture segment request")
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
        safe_public_payload(container.active_capture.recording_projector.to_public_recording_segment(segment)),
        request_id=request_id,
        audit_id=audit_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/{session_id}/segments")
def _get_segments(session_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="active_capture_session",
        resource_id=session_id,
        reason="read active capture recording segment manifest",
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
        manifest = container.active_capture.segment_manifest_for_session(session_id)
    except ValueError:
        envelope = container.responses.error(
            ErrorCode.NOT_FOUND, "Active capture session not found", request_id=request_id
        )
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_READ,
        resource_type="active_capture_session",
        resource_id=session_id,
        policy_decision_id=decision_id,
        success=True,
    )
    envelope = container.responses.success(
        safe_public_payload(container.active_capture.recording_projector.to_public_segment_manifest(manifest)),
        request_id=request_id,
        audit_id=audit_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.post("/{session_id}/triggers")
def _submit_trigger(session_id: str, body: dict[str, object], request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.CREATE_EVENT,
        resource_type="active_capture_session",
        resource_id=session_id,
        reason="submit active capture keyframe trigger",
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
        reason="keyframe_trigger_secret_missing",
        message="Keyframe trigger submission requires the local install secret",
    )
    if secret_denial is not None:
        return secret_denial
    try:
        _current_view, denial = guard.require_readable_session(session_id)
        if denial is not None:
            return denial
        candidate = container.active_capture.submit_keyframe_trigger(
            session_id=session_id,
            command=SubmitKeyframeTriggerCommand.model_validate(body),
        )
    except ValidationError as exc:
        return guard.validation_error(message="Invalid active capture trigger payload", exc=exc)
    except ValueError:
        return guard.domain_error(message="Invalid active capture trigger request")
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
    envelope = container.responses.success(safe_public_payload(candidate), request_id=request_id, audit_id=audit_id)
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.post("/{session_id}/actions")
def _record_action(session_id: str, body: dict[str, object], request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.CREATE_EVENT,
        resource_type="active_capture_session",
        resource_id=session_id,
        reason="record active capture human action",
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
        reason="human_action_secret_missing",
        message="Human action trace updates require the local install secret",
    )
    if secret_denial is not None:
        return secret_denial
    try:
        _current_view, denial = guard.require_readable_session(session_id)
        if denial is not None:
            return denial
        action = container.active_capture.record_human_action(
            session_id=session_id,
            command=RecordHumanActionCommand.model_validate(body),
        )
    except ValidationError as exc:
        return guard.validation_error(message="Invalid active capture human action payload", exc=exc)
    except ValueError:
        return guard.domain_error(message="Invalid active capture human action request")
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
    envelope = container.responses.success(safe_public_payload(action), request_id=request_id, audit_id=audit_id)
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.post("/{session_id}/producer-events")
def _record_producer_events(session_id: str, body: dict[str, object], request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.CREATE_EVENT,
        resource_type="active_capture_session",
        resource_id=session_id,
        reason="record active capture native producer input events",
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
        reason="producer_event_secret_missing",
        message="Producer input events require the local install secret",
    )
    if secret_denial is not None:
        return secret_denial
    try:
        _current_view, denial = guard.require_readable_session(session_id)
        if denial is not None:
            return denial
        if "events" in body:
            command = RecordProducerInputBatchCommand.model_validate(body)
        else:
            command = RecordProducerInputBatchCommand(events=(RecordProducerInputEventCommand.model_validate(body),))
        result = container.active_capture.record_producer_events(session_id=session_id, command=command)
    except ValidationError as exc:
        return guard.validation_error(message="Invalid active capture producer event payload", exc=exc)
    except ValueError:
        return guard.domain_error(message="Invalid active capture producer event request")
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


@router.post("/{session_id}/capture-instructions/pending")
def _poll_pending_capture_instructions(session_id: str, body: dict[str, object], request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.CREATE_EVENT,
        resource_type="active_capture_session",
        resource_id=session_id,
        reason="poll active capture settled keyframe instructions",
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
        reason="capture_instruction_poll_secret_missing",
        message="Pending capture instruction polling requires the local install secret",
    )
    if secret_denial is not None:
        return secret_denial
    native_denial = guard.require_native_capture_authority(
        session_id=session_id,
        reason="capture_instruction_poll_native_secret_missing",
        message="Pending capture instruction polling requires trusted local native capture authority",
    )
    if native_denial is not None:
        return native_denial
    try:
        _current_view, denial = guard.require_readable_session(session_id)
        if denial is not None:
            return denial
        result = container.active_capture.poll_pending_capture_instructions(
            session_id=session_id,
            command=PollKeyframeCaptureInstructionsCommand.model_validate(body),
        )
    except ValidationError as exc:
        return guard.validation_error(message="Invalid pending capture instruction poll payload", exc=exc)
    except ValueError:
        return guard.domain_error(message="Invalid pending capture instruction poll request")
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


@router.get("/{session_id}/vm-a11y/latest")
def _get_latest_vm_a11y_probe(session_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="active_capture_session",
        resource_id=session_id,
        reason="read latest VM accessibility probe sample",
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
    try:
        _current_view, denial = guard.require_readable_session(session_id)
        if denial is not None:
            return denial
        result = container.active_capture.vm_a11y_probe_snapshot_for_session(session_id)
    except ValueError:
        return guard.not_found()
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_READ,
        resource_type="active_capture_session",
        resource_id=session_id,
        policy_decision_id=decision_id,
        success=True,
    )
    envelope = container.responses.success(safe_public_payload(result), request_id=request_id, audit_id=audit_id)
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/{session_id}/storyboard")
def _get_storyboard(session_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="active_capture_session",
        resource_id=session_id,
        reason="read active capture storyboard",
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
        visible_view = filter_session_view_for_visible_events(container, current_view)
        storyboard = filter_storyboard_for_visible_keyframes(
            container.active_capture.storyboard_for_session(session_id),
            session_has_keyframes=bool(current_view.keyframes),
            visible_keyframe_ids={keyframe.keyframe_id for keyframe in visible_view.keyframes},
        )
    except ValueError:
        envelope = container.responses.error(
            ErrorCode.NOT_FOUND, "Active capture session not found", request_id=request_id
        )
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_READ,
        resource_type="active_capture_session",
        resource_id=session_id,
        policy_decision_id=decision_id,
        success=True,
    )
    envelope = container.responses.success(safe_public_payload(storyboard), request_id=request_id, audit_id=audit_id)
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/{session_id}/skill-distillation-input")
def _get_skill_distillation_input(session_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="active_capture_session",
        resource_id=session_id,
        reason="read safe active capture skill distillation input",
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
        visible_view = filter_session_view_for_visible_events(container, current_view)
        projection = filter_skill_input_for_visible_keyframes(
            container,
            container.active_capture.skill_distillation_input_for_session(session_id),
            session_has_keyframes=bool(current_view.keyframes),
            visible_keyframes=visible_view.keyframes,
        )
    except ValueError:
        envelope = container.responses.error(
            ErrorCode.NOT_FOUND, "Active capture session not found", request_id=request_id
        )
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_READ,
        resource_type="active_capture_session",
        resource_id=session_id,
        policy_decision_id=decision_id,
        success=True,
    )
    envelope = container.responses.success(safe_public_payload(projection), request_id=request_id, audit_id=audit_id)
    return JSONResponse(content=envelope.model_dump(mode="json"))


router.include_router(playback_router)
router.include_router(export_router)
router.include_router(completion_router)
router.include_router(instruction_failure_router)
