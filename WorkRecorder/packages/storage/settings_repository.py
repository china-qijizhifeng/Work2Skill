"""Repository for local daemon settings that are safe to persist in SQLite."""

from __future__ import annotations

import json
from typing import TypeAlias

from packages.contracts.common import JsonScalar

from .database import SQLiteDatabase

JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = dict[str, JsonValue]


class LocalSettingsRepository:
    """Persist non-secret local settings as typed JSON payloads."""

    def __init__(self, database: SQLiteDatabase) -> None:
        """Create a local settings repository."""

        self.database = database

    def get(self, key: str) -> JsonObject | None:
        """Return settings by key.

        Args:
            key: Stable settings namespace, for example ``visual_ocr``.

        Returns:
            Persisted JSON object, or ``None`` when the key has not been saved.
        """

        with self.database.transaction() as connection:
            row = connection.execute("SELECT payload FROM local_settings WHERE settings_key = ?", (key,)).fetchone()
        if row is None:
            return None
        payload = json.loads(str(row["payload"]))
        if not isinstance(payload, dict):
            return None
        return payload

    def set(self, key: str, payload: JsonObject) -> None:
        """Save settings by key.

        Args:
            key: Stable settings namespace.
            payload: Non-secret JSON object to persist.
        """

        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO local_settings(settings_key, payload, updated_at)
                VALUES (?, ?, datetime('now'))
                ON CONFLICT(settings_key) DO UPDATE SET
                  payload = excluded.payload,
                  updated_at = excluded.updated_at
                """,
                (key, encoded),
            )
