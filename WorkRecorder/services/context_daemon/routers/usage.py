"""Agent usage event routes."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from packages.contracts import (
    AccessScope,
    AgentUsageEventCreate,
    AgentUsageEventV2Create,
    AuditAction,
    ErrorCode,
    RetrievalCallKind,
    SnapshotKind,
)

from ..dependencies import route_support

router = APIRouter(prefix="/v1/agent-usage-events", tags=["agent-usage-events"])


@router.post("")
def _record_usage(body: AgentUsageEventCreate, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.RECORD_USAGE,
        resource_type="context_bundle",
        resource_id=body.bundle_id,
        reason=body.purpose,
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    bundle = container.repositories.bundles.get(body.bundle_id)
    if bundle is None:
        envelope = container.responses.error(ErrorCode.NOT_FOUND, "Bundle not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    run = container.agent_runs.ensure_run(
        actor=actor,
        requested_run_id=body.agent_run_id or request.headers.get("x-workrecorder-agent-run-id"),
        purpose=body.purpose,
    )
    context_query = container.agent_runs.context_query(
        run=run,
        query_text=f"usage record {body.bundle_id}",
        purpose=body.purpose,
        requested_query_id=request.headers.get("x-workrecorder-context-query-id"),
    )
    usage_body = AgentUsageEventV2Create(
        bundle_id=body.bundle_id,
        agent_run_id=run.agent_run_id,
        agent=body.agent,
        purpose=body.purpose,
        output_ref=body.output_ref,
        citation_ids=body.citation_ids,
        risk_advisory_ids=body.risk_advisory_ids,
        answer_hash=body.answer_hash,
    )
    usage = container.agent_runs.record_usage(run=run, body=usage_body)
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.USAGE_RECORDED,
        resource_type="context_bundle",
        resource_id=body.bundle_id,
        policy_decision_id=decision_id,
        success=True,
    )
    call, snapshot = container.agent_runs.trace_delivery(
        run=run,
        context_query=context_query,
        request_id=request_id,
        kind=RetrievalCallKind.USAGE_RECORD,
        resource_type="agent_usage",
        resource_id=usage.usage_id,
        purpose=body.purpose,
        request_payload=usage_body,
        response_payload=usage,
        snapshot_kind=SnapshotKind.USAGE,
        metadata={"audit_id": audit_id},
    )
    envelope = container.responses.success(
        usage,
        request_id=request_id,
        audit_id=audit_id,
        agent_run_id=run.agent_run_id,
        context_query_id=context_query.context_query_id,
        retrieval_call_id=call.retrieval_call_id,
        snapshot_id=snapshot.snapshot_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))
