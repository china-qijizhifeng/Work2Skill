"""Agent run ledger routes."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

from packages.contracts import (
    AccessScope,
    AgentRunBeginRequest,
    AgentRunOrigin,
    AgentRunStatus,
    AuditAction,
    ErrorCode,
)

from ..dependencies import route_support
from ..safe_metadata import safe_public_payload

router = APIRouter(prefix="/v1/agent-runs", tags=["agent-runs"])


@router.post("")
def _begin_run(body: AgentRunBeginRequest, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="agent_run",
        reason=body.purpose,
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    run = container.agent_runs.begin_run(actor=actor, body=body)
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_READ,
        resource_type="agent_run",
        resource_id=run.agent_run_id,
        policy_decision_id=decision_id,
        success=True,
        details={"operation": "begin", "origin": body.origin.value},
    )
    envelope = container.responses.success(
        safe_public_payload(run), request_id=request_id, audit_id=audit_id, agent_run_id=run.agent_run_id
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/current")
def _current_run(request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="agent_run",
        reason="read current agent run",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    requested = request.headers.get("x-workrecorder-agent-run-id")
    run = container.agent_runs.ensure_run(
        actor=actor,
        requested_run_id=requested,
        purpose="agent_current",
        origin=AgentRunOrigin.DAEMON_IMPLICIT,
    )
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_READ,
        resource_type="agent_run",
        resource_id=run.agent_run_id,
        policy_decision_id=decision_id,
        success=True,
        details={"operation": "current"},
    )
    envelope = container.responses.success(
        safe_public_payload(run), request_id=request_id, audit_id=audit_id, agent_run_id=run.agent_run_id
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.post("/{agent_run_id}/end")
def _end_run(
    agent_run_id: str,
    request: Request,
    run_status: AgentRunStatus = Query(AgentRunStatus.COMPLETED, alias="status"),
) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.RECORD_USAGE,
        resource_type="agent_run",
        resource_id=agent_run_id,
        reason="end agent run",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    run = container.agent_runs.end_run(agent_run_id=agent_run_id, actor=actor, status=run_status)
    if run is None:
        envelope = container.responses.error(ErrorCode.NOT_FOUND, "Agent run not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.USAGE_RECORDED,
        resource_type="agent_run",
        resource_id=agent_run_id,
        policy_decision_id=decision_id,
        success=True,
        details={"operation": "end", "status": run_status.value},
    )
    envelope = container.responses.success(
        safe_public_payload(run), request_id=request_id, audit_id=audit_id, agent_run_id=agent_run_id
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/{agent_run_id}/replay")
def _replay_run(agent_run_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_TEXT,
        resource_type="agent_run_replay",
        resource_id=agent_run_id,
        reason="replay agent context usage",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    replay = container.agent_runs.replay(agent_run_id, actor=actor)
    if replay is None:
        envelope = container.responses.error(ErrorCode.NOT_FOUND, "Agent run not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_READ,
        resource_type="agent_run_replay",
        resource_id=agent_run_id,
        policy_decision_id=decision_id,
        success=True,
    )
    envelope = container.responses.success(
        safe_public_payload(replay), request_id=request_id, audit_id=audit_id, agent_run_id=agent_run_id
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))
