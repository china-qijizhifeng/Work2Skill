from __future__ import annotations

import copy
import json
import subprocess
import threading
import time

from packages.active_capture.application import vm_a11y_probe as probe_module
from packages.active_capture.application.vm_a11y_probe import (
    VMAccessibilityProbeConfig,
    VMAccessibilityProbeService,
    VM_A11Y_PROFILE_OSWORLD_GATEWAY,
    _event_watch_hit,
)


class _FakeFetcher:
    """Records the operations it is asked to sample and returns canned samples."""

    def __init__(
        self,
        *,
        delay_seconds: float = 0.0,
        error: str | None = None,
        action_sample: dict[str, object] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._delay_seconds = delay_seconds
        self._error = error
        self._action_sample = action_sample
        self.operations: list[dict[str, object] | None] = []

    def __call__(
        self,
        config: VMAccessibilityProbeConfig,
        operation: dict[str, object] | None,
    ) -> tuple[dict[str, object] | None, str | None]:
        with self._lock:
            self.operations.append(copy.deepcopy(operation))
            index = len([op for op in self.operations if op is not None])
        if self._delay_seconds:
            time.sleep(self._delay_seconds)
        if operation is None:
            return {"active_window": "watch-window", "host_ts": time.time()}, None
        if self._error is not None:
            return None, self._error
        if self._action_sample is not None:
            return copy.deepcopy(self._action_sample), None
        return {"sample": index, "host_ts": time.time()}, None

    @property
    def action_calls(self) -> list[dict[str, object]]:
        with self._lock:
            return [op for op in self.operations if op is not None]


def _click(service: VMAccessibilityProbeService, *, ms: int, x: float, y: float, session: str = "acs_1") -> None:
    service.notify_local_operation(
        session_id=session,
        event_kind="pointer_click",
        occurred_at_monotonic_ms=ms,
        point_x=x,
        point_y=y,
        coordinate_space="macos_global",
    )


def test_vm_a11y_probe_samples_service_after_local_operation() -> None:
    sample = {
        "active_app": "electron",
        "active_window": "Calc",
        "hit": {"tag": "button", "text": "Save", "role": "button", "href": None},
        "nodes": 2,
        "elapsed_ms": 135.3,
        "tree": {
            "role": "window",
            "name": "Calc",
            "bbox": [0, 0, 1000, 800],
            "children": [{"role": "button", "name": "Save", "bbox": [900, 200, 100, 80], "children": []}],
        },
    }
    fetcher = _FakeFetcher(action_sample=sample)
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(periodic_enabled=False),
        sample_fetcher=fetcher,
    )

    _click(service, ms=123, x=944.0, y=244.0)
    snapshot = _wait_for_sample(service, samples_seen=1)

    assert len(fetcher.action_calls) == 1
    assert fetcher.action_calls[0]["point"] == {"x": 944.0, "y": 244.0, "coordinate_space": "macos_global"}
    assert snapshot["running"] is False
    assert snapshot["pending"] is False
    assert snapshot["samples_seen"] == 1
    assert isinstance(snapshot["latest"], dict)
    assert snapshot["latest"]["active_window"] == "Calc"

    records = service.export_records_for_session("acs_1")
    assert len(records) == 1
    assert records[0]["alignment"]["mac_point"] == {"x": 944.0, "y": 244.0, "coordinate_space": "macos_global"}
    assert records[0]["alignment"]["service_elapsed_ms"] == 135.3
    assert records[0]["hit_node"]["role"] == "button"
    assert records[0]["hit_node"]["name"] == "Save"
    assert records[0]["hit_dom"] == {"tag": "button", "text": "Save", "role": "button", "href": None}


def test_vm_a11y_probe_records_containing_frames_when_tree_misses_point() -> None:
    sample = {
        "active_window": "Wrong window",
        "tree": {
            "role": "window",
            "name": "Wrong window",
            "bbox": [300, 300, 100, 100],
            "children": [],
        },
        "frames": [
            {
                "app": "Firefox",
                "window": "SprintBoard",
                "role": "frame",
                "bbox": [66, 32, 1446, 833],
                "active": True,
                "states": ["ACTIVE", "SHOWING", "VISIBLE"],
            },
            {
                "app": "gjs",
                "window": "@!0,0",
                "role": "frame",
                "bbox": [0, 0, 1512, 865],
                "active": False,
                "states": ["SHOWING", "VISIBLE"],
            },
        ],
    }
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(periodic_enabled=False),
        sample_fetcher=_FakeFetcher(action_sample=sample),
    )

    _click(service, ms=123, x=131.0, y=222.0)
    _wait_for_sample(service, samples_seen=1)
    records = service.export_records_for_session("acs_1")

    assert records[0]["hit_node"] is None
    assert records[0]["hit_frames"][0]["app"] == "Firefox"
    assert records[0]["hit_frames"][0]["window"] == "SprintBoard"


