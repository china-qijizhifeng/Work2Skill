"""Projection-read helpers for the SQLite active-capture adapter."""

from __future__ import annotations

from typing import Protocol

from packages.contracts import ActionEvidenceLink, ActionResultObservation, KeyframeEvidenceLink
from packages.storage.database import SQLiteDatabase


class _HasDatabase(Protocol):
    database: SQLiteDatabase


class SQLiteProjectionReadRepositoryMixin:
    """Bounded read helpers used by active-capture projections."""

    database: SQLiteDatabase

    def count_keyframes_for_session(self: _HasDatabase, session_id: str) -> int:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM context_keyframes WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["count"])

    def list_evidence_links_for_keyframes(
        self: _HasDatabase, keyframe_ids: tuple[str, ...]
    ) -> tuple[KeyframeEvidenceLink, ...]:
        if not keyframe_ids:
            return ()
        placeholders = ",".join("?" for _ in keyframe_ids)
        with self.database.transaction() as connection:
            rows = connection.execute(
                f"""
                SELECT l.payload
                FROM keyframe_evidence_links l
                JOIN context_keyframes k ON k.keyframe_id = l.keyframe_id
                WHERE l.keyframe_id IN ({placeholders})
                ORDER BY k.sequence_index ASC, l.created_at ASC
                """,
                keyframe_ids,
            ).fetchall()
        return tuple(KeyframeEvidenceLink.model_validate_json(str(row["payload"])) for row in rows)

    def count_control_events_for_session(self: _HasDatabase, session_id: str) -> int:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM active_capture_control_events WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["count"])

    def count_human_actions_for_session(self: _HasDatabase, session_id: str) -> int:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM human_action_events WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["count"])

    def list_action_evidence_links_for_actions(
        self: _HasDatabase, action_ids: tuple[str, ...]
    ) -> tuple[ActionEvidenceLink, ...]:
        if not action_ids:
            return ()
        placeholders = ",".join("?" for _ in action_ids)
        with self.database.transaction() as connection:
            rows = connection.execute(
                f"""
                SELECT l.payload
                FROM action_evidence_links l
                JOIN human_action_events a ON a.action_id = l.action_id
                WHERE l.action_id IN ({placeholders})
                ORDER BY a.sequence_index ASC, l.created_at ASC, l.link_id ASC
                """,
                action_ids,
            ).fetchall()
        return tuple(ActionEvidenceLink.model_validate_json(str(row["payload"])) for row in rows)

    def list_action_observations_for_actions(
        self: _HasDatabase, action_ids: tuple[str, ...]
    ) -> tuple[ActionResultObservation, ...]:
        if not action_ids:
            return ()
        placeholders = ",".join("?" for _ in action_ids)
        with self.database.transaction() as connection:
            rows = connection.execute(
                f"""
                SELECT o.payload
                FROM action_result_observations o
                JOIN human_action_events a ON a.action_id = o.action_id
                WHERE o.action_id IN ({placeholders})
                ORDER BY a.sequence_index ASC, o.observed_at ASC
                """,
                action_ids,
            ).fetchall()
        return tuple(ActionResultObservation.model_validate_json(str(row["payload"])) for row in rows)
