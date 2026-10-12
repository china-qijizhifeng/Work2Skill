"""Authentication routes for local CLI token exchange."""

from __future__ import annotations

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import Field

from packages.contracts import AccessScope, ActorRef, AuditAction, AuditLogEventCreate, ErrorCode, TokenIssueResponse
from packages.contracts.base import ContractModel

from ..auth import DaemonAuth
from ..dependencies import route_support

router = APIRouter(prefix="/v1/auth", tags=["auth"])

DEFAULT_CLI_SCOPES: tuple[AccessScope, ...] = (
    AccessScope.READ_METADATA,
    AccessScope.READ_TEXT,
    AccessScope.READ_THUMBNAIL,
    AccessScope.CREATE_EVENT,
    AccessScope.CREATE_BUNDLE,
    AccessScope.RECORD_USAGE,
    AccessScope.DELETE_EVENT,
    AccessScope.CHECK_POLICY,
)
ALLOWED_CLI_SCOPES: tuple[AccessScope, ...] = (
    *DEFAULT_CLI_SCOPES,
    AccessScope.READ_IMAGE,
    AccessScope.READ_RAW_ARTIFACT,
    AccessScope.MANAGE_LOCAL_SETTINGS,
    AccessScope.RUN_ENRICHMENT,
    AccessScope.READ_JOB_STATUS,
    AccessScope.CREATE_SHARE,
    AccessScope.READ_SHARE,
    AccessScope.REVOKE_SHARE,
    AccessScope.IMPORT_SHARE,
)
PROVIDER_TOKEN_ACTORS = {"browser-extension", "macos-a11y-provider"}
ELEVATED_SCOPES: frozenset[AccessScope] = frozenset(
    {
        AccessScope.READ_IMAGE,
        AccessScope.READ_RAW_ARTIFACT,
        AccessScope.MANAGE_LOCAL_SETTINGS,
        AccessScope.RUN_ENRICHMENT,
        AccessScope.READ_JOB_STATUS,
    }
)


class TokenRequest(ContractModel):
    """Local token request sent by the CLI.

    Attributes:
        actor_id: Local caller id.
        display_name: Optional caller label.
        scopes: Requested scopes. P0 rejects unknown scopes through enum validation.
    """

    actor_id: str = Field(default="local-cli", min_length=1)
    display_name: str | None = "WorkRecorder CLI"
    scopes: tuple[AccessScope, ...] = DEFAULT_CLI_SCOPES


def _is_extension_origin(request: Request) -> bool:
    origin = request.headers.get("origin") or ""
    return origin.startswith("chrome-extension://")


@router.post("/tokens")
def _issue_token(body: TokenRequest, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth = DaemonAuth()
    provider_only_scopes = {AccessScope.REGISTER_PROVIDER_CONTEXT}
    if body.actor_id in PROVIDER_TOKEN_ACTORS:
        if container.settings.provider_registration_secret == "dev-provider-secret" and not container.settings.dev_mode:
            envelope = container.responses.error(
                code=ErrorCode.AUTH_INVALID,
                message="Development provider secret is disabled outside dev mode",
                request_id=request_id,
            )
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content=envelope.model_dump(mode="json"))
        if not auth.provider_registration_secret_matches(request, container):
            envelope = container.responses.error(
                code=ErrorCode.AUTH_INVALID,
                message="Invalid provider secret",
                request_id=request_id,
            )
            return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content=envelope.model_dump(mode="json"))
        if not set(body.scopes).issubset(provider_only_scopes):
            envelope = container.responses.error(
                code=ErrorCode.POLICY_DENIED,
                message="Provider actors may only request provider registration scopes",
                request_id=request_id,
            )
            return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=envelope.model_dump(mode="json"))
        actor = ActorRef(actor_id=body.actor_id, display_name=body.display_name)
        token, claims = container.tokens.issue(actor=actor, scopes=body.scopes)
        audit = container.audits.record(
            AuditLogEventCreate(
                request_id=request_id,
                actor=actor,
                action=AuditAction.TOKEN_ISSUED,
                resource_type="token",
                resource_id=claims.token_id,
                success=True,
                details={"audience": claims.audience, "provider_token": True},
            )
        )
        envelope = container.responses.success(
            TokenIssueResponse(access_token=token, claims=claims),
            request_id=request_id,
            audit_id=audit.audit_id,
        )
        return JSONResponse(content=envelope.model_dump(mode="json"))
    if _is_extension_origin(request):
        envelope = container.responses.error(
            code=ErrorCode.POLICY_DENIED,
            message="Browser extension origin may only request provider tokens",
            request_id=request_id,
        )
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=envelope.model_dump(mode="json"))
    if AccessScope.REGISTER_PROVIDER_CONTEXT in set(body.scopes):
        envelope = container.responses.error(
            code=ErrorCode.POLICY_DENIED,
            message="Provider registration scope is reserved for provider actors",
            request_id=request_id,
        )
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=envelope.model_dump(mode="json"))
    if container.settings.install_secret == "dev-install-secret" and not container.settings.dev_mode:
        envelope = container.responses.error(
            code=ErrorCode.AUTH_INVALID,
            message="Development install secret is disabled outside dev mode",
            request_id=request_id,
        )
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content=envelope.model_dump(mode="json"))
    if not auth.install_secret_matches(request, container):
        envelope = container.responses.error(
            code=ErrorCode.AUTH_INVALID,
            message="Invalid install secret",
            request_id=request_id,
        )
        return JSONResponse(status_code=status.HTTP_401_UNAUTHORIZED, content=envelope.model_dump(mode="json"))
    if container.settings.install_secret == "dev-install-secret" and set(body.scopes).intersection(ELEVATED_SCOPES):
        envelope = container.responses.error(
            code=ErrorCode.POLICY_DENIED,
            message="Elevated local scopes require a generated per-install secret",
            request_id=request_id,
        )
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=envelope.model_dump(mode="json"))
    if not set(body.scopes).issubset(set(ALLOWED_CLI_SCOPES)):
        envelope = container.responses.error(
            code=ErrorCode.POLICY_DENIED,
            message="Requested token scopes exceed P0 CLI grants",
            request_id=request_id,
        )
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=envelope.model_dump(mode="json"))
    actor = ActorRef(actor_id=body.actor_id, display_name=body.display_name)
    token, claims = container.tokens.issue(actor=actor, scopes=body.scopes)
    audit = container.audits.record(
        AuditLogEventCreate(
            request_id=request_id,
            actor=actor,
            action=AuditAction.TOKEN_ISSUED,
            resource_type="token",
            resource_id=claims.token_id,
            success=True,
            details={"audience": claims.audience},
        )
    )
    envelope = container.responses.success(
        TokenIssueResponse(access_token=token, claims=claims),
        request_id=request_id,
        audit_id=audit.audit_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/native-capture-authority")
def _native_capture_authority(request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    if not DaemonAuth().native_capture_secret_matches(request, container):
        envelope = container.responses.error(
            code=ErrorCode.AUTH_INVALID,
            message="Invalid native capture secret",
            request_id=request_id,
        )
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=envelope.model_dump(mode="json"))
    envelope = container.responses.success({"status": "ok"}, request_id=request_id)
    return JSONResponse(content=envelope.model_dump(mode="json"))
