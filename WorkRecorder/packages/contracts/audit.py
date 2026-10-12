"""Audit event contracts for request and policy traceability."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import ContractModel
from .common import ActorRef, JsonScalar
from .enums import AuditAction


class AuditLogEventCreate(ContractModel):
    """Create request for one append-only audit event.

    Attributes:
        request_id: Request id shared across policy, action, and response.
        actor: Caller responsible for the action.
        action: Audited action.
        resource_type: Resource family.
        resource_id: Optional concrete resource id.
        policy_decision_id: Optional policy decision carried by the action.
        success: Whether the action succeeded.
        details: Small scalar details with no raw content or secrets.
    """

    request_id: str
    actor: ActorRef
    action: AuditAction
    resource_type: str
    resource_id: str | None = None
    policy_decision_id: str | None = None
    success: bool
    details: dict[str, JsonScalar] = Field(default_factory=dict)


class AuditLogEvent(ContractModel):
    """Persisted append-only audit event.

    Attributes:
        audit_id: Stable audit event id.
        request_id: Request id shared across the flow.
        actor: Caller responsible for the action.
        action: Audited action.
        resource_type: Resource family.
        resource_id: Optional concrete resource id.
        policy_decision_id: Optional policy decision carried by the action.
        success: Whether the action succeeded.
        details: Small scalar details with no raw content or secrets.
        created_at: Persistence time.
    """

    audit_id: str
    request_id: str
    actor: ActorRef
    action: AuditAction
    resource_type: str
    resource_id: str | None
    policy_decision_id: str | None
    success: bool
    details: dict[str, JsonScalar]
    created_at: datetime
