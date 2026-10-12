"""Policy and token contracts for local daemon authorization."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import ContractModel
from .common import ActorRef, JsonScalar
from .enums import AccessScope, PolicyEffect


class AgentRunToken(ContractModel):
    """Decoded short-lived token claims for one local caller.

    Attributes:
        token_id: Stable token id used in audit logs.
        actor: Caller identity bound to the token.
        audience: Intended daemon audience.
        scopes: Granted access scopes.
        issued_at: Token issue time.
        expires_at: Token expiry time.
    """

    token_id: str
    actor: ActorRef
    audience: str
    scopes: tuple[AccessScope, ...]
    issued_at: datetime
    expires_at: datetime


class AccessRequest(ContractModel):
    """Request sent to policy before a sensitive action.

    Attributes:
        actor: Caller identity.
        action: Access scope being requested.
        resource_type: Resource family such as event, artifact, or bundle.
        resource_id: Optional concrete resource id.
        reason: Optional purpose shown in audit and UI.
    """

    actor: ActorRef
    action: AccessScope
    resource_type: str = Field(min_length=1)
    resource_id: str | None = None
    reason: str | None = None


class PolicyDecision(ContractModel):
    """Single authorization result that all sensitive actions must carry.

    Attributes:
        decision_id: Stable decision id.
        effect: Allow, deny, redact, or quarantine.
        actor: Caller evaluated by policy.
        action: Requested action.
        resource_type: Resource family.
        resource_id: Optional concrete resource id.
        reason_codes: Stable reason codes for UI and audit.
        evaluated_at: Evaluation time.
        details: Small scalar debug map without secrets or raw content.
    """

    decision_id: str
    effect: PolicyEffect
    actor: ActorRef
    action: AccessScope
    resource_type: str
    resource_id: str | None
    reason_codes: tuple[str, ...]
    evaluated_at: datetime
    details: dict[str, JsonScalar] = Field(default_factory=dict)
