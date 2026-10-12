"""Durable audit storage for policy-before-index decisions."""

from __future__ import annotations

from datetime import UTC, datetime

from packages.contracts import IndexPolicyAuditWriteState
from packages.indexing.safety import SafeIndexProjectionBatch

from .database import SQLiteDatabase


class IndexPolicyAuditRepository:
    """Persist safe index policy decisions without storing raw text."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save_batch_pending(self, batch: SafeIndexProjectionBatch) -> None:
        """Persist pending decision summaries before any index write."""

        self._save_batch(batch, write_state=IndexPolicyAuditWriteState.PENDING)

    def mark_batch_indexed(self, batch: SafeIndexProjectionBatch) -> None:
        """Mark decisions as indexed after the backend write succeeds."""

        self._save_batch(batch, write_state=IndexPolicyAuditWriteState.INDEXED)

    def mark_batch_failed(self, batch: SafeIndexProjectionBatch) -> None:
        """Mark decisions as failed when the backend write raises."""

        self._save_batch(batch, write_state=IndexPolicyAuditWriteState.FAILED)

    def save_batch(self, batch: SafeIndexProjectionBatch) -> None:
        """Persist decision summaries for compatibility with older callers."""

        self.mark_batch_indexed(batch)

    def _save_batch(self, batch: SafeIndexProjectionBatch, *, write_state: IndexPolicyAuditWriteState) -> None:
        """Persist decision summaries with a typed index write state."""

        created_at = datetime.now(tz=UTC).isoformat()
        with self.database.transaction() as connection:
            for projection in batch.projections:
                decision = projection.decision
                decision_payload = decision.model_copy(
                    update={"details": {**decision.details, "index_write_state": write_state.value}}
                )
                source = projection.source
                session_id = source.metadata.get("active_capture_session_id")
                source_id = source.evidence_id or source.artifact_id or source.metadata.get("index_document_key")
                connection.execute(
                    """
                    INSERT INTO index_policy_decisions(
                      decision_id, event_id, session_id, source_id, field_kind, status,
                      suppression_reason, sensitive_surface_type, source_text_hash, output_text_hash,
                      policy_version, payload, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(decision_id) DO UPDATE SET
                      status = excluded.status,
                      suppression_reason = excluded.suppression_reason,
                      sensitive_surface_type = excluded.sensitive_surface_type,
                      output_text_hash = excluded.output_text_hash,
                      payload = excluded.payload
                    """,
                    (
                        decision.decision_id,
                        source.event.event_id,
                        session_id if isinstance(session_id, str) else None,
                        source_id if isinstance(source_id, str) else None,
                        source.field_kind.value,
                        decision.status.value,
                        decision.suppression_reason.value,
                        decision.sensitive_surface_type.value,
                        decision.source_text_hash,
                        decision.output_text_hash,
                        decision.policy_version,
                        decision_payload.model_dump_json(),
                        created_at,
                    ),
                )

    def count_for_event(self, event_id: str) -> int:
        """Return number of persisted policy decisions for an event."""

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM index_policy_decisions WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return int(row["count"])
