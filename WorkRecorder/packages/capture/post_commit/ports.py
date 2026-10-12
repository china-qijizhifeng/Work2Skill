"""Ports for capture post-commit outbox dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from packages.contracts import (
    Artifact,
    CaptureAttemptRequest,
    CapturePostCommitOutboxTask,
    CapturePostCommitRef,
    ContextEvent,
    EventCaptureEnvelope,
)
from packages.contracts.enums import CapturePostCommitTaskStatus


@dataclass(frozen=True, slots=True)
class CapturePostCommitContext:
    """Hydrated context passed to post-commit handlers.

    Attributes:
        attempt: Original capture attempt request.
        event: Event ledger row created by the capture.
        artifacts: Artifacts committed with the event.
        envelope: Full capture envelope used by post-commit hooks.
    """

    attempt: CaptureAttemptRequest
    event: ContextEvent
    artifacts: tuple[Artifact, ...]
    envelope: EventCaptureEnvelope


class CapturePostCommitOutboxRepositoryPort(Protocol):
    """Persistence boundary used by the post-commit dispatcher."""

    def claim_due(
        self,
        *,
        now: datetime,
        limit: int,
        stale_running_before: datetime,
        event_id: str | None = None,
    ) -> tuple[CapturePostCommitOutboxTask, ...]: ...

    def mark_completed(self, *, task: CapturePostCommitOutboxTask, now: datetime) -> bool: ...

    def mark_retryable(
        self,
        *,
        task: CapturePostCommitOutboxTask,
        error: str,
        now: datetime,
        next_attempt_at: datetime,
    ) -> bool: ...

    def mark_failed(self, *, task: CapturePostCommitOutboxTask, error: str, now: datetime) -> bool: ...

    def count_by_status(self, status: CapturePostCommitTaskStatus) -> int: ...


class CapturePostCommitContextResolverPort(Protocol):
    """Resolve compact outbox refs into typed capture handler context."""

    def resolve(self, ref: CapturePostCommitRef) -> CapturePostCommitContext | None: ...
