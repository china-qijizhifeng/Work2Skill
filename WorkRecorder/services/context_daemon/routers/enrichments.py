"""Manual enrichment routes for user-approved derived evidence jobs.

This router exposes explicit, event-scoped enrichment entry points such as
visual OCR. These routes are intentionally separate from capture hot paths so
the daemon can enforce raw-artifact authorization, schedule durable jobs, and
return typed job state without making screenshot saves wait for model calls.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Request, status
from fastapi.responses import JSONResponse

from packages.contracts import AccessScope, ErrorCode

from ..dependencies import route_support

router = APIRouter(prefix="/v1/events", tags=["enrichments"])


@router.post("/{event_id}/enrichments/visual-ocr")
async def _run_visual_ocr(event_id: str, request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.RUN_ENRICHMENT,
        resource_type="event",
        resource_id=event_id,
        reason="run visual OCR enrichment",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    raw_auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_RAW_ARTIFACT,
        resource_type="event",
        resource_id=event_id,
        reason="authorize selected screenshot upload for visual OCR",
    )
    if not isinstance(raw_auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=raw_auth_result.model_dump(mode="json"))
    event = container.repositories.events.get(event_id)
    if event is None:
        response = container.responses.error(ErrorCode.NOT_FOUND, "Event not found", request_id=request_id)
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=response.model_dump(mode="json"))
    job = container.visual_ocr.schedule_for_event(event_id, reason="manual")
    background_tasks.add_task(container.visual_ocr.run_for_event, event_id)
    response = container.responses.success(
        {"job": job, "visual_ocr": container.visual_ocr.state_for_event(event_id)},
        request_id=request_id,
    )
    return JSONResponse(content=response.model_dump(mode="json"))
