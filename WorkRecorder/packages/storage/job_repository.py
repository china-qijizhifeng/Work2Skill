"""Repository for capture enrichment/index jobs."""

from __future__ import annotations

from datetime import datetime

from packages.contracts import CaptureJob, JobStatus
from packages.contracts.common import JsonScalar
from packages.contracts.enums import JobType

from .database import SQLiteDatabase


class CaptureJobRepository:
    """Persist durable capture jobs."""

    def __init__(self, database: SQLiteDatabase) -> None:
        """Create a job repository."""

        self.database = database

    def save(self, job: CaptureJob) -> CaptureJob:
        """Insert or update one capture job.

        Args:
            job: Durable enrichment/index job to persist.

        Returns:
            The saved job model.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO capture_jobs(job_id, event_id, job_type, status, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id, job_type) DO UPDATE SET
                  job_id = excluded.job_id,
                  status = excluded.status,
                  payload = excluded.payload,
                  updated_at = excluded.updated_at
                """,
                (
                    job.job_id,
                    job.event_id,
                    job.job_type.value,
                    job.status.value,
                    job.model_dump_json(),
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                ),
            )
        return job

    def list_for_event(self, event_id: str) -> tuple[CaptureJob, ...]:
        """Return jobs for an event.

        Args:
            event_id: Event whose capture jobs should be listed.

        Returns:
            Jobs ordered by creation time.
        """

        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT payload FROM capture_jobs WHERE event_id = ? ORDER BY created_at ASC",
                (event_id,),
            ).fetchall()
        return tuple(CaptureJob.model_validate_json(str(row["payload"])) for row in rows)

    def get_for_event_type(self, *, event_id: str, job_type: JobType) -> CaptureJob | None:
        """Return a job by event and type.

        Args:
            event_id: Event whose job should be loaded.
            job_type: Durable job type to match.

        Returns:
            Matching job when present, otherwise ``None``.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM capture_jobs WHERE event_id = ? AND job_type = ?",
                (event_id, job_type.value),
            ).fetchone()
        if row is None:
            return None
        return CaptureJob.model_validate_json(str(row["payload"]))

    def list_by_status(self, *, job_type: JobType, status: JobStatus, limit: int = 20) -> tuple[CaptureJob, ...]:
        """Return jobs with a matching type and status.

        Args:
            job_type: Durable job type to match.
            status: Lifecycle status to match.
            limit: Maximum number of jobs returned.

        Returns:
            Jobs ordered by creation time.
        """

        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM capture_jobs
                WHERE job_type = ? AND status = ?
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (job_type.value, status.value, limit),
            ).fetchall()
        return tuple(CaptureJob.model_validate_json(str(row["payload"])) for row in rows)

    def claim_for_run(
        self,
        *,
        event_id: str,
        job_type: JobType,
        now: datetime,
        payload_updates: dict[str, JsonScalar],
    ) -> CaptureJob | None:
        """Atomically transition a queued job into ``running``.

        Args:
            event_id: Event whose job should be claimed.
            job_type: Durable job type to claim.
            now: Timestamp for the status transition.
            payload_updates: Scalar payload fields merged into the job.

        Returns:
            Running job when this call won the claim, otherwise the current job
            state. ``None`` is returned when no job exists.
        """

        existing = self.get_for_event_type(event_id=event_id, job_type=job_type)
        if existing is None:
            return None
        if existing.status not in {JobStatus.PENDING, JobStatus.FAILED, JobStatus.SKIPPED}:
            return existing
        claimed = existing.model_copy(
            update={
                "status": JobStatus.RUNNING,
                "payload": {**existing.payload, **payload_updates},
                "updated_at": now,
            }
        )
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                UPDATE capture_jobs
                SET status = ?, payload = ?, updated_at = ?
                WHERE event_id = ?
                  AND job_type = ?
                  AND status IN (?, ?, ?)
                """,
                (
                    JobStatus.RUNNING.value,
                    claimed.model_dump_json(),
                    now.isoformat(),
                    event_id,
                    job_type.value,
                    JobStatus.PENDING.value,
                    JobStatus.FAILED.value,
                    JobStatus.SKIPPED.value,
                ),
            )
        if cursor.rowcount == 1:
            return claimed
        return self.get_for_event_type(event_id=event_id, job_type=job_type)

    def count_completed(self, event_id: str) -> int:
        """Return completed job count for tests and diagnostics.

        Args:
            event_id: Event whose completed jobs should be counted.

        Returns:
            Number of completed capture jobs.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM capture_jobs WHERE event_id = ? AND status = ?",
                (event_id, JobStatus.COMPLETED.value),
            ).fetchone()
        return int(row["count"] if row is not None else 0)
