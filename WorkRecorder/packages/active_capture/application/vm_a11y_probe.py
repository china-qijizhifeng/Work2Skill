"""VM DOM hit probe integration for active capture.

Each trusted pointer click triggers one lookup from a persistent VM-side HTTP
service. The default source is the Firefox/Marionette ``dom_at_point`` service,
but the probe can also consume the newer event-watch daemon that exposes recent
click/focus events over ``/events``.
"""

from __future__ import annotations

import copy
import http.client
import json
import logging
import shlex
import subprocess
import threading
import time
import urllib.parse
from collections import deque
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

_SUPPORTED_EVENT_KINDS = frozenset({"pointer_click", "pointer_drag"})
_EVENT_PRIORITY = {
    "pointer_click": 0,
    "pointer_drag": 0,
}

# Probe errors that indicate the VM service itself is unhealthy. Only these
# warrant the restart backoff; every other error (e.g. "no matching event") is a
# per-click soft miss that must not stall the probes for subsequent clicks.
_BACKOFF_ERROR_PREFIXES = (
    "vm_event_watch_request_failed",
    "vm_event_watch_http_",
    "vm_dom_probe_request_failed",
    "vm_dom_probe_http_",
    "vm_a11y_probe_failed",
    "vm_dom_probe_exhausted_retries",
)

VM_A11Y_PROFILE_MYPCBENCH = "mypcbench_v1"
VM_A11Y_PROFILE_OSWORLD_GATEWAY = "osworld_gateway_v1"
VM_A11Y_PROFILE_LINUX_ATSPI = "linux_atspi_v1"
VMAccessibilityProbeProfile = Literal["mypcbench_v1", "osworld_gateway_v1", "linux_atspi_v1"]
_SUPPORTED_VM_A11Y_PROFILES = frozenset(
    {
        VM_A11Y_PROFILE_MYPCBENCH,
        VM_A11Y_PROFILE_LINUX_ATSPI,
        VM_A11Y_PROFILE_OSWORLD_GATEWAY,
    }
)


def _error_should_backoff(error: str | None) -> bool:
    return error is not None and error.startswith(_BACKOFF_ERROR_PREFIXES)


class VMAccessibilityProbePort:
    """Port used by active capture to wake the VM DOM hit probe."""

    def notify_local_operation(
        self,
        *,
        session_id: str,
        event_kind: str,
        occurred_at_monotonic_ms: int | None,
        point_x: float | None = None,
        point_y: float | None = None,
        coordinate_space: str | None = None,
    ) -> None:
        """Schedule one VM DOM hit sample after a local operation."""

        raise NotImplementedError

    def latest_snapshot(self) -> dict[str, object]:
        """Return the latest probe state and sample."""

        raise NotImplementedError

    def export_records_for_session(self, session_id: str) -> tuple[dict[str, object], ...]:
        """Return VM DOM hit probe records associated with one session."""

        raise NotImplementedError

    def export_event_log_for_session(self, session_id: str) -> tuple[dict[str, object], ...]:
        """Return the full captured VM ``/events`` stream for one session."""

        raise NotImplementedError

    def export_click_log_for_session(self, session_id: str) -> tuple[dict[str, object], ...]:
        """Return the mirrored VM click watcher stream for one session."""

        raise NotImplementedError

    def archive_session(
        self,
        *,
        session_id: str,
        started_at_epoch: float | None,
        ended_at_epoch: float | None,
    ) -> bool:
        """Persist probe streams so a completed session remains exportable later."""

        return False

    def sample_point_for_export(
        self,
        *,
        session_id: str,
        occurred_at_monotonic_ms: int | None,
        point_x: float,
        point_y: float,
        coordinate_space: str,
    ) -> dict[str, object] | None:
        """Best-effort live DOM hit lookup used as an export-time fallback."""

        raise NotImplementedError


@dataclass(frozen=True)
class VMAccessibilityProbeConfig:
    """Runtime settings for the persistent VM DOM hit HTTP service."""

    enabled: bool = True
    profile: VMAccessibilityProbeProfile = VM_A11Y_PROFILE_MYPCBENCH
    source: str = "dom_at_point"
    url: str = "http://127.0.0.1:7071"
    a11y_path: str = "/dom_at_point"
    events_path: str = "/events"
    events_limit: int = 20
    # The live per-click probe is best-effort and intentionally short (~0.6s). It
    # is serial for the event_watch source, so a long window backs the queue up
    # when clicks are close together (each miss blocks the next probe). Late
    # targets (e.g. a dropdown that renders its items a second after the click) are
    # recovered post-hoc by matching against the full captured event log at export.
    events_poll_attempts: int = 12
    events_poll_interval_seconds: float = 0.05
    events_match_window_seconds: float = 2.0
    click_log_url: str | None = None
    click_log_path: str | None = None
    click_log_ssh_enabled: bool = False
    click_log_ssh_jump_host: str | None = None
    click_log_ssh_host: str = "127.0.0.1"
    click_log_ssh_port: int = 2222
    click_log_ssh_user: str = "user"
    click_log_ssh_key_path: str | None = None
    click_log_ssh_guest_path: str = "/tmp/clicks.jsonl"
    click_log_ssh_timeout_seconds: float = 5.0
    health_path: str = "/health"
    depth: int | None = None
    max_nodes: int | None = None
    periodic_depth: int | None = None
    periodic_max_nodes: int | None = None
    request_timeout_seconds: float = 5.0
    restart_backoff_seconds: float = 5.0
    max_concurrent_probes: int = 4
    max_pending_operations: int = 1000
    max_history_per_session: int = 1000
    periodic_enabled: bool = False
    periodic_interval_seconds: float = 0.5
    periodic_idle_stop_seconds: float = 45.0
    periodic_match_window_seconds: float = 2.0
    max_periodic_history_per_session: int = 3000
    export_drain_timeout_seconds: float = 3.0
    # Continuous full ``/events`` capture (event_watch source only). Records the
    # entire VM accessibility event stream during a recording into a sidecar log,
    # independent of which events get matched to clicks/drags.
    event_log_enabled: bool = True
    event_log_poll_interval_seconds: float = 0.3
    event_log_idle_stop_seconds: float = 90.0
    event_log_fetch_limit: int = 200
    max_event_log_per_session: int = 20000
    archive_dir: str | None = None

    def __post_init__(self) -> None:
        if self.profile not in _SUPPORTED_VM_A11Y_PROFILES:
            raise ValueError(f"unsupported VM accessibility probe profile: {self.profile}")


# Fetch one DOM hit sample for an operation (None is no longer sampled).
# Returns ``(sample, error)`` where exactly one side is set.
SampleFetcher = Callable[["VMAccessibilityProbeConfig", dict[str, object] | None], tuple[dict[str, object] | None, str | None]]


