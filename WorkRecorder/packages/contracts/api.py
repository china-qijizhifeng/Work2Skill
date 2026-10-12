"""API envelope contracts shared by FastAPI routes and CLI output."""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import Field

from .base import ContractModel
from .common import JsonScalar
from .enums import ErrorCode

TData = TypeVar("TData")


class ApiError(ContractModel):
    """Structured error body for daemon and CLI responses.

    Attributes:
        code: Stable error code.
        message: User-facing safe message.
        details: Small scalar details with no secrets or raw content.
    """

    code: ErrorCode
    message: str
    details: dict[str, JsonScalar] = Field(default_factory=dict)


class ApiEnvelope(ContractModel, Generic[TData]):
    """Stable response envelope returned by every public boundary.

    Attributes:
        ok: Whether the request succeeded.
        data: Optional typed success payload.
        error: Optional structured error.
        request_id: Request id for correlation.
        audit_id: Optional audit id written by the daemon.
    """

    ok: bool
    data: TData | None
    error: ApiError | None
    request_id: str
    audit_id: str | None = None
    agent_run_id: str | None = None
    context_query_id: str | None = None
    retrieval_call_id: str | None = None
    snapshot_id: str | None = None
