"""SQLite repository for durable capture post-commit outbox tasks."""

from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime

from packages.contracts import CapturePostCommitOutboxTask, CapturePostCommitTaskStatus
from packages.contracts.enums import CapturePostCommitTaskKind

from .database import SQLiteDatabase


class CapturePostCommitOutboxRepository:
    """Persist and claim capture post-commit tasks."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save_many_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        tasks: tuple[CapturePostCommitOutboxTask, ...],
    ) -> None:
        """Insert tasks into an existing capture transaction.

        Existing rows are intentionally preserved so idempotent capture retries
        cannot reset completed or retrying post-commit work.
        """

        for task in tasks:
            connection.execute(
                """
                INSERT INTO capture_post_commit_outbox(
                  task_id, kind, handler_id, status, event_id, trigger_id, attempt_count,
                  max_attempts, next_attempt_at, locked_at, lease_id, last_error, task_json,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(kind, handler_id, event_id) DO NOTHING
                """,
                self._row_values(task),
            )

    def claim_due(
        self,
        *,
        now: datetime,
        limit: int,
        stale_running_before: datetime,
        event_id: str | None = None,
    ) -> tuple[CapturePostCommitOutboxTask, ...]:
        """Atomically claim due tasks for handler execution."""

        claimed: list[CapturePostCommitOutboxTask] = []
        with self.database.transaction() as connection:
            event_filter = "AND event_id = ?" if event_id is not None else ""
            params: list[object] = [
                CapturePostCommitTaskStatus.PENDING.value,
                CapturePostCommitTaskStatus.RETRYABLE.value,
                now.isoformat(),
                CapturePostCommitTaskStatus.RUNNING.value,
                stale_running_before.isoformat(),
            ]
            if event_id is not None:
                params.append(event_id)
            params.append(limit)
            rows = connection.execute(
                f"""
                SELECT task_id, status
                FROM capture_post_commit_outbox
                WHERE (
                    (
                        status IN (?, ?)
                        AND next_attempt_at <= ?
                    ) OR (
                        status = ?
                        AND locked_at IS NOT NULL
                        AND locked_at <= ?
                    )
                )
                {event_filter}
                ORDER BY created_at ASC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
            for row in rows:
                task = self._get_by_id(connection, str(row["task_id"]))
                if task is None:
                    continue
                if task.status == CapturePostCommitTaskStatus.RUNNING and task.attempt_count >= task.max_attempts:
                    failed = task.model_copy(
                        update={
                            "status": CapturePostCommitTaskStatus.FAILED,
                            "locked_at": None,
                            "lease_id": None,
                            "last_error": "stale running task exceeded max attempts",
                            "updated_at": now,
                        }
                    )
                    connection.execute(
                        """
                        UPDATE capture_post_commit_outbox
                        SET status = ?,
                            locked_at = ?,
                            lease_id = ?,
                            last_error = ?,
                            task_json = ?,
                            updated_at = ?
                        WHERE task_id = ?
                          AND status = ?
                          AND attempt_count >= max_attempts
                          AND locked_at IS NOT NULL
                          AND locked_at <= ?
                        """,
                        (
                            failed.status.value,
                            failed.locked_at,
                            failed.lease_id,
                            failed.last_error,
                            failed.model_dump_json(),
                            failed.updated_at.isoformat(),
                            failed.task_id,
                            CapturePostCommitTaskStatus.RUNNING.value,
                            stale_running_before.isoformat(),
                        ),
                    )
                    continue
                running = task.model_copy(
                    update={
                        "status": CapturePostCommitTaskStatus.RUNNING,
                        "attempt_count": task.attempt_count + 1,
                        "locked_at": now,
                        "lease_id": self._new_lease_id(),
                        "updated_at": now,
                    }
                )
                cursor = connection.execute(
                    """
                    UPDATE capture_post_commit_outbox
                    SET status = ?,
                        attempt_count = ?,
                        locked_at = ?,
                        lease_id = ?,
                        last_error = ?,
                        task_json = ?,
                        updated_at = ?
                    WHERE task_id = ?
                      AND (
                        (
                          status IN (?, ?)
                          AND next_attempt_at <= ?
                        ) OR (
                          status = ?
                          AND locked_at IS NOT NULL
                          AND locked_at <= ?
                        )
                      )
                    """,
                    (
                        running.status.value,
                        running.attempt_count,
                        running.locked_at.isoformat() if running.locked_at else None,
                        running.lease_id,
                        running.last_error,
                        running.model_dump_json(),
                        running.updated_at.isoformat(),
                        running.task_id,
                        CapturePostCommitTaskStatus.PENDING.value,
                        CapturePostCommitTaskStatus.RETRYABLE.value,
                        now.isoformat(),
                        CapturePostCommitTaskStatus.RUNNING.value,
                        stale_running_before.isoformat(),
                    ),
                )
                if cursor.rowcount == 1:
                    claimed.append(running)
        return tuple(claimed)

    def mark_completed(self, *, task: CapturePostCommitOutboxTask, now: datetime) -> bool:
        """Mark one running task as completed."""

        return self._transition_from_claim(
            task=task,
            status=CapturePostCommitTaskStatus.COMPLETED,
            now=now,
            error=None,
        )

    def mark_retryable(
        self,
        *,
        task: CapturePostCommitOutboxTask,
        error: str,
        now: datetime,
        next_attempt_at: datetime,
    ) -> bool:
        """Release one task for a later retry."""

        return self._transition_from_claim(
            task=task,
            status=CapturePostCommitTaskStatus.RETRYABLE,
            now=now,
            error=error,
            next_attempt_at=next_attempt_at,
        )

    def mark_failed(self, *, task: CapturePostCommitOutboxTask, error: str, now: datetime) -> bool:
        """Mark one task as terminally failed."""

        return self._transition_from_claim(
            task=task,
            status=CapturePostCommitTaskStatus.FAILED,
            now=now,
            error=error,
        )

    def get(self, task_id: str) -> CapturePostCommitOutboxTask | None:
        """Return one outbox task by id."""

        with self.database.transaction() as connection:
            return self._get_by_id(connection, task_id)

    def get_for_event(
        self,
        *,
        kind: CapturePostCommitTaskKind,
        handler_id: str,
        event_id: str,
    ) -> CapturePostCommitOutboxTask | None:
        """Return one outbox task by idempotency key."""

        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT task_json FROM capture_post_commit_outbox
                WHERE kind = ? AND handler_id = ? AND event_id = ?
                """,
                (kind.value, handler_id, event_id),
            ).fetchone()
        if row is None:
            return None
        return CapturePostCommitOutboxTask.model_validate_json(str(row["task_json"]))

    def list_for_event(self, event_id: str) -> tuple[CapturePostCommitOutboxTask, ...]:
        """Return all tasks for one capture event."""

        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT task_json
                FROM capture_post_commit_outbox
                WHERE event_id = ?
                ORDER BY created_at ASC
                """,
                (event_id,),
            ).fetchall()
        return tuple(CapturePostCommitOutboxTask.model_validate_json(str(row["task_json"])) for row in rows)

    def count_by_status(self, status: CapturePostCommitTaskStatus) -> int:
        """Return task count for diagnostics and tests."""

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM capture_post_commit_outbox WHERE status = ?",
                (status.value,),
            ).fetchone()
        return int(row["count"] if row is not None else 0)

    def _transition_from_claim(
        self,
        *,
        task: CapturePostCommitOutboxTask,
        status: CapturePostCommitTaskStatus,
        now: datetime,
        error: str | None,
        next_attempt_at: datetime | None = None,
    ) -> bool:
        updated = task.model_copy(
            update={
                "status": status,
                "locked_at": None,
                "lease_id": None,
                "last_error": error,
                "next_attempt_at": next_attempt_at or task.next_attempt_at,
                "updated_at": now,
            }
        )
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE capture_post_commit_outbox
                SET status = ?,
                    attempt_count = ?,
                    max_attempts = ?,
                    next_attempt_at = ?,
                    locked_at = ?,
                    lease_id = ?,
                    last_error = ?,
                    task_json = ?,
                    updated_at = ?
                WHERE task_id = ?
                  AND status = ?
                  AND attempt_count = ?
                  AND lease_id = ?
                  AND locked_at = ?
                """,
                (
                    updated.status.value,
                    updated.attempt_count,
                    updated.max_attempts,
                    updated.next_attempt_at.isoformat(),
                    updated.locked_at.isoformat() if updated.locked_at else None,
                    updated.lease_id,
                    updated.last_error,
                    updated.model_dump_json(),
                    updated.updated_at.isoformat(),
                    task.task_id,
                    CapturePostCommitTaskStatus.RUNNING.value,
                    task.attempt_count,
                    task.lease_id,
                    task.locked_at.isoformat() if task.locked_at else None,
                ),
            )
        return cursor.rowcount == 1

    def _get_by_id(
        self,
        connection: sqlite3.Connection,
        task_id: str,
    ) -> CapturePostCommitOutboxTask | None:
        row = connection.execute(
            "SELECT task_json FROM capture_post_commit_outbox WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        if row is None:
            return None
        return CapturePostCommitOutboxTask.model_validate_json(str(row["task_json"]))

    def _row_values(self, task: CapturePostCommitOutboxTask) -> tuple[object, ...]:
        return (
            task.task_id,
            task.kind.value,
            task.handler_id,
            task.status.value,
            task.event_id,
            task.trigger_id,
            task.attempt_count,
            task.max_attempts,
            task.next_attempt_at.isoformat(),
            task.locked_at.isoformat() if task.locked_at else None,
            task.lease_id,
            task.last_error,
            task.model_dump_json(),
            task.created_at.isoformat(),
            task.updated_at.isoformat(),
        )

    def _new_lease_id(self) -> str:
        return f"cpc_lease_{secrets.token_urlsafe(12)}"
