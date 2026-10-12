"""Generic extension hooks for the capture pipeline."""

from __future__ import annotations

from typing import Protocol

from packages.contracts import Artifact, CaptureAttemptRequest, ContextEvent, EventCaptureEnvelope


class CapturePostCommitHook(Protocol):
    """Observer called after the existing capture pipeline commits an event."""

    def after_capture_committed(
        self,
        *,
        attempt: CaptureAttemptRequest,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        envelope: EventCaptureEnvelope,
    ) -> None: ...
