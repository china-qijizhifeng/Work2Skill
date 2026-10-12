"""Authentication helpers for local daemon routes."""

from __future__ import annotations

from fastapi import Request

from packages.contracts import AgentRunToken, ApiError, ErrorCode
from packages.policy.tokens import TokenError

from .container import DaemonContainer


class DaemonAuth:
    """Extract and verify local daemon bearer tokens."""

    def claims_from_request(self, request: Request, container: DaemonContainer) -> AgentRunToken | ApiError:
        """Return token claims or a structured auth error.

        Args:
            request: FastAPI request carrying headers.
            container: Daemon service container.

        Returns:
            Decoded claims on success, otherwise an API error body.
        """

        authorization = request.headers.get("authorization")
        if authorization is None or not authorization.lower().startswith("bearer "):
            return ApiError(code=ErrorCode.AUTH_MISSING, message="Missing bearer token", details={})
        token = authorization.split(" ", 1)[1].strip()
        try:
            return container.tokens.verify(token)
        except TokenError:
            return ApiError(code=ErrorCode.AUTH_INVALID, message="Invalid bearer token", details={})

    def install_secret_matches(self, request: Request, container: DaemonContainer) -> bool:
        """Check whether a request carries the local install secret.

        Args:
            request: FastAPI request carrying headers.
            container: Daemon service container.

        Returns:
            ``True`` when the secret matches.
        """

        return request.headers.get("x-workrecorder-install-secret") == container.settings.install_secret

    def provider_registration_secret_matches(self, request: Request, container: DaemonContainer) -> bool:
        """Check whether a request carries the provider-registration secret.

        Browser extensions and other provider shims only need authority to
        obtain ``register_provider_context`` tokens. They must never receive the
        broader install secret used by CLI and Workbench callers.
        """

        expected = container.settings.provider_registration_secret
        if expected == container.settings.install_secret:
            return False
        return request.headers.get("x-workrecorder-provider-secret") == expected

    def native_capture_secret_matches(self, request: Request, container: DaemonContainer) -> bool:
        """Check whether a request carries the native-only capture secret.

        Current-window native timing needs a secret that only the macOS shell
        receives. It intentionally does not fall back to the install secret.
        """

        expected = container.settings.native_capture_secret
        if expected is None or expected == container.settings.install_secret:
            return False
        return request.headers.get("x-workrecorder-native-capture-secret") == expected
