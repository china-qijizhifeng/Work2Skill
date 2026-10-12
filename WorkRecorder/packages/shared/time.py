"""Clock abstraction for deterministic tests and daemon services."""

from __future__ import annotations

from datetime import UTC, datetime


class Clock:
    """Provide timezone-aware timestamps through an injectable object."""

    def now(self) -> datetime:
        """Return the current UTC time.

        Returns:
            Timezone-aware UTC timestamp.
        """

        return datetime.now(tz=UTC)
