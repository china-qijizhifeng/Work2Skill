from __future__ import annotations

import pytest

from packages.contracts import AccessRequest, AccessScope, ActorRef, PolicyEffect
from packages.policy.evaluator import PolicyEvaluator
from packages.policy.tokens import LocalTokenService, TokenError
from packages.shared.ids import IdFactory
from packages.shared.time import Clock


def test_policy_allows_declared_scope():
    ids = IdFactory()
    clock = Clock()
    token_service = LocalTokenService(secret="secret-value", audience="test", ttl_seconds=600, ids=ids, clock=clock)
    _, token = token_service.issue(actor=ActorRef(actor_id="agent"), scopes=(AccessScope.READ_METADATA,))
    request = AccessRequest(actor=token.actor, action=AccessScope.READ_METADATA, resource_type="event")
    decision = PolicyEvaluator(ids=ids, clock=clock).evaluate(request=request, token=token)
    assert decision.effect == PolicyEffect.ALLOW


def test_policy_denies_missing_scope():
    ids = IdFactory()
    clock = Clock()
    token_service = LocalTokenService(secret="secret-value", audience="test", ttl_seconds=600, ids=ids, clock=clock)
    _, token = token_service.issue(actor=ActorRef(actor_id="agent"), scopes=(AccessScope.READ_METADATA,))
    request = AccessRequest(actor=token.actor, action=AccessScope.READ_IMAGE, resource_type="artifact")
    decision = PolicyEvaluator(ids=ids, clock=clock).evaluate(request=request, token=token)
    assert decision.effect == PolicyEffect.DENY


def test_policy_denies_actor_mismatch():
    ids = IdFactory()
    clock = Clock()
    token_service = LocalTokenService(secret="secret-value", audience="test", ttl_seconds=600, ids=ids, clock=clock)
    _, token = token_service.issue(actor=ActorRef(actor_id="agent"), scopes=(AccessScope.READ_METADATA,))
    request = AccessRequest(
        actor=ActorRef(actor_id="other-agent"),
        action=AccessScope.READ_METADATA,
        resource_type="event",
    )
    decision = PolicyEvaluator(ids=ids, clock=clock).evaluate(request=request, token=token)
    assert decision.effect == PolicyEffect.DENY
    assert decision.actor.actor_id == "agent"
    assert decision.reason_codes == ("actor.mismatch",)


@pytest.mark.parametrize("token", ["not-a-token", "abc.def", "!!!.sig"])
def test_token_service_rejects_malformed_tokens(token: str):
    ids = IdFactory()
    clock = Clock()
    token_service = LocalTokenService(secret="secret-value", audience="test", ttl_seconds=600, ids=ids, clock=clock)
    with pytest.raises(TokenError):
        token_service.verify(token)
