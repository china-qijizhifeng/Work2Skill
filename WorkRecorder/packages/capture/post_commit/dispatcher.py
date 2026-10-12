"""Planner and worker for durable capture post-commit handlers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from threading import Lock

from packages.capture.hooks import CapturePostCommitHook
from packages.capture.post_commit.ports import (
    CapturePostCommitContextResolverPort,
    CapturePostCommitOutboxRepositoryPort,
)
from packages.contracts import (
    Artifact,
    CaptureAttemptRequest,
    CapturePostCommitDrainResult,
    CapturePostCommitOutboxConfig,
    CapturePostCommitOutboxTask,
    CapturePostCommitRef,
    ContextEvent,
    EventCaptureEnvelope,
)
from packages.contracts.enums import CapturePostCommitTaskKind, CapturePostCommitTaskStatus
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CapturePostCommitHandler:
    """Registered handler for one typed outbox task kind.

    Attributes:
        kind: Durable task kind the handler can execute.
        handler_id: Stable plug-in identity for this handler.
        hook: Runtime hook called after capture commit.
    """

    kind: CapturePostCommitTaskKind
    handler_id: str
    hook: CapturePostCommitHook


class CapturePostCommitOutboxDispatcher:
    """Plan durable post-commit tasks and execute due tasks outside the hot path."""

    def __init__(
        self,
        *,
        repository: CapturePostCommitOutboxRepositoryPort,
        context_resolver: CapturePostCommitContextResolverPort,
        handlers: tuple[CapturePostCommitHandler, ...],
        ids: IdFactory,
        clock: Clock,
        config: CapturePostCommitOutboxConfig | None = None,
    ) -> None:
        self.repository = repository
        self.context_resolver = context_resolver
        self.handlers = self._handler_map(handlers)
        self.ids = ids
        self.clock = clock
        self.config = config or CapturePostCommitOutboxConfig()
        self._drain_lock = Lock()

    def plan_after_capture_committed(
        self,
        *,
        attempt: CaptureAttemptRequest,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        envelope: EventCaptureEnvelope,
    ) -> tuple[CapturePostCommitOutboxTask, ...]:
        """Create typed tasks for registered handlers without executing them."""

        if not self.config.enabled:
            return ()
        now = self.clock.now()
        ref = CapturePostCommitRef(
            event_id=event.event_id,
            capture_run_id=envelope.capture_run_id,
            trigger_id=attempt.trigger.trigger_id,
            artifact_ids=tuple(artifact.artifact_id for artifact in artifacts),
        )
        return tuple(
            CapturePostCommitOutboxTask(
                task_id=self.ids.new("cpc"),
                kind=kind_handler[0],
                handler_id=kind_handler[1],
                status=CapturePostCommitTaskStatus.PENDING,
                event_id=event.event_id,
                trigger_id=attempt.trigger.trigger_id,
                max_attempts=self.config.max_attempts,
                next_attempt_at=now,
                ref=ref,
                created_at=now,
                updated_at=now,
            )
            for kind_handler in self.handlers
        )

    def drain_due(self, event_id: str | None = None) -> CapturePostCommitDrainResult:
        """Claim and execute due post-commit tasks once."""

        return self._drain_due_locked(event_id=event_id, blocking=False)

    def drain_due_safe(self, event_id: str | None = None) -> CapturePostCommitDrainResult:
        """Drain due tasks while shielding daemon routes from worker failures."""

        try:
            return self.drain_due(event_id=event_id)
        except Exception:
            logger.exception("capture post-commit outbox drain failed")
            return CapturePostCommitDrainResult()

    def drain_due_before_terminal_safe(self, event_id: str | None = None) -> CapturePostCommitDrainResult:
        """Synchronously drain due tasks before a terminal workflow transition.

        Completion/failure routes use this as a small consistency barrier: a
        just-committed capture may have queued an active-capture keyframe task
        while the FastAPI background drain has not run yet. This method waits
        for any in-flight drain to finish, then processes one due batch so the
        success path can win before a session/candidate is made terminal.
        """

        try:
            return self._drain_due_locked(event_id=event_id, blocking=True)
        except Exception:
            logger.exception("capture post-commit terminal drain failed")
            return CapturePostCommitDrainResult()

    def _drain_due_locked(
        self,
        *,
        event_id: str | None,
        blocking: bool,
    ) -> CapturePostCommitDrainResult:
        if not self.config.enabled:
            return CapturePostCommitDrainResult()
        if not self._drain_lock.acquire(blocking=blocking):
            logger.info("capture post-commit drain skipped because another drain is active")
            return CapturePostCommitDrainResult()
        try:
            now = self.clock.now()
            stale_running_before = now - timedelta(milliseconds=self.config.stale_running_after_ms)
            tasks = self.repository.claim_due(
                now=now,
                limit=self.config.claim_limit,
                stale_running_before=stale_running_before,
                event_id=event_id,
            )
            result = CapturePostCommitDrainResult(claimed=len(tasks))
            for task in tasks:
                result = self._run_task(task=task, result=result)
            return result
        finally:
            self._drain_lock.release()

    def _run_task(
        self,
        *,
        task: CapturePostCommitOutboxTask,
        result: CapturePostCommitDrainResult,
    ) -> CapturePostCommitDrainResult:
        hook = self.handlers.get((task.kind, task.handler_id))
        if hook is None:
            message = f"no registered capture post-commit handler for {task.kind.value}"
            transitioned = self.repository.mark_failed(task=task, error=message, now=self.clock.now())
            logger.error(
                "capture post-commit task missing handler",
                extra={
                    "task_id": task.task_id,
                    "kind": task.kind.value,
                    "handler_id": task.handler_id,
                    "event_id": task.event_id,
                    "transitioned": transitioned,
                },
            )
            if transitioned:
                return result.model_copy(
                    update={"failed": result.failed + 1, "missing_handler": result.missing_handler + 1}
                )
            return result.model_copy(update={"stale_transition_ignored": result.stale_transition_ignored + 1})
        context = self.context_resolver.resolve(task.ref)
        if context is None:
            return self._handle_task_error(task=task, error=RuntimeError("post-commit context missing"), result=result)
        try:
            hook.after_capture_committed(
                attempt=context.attempt,
                event=context.event,
                artifacts=context.artifacts,
                envelope=context.envelope,
            )
        except Exception as exc:
            logger.warning(
                "capture post-commit task handler failed",
                extra={"task_id": task.task_id, "handler_id": task.handler_id, "event_id": task.event_id},
            )
            return self._handle_task_error(task=task, error=exc, result=result)
        transitioned = self.repository.mark_completed(task=task, now=self.clock.now())
        if not transitioned:
            logger.warning(
                "capture post-commit task completion ignored for stale lease",
                extra={
                    "task_id": task.task_id,
                    "kind": task.kind.value,
                    "handler_id": task.handler_id,
                    "event_id": task.event_id,
                    "attempt_count": task.attempt_count,
                },
            )
            return result.model_copy(update={"stale_transition_ignored": result.stale_transition_ignored + 1})
        logger.info(
            "capture post-commit task completed",
            extra={
                "task_id": task.task_id,
                "kind": task.kind.value,
                "handler_id": task.handler_id,
                "event_id": task.event_id,
            },
        )
        return result.model_copy(update={"completed": result.completed + 1})

    def _handle_task_error(
        self,
        *,
        task: CapturePostCommitOutboxTask,
        error: Exception,
        result: CapturePostCommitDrainResult,
    ) -> CapturePostCommitDrainResult:
        now = self.clock.now()
        message = _error_message(error)
        if task.attempt_count >= task.max_attempts:
            transitioned = self.repository.mark_failed(task=task, error=message, now=now)
            logger.exception(
                "capture post-commit task failed permanently",
                extra={
                    "task_id": task.task_id,
                    "kind": task.kind.value,
                    "handler_id": task.handler_id,
                    "event_id": task.event_id,
                    "attempt_count": task.attempt_count,
                    "transitioned": transitioned,
                },
            )
            if transitioned:
                return result.model_copy(update={"failed": result.failed + 1})
            return result.model_copy(update={"stale_transition_ignored": result.stale_transition_ignored + 1})
        next_attempt_at = now + timedelta(milliseconds=self._retry_delay_ms(task.attempt_count))
        transitioned = self.repository.mark_retryable(
            task=task,
            error=message,
            now=now,
            next_attempt_at=next_attempt_at,
        )
        if not transitioned:
            logger.warning(
                "capture post-commit retry ignored for stale lease",
                extra={
                    "task_id": task.task_id,
                    "kind": task.kind.value,
                    "handler_id": task.handler_id,
                    "event_id": task.event_id,
                    "attempt_count": task.attempt_count,
                },
            )
            return result.model_copy(update={"stale_transition_ignored": result.stale_transition_ignored + 1})
        logger.warning(
            "capture post-commit task will retry",
            extra={
                "task_id": task.task_id,
                "kind": task.kind.value,
                "handler_id": task.handler_id,
                "event_id": task.event_id,
                "attempt_count": task.attempt_count,
                "next_attempt_at": next_attempt_at.isoformat(),
            },
        )
        return result.model_copy(update={"retryable": result.retryable + 1})

    def _retry_delay_ms(self, attempt_count: int) -> int:
        base: int = self.config.retry_backoff_ms
        if base == 0:
            return 0
        delay: int = base * (2 ** max(attempt_count - 1, 0))
        cap: int = self.config.max_retry_delay_ms
        return delay if delay < cap else cap

    def _handler_map(
        self,
        handlers: tuple[CapturePostCommitHandler, ...],
    ) -> dict[tuple[CapturePostCommitTaskKind, str], CapturePostCommitHook]:
        registered: dict[tuple[CapturePostCommitTaskKind, str], CapturePostCommitHook] = {}
        for handler in handlers:
            key = (handler.kind, handler.handler_id)
            if key in registered:
                raise ValueError(f"duplicate capture post-commit handler {handler.kind.value}:{handler.handler_id}")
            registered[key] = handler.hook
        return registered


def _error_message(error: Exception) -> str:
    message = str(error).strip() or type(error).__name__
    return message[:1_000]
