"""Artifact metadata and policy-aware content routes."""

from __future__ import annotations

import base64

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

from packages.artifacts.public_projection import ArtifactPublicProjector
from packages.contracts import AccessScope, ApiError, AuditAction, ErrorCode, RetrievalCallKind, SnapshotKind

from ..dependencies import route_support
from ..safe_metadata import safe_public_payload

router = APIRouter(prefix="/v1/artifacts", tags=["artifacts"])
_artifact_projector = ArtifactPublicProjector()


@router.get("/{artifact_id}")
def _get_artifact(artifact_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="artifact",
        resource_id=artifact_id,
        reason="read artifact metadata",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    artifact = container.artifacts.get_metadata(artifact_id)
    if artifact is None:
        envelope = container.responses.error(ErrorCode.NOT_FOUND, "Artifact not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    event = container.repositories.events.get(artifact.event_id)
    os_window_context = _is_os_window_event(event)
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.ARTIFACT_READ,
        resource_type="artifact",
        resource_id=artifact_id,
        policy_decision_id=decision_id,
        success=True,
    )
    envelope = container.responses.success(
        safe_public_payload(_artifact_projector.project(artifact), _os_window_context=os_window_context),
        request_id=request_id,
        audit_id=audit_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/{artifact_id}/content")
def _get_artifact_content(
    artifact_id: str,
    request: Request,
    event_id: str = Query(..., min_length=1),
    purpose: str = Query(..., min_length=1, max_length=160),
    agent_run_id: str | None = Query(default=None, min_length=1, max_length=160),
) -> JSONResponse:
    return _artifact_content(
        artifact_id,
        request,
        AccessScope.READ_TEXT,
        event_id=event_id,
        purpose=purpose,
        agent_run_id=agent_run_id,
    )


@router.get("/{artifact_id}/raw")
def _get_raw_artifact(
    artifact_id: str,
    request: Request,
    event_id: str = Query(..., min_length=1),
    purpose: str = Query(..., min_length=1, max_length=160),
    agent_run_id: str | None = Query(default=None, min_length=1, max_length=160),
) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_RAW_ARTIFACT,
        resource_type="artifact",
        resource_id=artifact_id,
        reason=purpose,
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    artifact = container.artifacts.get_metadata(artifact_id)
    if artifact is None:
        envelope = container.responses.error(ErrorCode.NOT_FOUND, "Artifact not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    requested_run_id = agent_run_id or request.headers.get("x-workrecorder-agent-run-id")
    if not requested_run_id:
        audit_id = route_support.audit_action(
            request=request,
            request_id=request_id,
            actor=actor,
            action=AuditAction.DISCLOSURE_EVALUATED,
            resource_type="artifact",
            resource_id=artifact_id,
            policy_decision_id=decision_id,
            success=False,
            details={
                "artifact_id": artifact_id,
                "event_id": event_id,
                "purpose": purpose,
                "reason": "missing agent run",
            },
        )
        envelope = container.responses.error(
            ErrorCode.POLICY_DENIED,
            "Raw artifact requires an explicit agent run.",
            request_id=request_id,
            audit_id=audit_id,
        )
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=envelope.model_dump(mode="json"))
    run = container.agent_runs.ensure_run(
        actor=actor,
        requested_run_id=requested_run_id,
        purpose=purpose,
    )
    context_query = container.agent_runs.context_query(
        run=run,
        query_text=f"raw artifact {artifact_id}",
        purpose=purpose,
        requested_query_id=request.headers.get("x-workrecorder-context-query-id"),
    )
    if not container.repositories.agent_run_traces.has_successful_screenshot_ref_delivery(
        agent_run_id=run.agent_run_id, artifact_id=artifact_id, event_id=event_id
    ):
        audit_id = route_support.audit_action(
            request=request,
            request_id=request_id,
            actor=actor,
            action=AuditAction.DISCLOSURE_EVALUATED,
            resource_type="artifact",
            resource_id=artifact_id,
            policy_decision_id=decision_id,
            success=False,
            details={
                "artifact_id": artifact_id,
                "event_id": event_id,
                "purpose": purpose,
                "agent_run_id": run.agent_run_id,
                "reason": "raw artifact was not previously delivered as a ref in this agent run",
            },
        )
        call, snapshot = container.agent_runs.trace_delivery(
            run=run,
            context_query=context_query,
            request_id=request_id,
            kind=RetrievalCallKind.ARTIFACT_RAW,
            resource_type="artifact",
            resource_id=artifact_id,
            purpose=purpose,
            request_payload={"artifact_id": artifact_id, "event_id": event_id, "purpose": purpose},
            response_payload={
                "error": {
                    "code": ErrorCode.POLICY_DENIED.value,
                    "message": "Raw artifact requires a prior same-run screenshot_ref disclosure.",
                },
            },
            snapshot_kind=SnapshotKind.ARTIFACT_REF,
            metadata={"audit_id": audit_id, "raw_bytes_omitted": True},
            call_status="denied",
        )
        envelope = container.responses.error(
            ErrorCode.POLICY_DENIED,
            "Raw artifact requires a prior same-run screenshot_ref disclosure.",
            request_id=request_id,
            audit_id=audit_id,
            agent_run_id=run.agent_run_id,
            context_query_id=context_query.context_query_id,
            retrieval_call_id=call.retrieval_call_id,
            snapshot_id=snapshot.snapshot_id,
        )
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=envelope.model_dump(mode="json"))
    result = container.disclosure.raw_artifact(
        artifact=artifact,
        actor=actor,
        purpose=purpose,
        agent_run_id=run.agent_run_id,
        event_id=event_id,
    )
    if not isinstance(result, ApiError):
        audit_id = route_support.audit_action(
            request=request,
            request_id=request_id,
            actor=actor,
            action=AuditAction.DISCLOSURE_EVALUATED,
            resource_type="artifact",
            resource_id=artifact_id,
            policy_decision_id=decision_id,
            success=True,
            details=container.disclosure.decision_audit_details(result.disclosure_decision),
        )
        call, snapshot = container.agent_runs.trace_delivery(
            run=run,
            context_query=context_query,
            request_id=request_id,
            kind=RetrievalCallKind.ARTIFACT_RAW,
            resource_type="artifact",
            resource_id=artifact_id,
            purpose=purpose,
            request_payload={"artifact_id": artifact_id, "event_id": event_id, "purpose": purpose},
            response_payload=result,
            snapshot_kind=SnapshotKind.ARTIFACT_REF,
            metadata={"audit_id": audit_id, "raw_bytes_omitted": True},
        )
        envelope = container.responses.success(
            result,
            request_id=request_id,
            audit_id=audit_id,
            agent_run_id=run.agent_run_id,
            context_query_id=context_query.context_query_id,
            retrieval_call_id=call.retrieval_call_id,
            snapshot_id=snapshot.snapshot_id,
        )
        return JSONResponse(content=envelope.model_dump(mode="json"))
    error = result
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.DISCLOSURE_EVALUATED,
        resource_type="artifact",
        resource_id=artifact_id,
        policy_decision_id=decision_id,
        success=False,
        details={
            "artifact_id": artifact_id,
            "event_id": event_id,
            "purpose": purpose,
            "agent_run_id": run.agent_run_id,
            **error.details,
        },
    )
    envelope = container.responses.error(
        error.code,
        error.message,
        request_id=request_id,
        audit_id=audit_id,
        details=error.details,
    )
    call, snapshot = container.agent_runs.trace_delivery(
        run=run,
        context_query=context_query,
        request_id=request_id,
        kind=RetrievalCallKind.ARTIFACT_RAW,
        resource_type="artifact",
        resource_id=artifact_id,
        purpose=purpose,
        request_payload={"artifact_id": artifact_id, "event_id": event_id, "purpose": purpose},
        response_payload=envelope,
        snapshot_kind=SnapshotKind.ARTIFACT_REF,
        metadata={"audit_id": audit_id, "raw_bytes_omitted": True},
        call_status="denied",
    )
    envelope = envelope.model_copy(
        update={
            "agent_run_id": run.agent_run_id,
            "context_query_id": context_query.context_query_id,
            "retrieval_call_id": call.retrieval_call_id,
            "snapshot_id": snapshot.snapshot_id,
        }
    )
    status_code = status.HTTP_403_FORBIDDEN if error.code == ErrorCode.POLICY_DENIED else status.HTTP_404_NOT_FOUND
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


