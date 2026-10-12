"""Shared active-capture route guard helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from packages.contracts import ActiveCaptureSessionView, ActorRef, AuditAction, ErrorCode

from ..auth import DaemonAuth
from ..dependencies import route_support
from .active_capture_access import session_read_allowed
from .validation_errors import safe_validation_error_details

if TYPE_CHECKING:
    from ..container import DaemonContainer


@dataclass(frozen=True)
class ActiveCaptureRouteGuard:
    """Common guard logic for active-capture daemon routes.

    Attributes:
        request: FastAPI request being guarded.
        request_id: Stable request id for response envelopes and audit rows.
        container: Daemon dependency container.
        actor: Authorized caller identity.
        decision_id: Policy decision id returned by route authorization.
    """

    request: Request
    request_id: str
    container: "DaemonContainer"
    actor: ActorRef
    decision_id: str

    def require_trusted_writer(
        self,
        *,
        session_id: str,
        reason: str,
        message: str,
    ) -> JSONResponse | None:
        """Require the local install secret for trusted native writers."""

        if DaemonAuth().install_secret_matches(self.request, self.container):
            return None
        audit_id = route_support.audit_action(
            request=self.request,
            request_id=self.request_id,
            actor=self.actor,
            action=AuditAction.CAPTURE_ATTEMPTED,
            resource_type="active_capture_session",
            resource_id=session_id,
            policy_decision_id=self.decision_id,
            success=False,
            details={"reason": reason},
        )
        envelope = self.container.responses.error(
            ErrorCode.POLICY_DENIED,
            message,
            request_id=self.request_id,
            audit_id=audit_id,
        )
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=envelope.model_dump(mode="json"))

    def require_native_capture_authority(
        self,
        *,
        session_id: str,
        reason: str,
        message: str,
    ) -> JSONResponse | None:
        """Require the native-only capture secret for native timing/probe material."""

        if DaemonAuth().native_capture_secret_matches(self.request, self.container):
            return None
        audit_id = route_support.audit_action(
            request=self.request,
            request_id=self.request_id,
            actor=self.actor,
            action=AuditAction.CAPTURE_ATTEMPTED,
            resource_type="active_capture_session",
            resource_id=session_id,
            policy_decision_id=self.decision_id,
            success=False,
            details={"reason": reason},
        )
        envelope = self.container.responses.error(
            ErrorCode.POLICY_DENIED,
            message,
            request_id=self.request_id,
            audit_id=audit_id,
        )
        return JSONResponse(status_code=status.HTTP_403_FORBIDDEN, content=envelope.model_dump(mode="json"))

    def require_readable_session(self, session_id: str) -> tuple[ActiveCaptureSessionView | None, JSONResponse | None]:
        """Load and authorize one active-capture session, returning a 404 envelope on denial."""

        try:
            view = self.container.active_capture.view_session(session_id)
        except ValueError:
            return None, self.not_found()
        if not session_read_allowed(self.container, view, actor=self.actor, request=self.request):
            return None, self.not_found()
        return view, None

    def not_found(self) -> JSONResponse:
        """Return a generic not-found envelope that does not reveal hidden sessions."""

        envelope = self.container.responses.error(
            ErrorCode.NOT_FOUND,
            "Active capture session not found",
            request_id=self.request_id,
        )
        return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content=envelope.model_dump(mode="json"))

    def validation_error(self, *, message: str, exc: ValidationError) -> JSONResponse:
        """Return a sanitized validation error envelope."""

        envelope = self.container.responses.error(
            ErrorCode.VALIDATION_ERROR,
            message,
            request_id=self.request_id,
            details=safe_validation_error_details(exc),
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=envelope.model_dump(mode="json"))

    def domain_error(self, *, message: str) -> JSONResponse:
        """Return a fixed safe domain error envelope."""

        envelope = self.container.responses.error(
            ErrorCode.VALIDATION_ERROR,
            message,
            request_id=self.request_id,
        )
        return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, content=envelope.model_dump(mode="json"))
