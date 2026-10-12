"""Post-commit consistency barrier for active-capture terminal routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from packages.contracts import CapturePostCommitTaskStatus, KeyframeDropReason, KeyframeTriggerCandidateStatus

if TYPE_CHECKING:
    from services.context_daemon.container import DaemonContainer


@dataclass(frozen=True, slots=True)
class ActiveCapturePostCommitBarrierResult:
    """Result of draining committed keyframe captures before terminal state.

    Attributes:
        event_ids: Capture events discovered and drained for active candidates.
        blocked_event_ids: Capture events whose post-commit tasks are still not
            completed, so terminal routes should return a retryable response.
    """

    event_ids: tuple[str, ...] = ()
    blocked_event_ids: tuple[str, ...] = ()

    @property
    def blocked(self) -> bool:
        """Return whether terminal state should wait for post-commit work."""

        return bool(self.blocked_event_ids)


def drain_active_capture_keyframe_outbox_before_terminal(
    *,
    container: DaemonContainer,
    session_id: str,
    candidate_ids: frozenset[str] | None = None,
) -> ActiveCapturePostCommitBarrierResult:
    """Drain committed keyframe outbox tasks for accepted candidates in a session.

    Args:
        container: Daemon container exposing repositories and post-commit dispatcher.
        session_id: Active capture session being completed or failed.
        candidate_ids: Optional candidate filter. Completion uses the whole
            session; native failure ACKs should only be blocked by the candidate
            they are reporting.

    Returns:
        Barrier result with event ids drained and event ids still not safely
        terminal. Callers should avoid terminalizing the session/candidate when
        ``blocked`` is true.
    """

    active_capture = container.repositories.active_capture
    events = container.repositories.events
    outbox_repository = container.repositories.capture_post_commit_outbox
    dispatcher = container.capture_post_commit_outbox
    candidate_event_ids: list[str] = []
    failed_candidate_event_ids: dict[str, str] = {}
    for candidate in active_capture.list_trigger_candidates_for_session(session_id):
        if candidate_ids is not None and candidate.candidate_id not in candidate_ids:
            continue
        if candidate.status != KeyframeTriggerCandidateStatus.ACCEPTED or candidate.keyframe_id is not None:
            continue
        event_ids = []
        if candidate.event_id:
            event_ids.append(candidate.event_id)
        event_ids.extend(event.event_id for event in events.list_by_active_capture_candidate_id(candidate.candidate_id))
        for event_id in dict.fromkeys(event_ids):
            dispatcher.drain_due_before_terminal_safe(event_id=event_id)
            candidate_event_ids.append(event_id)
            tasks = outbox_repository.list_for_event(event_id)
            if tasks and all(task.status == CapturePostCommitTaskStatus.FAILED for task in tasks):
                failed_candidate_event_ids[candidate.candidate_id] = event_id

    blocked_event_ids = []
    for event_id in dict.fromkeys(candidate_event_ids):
        tasks = outbox_repository.list_for_event(event_id)
        if any(
            task.status
            in {
                CapturePostCommitTaskStatus.PENDING,
                CapturePostCommitTaskStatus.RUNNING,
                CapturePostCommitTaskStatus.RETRYABLE,
            }
            for task in tasks
        ):
            blocked_event_ids.append(event_id)
    for candidate_id, event_id in failed_candidate_event_ids.items():
        refreshed = active_capture.get_trigger_candidate(candidate_id)
        if refreshed is not None and refreshed.status == KeyframeTriggerCandidateStatus.ACCEPTED:
            container.active_capture.trigger_scheduler.mark_dropped(
                candidate_id=candidate_id,
                reason=KeyframeDropReason.INVALID_EVIDENCE,
                event_id=event_id,
                diagnostic="post_commit_outbox_failed_before_terminal",
            )

    return ActiveCapturePostCommitBarrierResult(
        event_ids=tuple(dict.fromkeys(candidate_event_ids)),
        blocked_event_ids=tuple(blocked_event_ids),
    )
