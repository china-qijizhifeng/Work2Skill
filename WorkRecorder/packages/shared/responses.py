"""Helpers for creating stable API envelopes."""

from __future__ import annotations

from packages.contracts import ApiEnvelope, ApiError, ErrorCode
from packages.contracts.common import JsonScalar


class ResponseFactory:
    """Create success and error envelopes with consistent request metadata."""

    def success(
        self,
        data: object,
        *,
        request_id: str,
        audit_id: str | None = None,
        agent_run_id: str | None = None,
        context_query_id: str | None = None,
        retrieval_call_id: str | None = None,
        snapshot_id: str | None = None,
    ) -> ApiEnvelope[object]:
        """Build a successful response envelope.

        Args:
            data: Typed response payload.
            request_id: Request correlation id.
            audit_id: Optional audit event id.

        Returns:
            API envelope with ``ok`` set to true.
        """

        return ApiEnvelope[object](
            ok=True,
            data=data,
            error=None,
            request_id=request_id,
            audit_id=audit_id,
            agent_run_id=agent_run_id,
            context_query_id=context_query_id,
            retrieval_call_id=retrieval_call_id,
            snapshot_id=snapshot_id,
        )

    def error(
        self,
        code: ErrorCode,
        message: str,
        *,
        request_id: str,
        audit_id: str | None = None,
        agent_run_id: str | None = None,
        context_query_id: str | None = None,
        retrieval_call_id: str | None = None,
        snapshot_id: str | None = None,
        details: dict[str, JsonScalar] | None = None,
    ) -> ApiEnvelope[object]:
        """Build an error response envelope.

        Args:
            code: Stable error code.
            message: Safe error message.
            request_id: Request correlation id.
            audit_id: Optional audit event id.
            details: Optional scalar details.

        Returns:
            API envelope with ``ok`` set to false.
        """

        body = ApiError(code=code, message=message, details=details or {})
        return ApiEnvelope[object](
            ok=False,
            data=None,
            error=body,
            request_id=request_id,
            audit_id=audit_id,
            agent_run_id=agent_run_id,
            context_query_id=context_query_id,
            retrieval_call_id=retrieval_call_id,
            snapshot_id=snapshot_id,
        )