class VMAccessibilityProbeService(VMAccessibilityProbePort):
    """Sample a persistent VM DOM hit service once per pointer click."""

    def __init__(
        self,
        *,
        config: VMAccessibilityProbeConfig | None = None,
        sample_fetcher: SampleFetcher | None = None,
    ) -> None:
        self.config = config or VMAccessibilityProbeConfig()
        self._sample_fetcher = sample_fetcher or self._http_sample_fetcher
        self._lock = threading.Lock()
        self._enabled = self.config.enabled
        self._latest_sample: dict[str, object] | None = None
        self._last_operation: dict[str, object] | None = None
        self._last_error: str | None = None
        self._started_at: float | None = None
        self._completed_at: float | None = None
        self._next_start_after = 0.0
        self._samples_seen = 0
        self._operation_queue: deque[dict[str, object]] = deque()
        self._active_probe_count = 0
        self._records_by_session: dict[str, list[dict[str, object]]] = {}
        self._periodic_threads: dict[str, threading.Thread] = {}
        self._periodic_stop: dict[str, bool] = {}
        self._periodic_last_activity: dict[str, float] = {}
        self._periodic_latest_sample: dict[str, object] | None = None
        self._periodic_samples_seen = 0
        self._periodic_last_error: str | None = None
        self._periodic_records_by_session: dict[str, list[dict[str, object]]] = {}
        self._connection_lock = threading.Lock()
        self._idle_connections: list[http.client.HTTPConnection] = []
        self._event_watch_last_seq: int | None = None
        self._event_log_by_session: dict[str, list[dict[str, object]]] = {}
        self._event_log_seen_seqs: dict[str, set[int]] = {}
        self._event_log_last_seq: dict[str, int | None] = {}
        self._event_log_threads: dict[str, threading.Thread] = {}
        self._event_log_stop: dict[str, bool] = {}
        self._event_log_last_activity: dict[str, float] = {}

    def notify_local_operation(
        self,
        *,
        session_id: str,
        event_kind: str,
        occurred_at_monotonic_ms: int | None,
        point_x: float | None = None,
        point_y: float | None = None,
        coordinate_space: str | None = None,
    ) -> None:
        """Schedule a one-shot DOM hit probe after a trusted local input event."""

        if event_kind not in _SUPPORTED_EVENT_KINDS:
            return
        if point_x is None or point_y is None:
            return
        now = time.time()
        with self._lock:
            self._last_operation = {
                "session_id": session_id,
                "event_kind": event_kind,
                "occurred_at_monotonic_ms": occurred_at_monotonic_ms,
                "point": (
                    {"x": point_x, "y": point_y, "coordinate_space": coordinate_space}
                    if point_x is not None and point_y is not None
                    else None
                ),
                "host_ts": now,
            }
            operation = copy.deepcopy(self._last_operation)
            if not self._enabled:
                return
            self._touch_periodic_watch_locked(session_id=session_id, now=now)
            self._touch_event_log_capture_locked(session_id=session_id, now=now)
            if now < self._next_start_after:
                self._last_error = "vm_dom_probe_backoff"
                self._completed_at = now
                self._append_record_locked(
                    operation=operation,
                    sample=None,
                    error="vm_dom_probe_backoff",
                    completed_at=now,
                )
                return
            if self._can_start_probe_locked() and not self._operation_queue:
                self._start_probe_locked(now=now, operation=operation)
                return
            self._enqueue_operation_locked(operation)
            while self._operation_queue and self._can_start_probe_locked():
                self._start_probe_locked(now=now, operation=self._pop_next_operation_locked())

    def latest_snapshot(self) -> dict[str, object]:
        """Return serializable probe state for diagnostics and consumers."""

        with self._lock:
            pending_count = len(self._operation_queue)
            return {
                "enabled": self._enabled,
                "running": self._active_probe_count > 0,
                "active_count": self._active_probe_count,
                "max_concurrent_probes": self._max_concurrent_probes(),
                "periodic": {
                    "enabled": self.config.periodic_enabled,
                    "running_session_count": sum(
                        1 for thread in self._periodic_threads.values() if thread.is_alive()
                    ),
                    "interval_seconds": self.config.periodic_interval_seconds,
                    "samples_seen": self._periodic_samples_seen,
                    "latest": copy.deepcopy(self._periodic_latest_sample),
                    "last_error": self._periodic_last_error,
                },
                "pending": pending_count > 0,
                "pending_count": pending_count,
                "url": self.config.url,
                "source": self.config.source,
                "a11y_path": self.config.a11y_path,
                "events_path": self.config.events_path,
                "click_log_url": self.config.click_log_url,
                "click_log_path": self.config.click_log_path,
                "click_log_ssh": {
                    "enabled": self.config.click_log_ssh_enabled,
                    "jump_host": self.config.click_log_ssh_jump_host,
                    "host": self.config.click_log_ssh_host,
                    "port": self.config.click_log_ssh_port,
                    "user": self.config.click_log_ssh_user,
                    "guest_path": self.config.click_log_ssh_guest_path,
                },
                "dom_at_point_path": self.config.a11y_path,
                "started_at_host_ts": self._started_at,
                "completed_at_host_ts": self._completed_at,
                "samples_seen": self._samples_seen,
                "latest": copy.deepcopy(self._latest_sample),
                "last_operation": copy.deepcopy(self._last_operation),
                "last_error": self._last_error,
            }

    def set_enabled(self, enabled: bool) -> None:
        """Update the runtime toggle used by the local settings UI."""

        with self._lock:
            self._enabled = enabled
            if not enabled:
                self._operation_queue.clear()
                for session_id in self._periodic_stop:
                    self._periodic_stop[session_id] = True
                for session_id in self._event_log_stop:
                    self._event_log_stop[session_id] = True

    def is_enabled(self) -> bool:
        """Return the current runtime enabled flag."""

        with self._lock:
            return self._enabled

    def export_records_for_session(self, session_id: str) -> tuple[dict[str, object], ...]:
        """Return immutable copies of all probe records for a recording session."""

        self._wait_for_export_drain(session_id)
        with self._lock:
            records = self._records_by_session.get(session_id, ())
            periodic_records = tuple(
                copy.deepcopy(record) for record in self._periodic_records_by_session.get(session_id, ())
            )
            action_records = tuple(
                _with_nearest_periodic_sample(
                    record=copy.deepcopy(record),
                    periodic_records=periodic_records,
                    match_window_seconds=self.config.periodic_match_window_seconds,
                )
                for record in records
            )
            records = (*action_records, *periodic_records)
        return records or self._archived_stream(session_id, "records")

    def export_event_log_for_session(self, session_id: str) -> tuple[dict[str, object], ...]:
        """Return the captured ``/events`` stream for a session, sorted by sequence.

        A final synchronous fetch grabs any tail events that arrived after the
        last background poll, then the per-session capture is stopped.
        """

        archived = self._archived_stream(session_id, "event_log")
        if archived:
            return archived
        if not self.config.event_log_enabled or self.config.source != "event_watch":
            return ()
        with self._lock:
            last_seq = self._event_log_last_seq.get(session_id)
            started = session_id in self._event_log_by_session or last_seq is not None
        try:
            events, error = self._fetch_event_list(
                since_seq=last_seq if started else None,
                limit=self.config.event_log_fetch_limit,
            )
        except Exception:  # noqa: BLE001 - export must never fail on a tail fetch
            events, error = [], "vm_event_log_tail_failed"
        if error is None and events:
            self._append_event_log_records(session_id=session_id, events=events)
        with self._lock:
            self._event_log_stop[session_id] = True
            records = tuple(copy.deepcopy(record) for record in self._event_log_by_session.get(session_id, ()))
        return tuple(
            sorted(records, key=lambda event: (_event_seq(event) if _event_seq(event) is not None else -1))
        )

    def export_click_log_for_session(self, session_id: str) -> tuple[dict[str, object], ...]:
        """Return the VM click watcher stream from the configured source."""

        archived = self._archived_stream(session_id, "click_log")
        if archived:
            return archived
        if self.config.click_log_url:
            url_records = _read_click_log_url(self.config.click_log_url, self.config.request_timeout_seconds)
            if url_records:
                return _records_for_profile(url_records, profile=self.config.profile)
        if self.config.click_log_ssh_enabled:
            remote_records = _read_remote_jsonl_file(
                host=self.config.click_log_ssh_host,
                port=self.config.click_log_ssh_port,
                user=self.config.click_log_ssh_user,
                key_path=self.config.click_log_ssh_key_path,
                jump_host=self.config.click_log_ssh_jump_host,
                guest_path=self.config.click_log_ssh_guest_path,
                timeout_seconds=self.config.click_log_ssh_timeout_seconds,
            )
            if remote_records:
                return _records_for_profile(remote_records, profile=self.config.profile)
        if self.config.click_log_path:
            return _records_for_profile(_read_jsonl_file(self.config.click_log_path), profile=self.config.profile)
        return ()

    def archive_session(
        self,
        *,
        session_id: str,
        started_at_epoch: float | None,
        ended_at_epoch: float | None,
    ) -> bool:
        """Persist bounded copies of all VM probe streams for a completed session."""

        archive_path = self._archive_path(session_id)
        if archive_path is None:
            return False
        records = self.export_records_for_session(session_id)
        event_log = _records_within_window(
            self.export_event_log_for_session(session_id),
            started_at_epoch=started_at_epoch,
            ended_at_epoch=ended_at_epoch,
        )
        click_log = _records_within_window(
            self.export_click_log_for_session(session_id),
            started_at_epoch=started_at_epoch,
            ended_at_epoch=ended_at_epoch,
        )
        payload = {
            "version": 2,
            "session_id": session_id,
            "profile": self.config.profile,
            "archived_at_epoch": time.time(),
            "records": records,
            "event_log": event_log,
            "click_log": click_log,
        }
        archive_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with suppress(OSError):
            archive_path.parent.chmod(0o700)
        temporary_path = archive_path.with_suffix(".json.tmp")
        try:
            temporary_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            temporary_path.chmod(0o600)
            temporary_path.replace(archive_path)
            archive_path.chmod(0o600)
        except OSError:
            with suppress(OSError):
                temporary_path.unlink()
            logger.exception("failed to archive VM accessibility streams", extra={"session_id": session_id})
            return False
        return True

    def _archive_path(self, session_id: str) -> Path | None:
        archive_dir = self.config.archive_dir
        if not archive_dir or not session_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for character in session_id):
            return None
        return Path(archive_dir).expanduser() / f"{session_id}.json"

    def _archived_stream(self, session_id: str, key: str) -> tuple[dict[str, object], ...]:
        archive_path = self._archive_path(session_id)
        if archive_path is None or not archive_path.is_file():
            return ()
        try:
            payload = json.loads(archive_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ()
        if not isinstance(payload, dict) or payload.get("session_id") != session_id:
            return ()
        rows = payload.get(key)
        if not isinstance(rows, list):
            return ()
        records = tuple(copy.deepcopy(row) for row in rows if isinstance(row, dict))
        if key == "records":
            return tuple(
                _normalize_archived_probe_record(
                    row,
                    profile=self.config.profile,
                    match_window_seconds=self.config.events_match_window_seconds,
                )
                for row in records
            )
        return _records_for_profile(records, profile=self.config.profile)

    def sample_point_for_export(
        self,
        *,
        session_id: str,
        occurred_at_monotonic_ms: int | None,
        point_x: float,
        point_y: float,
        coordinate_space: str,
    ) -> dict[str, object] | None:
        """Synchronously resolve one click point for export when no recorded probe exists."""

        if not self.is_enabled():
            return None
        operation: dict[str, object] = {
            "session_id": session_id,
            "event_kind": "pointer_click",
            "occurred_at_monotonic_ms": occurred_at_monotonic_ms,
            "point": {"x": point_x, "y": point_y, "coordinate_space": coordinate_space},
            "host_ts": time.time(),
        }
        started_at = time.time()
        sample: dict[str, object] | None = None
        error: str | None = None
        try:
            sample, error = self._sample_fetcher(self.config, operation)
        except Exception as exc:  # noqa: BLE001 - export fallback must never fail export
            error = f"vm_dom_probe_export_failed:{exc}"
        completed_at = time.time()
        record = _build_probe_record(
            operation=operation,
            sample=sample,
            error=error,
            started_at=started_at,
            completed_at=completed_at,
        )
        record["source"] = "export_live_dom_probe"
        return record

    def stop(self) -> None:
        """Signal periodic polling to stop and drop pending operations."""

        with self._lock:
            for session_id in self._periodic_stop:
                self._periodic_stop[session_id] = True
            for session_id in self._event_log_stop:
                self._event_log_stop[session_id] = True
            self._operation_queue.clear()
        with self._connection_lock:
            connections = tuple(self._idle_connections)
            self._idle_connections.clear()
        for connection in connections:
            try:
                connection.close()
            except OSError:
                pass

    def _wait_for_export_drain(self, session_id: str) -> None:
        timeout = max(self.config.export_drain_timeout_seconds, 0.0)
        if timeout == 0:
            return
        deadline = time.time() + timeout
        while True:
            with self._lock:
                if self._session_export_ready_locked(session_id=session_id):
                    return
            remaining = deadline - time.time()
            if remaining <= 0:
                return
            time.sleep(min(0.05, remaining))

    def _session_export_ready_locked(self, *, session_id: str) -> bool:
        pending_for_session = any(operation.get("session_id") == session_id for operation in self._operation_queue)
        if pending_for_session:
            return False
        if self._active_probe_count > 0:
            return False
        thread = self._periodic_threads.get(session_id)
        if thread is None or not thread.is_alive():
            return True
        return bool(self._periodic_records_by_session.get(session_id))

    def _start_probe_locked(self, *, now: float, operation: dict[str, object] | None) -> None:
        self._last_error = None
        self._started_at = now
        self._completed_at = None
        self._active_probe_count += 1
        threading.Thread(
            target=self._run_probe,
            args=(operation,),
            name="workrecorder-vm-a11y-probe",
            daemon=True,
        ).start()

    def _run_probe(self, operation: dict[str, object] | None) -> None:
        sample: dict[str, object] | None = None
        error: str | None = None
        try:
            sample, error = self._sample_fetcher(self.config, operation)
        except Exception as exc:  # noqa: BLE001 - probe failures must never crash ingest
            error = f"vm_a11y_probe_failed:{exc}"
            logger.warning("VM DOM hit probe request failed", exc_info=True)
        finally:
            self._record_probe_result(operation=operation, sample=sample, error=error)

    def _record_probe_result(
        self,
        *,
        operation: dict[str, object] | None,
        sample: dict[str, object] | None,
        error: str | None,
    ) -> None:
        with self._lock:
            self._active_probe_count = max(self._active_probe_count - 1, 0)
            if sample is not None:
                self._latest_sample = sample
                self._samples_seen += 1
            self._last_error = error
            self._completed_at = time.time()
            self._append_record_locked(operation=operation, sample=sample, error=error, completed_at=self._completed_at)
            if _error_should_backoff(error):
                # Only an unhealthy service (connection/HTTP failure) warrants a
                # backoff. A soft miss such as "no matching event found yet" is an
                # expected outcome for a single click and must not suppress the
                # probes for the clicks that follow it within the backoff window.
                self._next_start_after = self._completed_at + self.config.restart_backoff_seconds
                self._record_backoff_for_queued_operations_locked(completed_at=self._completed_at)
                return
            while self._operation_queue and self._can_start_probe_locked():
                self._start_probe_locked(now=self._completed_at, operation=self._pop_next_operation_locked())

    def _touch_periodic_watch_locked(self, *, session_id: str, now: float) -> None:
        _ = (session_id, now)
        return

    def _touch_event_log_capture_locked(self, *, session_id: str, now: float) -> None:
        """Start (or keep alive) the continuous full ``/events`` capture for a session."""

        if not self.config.event_log_enabled or self.config.source != "event_watch":
            return
        self._event_log_last_activity[session_id] = now
        thread = self._event_log_threads.get(session_id)
        if thread is not None and thread.is_alive():
            return
        self._event_log_stop[session_id] = False
        thread = threading.Thread(
            target=self._run_event_log_poll,
            args=(session_id,),
            name="workrecorder-vm-event-log",
            daemon=True,
        )
        self._event_log_threads[session_id] = thread
        thread.start()

    def _run_event_log_poll(self, session_id: str) -> None:
        interval = max(self.config.event_log_poll_interval_seconds, 0.0)
        idle_stop = self.config.event_log_idle_stop_seconds
        first = True
        while True:
            now = time.time()
            with self._lock:
                stop = self._event_log_stop.get(session_id, True) or not self._enabled
                last_activity = self._event_log_last_activity.get(session_id, now)
                last_seq = self._event_log_last_seq.get(session_id)
            if stop or (now - last_activity) > idle_stop:
                break
            try:
                events, error = self._fetch_event_list(
                    since_seq=None if first else last_seq,
                    limit=self.config.event_log_fetch_limit,
                )
            except Exception as exc:  # noqa: BLE001 - keep the capture loop alive on transient errors
                events, error = [], f"vm_event_log_failed:{exc}"
            first = False
            if error is None and events:
                self._append_event_log_records(session_id=session_id, events=events)
            if interval > 0:
                time.sleep(interval)
        with self._lock:
            if self._event_log_threads.get(session_id) is threading.current_thread():
                self._event_log_threads.pop(session_id, None)

    def _fetch_event_list(
        self, *, since_seq: int | None, limit: int
    ) -> tuple[list[dict[str, object]], str | None]:
        query: dict[str, str] = {}
        if since_seq is None:
            query["n"] = str(max(limit, 1))
        else:
            query["since_seq"] = str(since_seq)
        path = f"{self.config.events_path}?{urllib.parse.urlencode(query)}"
        try:
            status, body = self._http_get(path, self.config.request_timeout_seconds)
        except (http.client.HTTPException, OSError) as exc:
            return [], f"vm_event_log_request_failed:{exc}"
        if not 200 <= status < 300:
            return [], f"vm_event_log_http_{status}"
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            return [], "vm_event_log_invalid_json"
        return list(_records_for_profile(_events_from_response(parsed), profile=self.config.profile)), None

    def _append_event_log_records(self, *, session_id: str, events: list[dict[str, object]]) -> None:
        with self._lock:
            records = self._event_log_by_session.setdefault(session_id, [])
            seen = self._event_log_seen_seqs.setdefault(session_id, set())
            max_seq = self._event_log_last_seq.get(session_id)
            appended = False
            for event in events:
                seq = _event_seq(event)
                if seq is not None:
                    if seq in seen:
                        continue
                    seen.add(seq)
                    if max_seq is None or seq > max_seq:
                        max_seq = seq
                records.append(copy.deepcopy(event))
                appended = True
            self._event_log_last_seq[session_id] = max_seq
            if appended:
                self._event_log_last_activity[session_id] = time.time()
            limit = max(self.config.max_event_log_per_session, 1)
            if len(records) > limit:
                del records[: len(records) - limit]

    def _run_periodic_poll(self, session_id: str) -> None:
        interval = max(self.config.periodic_interval_seconds, 0.0)
        idle_stop = self.config.periodic_idle_stop_seconds
        while True:
            now = time.time()
            with self._lock:
                stop = self._periodic_stop.get(session_id, True) or not self._enabled
                last_activity = self._periodic_last_activity.get(session_id, now)
            if stop or (now - last_activity) > idle_stop:
                break
            try:
                sample, error = self._sample_fetcher(self.config, None)
            except Exception as exc:  # noqa: BLE001 - keep the poll loop alive on transient errors
                sample, error = None, f"vm_a11y_periodic_failed:{exc}"
            if error is not None:
                self._record_periodic_error(error)
            elif sample is not None:
                self._append_periodic_record(session_id=session_id, sample=sample, received_at=time.time())
            if interval > 0:
                time.sleep(interval)
        with self._lock:
            if self._periodic_threads.get(session_id) is threading.current_thread():
                self._periodic_threads.pop(session_id, None)

    def _append_periodic_record(self, *, session_id: str, sample: dict[str, object], received_at: float) -> None:
        sample_host_ts = sample.get("host_ts")
        record: dict[str, object] = {
            "source": "periodic_watch",
            "sample": copy.deepcopy(sample),
            "sample_host_ts": float(sample_host_ts) if isinstance(sample_host_ts, int | float) else None,
            "received_at_host_ts": received_at,
        }
        with self._lock:
            self._periodic_latest_sample = copy.deepcopy(sample)
            self._periodic_samples_seen += 1
            records = self._periodic_records_by_session.setdefault(session_id, [])
            records.append(record)
            max_history = max(self.config.max_periodic_history_per_session, 1)
            if len(records) > max_history:
                del records[: len(records) - max_history]

    def _record_periodic_error(self, error: str) -> None:
        with self._lock:
            self._periodic_last_error = error

    def _enqueue_operation_locked(self, operation: dict[str, object]) -> None:
        if _operation_priority(operation) > 0:
            self._operation_queue = deque(
                queued for queued in self._operation_queue if not _same_low_priority_bucket(queued, operation)
            )
        self._operation_queue.append(copy.deepcopy(operation))
        max_pending = max(self.config.max_pending_operations, 1)
        if len(self._operation_queue) > max_pending:
            self._drop_lowest_priority_operation_locked()

    def _pop_next_operation_locked(self) -> dict[str, object]:
        best_index = 0
        best_priority = _operation_priority(self._operation_queue[0])
        for index, operation in enumerate(self._operation_queue):
            priority = _operation_priority(operation)
            if priority < best_priority:
                best_index = index
                best_priority = priority
                if priority == 0:
                    break
        operation = self._operation_queue[best_index]
        del self._operation_queue[best_index]
        return operation

    def _drop_lowest_priority_operation_locked(self) -> None:
        worst_index = 0
        worst_priority = _operation_priority(self._operation_queue[0])
        for index, operation in enumerate(self._operation_queue):
            priority = _operation_priority(operation)
            if priority >= worst_priority:
                worst_index = index
                worst_priority = priority
        del self._operation_queue[worst_index]

    def _record_backoff_for_queued_operations_locked(self, *, completed_at: float) -> None:
        queued = tuple(self._operation_queue)
        self._operation_queue.clear()
        for operation in queued:
            self._append_record_locked(
                operation=operation,
                sample=None,
                error="vm_dom_probe_backoff",
                completed_at=completed_at,
            )

    def _append_record_locked(
        self,
        *,
        operation: dict[str, object] | None,
        sample: dict[str, object] | None,
        error: str | None,
        completed_at: float,
    ) -> None:
        if operation is None:
            return
        session_id = operation.get("session_id")
        if not isinstance(session_id, str):
            return
        record = _build_probe_record(
            operation=operation,
            sample=sample,
            error=error,
            started_at=self._started_at,
            completed_at=completed_at,
        )
        records = self._records_by_session.setdefault(session_id, [])
        records.append(record)
        max_history = max(self.config.max_history_per_session, 1)
        if len(records) > max_history:
            del records[: len(records) - max_history]

    def _can_start_probe_locked(self) -> bool:
        return self._active_probe_count < self._max_concurrent_probes()

    def _max_concurrent_probes(self) -> int:
        if self.config.source == "event_watch":
            return 1
        return max(self.config.max_concurrent_probes, 1)

    def _http_sample_fetcher(
        self,
        config: VMAccessibilityProbeConfig,
        operation: dict[str, object] | None,
    ) -> tuple[dict[str, object] | None, str | None]:
        if config.source == "event_watch":
            return self._event_watch_sample_fetcher(config, operation)
        path = config.a11y_path
        query: dict[str, str] = {}
        if operation is None:
            return None, "vm_dom_probe_requires_point_operation"
        point = _point_from_operation(operation) if operation is not None else None
        if point is None:
            return None, "vm_dom_probe_missing_point"
        query["x"] = _query_coordinate(point["x"])
        query["y"] = _query_coordinate(point["y"])
        if query:
            path = f"{path}?{urllib.parse.urlencode(query)}"
        try:
            status, body = self._http_get(path, config.request_timeout_seconds)
        except (http.client.HTTPException, OSError) as exc:
            return None, f"vm_dom_probe_request_failed:{exc}"
        if status == 404:
            fallback_path = _trailing_slash_path(path)
            if fallback_path != path:
                try:
                    status, body = self._http_get(fallback_path, config.request_timeout_seconds)
                    path = fallback_path
                except (http.client.HTTPException, OSError) as exc:
                    return None, f"vm_dom_probe_request_failed:{exc}"
        if not 200 <= status < 300:
            return None, f"vm_dom_probe_http_{status}:{path}:{_error_body_snippet(body)}"
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            logger.warning("VM DOM probe returned invalid JSON", extra={"body": body[:240]})
            return None, "vm_dom_probe_invalid_json"
        sample = parsed if isinstance(parsed, dict) else {"value": parsed}
        sample.setdefault("host_ts", time.time())
        return sample, None

    def _event_watch_sample_fetcher(
        self,
        config: VMAccessibilityProbeConfig,
        operation: dict[str, object] | None,
    ) -> tuple[dict[str, object] | None, str | None]:
        if operation is None:
            return None, "vm_event_watch_requires_operation"
        last_seq = self._event_watch_last_seq
        last_body: bytes = b""
        for _attempt in range(max(config.events_poll_attempts, 1)):
            query: dict[str, str] = {}
            if last_seq is None:
                query["n"] = str(max(config.events_limit, 1))
            else:
                query["since_seq"] = str(last_seq)
            path = config.events_path
            if query:
                path = f"{path}?{urllib.parse.urlencode(query)}"
            try:
                status, body = self._http_get(path, config.request_timeout_seconds)
            except (http.client.HTTPException, OSError) as exc:
                return None, f"vm_event_watch_request_failed:{exc}"
            last_body = body
            if not 200 <= status < 300:
                return None, f"vm_event_watch_http_{status}:{path}:{_error_body_snippet(body)}"
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                logger.warning("VM event-watch returned invalid JSON", extra={"body": body[:240]})
                return None, "vm_event_watch_invalid_json"
            events = list(_records_for_profile(_events_from_response(parsed), profile=config.profile))
            if events:
                event = _select_event_watch_event(
                    events,
                    operation=operation,
                    last_seq=last_seq,
                    match_window_seconds=config.events_match_window_seconds,
                )
                if event is not None:
                    seq = _event_seq(event)
                    if seq is not None:
                        self._event_watch_last_seq = seq
                        last_seq = seq
                    if _event_watch_is_generic_document_focus(event):
                        if config.events_poll_interval_seconds > 0:
                            time.sleep(config.events_poll_interval_seconds)
                        continue
                    return _normalize_event_watch_sample(event), None
                max_seq = _max_event_seq(events)
                if max_seq is not None:
                    self._event_watch_last_seq = max_seq
                    last_seq = max_seq
            if config.events_poll_interval_seconds > 0:
                time.sleep(config.events_poll_interval_seconds)
        fallback_sample, fallback_error = self._event_watch_recent_fallback(config, operation)
        if fallback_sample is not None:
            return fallback_sample, None
        if fallback_error is not None:
            return None, f"vm_event_watch_no_event:{_error_body_snippet(last_body)};{fallback_error}"
        return None, f"vm_event_watch_no_event:{_error_body_snippet(last_body)}"

    def _event_watch_recent_fallback(
        self,
        config: VMAccessibilityProbeConfig,
        operation: dict[str, object],
    ) -> tuple[dict[str, object] | None, str | None]:
        query = {"n": str(max(config.event_log_fetch_limit, config.events_limit, 200))}
        path = f"{config.events_path}?{urllib.parse.urlencode(query)}"
        try:
            status, body = self._http_get(path, config.request_timeout_seconds)
        except (http.client.HTTPException, OSError) as exc:
            return None, f"recent_fallback_request_failed:{exc}"
        if not 200 <= status < 300:
            return None, f"recent_fallback_http_{status}:{path}:{_error_body_snippet(body)}"
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            logger.warning("VM event-watch recent fallback returned invalid JSON", extra={"body": body[:240]})
            return None, "recent_fallback_invalid_json"
        events = list(_records_for_profile(_events_from_response(parsed), profile=config.profile))
        event = _select_event_watch_event(
            events,
            operation=operation,
            last_seq=None,
            match_window_seconds=config.events_match_window_seconds,
            prefer_nearest=True,
        )
        if event is None:
            return None, f"recent_fallback_no_match:{_error_body_snippet(body)}"
        seq = _event_seq(event)
        if seq is not None:
            self._event_watch_last_seq = seq
        sample = _normalize_event_watch_sample(event)
        sample["event_watch_match_source"] = "recent_fallback"
        return sample, None

    def _http_get(self, path: str, timeout: float) -> tuple[int, bytes]:
        for attempt in range(2):
            connection = self._acquire_connection(timeout)
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                body = response.read()
                status = response.status
                self._release_connection(connection)
                return status, body
            except (http.client.HTTPException, OSError):
                try:
                    connection.close()
                except OSError:
                    pass
                if attempt == 0:
                    continue
                raise
        raise http.client.HTTPException("vm_dom_probe_exhausted_retries")

    def _acquire_connection(self, timeout: float) -> http.client.HTTPConnection:
        with self._connection_lock:
            while self._idle_connections:
                connection = self._idle_connections.pop()
                connection.timeout = timeout
                return connection
        return self._new_connection(timeout)

    def _new_connection(self, timeout: float) -> http.client.HTTPConnection:
        parts = urllib.parse.urlsplit(self.config.url)
        host = parts.hostname or "127.0.0.1"
        port = parts.port or 80
        return http.client.HTTPConnection(host, port, timeout=timeout)

    def _release_connection(self, connection: http.client.HTTPConnection) -> None:
        with self._connection_lock:
            if len(self._idle_connections) < max(self.config.max_concurrent_probes, 1) + 1:
                self._idle_connections.append(connection)
                return
        try:
            connection.close()
        except OSError:
            pass


def _events_from_response(parsed: object) -> list[dict[str, object]]:
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if not isinstance(parsed, dict):
        return []
    for key in ("events", "clicks", "items", "records"):
        value = parsed.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    data = parsed.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("events", "clicks", "items", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _records_for_profile(
    records: Sequence[dict[str, object]],
    *,
    profile: VMAccessibilityProbeProfile,
) -> tuple[dict[str, object], ...]:
    """Convert transport-specific rows into the canonical VM event/click shape.

    MyPCBench rows already use the canonical shape and intentionally pass through
    unchanged. OSWorld's gateway wraps every row in an envelope whose target and
    timestamp live below ``payload``; only its explicit profile unwraps that data.
    """

    if profile in {VM_A11Y_PROFILE_MYPCBENCH, VM_A11Y_PROFILE_LINUX_ATSPI}:
        return tuple(records)
    return tuple(_normalize_osworld_gateway_record(record) for record in records)


def _normalize_osworld_gateway_record(record: dict[str, object]) -> dict[str, object]:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return copy.deepcopy(record)

    normalized = copy.deepcopy(payload)
    payload_seq = _event_seq(payload)
    gateway_seq = _event_seq(record)
    if payload_seq is not None and payload_seq != gateway_seq:
        normalized["source_seq"] = payload_seq
    if gateway_seq is not None:
        # Polling uses the gateway-wide cursor, not the producer-local payload seq.
        normalized["seq"] = gateway_seq

    received_at = record.get("received_at")
    payload_ts = _event_host_ts(payload)
    timestamp = payload_ts if payload_ts is not None else received_at
    if isinstance(timestamp, int | float) and not isinstance(timestamp, bool):
        normalized["ts"] = float(timestamp)
        normalized["host_ts"] = float(timestamp)
    if isinstance(received_at, int | float) and not isinstance(received_at, bool):
        normalized["received_at"] = float(received_at)

    kind = record.get("kind")
    generation = record.get("generation")
    if isinstance(kind, str) and kind:
        normalized["gateway_kind"] = kind
    if isinstance(generation, int) and not isinstance(generation, bool):
        normalized["gateway_generation"] = generation
    normalized["source_profile"] = VM_A11Y_PROFILE_OSWORLD_GATEWAY

    for point_key in ("mouse", "screen_point"):
        point = normalized.get(point_key)
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        x, y = point[:2]
        if isinstance(x, int | float) and not isinstance(x, bool):
            normalized.setdefault("x", x)
        if isinstance(y, int | float) and not isinstance(y, bool):
            normalized.setdefault("y", y)
        break
    return normalized


def _normalize_archived_probe_record(
    record: dict[str, object],
    *,
    profile: VMAccessibilityProbeProfile,
    match_window_seconds: float,
) -> dict[str, object]:
    normalized = copy.deepcopy(record)
    if profile != VM_A11Y_PROFILE_OSWORLD_GATEWAY:
        return normalized
    sample = normalized.get("sample")
    if not isinstance(sample, dict):
        return normalized
    canonical_sample = _normalize_osworld_gateway_record(sample)
    canonical_sample.setdefault("source", "event_watch")
    hit = _event_watch_hit(canonical_sample)
    trigger = normalized.get("trigger")
    trigger_ts = trigger.get("host_ts") if isinstance(trigger, dict) else None
    sample_ts = _event_host_ts(canonical_sample)
    within_window = (
        isinstance(trigger_ts, int | float)
        and not isinstance(trigger_ts, bool)
        and sample_ts is not None
        and abs(float(trigger_ts) - sample_ts) <= max(match_window_seconds, 0.0)
    )
    if hit is not None and within_window:
        canonical_sample["hit"] = copy.deepcopy(hit)
        normalized["hit_dom"] = copy.deepcopy(hit)
    else:
        normalized["hit_dom"] = None
        if hit is not None and normalized.get("error") is None:
            normalized["error"] = "vm_event_watch_no_event:archived_osworld_sample_outside_match_window"
    normalized["sample"] = canonical_sample
    return normalized


def _read_click_log_url(url: str, timeout: float) -> tuple[dict[str, object], ...]:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        return ()
    connection_cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
    host = parts.hostname or "127.0.0.1"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
    connection = connection_cls(host, port, timeout=timeout)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        if not 200 <= response.status < 300:
            logger.warning(
                "VM click log URL returned non-2xx",
                extra={"status": response.status, "url": url, "body": body[:240]},
            )
            return ()
    except (http.client.HTTPException, OSError) as exc:
        logger.warning("VM click log URL request failed", extra={"url": url, "error": str(exc)})
        return ()
    finally:
        with suppress(OSError):
            connection.close()
    return _parse_click_log_body(body)


def _parse_click_log_body(body: bytes) -> tuple[dict[str, object], ...]:
    text = body.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return _parse_jsonl_lines(text.splitlines())
    if isinstance(parsed, list):
        return tuple(item for item in parsed if isinstance(item, dict))
    if isinstance(parsed, dict):
        return tuple(_events_from_response(parsed))
    return ()


def _read_jsonl_file(path: str) -> tuple[dict[str, object], ...]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    return _parse_jsonl_lines(lines)


def _read_remote_jsonl_file(
    *,
    host: str,
    port: int,
    user: str,
    key_path: str | None,
    jump_host: str | None,
    guest_path: str,
    timeout_seconds: float,
) -> tuple[dict[str, object], ...]:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "ConnectTimeout=3",
        "-p",
        str(port),
    ]
    if jump_host:
        command.extend(["-J", jump_host])
    if key_path:
        command.extend(["-i", key_path, "-o", "IdentitiesOnly=yes"])
    command.extend([f"{user}@{host}", f"test -f {shlex.quote(guest_path)} && cat {shlex.quote(guest_path)} || true"])
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=max(timeout_seconds, 0.1),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("VM click log SSH snapshot failed", extra={"error": str(exc)})
        return ()
    if result.returncode != 0:
        logger.warning(
            "VM click log SSH snapshot returned non-zero",
            extra={
                "returncode": result.returncode,
                "stderr": result.stderr.decode("utf-8", errors="replace")[:240],
            },
        )
        return ()
    return _parse_jsonl_lines(result.stdout.decode("utf-8", errors="replace").splitlines())


def _parse_jsonl_lines(lines: Sequence[str]) -> tuple[dict[str, object], ...]:
    records: list[dict[str, object]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return tuple(records)


def _select_event_watch_event(
    events: list[dict[str, object]],
    *,
    operation: dict[str, object],
    last_seq: int | None,
    match_window_seconds: float,
    prefer_nearest: bool = False,
) -> dict[str, object] | None:
    candidates = []
    for event in events:
        seq = _event_seq(event)
        if last_seq is not None and seq is not None and seq <= last_seq:
            continue
        candidates.append(event)
    if not candidates:
        return None
    operation_ts = operation.get("host_ts")
    if isinstance(operation_ts, int | float):
        with_ts = [
            (abs(float(ts) - float(operation_ts)), _event_watch_specificity(event), event)
            for event in candidates
            if (ts := _event_host_ts(event)) is not None
        ]
        if with_ts:
            in_window = [item for item in with_ts if item[0] <= max(match_window_seconds, 0.0)]
            if in_window:
                if prefer_nearest:
                    return min(
                        in_window,
                        key=lambda item: (
                            item[0],
                            _event_watch_point_distance(item[2], operation),
                            -item[1],
                        ),
                    )[2]
                return min(in_window, key=lambda item: (-item[1], item[0]))[2]
            return None
    if any(_event_seq(event) is not None for event in candidates):
        return max(candidates, key=lambda event: (_event_seq(event) if _event_seq(event) is not None else -1))
    return candidates[-1]


def _event_watch_point_distance(event: dict[str, object], operation: dict[str, object]) -> float:
    point = operation.get("point")
    if not isinstance(point, dict):
        return float("inf")
    op_x = point.get("x")
    op_y = point.get("y")
    if not isinstance(op_x, (int, float)) or not isinstance(op_y, (int, float)):
        return float("inf")
    event_x = event.get("x")
    event_y = event.get("y")
    if (not isinstance(event_x, (int, float)) or not isinstance(event_y, (int, float))) and isinstance(
        event.get("event"), dict
    ):
        nested = event["event"]
        event_x = nested.get("x")
        event_y = nested.get("y")
    if not isinstance(event_x, (int, float)) or not isinstance(event_y, (int, float)):
        return float("inf")
    return abs(float(event_x) - float(op_x)) + abs(float(event_y) - float(op_y))


def _event_watch_is_generic_document_focus(event: dict[str, object]) -> bool:
    if _event_watch_specificity(event) > 0:
        return False
    raw_event = event.get("event")
    event_name = raw_event.get("event") if isinstance(raw_event, dict) else raw_event
    role = event.get("role")
    if role is None and isinstance(raw_event, dict):
        role = raw_event.get("role")
    return (
        isinstance(event_name, str)
        and event_name.startswith("focus")
        and isinstance(role, str)
        and role.strip().lower() == "document web"
    )


def _event_watch_specificity(event: dict[str, object]) -> int:
    score = 0
    for key in ("hit", "dom", "element", "target", "node"):
        if isinstance(event.get(key), dict):
            score += 2
    if isinstance(event.get("a11y"), dict):
        score += 1
    if event.get("button") is not None:
        score += 1
    nested = event.get("event")
    if isinstance(nested, dict):
        score += _event_watch_specificity(nested)
    return score


def _normalize_event_watch_sample(event: dict[str, object]) -> dict[str, object]:
    sample = copy.deepcopy(event)
    sample["source"] = "event_watch"
    seq = _event_seq(event)
    if seq is not None:
        sample["seq"] = seq
    host_ts = _event_host_ts(event)
    sample["host_ts"] = host_ts if host_ts is not None else time.time()
    hit = _event_watch_hit(event)
    if hit is not None:
        sample["hit"] = hit
    sample["event"] = copy.deepcopy(event)
    return sample


def _event_watch_hit(event: dict[str, object]) -> dict[str, object] | None:
    # A specific accessibility hit is the accurate click target, so it wins when
    # present. Generic page/window focus is not targetable; in that case the DOM
    # element is the safer fallback for the clicked web content.
    generic_a11y: dict[str, object] | None = None
    a11y = event.get("a11y")
    if isinstance(a11y, dict):
        normalized = _normalize_dom_hit(a11y)
        if normalized is not None:
            if not _normalized_hit_is_generic_focus(normalized):
                return normalized
            generic_a11y = normalized
    nested = event.get("event")
    if isinstance(nested, dict):
        nested_a11y = nested.get("a11y")
        if isinstance(nested_a11y, dict):
            normalized = _normalize_dom_hit(nested_a11y)
            if normalized is not None:
                if not _normalized_hit_is_generic_focus(normalized):
                    return normalized
                generic_a11y = generic_a11y or normalized
    for key in ("hit", "dom", "element", "target", "node", "focused", "focus"):
        value = event.get(key)
        if isinstance(value, dict):
            normalized = _normalize_dom_hit(value)
            if normalized is not None:
                return normalized
    if isinstance(nested, dict):
        for key in ("hit", "dom", "element", "target", "node", "focused", "focus"):
            value = nested.get(key)
            if isinstance(value, dict):
                normalized = _normalize_dom_hit(value)
                if normalized is not None:
                    return normalized
        hit = _event_watch_hit(nested)
        if hit is not None:
            return hit
    normalized_event = _normalize_dom_hit(event)
    if normalized_event is not None and not _normalized_hit_is_generic_focus(normalized_event):
        return normalized_event
    return generic_a11y or normalized_event


def _normalize_dom_hit(value: dict[str, object]) -> dict[str, object] | None:
    keys = ("tag", "id", "cls", "role", "aria", "name", "href", "text", "rect", "bbox")
    normalized = {key: copy.deepcopy(value.get(key)) for key in keys if key in value}
    if "text" not in normalized:
        for key in ("label", "title", "value", "description"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                normalized["text"] = text
                break
    if "tag" not in normalized:
        for key in ("node_name", "tagName", "type"):
            tag = value.get(key)
            if isinstance(tag, str) and tag.strip():
                normalized["tag"] = tag
                break
    if not any(normalized.get(key) for key in ("tag", "role", "aria", "name", "text", "href")):
        return None
    return normalized


def _normalized_hit_is_generic_focus(hit: dict[str, object]) -> bool:
    role = hit.get("role")
    role_text = role.strip().lower() if isinstance(role, str) else ""
    return role_text in {"document web", "window", "frame"}


def _event_seq(event: dict[str, object]) -> int | None:
    for key in ("seq", "sequence", "sequence_id", "id"):
        value = event.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _max_event_seq(events: list[dict[str, object]]) -> int | None:
    values = [seq for event in events if (seq := _event_seq(event)) is not None]
    return max(values) if values else None


def _event_host_ts(event: dict[str, object]) -> float | None:
    for key in ("host_ts", "ts", "timestamp", "time"):
        value = event.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            return float(value)
    return None


def _records_within_window(
    records: Sequence[dict[str, object]],
    *,
    started_at_epoch: float | None,
    ended_at_epoch: float | None,
    margin_seconds: float = 5.0,
) -> tuple[dict[str, object], ...]:
    """Keep external log rows near one recording instead of archiving global history."""

    if started_at_epoch is None and ended_at_epoch is None:
        return tuple(copy.deepcopy(record) for record in records)
    lower = started_at_epoch - margin_seconds if started_at_epoch is not None else None
    upper = ended_at_epoch + margin_seconds if ended_at_epoch is not None else None
    selected: list[dict[str, object]] = []
    for record in records:
        timestamp = _event_host_ts(record)
        if timestamp is None:
            continue
        if lower is not None and timestamp < lower:
            continue
        if upper is not None and timestamp > upper:
            continue
        selected.append(copy.deepcopy(record))
    return tuple(selected)


def _operation_priority(operation: dict[str, object]) -> int:
    event_kind = operation.get("event_kind")
    return _EVENT_PRIORITY.get(event_kind, 99) if isinstance(event_kind, str) else 99


def _same_low_priority_bucket(first: dict[str, object], second: dict[str, object]) -> bool:
    if _operation_priority(first) == 0 or _operation_priority(second) == 0:
        return False
    return first.get("session_id") == second.get("session_id") and first.get("event_kind") == second.get("event_kind")


def _with_nearest_periodic_sample(
    *,
    record: dict[str, object],
    periodic_records: tuple[dict[str, object], ...],
    match_window_seconds: float,
) -> dict[str, object]:
    trigger = record.get("trigger")
    operation_ts = trigger.get("host_ts") if isinstance(trigger, dict) else None
    if not isinstance(operation_ts, int | float) or not periodic_records:
        return record
    nearest: dict[str, object] | None = None
    nearest_delta = float("inf")
    for candidate in periodic_records:
        sample_ts = candidate.get("sample_host_ts") or candidate.get("received_at_host_ts")
        if not isinstance(sample_ts, int | float):
            continue
        abs_delta = abs(float(sample_ts) - float(operation_ts))
        if abs_delta < nearest_delta:
            nearest = candidate
            nearest_delta = abs_delta
    if nearest is None or nearest_delta > match_window_seconds:
        return record
    sample_ts = nearest.get("sample_host_ts") or nearest.get("received_at_host_ts")
    if not isinstance(sample_ts, int | float):
        return record
    record["periodic"] = {
        "source": "periodic_watch",
        "sample": copy.deepcopy(nearest.get("sample")),
        "sample_host_ts": float(sample_ts),
        "received_at_host_ts": nearest.get("received_at_host_ts"),
        "operation_to_sample_ms": round((float(sample_ts) - float(operation_ts)) * 1000, 3),
        "abs_operation_to_sample_ms": round(abs(float(sample_ts) - float(operation_ts)) * 1000, 3),
        "match_window_ms": round(match_window_seconds * 1000, 3),
    }
    return record


def _build_alignment(
    *,
    operation: dict[str, object],
    sample: dict[str, object] | None,
    completed_at: float,
) -> dict[str, object]:
    mac_point = _point_from_operation(operation)
    alignment: dict[str, object] = {"mac_point": mac_point}
    operation_ts = operation.get("host_ts")
    sample_ts = sample.get("host_ts") if sample is not None else None
    if isinstance(operation_ts, int | float):
        alignment["operation_to_completed_ms"] = round((completed_at - float(operation_ts)) * 1000, 3)
        if isinstance(sample_ts, int | float):
            alignment["operation_to_sample_ms"] = round((float(sample_ts) - float(operation_ts)) * 1000, 3)
    elapsed_ms = sample.get("elapsed_ms") if sample is not None else None
    if isinstance(elapsed_ms, int | float):
        alignment["service_elapsed_ms"] = round(float(elapsed_ms), 3)
    return alignment


def _build_probe_record(
    *,
    operation: dict[str, object],
    sample: dict[str, object] | None,
    error: str | None,
    started_at: float | None,
    completed_at: float,
) -> dict[str, object]:
    return {
        "trigger": copy.deepcopy(operation),
        "sample": copy.deepcopy(sample),
        "hit_node": _hit_node_for_operation(operation=operation, sample=sample),
        "hit_dom": _hit_dom_for_operation(sample=sample),
        "hit_frames": _hit_frames_for_operation(operation=operation, sample=sample),
        "alignment": _build_alignment(operation=operation, sample=sample, completed_at=completed_at),
        "error": error,
        "started_at_host_ts": started_at,
        "completed_at_host_ts": completed_at,
    }


def _hit_node_for_operation(
    *,
    operation: dict[str, object],
    sample: dict[str, object] | None,
) -> dict[str, object] | None:
    point = _point_from_operation(operation)
    if point is None or sample is None:
        return None
    tree = sample.get("tree")
    x = point.get("x")
    y = point.get("y")
    if not isinstance(tree, dict) or not isinstance(x, int | float) or not isinstance(y, int | float):
        return None
    return _deepest_node_containing(tree, float(x), float(y))


def _hit_frames_for_operation(
    *,
    operation: dict[str, object],
    sample: dict[str, object] | None,
) -> list[dict[str, object]]:
    point = _point_from_operation(operation)
    if point is None or sample is None:
        return []
    x = point.get("x")
    y = point.get("y")
    frames = sample.get("frames")
    if not isinstance(frames, list) or not isinstance(x, int | float) or not isinstance(y, int | float):
        return []
    matches = [
        _frame_hit_summary(frame)
        for frame in frames
        if isinstance(frame, dict) and _bbox_contains(frame.get("bbox"), float(x), float(y))
    ]
    return sorted(
        (match for match in matches if match is not None),
        key=lambda frame: (
            _bbox_area(frame.get("bbox")) or float("inf"),
            str(frame.get("app") or ""),
            str(frame.get("window") or ""),
        ),
    )


def _frame_hit_summary(frame: dict[str, object]) -> dict[str, object] | None:
    bbox = frame.get("bbox")
    if not _valid_bbox(bbox):
        return None
    return {
        "app": frame.get("app"),
        "window": frame.get("window"),
        "role": frame.get("role"),
        "bbox": copy.deepcopy(bbox),
        "active": frame.get("active"),
        "states": copy.deepcopy(frame.get("states")),
    }


def _deepest_node_containing(node: dict[str, object], x: float, y: float) -> dict[str, object] | None:
    if not _bbox_contains(node.get("bbox"), x, y):
        return None
    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                hit = _deepest_node_containing(child, x, y)
                if hit is not None:
                    return hit
    return {
        "role": node.get("role"),
        "name": node.get("name"),
        "bbox": copy.deepcopy(node.get("bbox")),
        "states": copy.deepcopy(node.get("states")),
    }


def _hit_dom_for_operation(*, sample: dict[str, object] | None) -> dict[str, object] | None:
    if sample is None:
        return None
    hit = sample.get("hit")
    if isinstance(hit, dict):
        return copy.deepcopy(hit)
    dom = sample.get("dom")
    if isinstance(dom, dict):
        return copy.deepcopy(dom)
    return None


def _bbox_contains(bbox: object, x: float, y: float) -> bool:
    if not _valid_bbox(bbox):
        return False
    coords = [_as_float(value) for value in bbox[:4]]  # type: ignore[index]
    bx, by, bw, bh = coords[0], coords[1], coords[2], coords[3]
    if bx is None or by is None or bw is None or bh is None:
        return False
    return bx <= x <= bx + bw and by <= y <= by + bh


def _valid_bbox(bbox: object) -> bool:
    if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
        return False
    coords = [_as_float(value) for value in bbox[:4]]
    if any(value is None for value in coords):
        return False
    bx, by, bw, bh = coords[0], coords[1], coords[2], coords[3]
    return bx is not None and by is not None and bw is not None and bh is not None and bw > 0 and bh > 0


def _bbox_area(bbox: object) -> float | None:
    if not _valid_bbox(bbox):
        return None
    coords = [_as_float(value) for value in bbox[:4]]  # type: ignore[index]
    width = coords[2]
    height = coords[3]
    if width is None or height is None:
        return None
    return width * height


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _point_from_operation(operation: dict[str, object]) -> dict[str, object] | None:
    point = operation.get("point")
    if not isinstance(point, dict):
        return None
    x = point.get("x")
    y = point.get("y")
    if not isinstance(x, int | float) or not isinstance(y, int | float):
        return None
    normalized: dict[str, object] = {"x": float(x), "y": float(y)}
    space = point.get("coordinate_space")
    if isinstance(space, str):
        normalized["coordinate_space"] = space
    return normalized


def _query_coordinate(value: object) -> str:
    return str(int(round(float(value))))


def _trailing_slash_path(path: str) -> str:
    base, separator, query = path.partition("?")
    if base.endswith("/"):
        return path
    return f"{base}/{separator}{query}" if separator else f"{base}/"


def _error_body_snippet(body: bytes, *, max_chars: int = 240) -> str:
    text = body.decode("utf-8", errors="replace").strip().replace("\n", " ")
    if len(text) > max_chars:
        return text[:max_chars] + "..."
    return text or "<empty>"