def test_vm_a11y_probe_queries_dom_at_click_point() -> None:
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(),
    )
    paths: list[str] = []

    def fake_http_get(path: str, timeout: float) -> tuple[int, bytes]:
        paths.append(path)
        assert timeout == service.config.request_timeout_seconds
        return 200, b'{"hit":{"tag":"button","text":"Save","role":"button"}}'

    setattr(service, "_http_get", fake_http_get)

    action_sample, action_error = service._http_sample_fetcher(
        service.config,
        {"session_id": "acs_1", "point": {"x": 451, "y": 434, "coordinate_space": "vm_screen"}},
    )

    assert action_error is None
    assert action_sample is not None
    assert action_sample["hit"] == {"tag": "button", "text": "Save", "role": "button"}
    assert paths == ["/dom_at_point?x=451&y=434"]


def test_vm_a11y_probe_rounds_fractional_dom_coordinates() -> None:
    service = VMAccessibilityProbeService(config=VMAccessibilityProbeConfig())
    paths: list[str] = []

    def fake_http_get(path: str, timeout: float) -> tuple[int, bytes]:
        paths.append(path)
        return 200, b'{"hit":null}'

    setattr(service, "_http_get", fake_http_get)

    sample, error = service._http_sample_fetcher(
        service.config,
        {"session_id": "acs_1", "point": {"x": 265.9232897202999, "y": 681.5255190311419}},
    )

    assert error is None
    assert sample is not None
    assert paths == ["/dom_at_point?x=266&y=682"]


def test_vm_a11y_probe_falls_back_to_trailing_slash_dom_path() -> None:
    service = VMAccessibilityProbeService(config=VMAccessibilityProbeConfig())
    paths: list[str] = []

    def fake_http_get(path: str, timeout: float) -> tuple[int, bytes]:
        paths.append(path)
        if len(paths) == 1:
            return 404, b'{"detail":"not found"}'
        return 200, b'{"hit":{"tag":"a","text":"Docs","role":"link"}}'

    setattr(service, "_http_get", fake_http_get)

    sample, error = service._http_sample_fetcher(
        service.config,
        {"session_id": "acs_1", "point": {"x": 451, "y": 434, "coordinate_space": "vm_screen"}},
    )

    assert error is None
    assert sample is not None
    assert sample["hit"] == {"tag": "a", "text": "Docs", "role": "link"}
    assert paths == ["/dom_at_point?x=451&y=434", "/dom_at_point/?x=451&y=434"]


def test_vm_a11y_probe_includes_error_body_for_http_failure() -> None:
    service = VMAccessibilityProbeService(config=VMAccessibilityProbeConfig())

    def fake_http_get(path: str, timeout: float) -> tuple[int, bytes]:
        return 500, b'{"error":"marionette target unavailable"}'

    setattr(service, "_http_get", fake_http_get)

    sample, error = service._http_sample_fetcher(
        service.config,
        {"session_id": "acs_1", "point": {"x": 1170, "y": 640}},
    )

    assert sample is None
    assert error == 'vm_dom_probe_http_500:/dom_at_point?x=1170&y=640:{"error":"marionette target unavailable"}'


def test_vm_a11y_probe_can_read_event_watch_events() -> None:
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(source="event_watch", url="http://127.0.0.1:7072"),
    )
    paths: list[str] = []

    def fake_http_get(path: str, timeout: float) -> tuple[int, bytes]:
        paths.append(path)
        return (
            200,
            b'{"events":[{"seq":41,"element":{"tag":"input","text":"old"}},'
            b'{"seq":42,"element":{"tag":"button","text":"Search with Google or enter address","role":"combobox"},'
            b'"url":"http://localhost:3004/","title":"Firefox"}]}',
        )

    setattr(service, "_http_get", fake_http_get)

    sample, error = service._http_sample_fetcher(
        service.config,
        {"session_id": "acs_1", "point": {"x": 451, "y": 434, "coordinate_space": "vm_screen"}},
    )

    assert error is None
    assert sample is not None
    assert sample["source"] == "event_watch"
    assert sample["seq"] == 42
    assert sample["hit"] == {
        "tag": "button",
        "role": "combobox",
        "text": "Search with Google or enter address",
    }
    assert paths == ["/events?n=20"]


