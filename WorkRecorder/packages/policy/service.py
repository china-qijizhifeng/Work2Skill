"""Policy orchestration that persists decisions and audit events."""

from __future__ import annotations

from packages.audit.writer import AuditWriter
from packages.contracts import AccessRequest, AgentRunToken, AuditAction, AuditLogEventCreate, PolicyDecision
from packages.policy.evaluator import PolicyEvaluator
from packages.storage.security_repository import PolicyDecisionRepository


class AuthorizationService:
    """Evaluate access requests, persist decisions, and audit checks."""

    def __init__(
        self,
        *,
        evaluator: PolicyEvaluator,
        decisions: PolicyDecisionRepository,
        audits: AuditWriter,
    ) -> None:
        """Create an authorization service.

        Args:
            evaluator: Deterministic policy evaluator.
            decisions: Repository for policy decisions.
            audits: Audit writer for policy-check events.
        """

        self.evaluator = evaluator
        self.decisions = decisions
        self.audits = audits

    def authorize(self, *, request: AccessRequest, token: AgentRunToken, request_id: str) -> PolicyDecision:
        """Evaluate and record one access request.

        Args:
            request: Requested action and resource.
            token: Caller token claims.
            request_id: Daemon request id.

        Returns:
            Persisted policy decision.
        """

        decision = self.decisions.save(self.evaluator.evaluate(request=request, token=token))
        self.audits.record(
            AuditLogEventCreate(
                request_id=request_id,
                actor=decision.actor,
                action=AuditAction.POLICY_CHECKED,
                resource_type=request.resource_type,
                resource_id=request.resource_id,
                policy_decision_id=decision.decision_id,
                success=True,
                details={"effect": decision.effect.value},
            )
        )
        return decision
