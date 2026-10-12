"""Policy routes for explicit access checks."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

from packages.contracts import AccessRequest, AccessScope, AgentRunToken

from ..dependencies import route_support

router = APIRouter(prefix="/v1/policy", tags=["policy"])


@router.post("/check-access")
def _check_access(body: AccessRequest, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.CHECK_POLICY,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
        reason="explicit policy check",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    claims_or_error = route_support.auth.claims_from_request(request, container)
    if not isinstance(claims_or_error, AgentRunToken):
        envelope = container.responses.error(
            code=claims_or_error.code,
            message=claims_or_error.message,
            request_id=request_id,
            details=claims_or_error.details,
        )
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content=envelope.model_dump(mode="json"))
    bound_request = body.model_copy(update={"actor": claims_or_error.actor})
    decision = container.authorization.authorize(
        request=bound_request,
        token=claims_or_error,
        request_id=request_id,
    )
    envelope = container.responses.success(decision, request_id=request_id)
    return JSONResponse(content=envelope.model_dump(mode="json"))