def test_vm_a11y_probe_osworld_profile_unwraps_gateway_event_envelope() -> None:
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(
            profile=VM_A11Y_PROFILE_OSWORLD_GATEWAY,
            source="event_watch",
            url="http://[::1]:7073",
        ),
    )
    operation_ts = 1784702586.85

    def fake_http_get(path: str, timeout: float) -> tuple[int, bytes]:
        assert path == "/events?n=20"
        return (
            200,
            b'[{"seq":4,"generation":0,"kind":"events","received_at":1784702586.837,'
            b'"payload":{"seq":1,"ts":1784702586.834,"event":"object:state-changed:focused",'
            b'"app":"code","role":"table","name":"Files","bbox":[555,235,1041,731],'
            b'"mouse":[228,204]}}]',
        )

    setattr(service, "_http_get", fake_http_get)
    sample, error = service._http_sample_fetcher(
        service.config,
        {
            "session_id": "acs_osworld",
            "host_ts": operation_ts,
            "point": {"x": 228, "y": 204, "coordinate_space": "vm_screen"},
        },
    )

    assert error is None
    assert sample is not None
    assert sample["source_profile"] == "osworld_gateway_v1"
    assert sample["seq"] == 4
    assert sample["source_seq"] == 1
    assert sample["host_ts"] == 1784702586.834
    assert sample["x"] == 228
    assert sample["y"] == 204
    assert sample["hit"] == {"role": "table", "name": "Files", "bbox": [555, 235, 1041, 731]}


def test_vm_a11y_probe_default_profile_does_not_unwrap_osworld_envelope() -> None:
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(source="event_watch", url="http://127.0.0.1:7072"),
    )

    def fake_http_get(path: str, timeout: float) -> tuple[int, bytes]:
        return (
            200,
            b'[{"seq":4,"generation":0,"kind":"events","received_at":1784702586.837,'
            b'"payload":{"ts":1784702586.834,"role":"table","name":"Files",'
            b'"bbox":[555,235,1041,731]}}]',
        )

    setattr(service, "_http_get", fake_http_get)
    sample, error = service._http_sample_fetcher(
        service.config,
        {"session_id": "acs_mypcbench", "point": {"x": 228, "y": 204}},
    )

    assert error is None
    assert sample is not None
    assert "payload" in sample
    assert "source_profile" not in sample
    assert "hit" not in sample


def test_vm_a11y_probe_event_watch_uses_since_seq_after_first_event() -> None:
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(source="event_watch", url="http://127.0.0.1:7072"),
    )
    paths: list[str] = []

    def fake_http_get(path: str, timeout: float) -> tuple[int, bytes]:
        paths.append(path)
        if len(paths) == 1:
            return 200, b'{"events":[{"seq":42,"hit":{"tag":"button","text":"First"}}]}'
        return 200, b'{"events":[{"seq":43,"hit":{"tag":"a","text":"Second","href":"https://example.test"}}]}'

    setattr(service, "_http_get", fake_http_get)

    first, first_error = service._http_sample_fetcher(
        service.config,
        {"session_id": "acs_1", "point": {"x": 1, "y": 1}},
    )
    second, second_error = service._http_sample_fetcher(
        service.config,
        {"session_id": "acs_1", "point": {"x": 2, "y": 2}},
    )

    assert first_error is None
    assert second_error is None
    assert first is not None and first["hit"]["text"] == "First"
    assert second is not None and second["hit"]["text"] == "Second"
    assert paths == ["/events?n=20", "/events?since_seq=42"]


def test_vm_a11y_probe_event_watch_recent_fallback_recovers_cursor_miss() -> None:
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(
            source="event_watch",
            url="http://127.0.0.1:7072",
            events_poll_attempts=1,
            events_poll_interval_seconds=0.0,
        ),
    )
    paths: list[str] = []
    operation_ts = 1782801358.12

    def fake_http_get(path: str, timeout: float) -> tuple[int, bytes]:
        paths.append(path)
        if len(paths) == 1:
            return 200, b'{"events":[]}'
        return (
            200,
            b'{"events":[{"ts":1782801358.144,"x":664,"y":364,"button":"left",'
            b'"dom":{"tag":"SPAN","text":"Reservation Confirmed","rect":[578,169,202,21]},'
            b'"a11y":{"role":"document web","name":"HooliChat Web","bbox":[66,183,1215,617]}}]}',
        )

    setattr(service, "_http_get", fake_http_get)

    sample, error = service._http_sample_fetcher(
        service.config,
        {
            "session_id": "acs_1",
            "host_ts": operation_ts,
            "point": {"x": 664, "y": 364, "coordinate_space": "vm_screen"},
        },
    )

    assert error is None
    assert sample is not None
    assert sample["event_watch_match_source"] == "recent_fallback"
    assert sample["hit"] == {"tag": "SPAN", "text": "Reservation Confirmed", "rect": [578, 169, 202, 21]}
    assert paths == ["/events?n=20", "/events?n=200"]


