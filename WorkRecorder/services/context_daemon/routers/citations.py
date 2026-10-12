"""Citation lookup routes for agent answers."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from packages.contracts import AccessScope, AuditAction, ErrorCode, RetrievalCallKind, SnapshotKind

from ..dependencies import route_support

router = APIRouter(prefix="/v1/citations", tags=["citations"])


@router.get("/{citation_id}")
def _resolve_citation(citation_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_TEXT,
        resource_type="citation",
        resource_id=citation_id,
        reason="resolve citation",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    run = container.agent_runs.ensure_run(
        actor=actor,
        requested_run_id=request.headers.get("x-workrecorder-agent-run-id"),
        purpose="citation_resolve",
    )
    context_query = container.agent_runs.context_query(
        run=run,
        query_text=f"resolve citation {citation_id}",
        purpose="citation_resolve",
        requested_query_id=request.headers.get("x-workrecorder-context-query-id"),
    )
    resolved = container.agent_runs.resolve_citation(citation_id=citation_id, actor=actor, run=run)
    if resolved is None:
        envelope = container.responses.error(
            ErrorCode.NOT_FOUND,
            "Citation not found",
            request_id=request_id,
            agent_run_id=run.agent_run_id,
            context_query_id=context_query.context_query_id,
        )
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_READ,
        resource_type="citation",
        resource_id=citation_id,
        policy_decision_id=decision_id,
        success=True,
    )
    call, snapshot = container.agent_runs.trace_delivery(
        run=run,
        context_query=context_query,
        request_id=request_id,
        kind=RetrievalCallKind.CITATION_RESOLVE,
        resource_type="citation",
        resource_id=citation_id,
        purpose="citation_resolve",
        request_payload={"citation_id": citation_id},
        response_payload=resolved,
        snapshot_kind=SnapshotKind.CITATION,
    )
    envelope = container.responses.success(
        resolved,
        request_id=request_id,
        audit_id=audit_id,
        agent_run_id=run.agent_run_id,
        context_query_id=context_query.context_query_id,
        retrieval_call_id=call.retrieval_call_id,
        snapshot_id=snapshot.snapshot_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))
