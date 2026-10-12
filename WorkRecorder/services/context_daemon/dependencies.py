"""Dependency helpers shared by daemon route modules."""

from __future__ import annotations

from typing import cast

from fastapi import Request

from packages.contracts import (
    AccessRequest,
    AccessScope,
    ActorRef,
    AgentRunToken,
    ApiEnvelope,
    AuditAction,
    AuditLogEventCreate,
)
from packages.contracts.common import JsonScalar
from packages.contracts.enums import ErrorCode, PolicyEffect

from .auth import DaemonAuth
from .container import DaemonContainer


class RouteSupport:
    """Shared helpers for auth, policy, audit, and response envelopes."""

    def __init__(self) -> None:
        """Create route support helpers."""

        self.auth = DaemonAuth()

    def container(self, request: Request) -> DaemonContainer:
        """Return the daemon container stored on the FastAPI app.

        Args:
            request: FastAPI request.

        Returns:
            Daemon service container.
        """

        return cast(DaemonContainer, request.app.state.container)

    def request_id(self, request: Request) -> str:
        """Return request id from headers or generate one.

        Args:
            request: FastAPI request.

        Returns:
            Request correlation id.
        """

        container = self.container(request)
        return request.headers.get("x-request-id") or container.ids.new("req")

    def actor_or_error(self, request: Request, request_id: str) -> ActorRef | ApiEnvelope[object]:
        """Authenticate request and return the actor or an error envelope.

        Args:
            request: FastAPI request.
            request_id: Request correlation id.

        Returns:
            Actor reference or structured error envelope.
        """

        container = self.container(request)
        claims_or_error = self.auth.claims_from_request(request, container)
        if isinstance(claims_or_error, AgentRunToken):
            return claims_or_error.actor
        return container.responses.error(
            code=claims_or_error.code,
            message=claims_or_error.message,
            request_id=request_id,
            details=claims_or_error.details,
        )

    def authorize(
        self,
        *,
        request: Request,
        request_id: str,
        action: AccessScope,
        resource_type: str,
        resource_id: str | None = None,
        reason: str | None = None,
    ) -> tuple[ActorRef, str] | ApiEnvelope[object]:
        """Authorize one sensitive action and return actor plus decision id.

        Args:
            request: FastAPI request.
            request_id: Request correlation id.
            action: Requested access scope.
            resource_type: Resource family.
            resource_id: Optional concrete resource id.
            reason: Optional purpose.

        Returns:
            Actor and decision id on allow, otherwise error envelope.
        """

        container = self.container(request)
        claims_or_error = self.auth.claims_from_request(request, container)
        if not isinstance(claims_or_error, AgentRunToken):
            return container.responses.error(
                code=claims_or_error.code,
                message=claims_or_error.message,
                request_id=request_id,
                details=claims_or_error.details,
            )
        access_request = AccessRequest(
            actor=claims_or_error.actor,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            reason=reason,
        )
        decision = container.authorization.authorize(
            request=access_request,
            token=claims_or_error,
            request_id=request_id,
        )
        if decision.effect != PolicyEffect.ALLOW:
            return container.responses.error(
                code=ErrorCode.POLICY_DENIED,
                message="Access denied",
                request_id=request_id,
                details={"policy_decision_id": decision.decision_id},
            )
        return claims_or_error.actor, decision.decision_id

    def audit_action(
        self,
        *,
        request: Request,
        request_id: str,
        actor: ActorRef,
        action: AuditAction,
        resource_type: str,
        resource_id: str | None,
        policy_decision_id: str | None,
        success: bool,
        details: dict[str, JsonScalar] | None = None,
    ) -> str:
        """Write one action audit event and return its id.

        Args:
            request: FastAPI request.
            request_id: Request correlation id.
            actor: Actor responsible for the action.
            action: Audited action.
            resource_type: Resource family.
            resource_id: Optional resource id.
            policy_decision_id: Policy decision carried by the action.
            success: Whether the action succeeded.
            details: Optional scalar details for audit diagnostics.

        Returns:
            Persisted audit event id.
        """

        event = self.container(request).audits.record(
            AuditLogEventCreate(
                request_id=request_id,
                actor=actor,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                policy_decision_id=policy_decision_id,
                success=success,
                details=details or {},
            )
        )
        return event.audit_id


route_support = RouteSupport()
