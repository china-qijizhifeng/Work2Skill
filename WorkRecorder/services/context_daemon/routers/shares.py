"""FastAPI routes for audited context share create, resolve, import, and sync."""

from __future__ import annotations

import hashlib
import logging

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

from packages.context_share.errors import ShareAccessError
from packages.contracts import (
    AccessScope,
    AuditAction,
    ContextShareCreateRequest,
    ContextShareStatus,
    ErrorCode,
    RetrievalCallKind,
    ShareImportRequest,
    ShareImportStatus,
    SnapshotKind,
    UserFilter,
)

from ..dependencies import route_support
from ..safe_metadata import safe_public_payload

router = APIRouter(prefix="/v1/shares", tags=["shares"])
logger = logging.getLogger(__name__)


@router.post("")
def _create_share(body: ContextShareCreateRequest, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.CREATE_SHARE,
        resource_type="context_share",
        resource_id=body.event_id,
        reason=body.purpose,
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    read_auth = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_TEXT,
        resource_type="context_share",
        resource_id=body.event_id,
        reason=body.purpose,
    )
    if not isinstance(read_auth, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=read_auth.model_dump(mode="json"))
    try:
        result = container.context_shares.create(request=body, actor=actor)
    except ShareAccessError as exc:
        return _share_error(request, request_id=request_id, error=exc)
    except Exception:
        logger.exception("context share creation failed", extra={"event_id": body.event_id})
        return _share_error(
            request,
            request_id=request_id,
            error=ShareAccessError("Failed to create share.", code=ErrorCode.INTERNAL_ERROR),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.SHARE_CREATED,
        resource_type="context_share",
        resource_id=result.share.share_id,
        policy_decision_id=decision_id,
        success=result.share.status in {ContextShareStatus.READY, ContextShareStatus.LOCAL_READY},
        details={
            "event_id": body.event_id,
            "target": body.target.value,
            "external_url_ready": bool(result.external_url),
        },
    )
    response = container.responses.success(
        safe_public_payload(result),
        request_id=request_id,
        audit_id=audit_id,
    )
    return JSONResponse(content=response.model_dump(mode="json"))


@router.get("")
def _list_shares(
    request: Request,
    user: str | None = Query(default=None, max_length=160),
    limit: int = Query(50, ge=1, le=100),
) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_SHARE,
        resource_type="context_share",
        reason="list context shares",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    shares = container.context_shares.list(user=UserFilter.from_query(user), limit=limit)
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.SHARE_READ,
        resource_type="context_share",
        resource_id=None,
        policy_decision_id=decision_id,
        success=True,
        details={"count": len(shares)},
    )
    response = container.responses.success(
        {"shares": safe_public_payload(shares)},
        request_id=request_id,
        audit_id=audit_id,
    )
    return JSONResponse(content=response.model_dump(mode="json"))


@router.get("/{share_id}")
def _get_share(share_id: str, request: Request) -> JSONResponse:
    return _resolve_share_impl(share_id, request, purpose="share_read", trace=False)


@router.post("/resolve")
def _resolve_share_reference(body: ShareImportRequest, request: Request) -> JSONResponse:
    return _resolve_share_impl(body.source, request, purpose=body.purpose, trace=True)


@router.post("/{share_id}/resolve")
def _resolve_share(share_id: str, request: Request) -> JSONResponse:
    return _resolve_share_impl(share_id, request, purpose="user_shared_context", trace=True)


@router.post("/{share_id}/sync")
def _sync_share(share_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.CREATE_SHARE,
        resource_type="context_share",
        resource_id=share_id,
        reason="sync context share",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    read_auth = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_TEXT,
        resource_type="context_share",
        resource_id=share_id,
        reason="sync context share",
    )
    if not isinstance(read_auth, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=read_auth.model_dump(mode="json"))
    try:
        result = container.context_shares.sync(share_id=share_id, actor=actor)
    except ShareAccessError as exc:
        return _share_error(request, request_id=request_id, error=exc)
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.SHARE_SYNCED,
        resource_type="context_share",
        resource_id=share_id,
        policy_decision_id=decision_id,
        success=result.share.status in {ContextShareStatus.READY, ContextShareStatus.LOCAL_READY},
    )
    response = container.responses.success(safe_public_payload(result), request_id=request_id, audit_id=audit_id)
    return JSONResponse(content=response.model_dump(mode="json"))


@router.post("/{share_id}/revoke")
def _revoke_share(share_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.REVOKE_SHARE,
        resource_type="context_share",
        resource_id=share_id,
        reason="revoke context share",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    try:
        share = container.context_shares.revoke(share_id=share_id, actor=actor)
    except ShareAccessError as exc:
        return _share_error(request, request_id=request_id, error=exc)
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.SHARE_REVOKED,
        resource_type="context_share",
        resource_id=share_id,
        policy_decision_id=decision_id,
        success=True,
    )
    response = container.responses.success(safe_public_payload(share), request_id=request_id, audit_id=audit_id)
    return JSONResponse(content=response.model_dump(mode="json"))


