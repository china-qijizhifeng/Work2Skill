"""Daemon background workers for asynchronous maintenance tasks."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from .container import DaemonContainer

logger = logging.getLogger(__name__)


class CapturePostCommitOutboxWorker:
    """Small periodic worker for retrying capture post-commit outbox tasks."""

    def __init__(self, container: DaemonContainer) -> None:
        self.container = container
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the worker when enabled by runtime configuration."""

        config = self.container.capture_post_commit_outbox.config
        if not config.enabled or not config.worker_enabled:
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="capture-post-commit-outbox-worker")

    async def stop(self) -> None:
        """Cancel the worker and wait for shutdown."""

        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        config = self.container.capture_post_commit_outbox.config
        interval_seconds = config.worker_poll_interval_ms / 1000
        while True:
            try:
                await asyncio.to_thread(self.container.capture_post_commit_outbox.drain_due_safe)
            except Exception:
                logger.exception("capture post-commit outbox worker failed one drain pass")
            await asyncio.sleep(interval_seconds)
