"""Shared CLI error handling for stable agent-facing JSON envelopes."""

from __future__ import annotations

import os

import click
import httpx
import typer

from packages.contracts import ErrorCode

from .client import DaemonClientError
from .output import OutputWriter


def run_cli_app(app: typer.Typer, *, writer: OutputWriter) -> int | None:
    """Run the Typer app and convert expected failures into JSON envelopes.

    Args:
        app: Typer application to execute.
        writer: Output writer used for stable agent-facing error envelopes.

    Returns:
        ``None`` on success or ``1`` after writing an expected error envelope.

    Raises:
        DaemonClientError: Re-raised when ``WORKRECORDER_CLI_DEBUG`` is set.
        click.ClickException: Re-raised when ``WORKRECORDER_CLI_DEBUG`` is set.
        httpx.HTTPError: Re-raised when ``WORKRECORDER_CLI_DEBUG`` is set.
        RuntimeError: Re-raised when ``WORKRECORDER_CLI_DEBUG`` is set.
        ValueError: Re-raised when ``WORKRECORDER_CLI_DEBUG`` is set.
    """

    try:
        app(standalone_mode=False)
    except DaemonClientError as exc:
        if os.environ.get("WORKRECORDER_CLI_DEBUG"):
            raise
        writer.write_error(
            exc.message,
            code=exc.code,
            details=exc.details,
            request_id=exc.request_id or "cli_error",
        )
        return 1
    except click.ClickException as exc:
        if os.environ.get("WORKRECORDER_CLI_DEBUG"):
            raise
        writer.write_error(str(exc), code=ErrorCode.VALIDATION_ERROR)
        return 1
    except (httpx.HTTPError, RuntimeError, ValueError) as exc:
        if os.environ.get("WORKRECORDER_CLI_DEBUG"):
            raise
        writer.write_error(str(exc), code=ErrorCode.INTERNAL_ERROR)
        return 1
    return None
