"""Repository for lightweight Workbench event change notifications."""

from __future__ import annotations

import json
import sqlite3

from packages.contracts import EventChange
from packages.contracts.common import JsonScalar
from packages.contracts.enums import EventChangeType

from .database import SQLiteDatabase


class EventChangeRepository:
    """Persist event-scoped update notifications for long-polling clients."""

    def __init__(self, database: SQLiteDatabase) -> None:
        """Create an event change repository."""

        self.database = database

    def append(self, *, event_id: str, change_type: EventChangeType, payload: dict[str, JsonScalar]) -> EventChange:
        """Append one event change and return its typed row.

        Args:
            event_id: Event that changed.
            change_type: Typed change category.
            payload: Small scalar payload for long-polling clients.

        Returns:
            Persisted change record.

        Raises:
            RuntimeError: Raised if SQLite does not return the inserted row.
        """

        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO event_changes(event_id, change_type, payload, created_at)
                VALUES (?, ?, ?, datetime('now'))
                """,
                (event_id, change_type.value, encoded),
            )
            row = connection.execute(
                """
                SELECT change_id, event_id, change_type, payload, created_at
                FROM event_changes
                WHERE change_id = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to append event change")
        return self._row_to_change(row)

    def list_since(self, *, event_id: str, since: int, limit: int = 20) -> tuple[EventChange, ...]:
        """List event changes newer than a known revision.

        Args:
            event_id: Event whose changes should be listed.
            since: Last observed change id.
            limit: Maximum number of records returned.

        Returns:
            Ordered change records newer than ``since``.
        """

        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT change_id, event_id, change_type, payload, created_at
                FROM event_changes
                WHERE event_id = ? AND change_id > ?
                ORDER BY change_id ASC
                LIMIT ?
                """,
                (event_id, since, limit),
            ).fetchall()
        return tuple(self._row_to_change(row) for row in rows)

    def latest_id(self, event_id: str) -> int:
        """Return the latest change id for an event.

        Args:
            event_id: Event whose latest revision should be loaded.

        Returns:
            Latest event change id, or zero if no change exists.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT MAX(change_id) AS latest FROM event_changes WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        if row is None or row["latest"] is None:
            return 0
        return int(row["latest"])

    def _row_to_change(self, row: sqlite3.Row) -> EventChange:
        payload_raw = json.loads(str(row["payload"]))
        payload = payload_raw if isinstance(payload_raw, dict) else {}
        return EventChange(
            change_id=int(row["change_id"]),
            event_id=str(row["event_id"]),
            change_type=EventChangeType(str(row["change_type"])),
            payload={
                key: value
                for key, value in payload.items()
                if isinstance(value, (str, int, float, bool)) or value is None
            },
            created_at=str(row["created_at"]),
        )
