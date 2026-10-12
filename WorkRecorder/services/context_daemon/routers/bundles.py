"""Context bundle routes for consumer agents."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

from packages.contracts import (
    AccessScope,
    AuditAction,
    BundleRequest,
    ContextBundle,
    ErrorCode,
    RetrievalCallKind,
    SnapshotKind,
)

from ..dependencies import route_support
from ..safe_metadata import safe_public_payload

router = APIRouter(prefix="/v1/context-bundles", tags=["context-bundles"])


@router.post("")
def _create_bundle(body: BundleRequest, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.CREATE_BUNDLE,
        resource_type="context_bundle",
        reason=body.purpose,
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    text_auth = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_TEXT,
        resource_type="context_bundle",
        reason=f"build context bundle: {body.purpose}",
    )
    if not isinstance(text_auth, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=text_auth.model_dump(mode="json"))
    run = container.agent_runs.ensure_run(
        actor=actor,
        requested_run_id=request.headers.get("x-workrecorder-agent-run-id"),
        purpose=body.purpose,
        user_question=body.query,
    )
    context_query = container.agent_runs.context_query(
        run=run,
        query_text=body.query,
        purpose=body.purpose,
        requested_query_id=request.headers.get("x-workrecorder-context-query-id"),
        metadata={"operation": "bundle_create"},
    )
    bundle = container.agent_runs.attach_bundle_citations(run=run, bundle=container.bundles.build(body))
    saved = container.bundles.save(bundle.model_copy(update={"context_query_id": context_query.context_query_id}))
    safe_saved = safe_public_payload(saved)
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.BUNDLE_CREATED,
        resource_type="context_bundle",
        resource_id=saved.bundle_id,
        policy_decision_id=decision_id,
        success=True,
    )
    call, snapshot = container.agent_runs.trace_delivery(
        run=run,
        context_query=context_query,
        request_id=request_id,
        kind=RetrievalCallKind.BUNDLE_CREATE,
        resource_type="context_bundle",
        resource_id=saved.bundle_id,
        purpose=body.purpose,
        request_payload=body,
        response_payload=safe_saved,
        snapshot_kind=SnapshotKind.CONTEXT_BUNDLE,
        metadata={"audit_id": audit_id},
    )
    envelope = container.responses.success(
        safe_saved,
        request_id=request_id,
        audit_id=audit_id,
        agent_run_id=run.agent_run_id,
        context_query_id=context_query.context_query_id,
        retrieval_call_id=call.retrieval_call_id,
        snapshot_id=snapshot.snapshot_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/{bundle_id}")
def _get_bundle(bundle_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_TEXT,
        resource_type="context_bundle",
        resource_id=bundle_id,
        reason="read context bundle",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    bundle = _visible_bundle(container, container.repositories.bundles.get(bundle_id))
    if bundle is None:
        envelope = container.responses.error(ErrorCode.NOT_FOUND, "Bundle not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.BUNDLE_READ,
        resource_type="context_bundle",
        resource_id=bundle_id,
        policy_decision_id=decision_id,
        success=True,
    )
    run = container.agent_runs.ensure_run(
        actor=actor,
        requested_run_id=request.headers.get("x-workrecorder-agent-run-id"),
        purpose="bundle_read",
    )
    context_query = container.agent_runs.context_query(
        run=run,
        query_text=f"bundle show {bundle_id}",
        purpose="bundle_read",
        requested_query_id=request.headers.get("x-workrecorder-context-query-id"),
    )
    call, snapshot = container.agent_runs.trace_delivery(
        run=run,
        context_query=context_query,
        request_id=request_id,
        kind=RetrievalCallKind.BUNDLE_READ,
        resource_type="context_bundle",
        resource_id=bundle_id,
        purpose="bundle_read",
        request_payload={"bundle_id": bundle_id},
        response_payload=safe_public_payload(bundle),
        snapshot_kind=SnapshotKind.CONTEXT_BUNDLE,
        metadata={"audit_id": audit_id},
    )
    envelope = container.responses.success(
        safe_public_payload(bundle),
        request_id=request_id,
        audit_id=audit_id,
        agent_run_id=run.agent_run_id,
        context_query_id=context_query.context_query_id,
        retrieval_call_id=call.retrieval_call_id,
        snapshot_id=snapshot.snapshot_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/{bundle_id}/export")
def _export_bundle(
    bundle_id: str,
    request: Request,
    format: str = Query("markdown", pattern="^(markdown|json)$"),
) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_TEXT,
        resource_type="context_bundle",
        resource_id=bundle_id,
        reason="export context bundle",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    bundle = _visible_bundle(container, container.repositories.bundles.get(bundle_id))
    if bundle is None:
        envelope = container.responses.error(ErrorCode.NOT_FOUND, "Bundle not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    if format == "json":
        exported: object = bundle.model_dump(mode="json")
    else:
        lines = [f"# WorkRecorder Context Bundle {bundle.bundle_id}", "", f"Purpose: {bundle.purpose}", ""]
        for index, item in enumerate(bundle.items, start=1):
            lines.append(f"{index}. {item.claim}")
            lines.append(f"   - event_id: {item.event_id}")
        exported = "\n".join(lines).strip() + "\n"
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.BUNDLE_READ,
        resource_type="context_bundle",
        resource_id=bundle_id,
        policy_decision_id=decision_id,
        success=True,
        details={"operation": "export", "format": format},
    )
    run = container.agent_runs.ensure_run(
        actor=actor,
        requested_run_id=request.headers.get("x-workrecorder-agent-run-id"),
        purpose="bundle_export",
    )
    context_query = container.agent_runs.context_query(
        run=run,
        query_text=f"bundle export {bundle_id}",
        purpose="bundle_export",
        requested_query_id=request.headers.get("x-workrecorder-context-query-id"),
    )
    response_payload = safe_public_payload({"bundle_id": bundle_id, "format": format, "content": exported})
    call, snapshot = container.agent_runs.trace_delivery(
        run=run,
        context_query=context_query,
        request_id=request_id,
        kind=RetrievalCallKind.BUNDLE_EXPORT,
        resource_type="context_bundle",
        resource_id=bundle_id,
        purpose="bundle_export",
        request_payload={"bundle_id": bundle_id, "format": format},
        response_payload=response_payload,
        snapshot_kind=SnapshotKind.CONTEXT_BUNDLE,
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


def _visible_bundle(container: object, bundle: ContextBundle | None) -> ContextBundle | None:
    if bundle is None:
        return None
    repositories = getattr(container, "repositories")
    visible_items = tuple(item for item in bundle.items if repositories.events.get(item.event_id) is not None)
    return bundle.model_copy(
        update={"items": visible_items, "degraded": bundle.degraded or len(visible_items) < len(bundle.items)}
    )