def test_vm_a11y_probe_event_watch_recent_fallback_prefers_nearest_timestamp() -> None:
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(
            source="event_watch",
            url="http://127.0.0.1:7072",
            events_poll_attempts=1,
            events_poll_interval_seconds=0.0,
        ),
    )
    paths: list[str] = []
    operation_ts = 100.0

    def fake_http_get(path: str, timeout: float) -> tuple[int, bytes]:
        paths.append(path)
        if len(paths) == 1:
            return 200, b'{"events":[]}'
        return (
            200,
            b'{"events":[{"ts":99.2,"x":10,"y":10,"button":"left",'
            b'"a11y":{"role":"push button","name":"Previous","bbox":[1,2,3,4]}},'
            b'{"ts":100.03,"x":220,"y":74,"button":"left",'
            b'"dom":{"tag":"SPAN","text":"Current","rect":[200,60,50,20]},'
            b'"a11y":{"role":"document web","name":"HooliChat Web","bbox":[66,183,1215,617]}}]}',
        )

    setattr(service, "_http_get", fake_http_get)

    sample, error = service._http_sample_fetcher(
        service.config,
        {
            "session_id": "acs_1",
            "host_ts": operation_ts,
            "point": {"x": 220, "y": 74, "coordinate_space": "vm_screen"},
        },
    )

    assert error is None
    assert sample is not None
    assert sample["hit"] == {"tag": "SPAN", "text": "Current", "rect": [200, 60, 50, 20]}


def test_vm_a11y_probe_event_watch_rejects_stale_focus_before_click_hit() -> None:
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(
            source="event_watch",
            url="http://127.0.0.1:7072",
            events_poll_interval_seconds=0.0,
        ),
    )
    paths: list[str] = []
    operation_ts = 1782721282.308504

    def fake_http_get(path: str, timeout: float) -> tuple[int, bytes]:
        paths.append(path)
        if len(paths) == 1:
            return (
                200,
                b'{"events":[{"seq":131,"ts":1782721268.639,"event":"focus:",'
                b'"role":"document web","name":"HooliMail","bbox":[66,183,1216,618]}]}',
            )
        return (
            200,
            b'{"events":[{"seq":132,"ts":1782721282.344,"x":460,"y":401,"button":"left",'
            b'"dom":{"tag":"DIV","text":"reservations","rect":[378,209,200,21]},'
            b'"a11y":{"role":"combo box","name":"Filter issues by cycle","bbox":[338,389,309,24]}}]}',
        )

    setattr(service, "_http_get", fake_http_get)

    sample, error = service._http_sample_fetcher(
        service.config,
        {
            "session_id": "acs_1",
            "host_ts": operation_ts,
            "point": {"x": 516, "y": 413, "coordinate_space": "vm_screen"},
        },
    )

    assert error is None
    assert sample is not None
    assert sample["seq"] == 132
    # The accessibility hit always wins over the (often stale) DOM node when present,
    # so the click resolves to the a11y element rather than the DOM "reservations".
    assert sample["hit"] == {"role": "combo box", "name": "Filter issues by cycle", "bbox": [338, 389, 309, 24]}
    assert paths == ["/events?n=20", "/events?since_seq=131"]


def test_vm_a11y_probe_does_not_run_periodic_polling_by_default() -> None:
    fetcher = _FakeFetcher(action_sample={"active_window": "click-window", "host_ts": time.time()})
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(),
        sample_fetcher=fetcher,
    )

    _click(service, ms=123, x=944, y=244)
    _wait_for_sample(service, samples_seen=1)
    records = service.export_records_for_session("acs_1")
    service.stop()

    periodic_records = [record for record in records if record.get("source") == "periodic_watch"]
    assert periodic_records == []
    assert fetcher.operations == [fetcher.action_calls[0]]


def test_vm_a11y_probe_queues_operations_while_probe_is_running() -> None:
    fetcher = _FakeFetcher(delay_seconds=0.05)
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(max_concurrent_probes=1, periodic_enabled=False),
        sample_fetcher=fetcher,
    )

    _click(service, ms=1, x=111, y=222)
    _wait_for_running(service)
    _click(service, ms=2, x=333, y=444)
    pending_snapshot = service.latest_snapshot()
    assert pending_snapshot["pending"] is True
    assert pending_snapshot["pending_count"] == 1
    snapshot = _wait_for_sample(service, samples_seen=2)

    calls = fetcher.action_calls
    assert len(calls) == 2
    assert calls[0]["point"]["x"] == 111
    assert calls[1]["point"]["x"] == 333
    assert snapshot["pending"] is False
    records = service.export_records_for_session("acs_1")
    assert [record["trigger"]["occurred_at_monotonic_ms"] for record in records] == [1, 2]


