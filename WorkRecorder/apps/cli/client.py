"""HTTP client used by the WorkRecorder Typer CLI."""

from __future__ import annotations

from collections.abc import Mapping

import httpx

from packages.contracts import AccessScope, ErrorCode


class DaemonClientError(RuntimeError):
    """Raised when the daemon returns a non-success envelope."""

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        details: Mapping[str, object] | None = None,
        request_id: str | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = dict(details or {})
        self.request_id = request_id
        self.status_code = status_code


class DaemonClient:
    """Small typed wrapper around the local daemon HTTP API."""

    def __init__(self, *, base_url: str, install_secret: str) -> None:
        """Create a daemon client.

        Args:
            base_url: Local daemon base URL.
            install_secret: Per-install secret used to request short tokens.
        """

        self.base_url = base_url.rstrip("/")
        self.install_secret = install_secret

    def health(self) -> Mapping[str, object]:
        """Return daemon health payload.

        Returns:
            Decoded JSON response.
        """

        response = httpx.get(f"{self.base_url}/health", timeout=5)
        return self._json_payload(response)

    def get(
        self,
        path: str,
        *,
        scopes: tuple[AccessScope, ...],
        agent_run_id: str | None = None,
        context_query_id: str | None = None,
    ) -> Mapping[str, object]:
        """Run an authenticated GET request.

        Args:
            path: API path starting with a slash.
            scopes: Scopes requested for the short token.

        Returns:
            Decoded JSON response envelope.
        """

        token = self._issue_token(scopes=scopes)
        response = httpx.get(
            f"{self.base_url}{path}",
            headers=self._auth_headers(token, agent_run_id=agent_run_id, context_query_id=context_query_id),
            timeout=60,
        )
        return self._json_payload(response)

    def post(
        self,
        path: str,
        *,
        body: object,
        scopes: tuple[AccessScope, ...],
        agent_run_id: str | None = None,
        context_query_id: str | None = None,
    ) -> Mapping[str, object]:
        """Run an authenticated POST request.

        Args:
            path: API path starting with a slash.
            body: JSON-serializable request body.
            scopes: Scopes requested for the short token.

        Returns:
            Decoded JSON response envelope.
        """

        token = self._issue_token(scopes=scopes)
        response = httpx.post(
            f"{self.base_url}{path}",
            json=body,
            headers=self._auth_headers(token, agent_run_id=agent_run_id, context_query_id=context_query_id),
            timeout=60,
        )
        return self._json_payload(response)

    def delete(
        self,
        path: str,
        *,
        scopes: tuple[AccessScope, ...],
        agent_run_id: str | None = None,
        context_query_id: str | None = None,
    ) -> Mapping[str, object]:
        """Run an authenticated DELETE request.

        Args:
            path: API path starting with a slash.
            scopes: Scopes requested for the short token.

        Returns:
            Decoded JSON response envelope.
        """

        token = self._issue_token(scopes=scopes)
        response = httpx.delete(
            f"{self.base_url}{path}",
            headers=self._auth_headers(token, agent_run_id=agent_run_id, context_query_id=context_query_id),
            timeout=10,
        )
        return self._json_payload(response)

    def _issue_token(self, *, scopes: tuple[AccessScope, ...]) -> str:
        response = httpx.post(
            f"{self.base_url}/v1/auth/tokens",
            headers={"x-workrecorder-install-secret": self.install_secret},
            json={
                "actor_id": "local-cli",
                "display_name": "WorkRecorder CLI",
                "scopes": [scope.value for scope in scopes],
            },
            timeout=5,
        )
        payload = self._json_payload(response)
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("token response missing data")
        token = data.get("access_token")
        if not isinstance(token, str):
            raise RuntimeError("token response missing access_token")
        return token

    def _auth_headers(
        self, token: str, *, agent_run_id: str | None = None, context_query_id: str | None = None
    ) -> dict[str, str]:
        headers = {"authorization": f"Bearer {token}"}
        if agent_run_id:
            headers["x-workrecorder-agent-run-id"] = agent_run_id
        if context_query_id:
            headers["x-workrecorder-context-query-id"] = context_query_id
        return headers

    def _json_payload(self, response: httpx.Response) -> Mapping[str, object]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise DaemonClientError(
                f"daemon returned non-JSON response: HTTP {response.status_code}",
                status_code=response.status_code,
            ) from exc
        if not isinstance(payload, dict):
            raise DaemonClientError("daemon returned non-object JSON", status_code=response.status_code)
        if response.status_code >= 400:
            message, code, details, request_id = self._error_fields(payload)
            raise DaemonClientError(
                message or f"daemon request failed: HTTP {response.status_code}",
                code=code,
                details=details,
                request_id=request_id,
                status_code=response.status_code,
            )
        if payload.get("ok") is False:
            message, code, details, request_id = self._error_fields(payload)
            raise DaemonClientError(
                message or "daemon returned an error envelope",
                code=code,
                details=details,
                request_id=request_id,
                status_code=response.status_code,
            )
        return payload

    def _error_fields(
        self, payload: Mapping[str, object]
    ) -> tuple[str | None, ErrorCode, Mapping[str, object], str | None]:
        error = payload.get("error")
        message: str | None = None
        code = ErrorCode.INTERNAL_ERROR
        details: Mapping[str, object] = {}
        if isinstance(error, dict):
            raw_message = error.get("message")
            if isinstance(raw_message, str):
                message = raw_message
            raw_code = error.get("code")
            if isinstance(raw_code, str):
                try:
                    code = ErrorCode(raw_code)
                except ValueError:
                    code = ErrorCode.INTERNAL_ERROR
            raw_details = error.get("details")
            if isinstance(raw_details, dict):
                details = {str(key): value for key, value in raw_details.items()}
        request_id = payload.get("request_id")
        return message, code, details, request_id if isinstance(request_id, str) else None
