"""Module entry point for WorkRecorder routing and audit APIs."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import JSONResponse

from packages.contracts import AccessScope

from ..dependencies import route_support

router = APIRouter(prefix="/v1/audit", tags=["audit"])


@router.get("")
def _export_audit(request: Request, event_id: str = Query(..., alias="event")) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="audit",
        resource_id=event_id,
        reason="export event audit trail",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    capture_envelope = container.repositories.ledger.get_envelope_by_event_id(event_id)
    resource_ids = [event_id]
    if capture_envelope is not None:
        resource_ids.extend(capture_envelope.artifact_ids)
        resource_ids.extend(evidence.evidence_id for evidence in capture_envelope.evidence_records)
        resource_ids.extend(capture_envelope.audit_refs)
    events = container.repositories.audits.list_for_resources(resource_ids=tuple(dict.fromkeys(resource_ids)))
    envelope = container.responses.success(
        {"event_id": event_id, "resource_ids": tuple(dict.fromkeys(resource_ids)), "audit": events},
        request_id=request_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))
