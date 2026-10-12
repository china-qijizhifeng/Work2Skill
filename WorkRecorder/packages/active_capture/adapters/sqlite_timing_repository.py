"""SQLite timing-read helpers for active capture keyframe planning."""

from __future__ import annotations

from typing import Protocol

from packages.contracts import (
    ContextKeyframe,
    KeyframeTriggerCandidate,
    KeyframeTriggerCandidateStatus,
    SettleAuditRecord,
)
from packages.storage.database import SQLiteDatabase

from .sqlite_repository_helpers import _insert_trigger_candidate


class _HasDatabase(Protocol):
    database: SQLiteDatabase


class SQLiteTimingRepositoryMixin:
    """Bounded read helpers used by keyframe timing and trigger scheduling."""

    database: SQLiteDatabase

    def get_latest_keyframe_before(
        self: _HasDatabase, *, session_id: str, occurred_at_monotonic_ms: int | None
    ) -> ContextKeyframe | None:
        if occurred_at_monotonic_ms is None:
            query = """
                SELECT payload FROM context_keyframes
                WHERE session_id = ?
                ORDER BY sequence_index DESC, captured_at DESC
                LIMIT 1
                """
            params: tuple[object, ...] = (session_id,)
        else:
            query = """
                SELECT payload FROM context_keyframes
                WHERE session_id = ?
                  AND json_extract(payload, '$.captured_at_monotonic_ms') IS NOT NULL
                  AND json_extract(payload, '$.captured_at_monotonic_ms') <= ?
                ORDER BY json_extract(payload, '$.captured_at_monotonic_ms') DESC,
                         sequence_index DESC,
                         captured_at DESC
                LIMIT 1
                """
            params = (session_id, occurred_at_monotonic_ms)
        with self.database.transaction() as connection:
            row = connection.execute(query, params).fetchone()
        if row is None:
            return None
        return ContextKeyframe.model_validate_json(str(row["payload"]))

    def list_active_trigger_candidates_for_session(
        self: _HasDatabase, session_id: str, *, limit: int | None = None
    ) -> tuple[KeyframeTriggerCandidate, ...]:
        return _list_trigger_candidates_by_status(
            database=self.database,
            session_id=session_id,
            statuses=(
                KeyframeTriggerCandidateStatus.RECEIVED,
                KeyframeTriggerCandidateStatus.ACCEPTED,
            ),
            limit=limit,
        )

    def list_recent_trigger_candidates_for_session(
        self: _HasDatabase,
        session_id: str,
        *,
        statuses: tuple[KeyframeTriggerCandidateStatus, ...],
        limit: int,
    ) -> tuple[KeyframeTriggerCandidate, ...]:
        return _list_trigger_candidates_by_status(
            database=self.database,
            session_id=session_id,
            statuses=statuses,
            limit=limit,
        )

    def save_settle_audit(self: _HasDatabase, record: SettleAuditRecord) -> SettleAuditRecord:
        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO active_capture_settle_audits(
                  audit_id, plan_id, candidate_id, session_id, status,
                  stop_reason, sample_count, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(audit_id) DO UPDATE SET
                  status = excluded.status,
                  stop_reason = excluded.stop_reason,
                  sample_count = excluded.sample_count,
                  payload = excluded.payload
                """,
                (
                    record.audit_id,
                    record.plan_id,
                    record.candidate_id,
                    record.session_id,
                    record.status.value,
                    record.stop_reason.value,
                    record.sample_count,
                    record.model_dump_json(),
                    record.created_at.isoformat(),
                ),
            )
        return record

    def save_settle_candidate_decision(
        self: _HasDatabase, *, candidate: KeyframeTriggerCandidate, now_monotonic_ms: int
    ) -> KeyframeTriggerCandidate:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT payload FROM active_capture_trigger_candidates WHERE candidate_id = ?",
                (candidate.candidate_id,),
            ).fetchone()
            if row is not None:
                current = KeyframeTriggerCandidate.model_validate_json(str(row["payload"]))
                if _has_active_capture_claim(current, now_monotonic_ms=now_monotonic_ms):
                    return current
            _insert_trigger_candidate(connection, candidate)
        return candidate

    def claim_settle_candidate_for_capture(
        self: _HasDatabase, *, candidate_id: str, claim_id: str, now_monotonic_ms: int, lease_ms: int
    ) -> KeyframeTriggerCandidate | None:
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT payload FROM active_capture_trigger_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
            if row is None:
                return None
            current = KeyframeTriggerCandidate.model_validate_json(str(row["payload"]))
            if current.keyframe_id is not None or current.status != KeyframeTriggerCandidateStatus.ACCEPTED:
                return None
            state = current.metadata.get("settle_live_polling_state")
            if state == "capturing" and not _capture_claim_expired(current, now_monotonic_ms=now_monotonic_ms):
                return None
            if state != "ready" and state != "capturing":
                return None
            metadata = current.metadata | {
                "settle_live_polling_state": "capturing",
                "settle_capture_claim_id": claim_id,
                "settle_capture_claimed_at_monotonic_ms": now_monotonic_ms,
                "settle_capture_claim_expires_monotonic_ms": now_monotonic_ms + lease_ms,
            }
            claimed = current.model_copy(update={"metadata": metadata})
            _insert_trigger_candidate(connection, claimed)
        return claimed

    def list_settle_audits_for_candidate(self: _HasDatabase, candidate_id: str) -> tuple[SettleAuditRecord, ...]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM active_capture_settle_audits
                WHERE candidate_id = ?
                ORDER BY created_at ASC, audit_id ASC
                """,
                (candidate_id,),
            ).fetchall()
        return tuple(SettleAuditRecord.model_validate_json(str(row["payload"])) for row in rows)


def _list_trigger_candidates_by_status(
    *,
    database: SQLiteDatabase,
    session_id: str,
    statuses: tuple[KeyframeTriggerCandidateStatus, ...],
    limit: int | None,
) -> tuple[KeyframeTriggerCandidate, ...]:
    if not statuses:
        return ()
    placeholders = ",".join("?" for _ in statuses)
    query = f"""
        SELECT payload FROM active_capture_trigger_candidates
        WHERE session_id = ?
          AND status IN ({placeholders})
        ORDER BY occurred_at DESC, candidate_id DESC
        """
    params: tuple[object, ...] = (session_id, *(status.value for status in statuses))
    if limit is not None:
        query = f"{query} LIMIT ?"
        params = (*params, limit)
    with database.transaction() as connection:
        rows = connection.execute(query, params).fetchall()
    parsed = tuple(KeyframeTriggerCandidate.model_validate_json(str(row["payload"])) for row in rows)
    return tuple(reversed(parsed))


def _has_active_capture_claim(candidate: KeyframeTriggerCandidate, *, now_monotonic_ms: int) -> bool:
    return (
        candidate.metadata.get("settle_live_polling_state") == "capturing"
        and candidate.keyframe_id is None
        and not _capture_claim_expired(candidate, now_monotonic_ms=now_monotonic_ms)
    )


def _capture_claim_expired(candidate: KeyframeTriggerCandidate, *, now_monotonic_ms: int) -> bool:
    expires = candidate.metadata.get("settle_capture_claim_expires_monotonic_ms")
    return not isinstance(expires, int | float) or int(expires) <= now_monotonic_ms
