"""Health route for the local context daemon."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from packages.contracts import HealthResponse

from ..dependencies import route_support

router = APIRouter(tags=["health"])


@router.get("/health")
def _health(request: Request) -> JSONResponse:
    container = route_support.container(request)
    request_id = route_support.request_id(request)
    envelope = container.responses.success(
        HealthResponse(
            status="ok",
            database_path=str(container.settings.database_path),
            recording_target=container.settings.recording_target,
        ),
        request_id=request_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))
