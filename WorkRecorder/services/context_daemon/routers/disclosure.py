"""Disclosure policy diagnostics routes."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from packages.contracts import AccessScope

from ..dependencies import route_support

router = APIRouter(prefix="/v1/disclosure", tags=["disclosure"])


@router.get("/profiles")
def _list_disclosure_profiles(request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="disclosure_profile",
        reason="list disclosure policy SDK profiles",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    profiles = container.disclosure_registry.list_profiles()
    envelope = container.responses.success(
        {
            "profiles": profiles,
            "workspace_override_warnings": container.disclosure_registry.workspace_override_warnings(),
        },
        request_id=request_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))
