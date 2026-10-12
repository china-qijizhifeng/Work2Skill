"""Search routes for agent-facing context retrieval."""

from __future__ import annotations

import hashlib
from datetime import datetime

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

from packages.contracts import (
    AccessScope,
    AuditAction,
    EventStatus,
    EvidenceKind,
    EvidenceSensitivity,
    RetrievalCallKind,
    RetrievalMode,
    SearchFilters,
    SearchQuery,
    SearchSort,
    SnapshotKind,
    SourceType,
    UserFilter,
)

from ..dependencies import route_support
from ..safe_metadata import safe_public_payload

router = APIRouter(prefix="/v1/search", tags=["search"])


@router.get("")
def _search(
    request: Request,
    query: str = Query("", max_length=500),
    mode: RetrievalMode = Query(RetrievalMode.KEYWORD),
    limit: int = Query(20, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=500),
    sort: SearchSort = Query(SearchSort.SCORE),
    explain: bool = Query(False),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    workspace: str | None = Query(default=None, max_length=160),
    app: str | None = Query(default=None, max_length=160),
    domain: str | None = Query(default=None, max_length=255),
    origin: str | None = Query(default=None, max_length=500),
    source: SourceType | None = Query(default=None),
    provider: str | None = Query(default=None, max_length=160),
    event_type: str | None = Query(default=None, max_length=160),
    evidence_kind: EvidenceKind | None = Query(default=None),
    event_status: EventStatus | None = Query(default=None, alias="status"),
    sensitivity: EvidenceSensitivity | None = Query(default=None),
    entity: str | None = Query(default=None, max_length=160),
    project: str | None = Query(default=None, max_length=160),
    user: str | None = Query(default=None, max_length=160),
) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_TEXT,
        resource_type="search",
        reason="search context events",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    run = container.agent_runs.ensure_run(
        actor=actor,
        requested_run_id=request.headers.get("x-workrecorder-agent-run-id"),
        purpose="search",
        user_question=query,
        workspace_id=workspace,
    )
    context_query = container.agent_runs.context_query(
        run=run,
        query_text=query,
        purpose="search",
        requested_query_id=request.headers.get("x-workrecorder-context-query-id"),
        workspace_id=workspace,
        metadata={"mode": mode.value},
    )
    search_query = SearchQuery(
        query=query,
        mode=mode,
        filters=SearchFilters(
            since=since,
            until=until,
            workspace=workspace,
            app=app,
            domain=domain,
            origin=origin,
            source=source,
            provider=provider,
            event_type=event_type,
            evidence_kind=evidence_kind,
            status=event_status,
            sensitivity=sensitivity,
            entity=entity,
            project=project,
            user=UserFilter.from_query(user),
        ),
        limit=limit,
        cursor=cursor,
        sort=sort,
        explain=explain,
    )
    response = container.agent_runs.attach_search_citations(
        run=run,
        response=container.search.search(search_query),
    )
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.SEARCH_PERFORMED,
        resource_type="search",
        resource_id=None,
        policy_decision_id=decision_id,
        success=True,
        details={
            "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "mode": mode.value,
            "backend": response.backend,
            "result_count": len(response.results),
            "degraded": response.degraded,
            "explain": explain,
        },
    )
    call, snapshot = container.agent_runs.trace_delivery(
        run=run,
        context_query=context_query,
        request_id=request_id,
        kind=RetrievalCallKind.SEARCH,
        resource_type="search",
        resource_id=None,
        purpose="search",
        request_payload=search_query,
        response_payload=response,
        snapshot_kind=SnapshotKind.SEARCH_RESULT,
        metadata={"audit_id": audit_id},
    )
    envelope = container.responses.success(
        response,
        request_id=request_id,
        audit_id=audit_id,
        agent_run_id=run.agent_run_id,
        context_query_id=context_query.context_query_id,
        retrieval_call_id=call.retrieval_call_id,
        snapshot_id=snapshot.snapshot_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/facets")
def _facets(
    request: Request,
    query: str = Query("", max_length=500),
    limit: int = Query(100, ge=1, le=500),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    workspace: str | None = Query(default=None, max_length=160),
    app: str | None = Query(default=None, max_length=160),
    domain: str | None = Query(default=None, max_length=255),
    origin: str | None = Query(default=None, max_length=500),
    source: SourceType | None = Query(default=None),
    provider: str | None = Query(default=None, max_length=160),
    event_status: EventStatus | None = Query(default=None, alias="status"),
    user: str | None = Query(default=None, max_length=160),
) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="search_facets",
        reason="list safe search facets",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    facets = container.search.facets(
        SearchQuery(
            query=query,
            filters=SearchFilters(
                since=since,
                until=until,
                workspace=workspace,
                app=app,
                domain=domain,
                origin=origin,
                source=source,
                provider=provider,
                status=event_status,
                user=UserFilter.from_query(user),
            ),
            limit=min(limit, 100),
        )
    )
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.SEARCH_PERFORMED,
        resource_type="search_facets",
        resource_id=None,
        policy_decision_id=decision_id,
        success=True,
        details={"query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(), "facet_count": len(facets)},
    )
    envelope = container.responses.success(
        safe_public_payload({"facets": facets}), request_id=request_id, audit_id=audit_id
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/entities")
def _entities(
    request: Request,
    query: str = Query("", max_length=500),
    limit: int = Query(100, ge=1, le=500),
) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="search_entities",
        reason="list safe entity facets",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.SEARCH_PERFORMED,
        resource_type="search_entities",
        resource_id=None,
        policy_decision_id=decision_id,
        success=True,
        details={"query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest(), "degraded": True},
    )
    envelope = container.responses.success(
        {
            "entities": (),
            "degraded": True,
            "reason": "entity_index_not_implemented",
            "query": safe_public_payload(query),
            "limit": limit,
        },
        request_id=request_id,
        audit_id=audit_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))
