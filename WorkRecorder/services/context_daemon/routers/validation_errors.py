"""Safe validation-error formatting for local daemon routes."""

from __future__ import annotations

import json

from pydantic import ValidationError

from packages.contracts.common import JsonScalar

MAX_VALIDATION_ERROR_CHARS = 8_192


def safe_validation_error_details(exc: ValidationError) -> dict[str, JsonScalar]:
    """Return validation details without echoing user-provided input values.

    Args:
        exc: Pydantic validation error raised while parsing a request body.

    Returns:
        JSON-scalar diagnostics suitable for `ResponseFactory.error`.
    """

    errors = exc.errors(include_input=False, include_context=False)
    rendered = json.dumps(errors, ensure_ascii=False, separators=(",", ":"))
    if len(rendered) > MAX_VALIDATION_ERROR_CHARS:
        rendered = rendered[:MAX_VALIDATION_ERROR_CHARS] + "...[truncated]"
    return {"errors": rendered}