@router.get("/{artifact_id}/verify")
def _verify_artifact(artifact_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="artifact",
        resource_id=artifact_id,
        reason="verify artifact integrity",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    artifact = container.artifacts.get_metadata(artifact_id)
    if artifact is None:
        envelope = container.responses.error(ErrorCode.NOT_FOUND, "Artifact not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    result = container.artifacts.verify_integrity(artifact)
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.ARTIFACT_READ,
        resource_type="artifact",
        resource_id=artifact_id,
        policy_decision_id=decision_id,
        success=isinstance(result, dict) and bool(result.get("ok")),
        details={"operation": "verify_integrity"},
    )
    if isinstance(result, dict):
        envelope = container.responses.success(
            safe_public_payload(_artifact_projector.project_integrity(artifact, result)),
            request_id=request_id,
            audit_id=audit_id,
        )
        return JSONResponse(content=envelope.model_dump(mode="json"))
    envelope = container.responses.error(
        result.code,
        result.message,
        request_id=request_id,
        audit_id=audit_id,
        details=result.details,
    )
    status_code = status.HTTP_404_NOT_FOUND if result.code == ErrorCode.NOT_FOUND else status.HTTP_501_NOT_IMPLEMENTED
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


@router.get("/{artifact_id}/thumbnail")
def _get_artifact_thumbnail(
    artifact_id: str,
    request: Request,
    event_id: str = Query(..., max_length=160),
) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_THUMBNAIL,
        resource_type="artifact",
        resource_id=artifact_id,
        reason="read artifact thumbnail",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    artifact = container.artifacts.get_metadata(artifact_id)
    if artifact is None:
        envelope = container.responses.error(ErrorCode.NOT_FOUND, "Artifact not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    if event_id != artifact.event_id:
        audit_id = route_support.audit_action(
            request=request,
            request_id=request_id,
            actor=actor,
            action=AuditAction.ARTIFACT_READ,
            resource_type="artifact",
            resource_id=artifact_id,
            policy_decision_id=decision_id,
            success=False,
            details={"operation": "thumbnail", "error": "event_binding_required"},
        )
        envelope = container.responses.error(
            ErrorCode.POLICY_DENIED,
            "Thumbnail reads must be bound to the owning event.",
            request_id=request_id,
            audit_id=audit_id,
            details={"operation": "thumbnail"},
        )
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=envelope.model_dump(mode="json"))
    content = container.artifacts.read_thumbnail_content(artifact=artifact, actor=actor)
    if isinstance(content, ApiError):
        audit_id = route_support.audit_action(
            request=request,
            request_id=request_id,
            actor=actor,
            action=AuditAction.ARTIFACT_READ,
            resource_type="artifact",
            resource_id=artifact_id,
            policy_decision_id=decision_id,
            success=False,
            details={"operation": "thumbnail", "error": content.code.value},
        )
        envelope = container.responses.error(
            content.code,
            content.message,
            request_id=request_id,
            audit_id=audit_id,
            details=content.details,
        )
        status_code = (
            status.HTTP_403_FORBIDDEN if content.code == ErrorCode.POLICY_DENIED else status.HTTP_404_NOT_FOUND
        )
        if content.code == ErrorCode.NOT_IMPLEMENTED:
            status_code = status.HTTP_501_NOT_IMPLEMENTED
        return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.ARTIFACT_READ,
        resource_type="artifact",
        resource_id=artifact_id,
        policy_decision_id=decision_id,
        success=True,
        details={"operation": "thumbnail", "byte_size": len(content)},
    )
    payload = {
        "artifact_id": artifact.artifact_id,
        "content_type": "image/png",
        "data_base64": base64.b64encode(content).decode("ascii"),
        "byte_size": len(content),
    }
    envelope = container.responses.success(payload, request_id=request_id, audit_id=audit_id)
    return JSONResponse(content=envelope.model_dump(mode="json"))


