"""CLI output rendering helpers."""

from __future__ import annotations

import json
from collections.abc import Mapping

import typer

from packages.contracts import ErrorCode


class OutputWriter:
    """Render daemon responses in agent-friendly JSON form."""

    def write_json(self, payload: Mapping[str, object]) -> None:
        """Write a JSON payload to stdout.

        Args:
            payload: Response payload decoded from the daemon.
        """

        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))

    def write_error(
        self,
        message: str,
        *,
        code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        details: Mapping[str, object] | None = None,
        request_id: str = "cli_error",
    ) -> None:
        """Write a stable error envelope to stderr.

        Args:
            message: Safe error message.
            code: Stable daemon-compatible error code.
        """

        payload: dict[str, object] = {
            "ok": False,
            "data": None,
            "error": {"code": code.value, "message": message, "details": dict(details or {})},
            "request_id": request_id,
            "audit_id": None,
        }
        typer.echo(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), err=True)
