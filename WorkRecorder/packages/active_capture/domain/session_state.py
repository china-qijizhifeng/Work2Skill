"""Active capture session state machine."""

from __future__ import annotations

from packages.contracts import ActiveCaptureSession, ActiveCaptureStatus


class ActiveCaptureStateError(ValueError):
    """Raised when a session transition is not valid."""


class ActiveCaptureSessionStateMachine:
    """Centralized state transition policy for active capture sessions."""

    _allowed: dict[ActiveCaptureStatus, frozenset[ActiveCaptureStatus]] = {
        ActiveCaptureStatus.CREATED: frozenset(
            {
                ActiveCaptureStatus.SELECTING_SCOPE,
                ActiveCaptureStatus.RECORDING,
                ActiveCaptureStatus.FINALIZING,
                ActiveCaptureStatus.CANCELLED,
                ActiveCaptureStatus.FAILED,
                ActiveCaptureStatus.COMPLETED,
            }
        ),
        ActiveCaptureStatus.SELECTING_SCOPE: frozenset(
            {
                ActiveCaptureStatus.RECORDING,
                ActiveCaptureStatus.CANCELLED,
                ActiveCaptureStatus.FAILED,
            }
        ),
        ActiveCaptureStatus.RECORDING: frozenset(
            {
                ActiveCaptureStatus.PAUSED,
                ActiveCaptureStatus.SCOPE_LOST,
                ActiveCaptureStatus.STOPPING,
                ActiveCaptureStatus.FINALIZING,
                ActiveCaptureStatus.COMPLETED_WITH_WARNINGS,
                ActiveCaptureStatus.FAILED,
                ActiveCaptureStatus.CANCELLED,
            }
        ),
        ActiveCaptureStatus.PAUSED: frozenset(
            {
                ActiveCaptureStatus.RECORDING,
                ActiveCaptureStatus.STOPPING,
                ActiveCaptureStatus.CANCELLED,
                ActiveCaptureStatus.FAILED,
            }
        ),
        ActiveCaptureStatus.SCOPE_LOST: frozenset(
            {
                ActiveCaptureStatus.RECORDING,
                ActiveCaptureStatus.STOPPING,
                ActiveCaptureStatus.FINALIZING,
                ActiveCaptureStatus.COMPLETED_WITH_WARNINGS,
                ActiveCaptureStatus.FAILED,
                ActiveCaptureStatus.CANCELLED,
            }
        ),
        ActiveCaptureStatus.STOPPING: frozenset(
            {
                ActiveCaptureStatus.FINALIZING,
                ActiveCaptureStatus.COMPLETED,
                ActiveCaptureStatus.COMPLETED_WITH_WARNINGS,
                ActiveCaptureStatus.FAILED,
                ActiveCaptureStatus.CANCELLED,
            }
        ),
        ActiveCaptureStatus.FINALIZING: frozenset(
            {
                ActiveCaptureStatus.COMPLETED,
                ActiveCaptureStatus.COMPLETED_WITH_WARNINGS,
                ActiveCaptureStatus.FAILED,
                ActiveCaptureStatus.CANCELLED,
            }
        ),
        ActiveCaptureStatus.COMPLETED: frozenset(),
        ActiveCaptureStatus.COMPLETED_WITH_WARNINGS: frozenset(),
        ActiveCaptureStatus.FAILED: frozenset(),
        ActiveCaptureStatus.CANCELLED: frozenset(),
    }

    def assert_transition(self, session: ActiveCaptureSession, target: ActiveCaptureStatus) -> None:
        """Raise when ``session`` cannot move to ``target``."""

        if target == session.status:
            return
        if target not in self._allowed[session.status]:
            raise ActiveCaptureStateError(f"invalid active capture transition {session.status.value} -> {target.value}")

    def transition(self, session: ActiveCaptureSession, target: ActiveCaptureStatus) -> ActiveCaptureSession:
        """Return a copy of ``session`` with a validated target status."""

        self.assert_transition(session, target)
        return session.model_copy(update={"status": target})
