"""Shared API error code enums."""

from __future__ import annotations

from enum import StrEnum


class ErrorCode(StrEnum):
    """Stable machine-readable error codes for API and CLI envelopes."""

    AUTH_MISSING = "auth.missing"
    AUTH_INVALID = "auth.invalid"
    POLICY_DENIED = "policy.denied"
    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    NOT_IMPLEMENTED = "not_implemented"
    INTERNAL_ERROR = "internal_error"
