"""Shared context-share exceptions mapped to stable API error codes."""

from __future__ import annotations

from packages.contracts import ErrorCode


class ShareAccessError(RuntimeError):
    """Share-layer validation error that maps cleanly to API errors."""

    def __init__(self, message: str, *, code: ErrorCode = ErrorCode.VALIDATION_ERROR) -> None:
        super().__init__(message)
        self.code = code
