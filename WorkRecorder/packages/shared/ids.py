"""Stable identifier generation for WorkRecorder domain objects."""

from __future__ import annotations

import secrets


class IdFactory:
    """Generate short prefixed identifiers for local product objects."""

    def new(self, prefix: str) -> str:
        """Return a new opaque identifier.

        Args:
            prefix: Human-readable id prefix such as ``evt`` or ``aud``.

        Returns:
            Identifier with the requested prefix and URL-safe entropy.
        """

        return f"{prefix}_{secrets.token_urlsafe(12)}"
