"""Protocols for index backend plug-ins."""

from __future__ import annotations

from typing import Protocol

from packages.contracts import IndexHit
from packages.indexing.contracts import IndexHealth, IndexQuery, IndexReceipt, IndexWriteBatch


class IndexBackend(Protocol):
    """Backend plug-in contract used by the index registry."""

    name: str
    version: str

    def upsert(self, batch: IndexWriteBatch) -> IndexReceipt:
        """Insert or replace one event's indexable projections.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""
        ...

    def delete_event(self, event_id: str) -> IndexReceipt:
        """Delete all index rows for one event.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""
        ...

    def search(self, query: IndexQuery) -> tuple[IndexHit, ...]:
        """Return safe hit references, never raw artifact content.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""
        ...

    def facets(self, query: IndexQuery) -> dict[str, tuple[str, ...]]:
        """Return safe metadata facets for CLI discovery commands.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""
        ...

    def facets_for_event_ids(self, query: IndexQuery, event_ids: set[str]) -> dict[str, tuple[str, ...]]:
        """Return safe facets constrained to live-visible event ids.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""
        ...

    def explain(self, hit: IndexHit) -> IndexHit:
        """Attach backend-specific safe explanation to a hit.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""
        ...

    def health(self) -> IndexHealth:
        """Return backend health.

        Returns:
            Availability, degradation state, capabilities, and backend details.
        """
        ...

    def rebuild(self, batches: tuple[IndexWriteBatch, ...]) -> IndexReceipt:
        """Rebuild index contents from daemon-owned projection batches.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""
        ...