def test_vm_a11y_export_waits_for_inflight_probe() -> None:
    fetcher = _FakeFetcher(delay_seconds=0.05, action_sample={"active_window": "delayed-vm", "host_ts": 1.25})
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(periodic_enabled=False, export_drain_timeout_seconds=1.0),
        sample_fetcher=fetcher,
    )

    _click(service, ms=1, x=111, y=222)
    records = service.export_records_for_session("acs_1")

    assert len(records) == 1
    assert records[0]["sample"]["active_window"] == "delayed-vm"


def test_vm_a11y_probe_runs_clicks_with_bounded_concurrency() -> None:
    fetcher = _FakeFetcher(delay_seconds=0.05)
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(max_concurrent_probes=2, periodic_enabled=False),
        sample_fetcher=fetcher,
    )

    _click(service, ms=1, x=111, y=222)
    _wait_for_running(service)
    _click(service, ms=2, x=333, y=444)
    snapshot = _wait_for_active_count(service, active_count=2)

    assert snapshot["active_count"] == 2
    assert snapshot["pending"] is False
    snapshot = _wait_for_sample(service, samples_seen=2)
    assert snapshot["active_count"] == 0
    assert len(fetcher.action_calls) == 2


def test_vm_a11y_probe_ignores_raw_keystrokes() -> None:
    fetcher = _FakeFetcher()
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(max_concurrent_probes=1, periodic_enabled=False),
        sample_fetcher=fetcher,
    )

    service.notify_local_operation(session_id="acs_1", event_kind="key_down", occurred_at_monotonic_ms=1)
    service.notify_local_operation(session_id="acs_1", event_kind="key_up", occurred_at_monotonic_ms=2)
    snapshot = service.latest_snapshot()

    assert fetcher.operations == []
    assert snapshot["running"] is False
    assert snapshot["pending"] is False
    assert service.export_records_for_session("acs_1") == ()


def test_vm_a11y_probe_ignores_scroll_and_typing_pause() -> None:
    fetcher = _FakeFetcher(delay_seconds=0.05)
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(max_concurrent_probes=1, periodic_enabled=False),
        sample_fetcher=fetcher,
    )

    service.notify_local_operation(session_id="acs_1", event_kind="scroll", occurred_at_monotonic_ms=1)
    service.notify_local_operation(session_id="acs_1", event_kind="typing_pause", occurred_at_monotonic_ms=2)
    snapshot = service.latest_snapshot()

    assert fetcher.action_calls == []
    assert snapshot["running"] is False
    assert snapshot["pending"] is False
    records = service.export_records_for_session("acs_1")
    assert records == ()


def test_vm_a11y_probe_records_fetch_error_and_backs_off() -> None:
    fetcher = _FakeFetcher(error="vm_dom_probe_http_503:/dom_at_point?x=111&y=222")
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(periodic_enabled=False, restart_backoff_seconds=10.0),
        sample_fetcher=fetcher,
    )

    _click(service, ms=456, x=111, y=222)
    snapshot = _wait_for_completion(service)

    assert snapshot["latest"] is None
    assert snapshot["last_error"] == "vm_dom_probe_http_503:/dom_at_point?x=111&y=222"
    records = service.export_records_for_session("acs_1")
    assert records[-1]["error"] == "vm_dom_probe_http_503:/dom_at_point?x=111&y=222"

    # The backoff defers the next probe instead of hammering the unavailable service.
    _click(service, ms=789, x=333, y=444)
    deferred = service.latest_snapshot()
    assert deferred["pending_count"] == 0
    assert len(fetcher.action_calls) == 1
    records = service.export_records_for_session("acs_1")
    assert records[-1]["error"] == "vm_dom_probe_backoff"


def test_vm_a11y_probe_soft_miss_does_not_back_off_next_click() -> None:
    # "No matching event found" is an expected per-click miss, not an unhealthy
    # service, so it must not suppress the probe for the click that follows it.
    fetcher = _FakeFetcher(error='vm_event_watch_no_event:{"events": []}')
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(periodic_enabled=False, restart_backoff_seconds=10.0),
        sample_fetcher=fetcher,
    )

    _click(service, ms=456, x=111, y=222)
    _wait_for_completion(service)
    _click(service, ms=789, x=333, y=444)
    _wait_for_completion(service)

    # Both clicks were actually probed; the first miss did not defer the second.
    assert len(fetcher.action_calls) == 2
    records = service.export_records_for_session("acs_1")
    assert [record["error"] for record in records] == [
        'vm_event_watch_no_event:{"events": []}',
        'vm_event_watch_no_event:{"events": []}',
    ]


