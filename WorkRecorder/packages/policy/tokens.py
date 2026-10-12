"""Short-lived local token issuer for daemon and CLI calls."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
from datetime import timedelta

from pydantic import ValidationError

from packages.contracts import AccessScope, ActorRef, AgentRunToken
from packages.shared.ids import IdFactory
from packages.shared.time import Clock


class TokenError(Exception):
    """Raised when a bearer token is missing, malformed, expired, or invalid."""


class LocalTokenService:
    """Issue and verify signed short-lived local daemon tokens."""

    def __init__(self, *, secret: str, audience: str, ttl_seconds: int, ids: IdFactory, clock: Clock) -> None:
        """Create a local token service.

        Args:
            secret: Per-install secret used as HMAC key.
            audience: Expected token audience.
            ttl_seconds: Token lifetime in seconds.
            ids: Identifier generator.
            clock: Clock used for issue and expiry times.
        """

        self.secret = secret.encode("utf-8")
        self.audience = audience
        self.ttl_seconds = ttl_seconds
        self.ids = ids
        self.clock = clock

    def issue(self, *, actor: ActorRef, scopes: tuple[AccessScope, ...]) -> tuple[str, AgentRunToken]:
        """Issue a signed bearer token.

        Args:
            actor: Caller identity.
            scopes: Scopes granted to the caller.

        Returns:
            Pair of encoded token string and decoded token claims.
        """

        issued_at = self.clock.now()
        claims = AgentRunToken(
            token_id=self.ids.new("tok"),
            actor=actor,
            audience=self.audience,
            scopes=scopes,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=self.ttl_seconds),
        )
        payload = claims.model_dump_json().encode("utf-8")
        encoded_payload = self._encode(payload)
        signature = self._sign(encoded_payload)
        return f"{encoded_payload}.{signature}", claims

    def verify(self, token: str) -> AgentRunToken:
        """Verify a signed bearer token.

        Args:
            token: Encoded token string.

        Returns:
            Decoded token claims.

        Raises:
            TokenError: When the token cannot be trusted.
        """

        try:
            encoded_payload, signature = token.split(".", 1)
        except ValueError as exc:
            raise TokenError("malformed token") from exc
        expected = self._sign(encoded_payload)
        if not hmac.compare_digest(signature, expected):
            raise TokenError("invalid signature")
        try:
            payload = base64.urlsafe_b64decode(self._pad(encoded_payload)).decode("utf-8")
            claims = AgentRunToken.model_validate_json(payload)
        except (binascii.Error, UnicodeDecodeError, ValidationError) as exc:
            raise TokenError("malformed token payload") from exc
        if claims.audience != self.audience:
            raise TokenError("invalid audience")
        if claims.expires_at <= self.clock.now():
            raise TokenError("expired token")
        return claims

    def _sign(self, encoded_payload: str) -> str:
        digest = hmac.new(self.secret, encoded_payload.encode("utf-8"), hashlib.sha256).digest()
        return self._encode(digest)

    def _encode(self, payload: bytes) -> str:
        return base64.urlsafe_b64encode(payload).decode("utf-8").rstrip("=")

    def _pad(self, encoded: str) -> bytes:
        return (encoded + "=" * (-len(encoded) % 4)).encode("utf-8")
