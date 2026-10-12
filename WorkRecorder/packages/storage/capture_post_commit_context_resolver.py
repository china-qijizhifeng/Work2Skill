"""Storage-backed resolver for capture post-commit outbox references."""

from __future__ import annotations

from packages.capture.post_commit import CapturePostCommitContext
from packages.contracts import (
    Artifact,
    CaptureAttemptRequest,
    CapturePostCommitRef,
    ContextEvent,
    EventCaptureEnvelope,
)

from .database import SQLiteDatabase


class SQLiteCapturePostCommitContextResolver:
    """Hydrate compact outbox refs from the capture ledger."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def resolve(self, ref: CapturePostCommitRef) -> CapturePostCommitContext | None:
        """Return handler context for a committed capture, if still available."""

        with self.database.transaction() as connection:
            attempt_row = connection.execute(
                "SELECT payload FROM capture_attempts WHERE trigger_id = ?",
                (ref.trigger_id,),
            ).fetchone()
            event_row = connection.execute(
                "SELECT payload FROM context_events WHERE event_id = ?",
                (ref.event_id,),
            ).fetchone()
            envelope_row = connection.execute(
                """
                SELECT envelope_payload FROM capture_runs
                WHERE capture_run_id = ? AND event_id = ?
                """,
                (ref.capture_run_id, ref.event_id),
            ).fetchone()
            artifact_rows = connection.execute(
                "SELECT payload FROM artifacts WHERE event_id = ? ORDER BY created_at ASC",
                (ref.event_id,),
            ).fetchall()
        if attempt_row is None or event_row is None or envelope_row is None:
            return None
        artifact_ids = set(ref.artifact_ids)
        artifacts = tuple(
            artifact
            for artifact in (Artifact.model_validate_json(str(row["payload"])) for row in artifact_rows)
            if not artifact_ids or artifact.artifact_id in artifact_ids
        )
        return CapturePostCommitContext(
            attempt=CaptureAttemptRequest.model_validate_json(str(attempt_row["payload"])),
            event=ContextEvent.model_validate_json(str(event_row["payload"])),
            artifacts=artifacts,
            envelope=EventCaptureEnvelope.model_validate_json(str(envelope_row["envelope_payload"])),
        )