def test_vm_a11y_probe_samples_on_pointer_drag() -> None:
    fetcher = _FakeFetcher(action_sample={"hit": {"tag": "div", "text": "Drop here"}, "host_ts": time.time()})
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(periodic_enabled=False),
        sample_fetcher=fetcher,
    )

    service.notify_local_operation(
        session_id="acs_1",
        event_kind="pointer_drag",
        occurred_at_monotonic_ms=5,
        point_x=3.0,
        point_y=4.0,
        coordinate_space="vm_screen",
    )
    _wait_for_completion(service)

    records = service.export_records_for_session("acs_1")
    assert records
    trigger = records[-1].get("trigger")
    assert isinstance(trigger, dict) and trigger.get("event_kind") == "pointer_drag"
    assert records[-1]["hit_dom"] == {"tag": "div", "text": "Drop here"}


def test_event_watch_hit_uses_dom_when_a11y_is_generic_document_focus() -> None:
    hit = _event_watch_hit(
        {
            "dom": {
                "tag": "SPAN",
                "text": "reservations@pizzabyalfredo.com",
                "rect": [324, 217, 211, 21],
            },
            "a11y": {"role": "document web", "name": "HooliChat Web", "bbox": [66, 183, 1215, 617]},
        }
    )

    assert hit == {
        "tag": "SPAN",
        "text": "reservations@pizzabyalfredo.com",
        "rect": [324, 217, 211, 21],
    }


def test_event_watch_hit_keeps_specific_a11y_before_dom() -> None:
    hit = _event_watch_hit(
        {
            "dom": {"tag": "SPAN", "text": "Reservation Confirmed"},
            "a11y": {"role": "push button", "name": "Forward", "bbox": [628, 767, 117, 39]},
        }
    )

    assert hit == {"role": "push button", "name": "Forward", "bbox": [628, 767, 117, 39]}


def test_vm_a11y_probe_event_log_captures_full_stream() -> None:
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(
            source="event_watch",
            url="http://127.0.0.1:7072",
            event_log_poll_interval_seconds=0.0,
            event_log_idle_stop_seconds=0.05,
        ),
    )
    batches: list[tuple[list[dict[str, object]], None]] = [
        ([{"seq": 2, "name": "B"}, {"seq": 1, "name": "A"}], None),
        ([{"seq": 2, "name": "B"}, {"seq": 3, "name": "C"}], None),  # seq 2 is a duplicate
        ([], None),
    ]

    def fake_fetch(*, since_seq: int | None, limit: int) -> tuple[list[dict[str, object]], None]:
        return batches.pop(0) if batches else ([], None)

    setattr(service, "_fetch_event_list", fake_fetch)
    with service._lock:
        service._touch_event_log_capture_locked(session_id="acs_1", now=time.time())

    for _ in range(200):
        with service._lock:
            if len(service._event_log_by_session.get("acs_1", [])) >= 3:
                break
        time.sleep(0.01)

    events = service.export_event_log_for_session("acs_1")
    # Full stream, de-duplicated by seq and ordered by sequence.
    assert [event["name"] for event in events] == ["A", "B", "C"]


def test_vm_a11y_probe_exports_configured_click_log(tmp_path) -> None:
    click_log = tmp_path / "clicks.jsonl"
    click_log.write_text(
        '{"ts":1782801358.144,"dom":{"tag":"SPAN","text":"Reservation Confirmed"}}\n'
        "not json\n"
        '{"ts":1782801361.062,"a11y":{"role":"entry","name":"Search HooliMail"}}\n',
        encoding="utf-8",
    )
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(click_log_path=str(click_log), periodic_enabled=False),
    )

    records = service.export_click_log_for_session("acs_1")

    assert len(records) == 2
    assert records[0]["dom"]["text"] == "Reservation Confirmed"
    assert records[1]["a11y"]["name"] == "Search HooliMail"


