"""Provider session, command, and diagnostics routes."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, cast

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from packages.contracts import (
    AccessScope,
    AgentRunToken,
    CollectEvidenceResult,
    ErrorCode,
    ProviderCapability,
    ProviderHeartbeat,
    ProviderKind,
    ProviderSessionRegistration,
)
from packages.policy.tokens import TokenError

from ..dependencies import route_support
from ..safe_metadata import safe_public_payload

if TYPE_CHECKING:
    from ..container import DaemonContainer

router = APIRouter(prefix="/v1/providers", tags=["providers"])
logger = logging.getLogger(__name__)
PROVIDER_WS_SUBPROTOCOL = "workrecorder-provider-v1"
TOKEN_SUBPROTOCOL_PREFIX = "workrecorder-token."
SYSTEM_PROVIDER_ACTORS = {"system.macos_a11y": "macos-a11y-provider"}


@router.get("")
def _list_providers(request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="provider",
        reason="list capture providers",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    providers = [
        {
            "provider_key": provider.name,
            "capabilities": [capability.value for capability in provider.capabilities],
            "manifest": provider.manifest,
        }
        for provider in container.source_providers.list()
    ]
    envelope = container.responses.success({"providers": providers}, request_id=request_id)
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/manifests")
def _list_provider_manifests(request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="provider_manifest",
        reason="list provider SDK manifests",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    manifests = [provider.manifest for provider in container.source_providers.list()]
    envelope = container.responses.success({"manifests": manifests}, request_id=request_id)
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/sessions")
async def _list_provider_sessions(request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="provider_session",
        reason="list provider sessions",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    sessions = await container.provider_sessions.list_sessions()
    envelope = container.responses.success(
        {"sessions": tuple(_safe_provider_session_ref(session) for session in sessions)},
        request_id=request_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/definitions")
def _list_provider_definitions(request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="provider_definition",
        reason="list provider lifecycle definitions",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    envelope = container.responses.success(
        {"definitions": container.provider_lifecycle.definitions()},
        request_id=request_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.get("/status")
async def _provider_status(request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="provider_status",
        reason="list provider lifecycle status",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    envelope = container.responses.success(
        {"providers": await container.provider_lifecycle.status_reports()},
        request_id=request_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.post("/{provider_key}/diagnostics/run")
async def _run_provider_diagnostics(provider_key: str, request: Request) -> JSONResponse:
    request_id = route_support.request_id(request)
    container = route_support.container(request)
    auth_result = route_support.authorize(
        request=request,
        request_id=request_id,
        action=AccessScope.READ_METADATA,
        resource_type="provider_diagnostics",
        resource_id=provider_key,
        reason="run provider lifecycle diagnostics",
    )
    if not isinstance(auth_result, tuple):
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=auth_result.model_dump(mode="json"))
    diagnostics = await container.provider_lifecycle.diagnostics(provider_key)
    if diagnostics is None:
        envelope = container.responses.error(
            ErrorCode.NOT_FOUND, "Provider definition not found", request_id=request_id
        )
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))
    envelope = container.responses.success(
        {
            "provider_key": provider_key,
            "diagnostics": diagnostics.diagnostics,
            "status": diagnostics.status,
        },
        request_id=request_id,
    )
    return JSONResponse(content=envelope.model_dump(mode="json"))


@router.websocket("/sessions/ws")
async def _provider_session_ws(websocket: WebSocket) -> None:
    container = cast("DaemonContainer", websocket.app.state.container)
    token = _provider_ws_token(websocket)
    if token is None:
        await websocket.close(code=1008)
        return
    try:
        claims = container.tokens.verify(token)
    except TokenError:
        await websocket.close(code=1008)
        return
    if AccessScope.REGISTER_PROVIDER_CONTEXT not in claims.scopes:
        await websocket.close(code=1008)
        return
    await websocket.accept(subprotocol=_accepted_subprotocol(websocket))
    registration: ProviderSessionRegistration | None = None
    outbound: _ProviderOutbound | None = None
    sender: asyncio.Task[None] | None = None
    try:
        raw = await websocket.receive_text()
        payload = _json_object(raw)
        registration = ProviderSessionRegistration.model_validate(payload.get("registration", payload))
        registration = _authorized_registration(container, registration, claims)
        logger.info(
            "provider websocket registration accepted provider_key=%s session_id=%s kind=%s capabilities=%s has_tab=%s",
            registration.provider_key,
            registration.provider_session_id,
            registration.provider_kind,
            len(registration.capabilities),
            registration.tab is not None,
            extra={
                "provider_key": registration.provider_key,
                "provider_kind": registration.provider_kind,
                "provider_session_id": registration.provider_session_id,
                "capability_count": len(registration.capabilities),
                "has_tab": registration.tab is not None,
            },
        )
        outbound = _ProviderOutbound(
            provider_key=registration.provider_key,
            provider_session_id=registration.provider_session_id,
        )
        ref = await container.provider_sessions.register(websocket=outbound, registration=registration)
        await websocket.send_text(
            json.dumps({"message_type": "provider_session_accepted", "session": ref.model_dump(mode="json")})
        )
        sender = asyncio.create_task(_send_provider_outbound(websocket=websocket, outbound=outbound))
        while True:
            payload = _json_object(await websocket.receive_text())
            message_type = payload.get("message_type")
            if message_type == "provider_heartbeat":
                heartbeat = ProviderHeartbeat.model_validate(payload.get("heartbeat", payload))
                await container.provider_sessions.heartbeat(
                    heartbeat,
                    provider_key=registration.provider_key,
                    provider_session_id=registration.provider_session_id,
                )
                continue
            if message_type == "collect_evidence_result":
                result = CollectEvidenceResult.model_validate(payload)
                await container.provider_sessions.handle_collect_result(
                    result,
                    provider_session_id=registration.provider_session_id,
                )
                continue
            logger.warning("unknown provider websocket message", extra={"message_type": message_type})
    except WebSocketDisconnect:
        pass
    except (ValidationError, ValueError, TypeError):
        logger.exception("invalid provider websocket message")
        await websocket.close(code=1003)
    finally:
        if sender is not None:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        if registration is not None:
            await container.provider_sessions.unregister(
                registration.provider_session_id,
                websocket=outbound,
            )


class _ProviderOutbound:
    """Queue outgoing command frames so WebSocket sends stay inside the route task."""

    def __init__(self, *, provider_key: str, provider_session_id: str) -> None:
        self.provider_key = provider_key
        self.provider_session_id = provider_session_id
        self.loop = asyncio.get_running_loop()
        self.queue: asyncio.Queue[str] = asyncio.Queue()

    async def send_text(self, data: str) -> None:
        """Queue one outbound text frame for the provider WebSocket.

        Args:
            data: Serialized provider command envelope to send.
        """

        logger.info(
            "provider outbound command queued",
            extra={
                "provider_key": self.provider_key,
                "provider_session_id": self.provider_session_id,
                "bytes": len(data),
            },
        )
        if asyncio.get_running_loop() is self.loop:
            await self.queue.put(data)
            return
        future = asyncio.run_coroutine_threadsafe(self.queue.put(data), self.loop)
        await asyncio.wrap_future(future)


async def _send_provider_outbound(*, websocket: WebSocket, outbound: _ProviderOutbound) -> None:
    try:
        while True:
            data = await outbound.queue.get()
            logger.info(
                "provider outbound command sending",
                extra={
                    "provider_key": outbound.provider_key,
                    "provider_session_id": outbound.provider_session_id,
                    "bytes": len(data),
                },
            )
            await websocket.send_text(data)
            logger.info(
                "provider outbound command sent",
                extra={
                    "provider_key": outbound.provider_key,
                    "provider_session_id": outbound.provider_session_id,
                    "bytes": len(data),
                },
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("provider outbound sender failed")
        raise


def _json_object(raw: str) -> dict[str, object]:
    payload: object = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("provider websocket message must be a JSON object")
    return cast(dict[str, object], payload)


def _safe_provider_session_ref(session: object) -> dict[str, object]:
    if isinstance(session, BaseModel):
        payload = cast(dict[str, object], session.model_dump(mode="json"))
    elif isinstance(session, dict):
        payload = cast(dict[str, object], dict(session))
    else:
        payload = {}
    tab = payload.get("tab")
    safe_tab: dict[str, object] | None = None
    if isinstance(tab, dict):
        safe_tab = cast(
            dict[str, object],
            safe_public_payload(
                {
                    "browser": tab.get("browser"),
                    "origin": tab.get("origin"),
                    "title": tab.get("title"),
                }
            ),
        )
    safe_labels = cast(
        dict[str, object],
        safe_public_payload(
            {
                "display_name": payload.get("display_name"),
                "app_name": payload.get("app_name"),
            }
        ),
    )
    return {
        "provider_key": payload.get("provider_key"),
        "provider_kind": payload.get("provider_kind"),
        "display_name": safe_labels.get("display_name"),
        "app_name": safe_labels.get("app_name"),
        "capabilities": payload.get("capabilities") or [],
        "registered_at": payload.get("registered_at"),
        "last_seen_at": payload.get("last_seen_at"),
        "expires_at": payload.get("expires_at"),
        "connected": payload.get("connected"),
        "has_tab": safe_tab is not None,
        "tab": safe_tab,
        # Keep legacy keys as explicit nulls so older diagnostics can tell that
        # the fields are intentionally hidden rather than absent.
        "process_id": None,
        "window_id": None,
    }


def _provider_ws_token(websocket: WebSocket) -> str | None:
    protocols = websocket.headers.get("sec-websocket-protocol", "")
    for raw_protocol in protocols.split(","):
        protocol = raw_protocol.strip()
        if protocol.startswith(TOKEN_SUBPROTOCOL_PREFIX):
            return protocol.removeprefix(TOKEN_SUBPROTOCOL_PREFIX)
    return None


def _accepted_subprotocol(websocket: WebSocket) -> str | None:
    protocols = {protocol.strip() for protocol in websocket.headers.get("sec-websocket-protocol", "").split(",")}
    return PROVIDER_WS_SUBPROTOCOL if PROVIDER_WS_SUBPROTOCOL in protocols else None


def _authorized_registration(
    container: "DaemonContainer", registration: ProviderSessionRegistration, claims: AgentRunToken
) -> ProviderSessionRegistration:
    source_provider = container.source_providers.get(registration.provider_key)
    if source_provider is not None:
        if registration.provider_kind != ProviderKind.SOURCE:
            raise ValueError("source provider registered with wrong kind")
        allowed = set(source_provider.capabilities)
        capabilities = tuple(capability for capability in registration.capabilities if capability in allowed)
        return registration.model_copy(update={"capabilities": capabilities})
    if registration.provider_key == "system.macos_a11y":
        if claims.actor.actor_id != SYSTEM_PROVIDER_ACTORS[registration.provider_key]:
            raise ValueError("a11y provider token actor mismatch")
        if registration.provider_kind != ProviderKind.SYSTEM_EVIDENCE:
            raise ValueError("a11y provider registered with wrong kind")
        allowed = {ProviderCapability.READ_A11Y}
        capabilities = tuple(capability for capability in registration.capabilities if capability in allowed)
        if ProviderCapability.READ_A11Y not in capabilities:
            raise ValueError("a11y provider missing read_a11y capability")
        return registration.model_copy(update={"capabilities": capabilities})
    raise ValueError("unknown provider key")
