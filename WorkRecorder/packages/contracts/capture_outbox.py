"""Typed contracts for durable capture post-commit work."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from .base import ContractModel
from .enums import CapturePostCommitTaskKind, CapturePostCommitTaskStatus


class CapturePostCommitRef(ContractModel):
    """Compact reference payload for one committed capture."""

    schema_version: int = Field(default=1, ge=1)
    event_id: str = Field(min_length=1)
    capture_run_id: str = Field(min_length=1)
    trigger_id: str = Field(min_length=1)
    artifact_ids: tuple[str, ...] = Field(default_factory=tuple)


class CapturePostCommitOutboxTask(ContractModel):
    """Durable outbox task for one capture post-commit handler."""

    task_id: str = Field(min_length=1)
    kind: CapturePostCommitTaskKind
    handler_id: str = Field(min_length=1)
    status: CapturePostCommitTaskStatus = CapturePostCommitTaskStatus.PENDING
    event_id: str = Field(min_length=1)
    trigger_id: str = Field(min_length=1)
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    next_attempt_at: datetime
    locked_at: datetime | None = None
    lease_id: str | None = None
    last_error: str | None = None
    ref: CapturePostCommitRef
    created_at: datetime
    updated_at: datetime


class CapturePostCommitOutboxConfig(ContractModel):
    """Runtime policy for planning, claiming, and retrying outbox tasks."""

    enabled: bool = True
    max_attempts: int = Field(default=3, ge=1, le=20)
    claim_limit: int = Field(default=20, ge=1, le=200)
    retry_backoff_ms: int = Field(default=1_000, ge=0)
    max_retry_delay_ms: int = Field(default=30_000, ge=0)
    stale_running_after_ms: int = Field(default=60_000, ge=1_000)
    worker_enabled: bool = True
    worker_poll_interval_ms: int = Field(default=1_000, ge=100)

    @model_validator(mode="after")
    def _validate_retry_window(self) -> "CapturePostCommitOutboxConfig":
        if self.max_retry_delay_ms < self.retry_backoff_ms:
            raise ValueError("max_retry_delay_ms must be greater than or equal to retry_backoff_ms")
        return self


class CapturePostCommitDrainResult(ContractModel):
    """Summary of one outbox drain pass."""

    claimed: int = 0
    completed: int = 0
    retryable: int = 0
    failed: int = 0
    missing_handler: int = 0
    stale_transition_ignored: int = 0
