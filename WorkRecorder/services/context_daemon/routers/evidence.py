"""Module entry point for WorkRecorder routing and audit APIs."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

from packages.contracts import AccessScope, AuditAction, ErrorCode, EventStatus

from ..dependencies import route_support
from ..safe_metadata import safe_public_payload

router = APIRouter(prefix="/v1/evidence", tags=["evidence"])


@router.get("")
def _list_evidence(request: Request, event_id: str = Query(..., alias="event")) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="evidence",
        resource_id=event_id,
        reason="list event evidence records",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    event = container.repositories.events.get(event_id)
    if event is None or event.status in {EventStatus.DELETED, EventStatus.RESTRICTED}:
        response = container.responses.error(ErrorCode.NOT_FOUND, "Evidence records not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=response.model_dump(mode="json"))
    evidence = container.repositories.ledger.list_evidence_for_event(event_id)
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_READ,
        resource_type="evidence",
        resource_id=event_id,
        policy_decision_id=decision_id,
        success=True,
    )
    envelope = container.responses.success(
        {"evidence": safe_public_payload(evidence)}, request_id=request_id, audit_id=audit_id
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/{evidence_id}")
def _get_evidence(evidence_id: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="evidence",
        resource_id=evidence_id,
        reason="read evidence record",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    actor, decision_id = auth_result
    evidence = container.repositories.ledger.get_evidence(evidence_id)
    event = container.repositories.events.get(evidence.event_id) if evidence is not None else None
    if evidence is None or event is None or event.status in {EventStatus.DELETED, EventStatus.RESTRICTED}:
        response = container.responses.error(ErrorCode.NOT_FOUND, "Evidence record not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=response.model_dump(mode="json"))
    audit_id = route_support.audit_action(
        request=request,
        request_id=request_id,
        actor=actor,
        action=AuditAction.EVENT_READ,
        resource_type="evidence",
        resource_id=evidence_id,
        policy_decision_id=decision_id,
        success=True,
    )
    response = container.responses.success(safe_public_payload(evidence), request_id=request_id, audit_id=audit_id)
    return JSONResponse(content=response.model_dump(mode="json"))