def test_vm_a11y_probe_archives_completed_session_streams_for_restart(tmp_path) -> None:
    click_log = tmp_path / "clicks.jsonl"
    click_log.write_text(
        '{"ts":101.5,"dom":{"tag":"BUTTON","text":"Archived click"}}\n'
        '{"ts":999.0,"dom":{"tag":"BUTTON","text":"Other session"}}\n',
        encoding="utf-8",
    )
    archive_dir = tmp_path / "archives"
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(
            source="event_watch",
            click_log_path=str(click_log),
            archive_dir=str(archive_dir),
        ),
    )
    setattr(service, "_fetch_event_list", lambda **_kwargs: ([], None))
    with service._lock:
        service._records_by_session["acs_1"] = [{"trigger": {"session_id": "acs_1"}, "hit_dom": {"text": "Live"}}]
        service._event_log_by_session["acs_1"] = [{"seq": 7, "ts": 102.0, "name": "Archived event"}]

    assert service.archive_session(
        session_id="acs_1",
        started_at_epoch=100.0,
        ended_at_epoch=110.0,
    )

    restarted = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(
            source="dom_at_point",
            archive_dir=str(archive_dir),
        ),
    )
    assert restarted.export_records_for_session("acs_1")[0]["hit_dom"]["text"] == "Live"
    assert restarted.export_event_log_for_session("acs_1")[0]["name"] == "Archived event"
    archived_clicks = restarted.export_click_log_for_session("acs_1")
    assert len(archived_clicks) == 1
    assert archived_clicks[0]["dom"]["text"] == "Archived click"


def test_vm_a11y_probe_osworld_profile_recovers_enveloped_archive(tmp_path) -> None:
    archive_dir = tmp_path / "archives"
    archive_dir.mkdir()
    envelope_event = {
        "seq": 4,
        "generation": 0,
        "kind": "events",
        "received_at": 1784702586.837,
        "payload": {
            "seq": 1,
            "ts": 1784702586.834,
            "role": "table",
            "name": "Files",
            "bbox": [555, 235, 1041, 731],
            "mouse": [228, 204],
        },
    }
    envelope_click = {
        "seq": 7,
        "generation": 0,
        "kind": "clicks",
        "received_at": 1784702604.119,
        "payload": {
            "ts": 1784702604.113,
            "screen_point": [1038, 493],
            "element": {"tag": "ntp-app", "text": "", "rect": [0, 0, 1850, 966]},
        },
    }
    (archive_dir / "acs_osworld.json").write_text(
        json.dumps(
            {
                "version": 1,
                "session_id": "acs_osworld",
                "records": [
                    {
                        "trigger": {
                            "session_id": "acs_osworld",
                            "event_kind": "pointer_click",
                            "host_ts": 1784702586.85,
                        },
                        "sample": envelope_event,
                        "hit_dom": None,
                        "error": None,
                    },
                    {
                        "trigger": {
                            "session_id": "acs_osworld",
                            "event_kind": "pointer_click",
                            "host_ts": 1784702600.0,
                        },
                        "sample": envelope_event,
                        "hit_dom": {"role": "table", "name": "stale value"},
                        "error": None,
                    },
                ],
                "event_log": [envelope_event],
                "click_log": [envelope_click],
            }
        ),
        encoding="utf-8",
    )
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(
            profile=VM_A11Y_PROFILE_OSWORLD_GATEWAY,
            source="event_watch",
            archive_dir=str(archive_dir),
        )
    )

    records = service.export_records_for_session("acs_osworld")
    events = service.export_event_log_for_session("acs_osworld")
    clicks = service.export_click_log_for_session("acs_osworld")

    assert records[0]["hit_dom"] == {"role": "table", "name": "Files", "bbox": [555, 235, 1041, 731]}
    assert records[1]["hit_dom"] is None
    assert records[1]["error"] == "vm_event_watch_no_event:archived_osworld_sample_outside_match_window"
    assert events[0]["seq"] == 4
    assert events[0]["ts"] == 1784702586.834
    assert events[0]["name"] == "Files"
    assert clicks[0]["seq"] == 7
    assert clicks[0]["ts"] == 1784702604.113
    assert clicks[0]["element"]["tag"] == "ntp-app"


def test_vm_a11y_probe_exports_click_log_from_configured_url(monkeypatch) -> None:
    calls: list[tuple[str, float]] = []

    def fake_read_url(url: str, timeout: float) -> tuple[dict[str, object], ...]:
        calls.append((url, timeout))
        return ({"ts": 1782802514.577, "dom": {"tag": "SPAN", "text": "Reservation Confirmed"}},)

    monkeypatch.setattr(probe_module, "_read_click_log_url", fake_read_url)
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(
            click_log_url="http://linux-host:7073/clicks",
            request_timeout_seconds=2.5,
            periodic_enabled=False,
        ),
    )

    records = service.export_click_log_for_session("acs_1")

    assert records[0]["dom"]["text"] == "Reservation Confirmed"
    assert calls == [("http://linux-host:7073/clicks", 2.5)]


