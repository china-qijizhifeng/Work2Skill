"""Deterministic policy evaluator for P0 local daemon actions."""

from __future__ import annotations

from packages.contracts import AccessRequest, AgentRunToken, PolicyDecision, PolicyEffect
from packages.shared.ids import IdFactory
from packages.shared.time import Clock


class PolicyEvaluator:
    """Evaluate typed access requests against short-lived token scopes."""

    def __init__(self, *, ids: IdFactory, clock: Clock) -> None:
        """Create a policy evaluator.

        Args:
            ids: Identifier generator.
            clock: Clock used for decision timestamps.
        """

        self.ids = ids
        self.clock = clock

    def evaluate(self, *, request: AccessRequest, token: AgentRunToken) -> PolicyDecision:
        """Return a policy decision for one action.

        Args:
            request: Requested action and resource.
            token: Decoded caller token.

        Returns:
            Policy decision. Missing scopes always deny.
        """

        if request.actor != token.actor:
            effect = PolicyEffect.DENY
            reasons = ("actor.mismatch",)
        elif request.action in token.scopes:
            effect = PolicyEffect.ALLOW
            reasons = ("scope.allowed",)
        else:
            effect = PolicyEffect.DENY
            reasons = ("scope.missing",)
        return PolicyDecision(
            decision_id=self.ids.new("pol"),
            effect=effect,
            actor=token.actor,
            action=request.action,
            resource_type=request.resource_type,
            resource_id=request.resource_id,
            reason_codes=reasons,
            evaluated_at=self.clock.now(),
            details={"token_id": token.token_id, "requested_actor_id": request.actor.actor_id},
        )