def _is_os_window_event(event: object | None) -> bool:
    if event is None:
        return False
    event_type = getattr(event, "event_type", None)
    if getattr(event_type, "value", event_type) == "screen.window.captured":
        return True
    trigger = getattr(event, "trigger", None)
    strategy = getattr(trigger, "capture_strategy", None)
    return getattr(strategy, "value", strategy) == "os_window"


def _artifact_content(
    artifact_id: str,
    request: Request,
    scope: AccessScope,
    *,
    event_id: str,
    purpose: str,
    agent_run_id: str | None,
) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=scope,
        resource_type="artifact",
        resource_id=artifact_id,
        reason="read artifact content",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    artifact = container.artifacts.get_metadata(artifact_id)
    if artifact is None:
        envelope = container.responses.error(ErrorCode.NOT_FOUND, "Artifact not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    run = container.agent_runs.ensure_run(
        actor=actor,
        requested_run_id=agent_run_id or request.headers.get("x-workrecorder-agent-run-id"),
        purpose=purpose,
    )
    context_query = container.agent_runs.context_query(
        run=run,
        query_text=f"artifact content {artifact_id}",
        purpose=purpose,
        requested_query_id=request.headers.get("x-workrecorder-context-query-id"),
    )
    disclosure_decision, content = container.disclosure.text_content(
        artifact=artifact,
        actor=actor,
        purpose=purpose,
        agent_run_id=run.agent_run_id,
        event_id=event_id,
    )
    if isinstance(content, ApiError):
        audit_id = route_support.audit_action(
            request=request,
            request_id=request_id,
            actor=actor,
            action=AuditAction.DISCLOSURE_EVALUATED,
            resource_type="artifact",
            resource_id=artifact_id,
            policy_decision_id=decision_id,
            success=False,
            details=container.disclosure.decision_audit_details(disclosure_decision),
        )
        envelope = container.responses.error(
            content.code,
            content.message,
            request_id=request_id,
            audit_id=audit_id,
            details=content.details,
        )
        call, snapshot = container.agent_runs.trace_delivery(
            run=run,
            context_query=context_query,
            request_id=request_id,
            kind=RetrievalCallKind.ARTIFACT_PREVIEW,
            resource_type="artifact",
            resource_id=artifact_id,
            purpose=purpose,
            request_payload={"artifact_id": artifact_id, "event_id": event_id, "purpose": purpose},
            response_payload=envelope,
            snapshot_kind=SnapshotKind.ARTIFACT_TEXT,
            metadata={"audit_id": audit_id},
            call_status="denied",
        )
        envelope = envelope.model_copy(
            update={
                "agent_run_id": run.agent_run_id,
                "context_query_id": context_query.context_query_id,
                "retrieval_call_id": call.retrieval_call_id,
                "snapshot_id": snapshot.snapshot_id,
            }
        )
        if content.code == ErrorCode.POLICY_DENIED:
            status_code = status.HTTP_403_FORBIDDEN
        elif content.code == ErrorCode.NOT_FOUND:
            status_code = status.HTTP_404_NOT_FOUND
        elif content.code == ErrorCode.INTERNAL_ERROR:
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
        else:
            status_code = status.HTTP_501_NOT_IMPLEMENTED
        return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.DISCLOSURE_EVALUATED,
        resource_type="artifact",
        resource_id=artifact_id,
        policy_decision_id=decision_id,
        success=True,
        details=container.disclosure.decision_audit_details(disclosure_decision),
    )
    response_payload = {
        "artifact_id": artifact.artifact_id,
        "content_type": artifact.content_type,
        "text": content,
        "disclosure_decision": disclosure_decision,
    }
    call, snapshot = container.agent_runs.trace_delivery(
        run=run,
        context_query=context_query,
        request_id=request_id,
        kind=RetrievalCallKind.ARTIFACT_PREVIEW,
        resource_type="artifact",
        resource_id=artifact_id,
        purpose=purpose,
        request_payload={"artifact_id": artifact_id, "event_id": event_id, "purpose": purpose},
        response_payload=response_payload,
        snapshot_kind=SnapshotKind.ARTIFACT_TEXT,
        metadata={"audit_id": audit_id},
    )
    envelope = container.responses.success(
        response_payload,
        request_id=request_id,
        audit_id=audit_id,
        agent_run_id=run.agent_run_id,
        context_query_id=context_query.context_query_id,
        retrieval_call_id=call.retrieval_call_id,
        snapshot_id=snapshot.snapshot_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


def _unavailable_artifact_content(artifact_id: str, request: Request, scope: AccessScope) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=scope,
        resource_type="artifact",
        resource_id=artifact_id,
        reason="read unavailable artifact view",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    envelope = container.responses.error(
        ErrorCode.NOT_IMPLEMENTED,
        "This artifact view requires an explicit content endpoint.",
        request_id=request_id,
        details={"artifact_id": artifact_id, "scope": scope.value},
    )
    return JSONResponse(status_code=status.HTTP_501_NOT_IMPLEMENTED, content=envelope.model_dump(mode="json"))
