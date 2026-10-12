"""SQLite persistence for click target resolutions."""

from __future__ import annotations

from typing import Protocol

from packages.contracts import ClickTargetCandidate, ClickTargetResolution, HumanActionEvent
from packages.storage.database import SQLiteDatabase

ACTION_TARGET_READ_CHUNK_SIZE = 800


class _HasDatabase(Protocol):
    database: SQLiteDatabase


class SQLiteClickTargetRepositoryMixin:
    """SQLite helpers for the click target bounded context."""

    database: SQLiteDatabase

    def get_human_action(self: _HasDatabase, action_id: str) -> HumanActionEvent | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM human_action_events WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        if row is None:
            return None
        return HumanActionEvent.model_validate_json(str(row["payload"]))

    def save_click_target_resolution_graph(
        self: _HasDatabase,
        *,
        resolution: ClickTargetResolution,
        candidates: tuple[ClickTargetCandidate, ...],
    ) -> ClickTargetResolution:
        with self.database.transaction() as connection:
            existing = connection.execute(
                """
                SELECT resolution_id, payload
                FROM action_target_resolutions
                WHERE action_id = ? AND resolver_version = ? AND input_fingerprint = ?
                """,
                (resolution.action_id, resolution.resolver_version, resolution.input_fingerprint),
            ).fetchone()
            stored_resolution = resolution
            if existing is not None:
                previous = ClickTargetResolution.model_validate_json(str(existing["payload"]))
                stored_resolution = resolution.model_copy(
                    update={
                        "resolution_id": str(existing["resolution_id"]),
                        "created_at": previous.created_at,
                        "candidate_ids": tuple(candidate.candidate_id for candidate in candidates),
                    }
                )
            connection.execute(
                """
                INSERT INTO action_target_resolutions(
                  resolution_id, action_id, session_id, status, semantic_kind, confidence,
                  input_fingerprint, resolver_version, payload, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(action_id, resolver_version, input_fingerprint) DO UPDATE SET
                  status = excluded.status,
                  semantic_kind = excluded.semantic_kind,
                  confidence = excluded.confidence,
                  payload = excluded.payload,
                  updated_at = excluded.updated_at
                """,
                (
                    stored_resolution.resolution_id,
                    stored_resolution.action_id,
                    stored_resolution.session_id,
                    stored_resolution.status.value,
                    stored_resolution.semantic_kind.value,
                    stored_resolution.confidence,
                    stored_resolution.input_fingerprint,
                    stored_resolution.resolver_version,
                    stored_resolution.model_dump_json(),
                    stored_resolution.created_at.isoformat(),
                    stored_resolution.updated_at.isoformat(),
                ),
            )
            connection.execute(
                "DELETE FROM action_target_candidates WHERE resolution_id = ?",
                (stored_resolution.resolution_id,),
            )
            for candidate in candidates:
                stored_candidate = candidate.model_copy(update={"resolution_id": stored_resolution.resolution_id})
                connection.execute(
                    """
                    INSERT OR REPLACE INTO action_target_candidates(
                      candidate_id, resolution_id, action_id, session_id, source_kind,
                      semantic_kind, confidence, payload, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        stored_candidate.candidate_id,
                        stored_candidate.resolution_id,
                        stored_candidate.action_id,
                        stored_candidate.session_id,
                        stored_candidate.source_kind.value,
                        stored_candidate.semantic_kind.value,
                        stored_candidate.confidence,
                        stored_candidate.model_dump_json(),
                        stored_candidate.created_at.isoformat(),
                    ),
                )
        return stored_resolution

    def list_click_target_resolutions_for_actions(
        self: _HasDatabase, action_ids: tuple[str, ...]
    ) -> tuple[ClickTargetResolution, ...]:
        if not action_ids:
            return ()
        latest: dict[str, ClickTargetResolution] = {}
        with self.database.transaction() as connection:
            for index in range(0, len(action_ids), ACTION_TARGET_READ_CHUNK_SIZE):
                chunk = action_ids[index : index + ACTION_TARGET_READ_CHUNK_SIZE]
                placeholders = ",".join("?" for _ in chunk)
                rows = connection.execute(
                    f"""
                    SELECT r.payload
                    FROM action_target_resolutions r
                    JOIN human_action_events a ON a.action_id = r.action_id
                    WHERE r.action_id IN ({placeholders})
                    ORDER BY a.sequence_index ASC, r.updated_at DESC, r.resolution_id ASC
                    """,
                    chunk,
                ).fetchall()
                for row in rows:
                    resolution = ClickTargetResolution.model_validate_json(str(row["payload"]))
                    latest.setdefault(resolution.action_id, resolution)
        return tuple(latest[action_id] for action_id in action_ids if action_id in latest)
