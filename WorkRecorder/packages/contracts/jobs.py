"""Durable enrichment and indexing job contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import ContractModel
from .common import JsonScalar
from .enums import JobStatus, JobType


class CaptureJob(ContractModel):
    """Durable job scheduled from capture persistence."""

    job_id: str
    event_id: str
    job_type: JobType
    status: JobStatus = JobStatus.PENDING
    payload: dict[str, JsonScalar] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
