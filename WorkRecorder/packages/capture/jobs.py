"""Capture job planning for the inline P3 enrichment ledger."""

from __future__ import annotations

from datetime import datetime

from packages.contracts import CaptureJob, JobStatus, JobType
from packages.shared.ids import IdFactory


class CaptureJobPlanner:
    """Create durable enrichment/index job rows for a persisted capture."""

    def __init__(self, *, ids: IdFactory) -> None:
        self.ids = ids

    def jobs_for_event(self, event_id: str, *, now: datetime) -> tuple[CaptureJob, ...]:
        """Return the fixed P3 local enrichment sequence for one event.

        Args:
            event_id: Event that owns the planned jobs.
            now: Timestamp used for deterministic job creation.

        Returns:
            Completed inline job rows in the durable enrichment order.
        """

        return tuple(
            CaptureJob(
                job_id=self.ids.new("job"),
                event_id=event_id,
                job_type=job_type,
                status=JobStatus.COMPLETED,
                payload={"mode": "p3_inline_ledger_v1"},
                created_at=now,
                updated_at=now,
            )
            for job_type in (
                JobType.DLP_CLASSIFICATION,
                JobType.CANONICAL_TEXT_V0,
                JobType.FTS_REFRESH,
                JobType.EVIDENCE_LAYER_EXTRACTION,
            )
        )
