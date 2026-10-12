"""Helpers for closing native keyframe capture instructions."""

from __future__ import annotations

from packages.active_capture.application.keyframe_triggers import KeyframeTriggerScheduler
from packages.active_capture.application.recording_projection import RecordingPublicProjector
from packages.active_capture.repositories.protocol import ActiveCaptureRepository
from packages.contracts import (
    ActiveCaptureSession,
    KeyframeTriggerPublicSummary,
    ReportKeyframeCaptureFailureCommand,
)


def report_keyframe_capture_failure(
    *,
    repository: ActiveCaptureRepository,
    trigger_scheduler: KeyframeTriggerScheduler,
    projector: RecordingPublicProjector,
    session: ActiveCaptureSession,
    command: ReportKeyframeCaptureFailureCommand,
) -> KeyframeTriggerPublicSummary:
    """Close a capture instruction that native code could not commit.

    Args:
        repository: Active-capture repository used for candidate lookup.
        trigger_scheduler: Scheduler responsible for terminal candidate state.
        projector: Public response projector for trigger summaries.
        session: Session that owns the capture instruction.
        command: Typed native failure report.

    Returns:
        Public summary for the dropped trigger candidate.

    Raises:
        ValueError: If the candidate is missing or belongs to another session.
    """

    candidate = repository.get_trigger_candidate(command.candidate_id)
    if candidate is None or candidate.session_id != session.session_id:
        raise ValueError("keyframe trigger candidate does not belong to active capture session")
    trigger_scheduler.mark_dropped(
        candidate_id=command.candidate_id,
        reason=command.reason,
        diagnostic=command.diagnostic or "native capture instruction did not produce a committed keyframe",
    )
    updated = repository.get_trigger_candidate(command.candidate_id)
    if updated is None:
        raise ValueError("keyframe trigger candidate not found after failure report")
    return projector.to_public_trigger_candidate(updated)