@router.get("/{share_id}/jobs")
def _share_jobs(share_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_SHARE,
        resource_type="context_share_jobs",
        resource_id=share_id,
        reason="read context share jobs",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    jobs = container.context_shares.jobs(share_id=share_id)
    response = container.responses.success({"jobs": safe_public_payload(jobs)}, request_id=request_id)
    return JSONResponse(content=response.model_dump(mode="json"))


@router.post("/import")
def _import_share(body: ShareImportRequest, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.IMPORT_SHARE,
        resource_type="context_share",
        reason=body.purpose,
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    if body.source.strip().startswith(("workrecorder://share/", "shr_")):
        read_auth = route_support.authorize(
            request=request,
            request_id=request_id,
            action=AccessScope.READ_SHARE,
            resource_type="context_share",
            reason=body.purpose,
        )
        if not isinstance(read_auth, tuple):
            return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=read_auth.model_dump(mode="json"))
    result = container.context_shares.import_share(request=body, actor=actor)
    success = result.status in {
        ShareImportStatus.LINKED_EXISTING_EVENT,
        ShareImportStatus.IMPORTED,
        ShareImportStatus.UPDATED_EXISTING_EVENT,
    }
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.SHARE_IMPORTED,
        resource_type="context_share",
        resource_id=result.share_id,
        policy_decision_id=decision_id,
        success=success,
        details={"status": result.status.value},
    )
    if not success:
        code = status.HTTP_422_UNPROCESSABLE_CONTENT
        if result.status == ShareImportStatus.PERMISSION_REQUIRED:
            code = status.HTTP_403_FORBIDDEN
        envelope = container.responses.error(
            (
                ErrorCode.NOT_IMPLEMENTED
                if result.status == ShareImportStatus.UNSUPPORTED_SOURCE
                else ErrorCode.VALIDATION_ERROR
            ),
            result.message,
            request_id=request_id,
            audit_id=audit_id,
            details={"status": result.status.value},
        )
        return JSONResponse(status_code=code, content=envelope.model_dump(mode="json"))
    response = container.responses.success(safe_public_payload(result), request_id=request_id, audit_id=audit_id)
    return JSONResponse(content=response.model_dump(mode="json"))


def _resolve_share_impl(share_id: str, request: Request, *, purpose: str, trace: bool) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_SHARE,
        resource_type="context_share",
        resource_id=share_id,
        reason=purpose,
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    try:
        result = container.context_shares.resolve(link_or_share_id=share_id, actor=actor)
    except ShareAccessError as exc:
        return _share_error(request, request_id=request_id, error=exc)
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.SHARE_READ,
        resource_type="context_share",
        resource_id=result.share.share_id,
        policy_decision_id=decision_id,
        success=True,
        details={"event_id": result.share.event_id, "external_url_ready": bool(result.external_url)},
    )
    if not trace:
        response = container.responses.success(safe_public_payload(result), request_id=request_id, audit_id=audit_id)
        return JSONResponse(content=response.model_dump(mode="json"))
    run = container.agent_runs.ensure_run(
        actor=actor,
        requested_run_id=request.headers.get("x-workrecorder-agent-run-id"),
        purpose=purpose,
        user_question=f"resolve share {result.share.share_id}",
    )
    context_query = container.agent_runs.context_query(
        run=run,
        query_text=f"resolve share {result.share.share_id}",
        purpose=purpose,
        requested_query_id=request.headers.get("x-workrecorder-context-query-id"),
        metadata={"share_id": result.share.share_id},
    )
    call, snapshot = container.agent_runs.trace_delivery(
        run=run,
        context_query=context_query,
        request_id=request_id,
        kind=RetrievalCallKind.SHARE_RESOLVE,
        resource_type="context_share",
        resource_id=result.share.share_id,
        purpose=purpose,
        request_payload={"share_id": result.share.share_id},
        response_payload=result,
        snapshot_kind=SnapshotKind.SHARE,
        metadata={"audit_id": audit_id, "query_hash": hashlib.sha256(share_id.encode("utf-8")).hexdigest()},
    )
    response = container.responses.success(
        safe_public_payload(result),
        request_id=request_id,
        audit_id=audit_id,
        agent_run_id=run.agent_run_id,
        context_query_id=context_query.context_query_id,
        retrieval_call_id=call.retrieval_call_id,
        snapshot_id=snapshot.snapshot_id,
    )
    return JSONResponse(content=response.model_dump(mode="json"))


def _share_error(
    request: Request,
    *,
    request_id: str,
    error: ShareAccessError,
    status_code: int | None = None,
) -> JSONResponse:
    container = route_support.container(request)
    code = status_code
    if code is None:
        code = status.HTTP_404_NOT_FOUND if error.code == ErrorCode.NOT_FOUND else status.HTTP_422_UNPROCESSABLE_CONTENT
    response = container.responses.error(error.code, str(error), request_id=request_id)
    return JSONResponse(status_code=code, content=response.model_dump(mode="json"))
