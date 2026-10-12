"""Repository for persisted context events."""

from __future__ import annotations

from packages.contracts import ContextEvent, EventStatus

from .database import SQLiteDatabase


class ContextEventRepository:
    """Persist and retrieve context events through SQLite."""

    def __init__(self, database: SQLiteDatabase) -> None:
        """Create an event repository.

        Args:
            database: Database wrapper used for all operations.
        """

        self.database = database

    def save(self, event: ContextEvent) -> ContextEvent:
        """Insert or replace one context event.

        Args:
            event: Event contract to persist.

        Returns:
            Persisted event.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO context_events(event_id, status, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.status.value,
                    event.model_dump_json(),
                    event.created_at.isoformat(),
                    event.updated_at.isoformat(),
                ),
            )
        return event

    def get(self, event_id: str) -> ContextEvent | None:
        """Return one event by id.

        Args:
            event_id: Event identifier.

        Returns:
            Event when found, otherwise ``None``.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM context_events WHERE event_id = ? AND status NOT IN (?, ?)",
                (event_id, EventStatus.DELETED.value, EventStatus.RESTRICTED.value),
            ).fetchone()
        if row is None:
            return None
        return ContextEvent.model_validate_json(str(row["payload"]))

    def get_including_deleted(self, event_id: str) -> ContextEvent | None:
        """Return one event including its soft-deleted tombstone."""

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM context_events WHERE event_id = ? AND status != ?",
                (event_id, EventStatus.RESTRICTED.value),
            ).fetchone()
        if row is None:
            return None
        return ContextEvent.model_validate_json(str(row["payload"]))

    def list_by_ids(self, event_ids: tuple[str, ...]) -> tuple[ContextEvent, ...]:
        """Return visible events for a bounded set of ids."""

        if not event_ids:
            return ()
        placeholders = ",".join("?" for _ in event_ids)
        with self.database.transaction() as connection:
            rows = connection.execute(
                f"""
                SELECT payload FROM context_events
                WHERE event_id IN ({placeholders}) AND status NOT IN (?, ?)
                """,
                (*event_ids, EventStatus.DELETED.value, EventStatus.RESTRICTED.value),
            ).fetchall()
        events_by_id = {
            event.event_id: event for event in (ContextEvent.model_validate_json(str(row["payload"])) for row in rows)
        }
        return tuple(event for event_id in event_ids if (event := events_by_id.get(event_id)) is not None)

    def list(self, *, limit: int = 50) -> tuple[ContextEvent, ...]:
        """List recent non-deleted events.

        Args:
            limit: Maximum number of events returned.

        Returns:
            Events sorted by creation time descending.
        """

        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM context_events
                WHERE status NOT IN (?, ?)
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (EventStatus.DELETED.value, EventStatus.RESTRICTED.value, limit),
            ).fetchall()
        return tuple(ContextEvent.model_validate_json(str(row["payload"])) for row in rows)

    def list_by_active_capture_candidate_id(self, candidate_id: str, *, limit: int = 20) -> tuple[ContextEvent, ...]:
        """Return visible capture events bound to one active-capture candidate.

        The active-capture candidate id is stored in the event trigger metadata
        by native capture persistence. SQLite JSON support is not assumed here,
        so the query uses a bounded payload prefilter and verifies the typed
        trigger metadata after decoding.
        """

        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM context_events
                WHERE payload LIKE ? AND status NOT IN (?, ?)
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (
                    f"%{candidate_id}%",
                    EventStatus.DELETED.value,
                    EventStatus.RESTRICTED.value,
                    limit,
                ),
            ).fetchall()
        events = (ContextEvent.model_validate_json(str(row["payload"])) for row in rows)
        return tuple(
            event for event in events if event.trigger.metadata.get("active_capture_candidate_id") == candidate_id
        )

    def mark_deleted(self, event_id: str, *, deleted_payload: ContextEvent) -> ContextEvent:
        """Persist a deleted event tombstone.

        Args:
            event_id: Event identifier.
            deleted_payload: Event contract with deleted status.

        Returns:
            Deleted event payload.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                UPDATE context_events
                SET status = ?, payload = ?, updated_at = ?
                WHERE event_id = ?
                """,
                (
                    EventStatus.DELETED.value,
                    deleted_payload.model_dump_json(),
                    deleted_payload.updated_at.isoformat(),
                    event_id,
                ),
            )
        return deleted_payload