def test_vm_a11y_probe_osworld_profile_unwraps_click_log_url(monkeypatch) -> None:
    def fake_read_url(url: str, timeout: float) -> tuple[dict[str, object], ...]:
        return (
            {
                "seq": 7,
                "generation": 0,
                "kind": "clicks",
                "received_at": 1784702604.119,
                "payload": {
                    "ts": 1784702604.113,
                    "screen_point": [1038, 493],
                    "scope": "web_content",
                    "element": {"tag": "ntp-app", "text": "", "rect": [0, 0, 1850, 966]},
                },
            },
        )

    monkeypatch.setattr(probe_module, "_read_click_log_url", fake_read_url)
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(
            profile=VM_A11Y_PROFILE_OSWORLD_GATEWAY,
            click_log_url="http://[::1]:7073/clicks?n=5000",
        ),
    )

    records = service.export_click_log_for_session("acs_osworld")

    assert records[0]["source_profile"] == "osworld_gateway_v1"
    assert records[0]["seq"] == 7
    assert records[0]["host_ts"] == 1784702604.113
    assert records[0]["x"] == 1038
    assert records[0]["y"] == 493
    assert records[0]["element"]["tag"] == "ntp-app"


def test_vm_a11y_probe_exports_click_log_from_guest_ssh(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        assert kwargs["capture_output"] is True
        assert kwargs["check"] is False
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=b'{"ts":1782802514.577,"dom":{"tag":"SPAN","text":"Reservation Confirmed"}}\n',
            stderr=b"",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(
            click_log_ssh_enabled=True,
            click_log_ssh_jump_host="vm-host",
            click_log_ssh_key_path="/tmp/key",
            click_log_ssh_guest_path="/tmp/clicks.jsonl",
            periodic_enabled=False,
        ),
    )

    records = service.export_click_log_for_session("acs_1")

    assert records[0]["dom"]["text"] == "Reservation Confirmed"
    assert calls[0][:2] == ["ssh", "-o"]
    assert "-J" in calls[0]
    assert "vm-host" in calls[0]
    assert "-i" in calls[0]
    assert "/tmp/key" in calls[0]
    assert "user@127.0.0.1" in calls[0]
    assert "cat /tmp/clicks.jsonl" in calls[0][-1]


def test_vm_a11y_probe_falls_back_to_local_click_log_when_ssh_empty(tmp_path, monkeypatch) -> None:
    click_log = tmp_path / "clicks.jsonl"
    click_log.write_text('{"ts":1782802517.28,"dom":{"tag":"SPAN","text":"reservations@example.com"}}\n')

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(subprocess, "run", fake_run)
    service = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(
            click_log_ssh_enabled=True,
            click_log_path=str(click_log),
            periodic_enabled=False,
        ),
    )

    records = service.export_click_log_for_session("acs_1")

    assert records[0]["dom"]["text"] == "reservations@example.com"


def _wait_for_running(service: VMAccessibilityProbeService) -> dict[str, object]:
    for _ in range(100):
        snapshot = service.latest_snapshot()
        if snapshot["running"] is True:
            return snapshot
        time.sleep(0.01)
    return service.latest_snapshot()


def _wait_for_sample(service: VMAccessibilityProbeService, *, samples_seen: int) -> dict[str, object]:
    for _ in range(200):
        snapshot = service.latest_snapshot()
        if snapshot["samples_seen"] == samples_seen:
            return snapshot
        time.sleep(0.01)
    return service.latest_snapshot()


def _wait_for_active_count(service: VMAccessibilityProbeService, *, active_count: int) -> dict[str, object]:
    for _ in range(100):
        snapshot = service.latest_snapshot()
        if snapshot["active_count"] == active_count:
            return snapshot
        time.sleep(0.01)
    return service.latest_snapshot()


def _wait_for_periodic_sample(service: VMAccessibilityProbeService, *, samples_seen: int) -> dict[str, object]:
    for _ in range(200):
        snapshot = service.latest_snapshot()
        periodic = snapshot["periodic"]
        if isinstance(periodic, dict) and periodic["samples_seen"] >= samples_seen:
            return snapshot
        time.sleep(0.01)
    return service.latest_snapshot()


def _wait_for_completion(service: VMAccessibilityProbeService) -> dict[str, object]:
    for _ in range(100):
        snapshot = service.latest_snapshot()
        if snapshot["running"] is False and snapshot["completed_at_host_ts"] is not None:
            return snapshot
        time.sleep(0.01)
    return service.latest_snapshot()
