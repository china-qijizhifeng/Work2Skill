"""Repository for artifact metadata."""

from __future__ import annotations

from packages.contracts import Artifact

from .database import SQLiteDatabase


class ArtifactRepository:
    """Persist and retrieve artifact metadata, never raw content."""

    def __init__(self, database: SQLiteDatabase) -> None:
        """Create an artifact repository.

        Args:
            database: Database wrapper used for all operations.
        """

        self.database = database

    def save(self, artifact: Artifact) -> Artifact:
        """Insert or replace one artifact metadata record.

        Args:
            artifact: Artifact contract to persist.

        Returns:
            Persisted artifact.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO artifacts(artifact_id, event_id, artifact_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    artifact.artifact_id,
                    artifact.event_id,
                    artifact.artifact_type.value,
                    artifact.model_dump_json(),
                    artifact.created_at.isoformat(),
                ),
            )
        return artifact

    def get(self, artifact_id: str) -> Artifact | None:
        """Return one artifact by id.

        Args:
            artifact_id: Artifact identifier.

        Returns:
            Artifact when found, otherwise ``None``.
        """

        with self.database.transaction() as connection:
            row = connection.execute("SELECT payload FROM artifacts WHERE artifact_id = ?", (artifact_id,)).fetchone()
        if row is None:
            return None
        return Artifact.model_validate_json(str(row["payload"]))

    def list_for_event(self, event_id: str) -> tuple[Artifact, ...]:
        """List artifacts for one event.

        Args:
            event_id: Event identifier.

        Returns:
            Artifacts in creation order.
        """

        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT payload FROM artifacts WHERE event_id = ? ORDER BY created_at ASC",
                (event_id,),
            ).fetchall()
        return tuple(Artifact.model_validate_json(str(row["payload"])) for row in rows)

    def count_by_storage_uri(self, storage_uri: str) -> int:
        """Return how many artifact metadata rows reference one vault URI."""

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM artifacts WHERE json_extract(payload, '$.storage_uri') = ?",
                (storage_uri,),
            ).fetchone()
        return int(row["count"])

    def delete_for_event_by_provider(self, *, event_id: str, provider_key: str) -> int:
        """Delete artifact metadata for one event/provider pair.

        Args:
            event_id: Event whose imported artifacts should be replaced.
            provider_key: Provider namespace that created the artifacts.

        Returns:
            Number of artifact rows removed.
        """

        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                DELETE FROM artifacts
                WHERE event_id = ?
                  AND json_extract(payload, '$.provider_key') = ?
                """,
                (event_id, provider_key),
            )
            return int(cursor.rowcount or 0)
