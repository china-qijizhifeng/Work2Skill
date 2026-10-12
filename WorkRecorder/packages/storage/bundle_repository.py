"""Repositories for context bundles and usage events."""

from __future__ import annotations

from packages.contracts import AgentUsageEvent, ContextBundle

from .database import SQLiteDatabase


class ContextBundleRepository:
    """Persist retrieval-time context bundle manifests."""

    def __init__(self, database: SQLiteDatabase) -> None:
        """Create a context bundle repository.

        Args:
            database: Database wrapper used for all operations.
        """

        self.database = database

    def save(self, bundle: ContextBundle) -> ContextBundle:
        """Persist one context bundle.

        Args:
            bundle: Bundle contract to persist.

        Returns:
            Persisted context bundle.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO context_bundles(bundle_id, query, purpose, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    bundle.bundle_id,
                    bundle.query,
                    bundle.purpose,
                    bundle.model_dump_json(),
                    bundle.created_at.isoformat(),
                ),
            )
        return bundle

    def get(self, bundle_id: str) -> ContextBundle | None:
        """Return one bundle by id.

        Args:
            bundle_id: Bundle identifier.

        Returns:
            Bundle when found, otherwise ``None``.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM context_bundles WHERE bundle_id = ?",
                (bundle_id,),
            ).fetchone()
        if row is None:
            return None
        return ContextBundle.model_validate_json(str(row["payload"]))


class AgentUsageRepository:
    """Persist consumer-agent usage events."""

    def __init__(self, database: SQLiteDatabase) -> None:
        """Create a usage repository.

        Args:
            database: Database wrapper used for all operations.
        """

        self.database = database

    def save(self, usage: AgentUsageEvent) -> AgentUsageEvent:
        """Persist one usage event.

        Args:
            usage: Usage event contract to persist.

        Returns:
            Persisted usage event.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO agent_usage_events(usage_id, bundle_id, agent, purpose, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    usage.usage_id,
                    usage.bundle_id,
                    usage.agent,
                    usage.purpose,
                    usage.model_dump_json(),
                    usage.created_at.isoformat(),
                ),
            )
        return usage
