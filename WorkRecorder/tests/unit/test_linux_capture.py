"""Exercise AT-SPI transport, evidence preservation, and recording-mode isolation."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from fastapi.testclient import TestClient

from apps.linux_capture.service import EventStore, desktop_geometry, make_handler
from packages.active_capture.application.vm_a11y_probe import VMAccessibilityProbeConfig, VMAccessibilityProbeService
from packages.settings.vm_a11y import VMA11yProbeSettingsUpdate
from scripts.start_linux_recording import resolve_dimensions, runtime_environment
from services.context_daemon.app import DaemonAppFactory


@pytest.fixture()
def atspi_server(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    store.snapshot = {
        "started_at": time.time(),
        "completed_at": time.time(),
        "tree": {"children": [{"role": "push button", "name": "Save"}]},
    }
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(store, 1, lambda: True, {"ok": True}, lambda: {"width": 2560, "height": 1440})
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield store, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_atspi_http_cursor_clicks_and_snapshot(atspi_server):
    store, url = atspi_server
    store.append({"seq": 30, "ts": time.time(), "event": "focus:", "role": "entry", "name": "Name"})
    store.append(
        {
            "seq": 31,
            "ts": time.time(),
            "event": "pointer-resolution",
            "button": "left",
            "target": {"role": "push button", "name": "Save", "bbox": [1, 2, 30, 20]},
        }
    )
    with urlopen(url + "/events?since_seq=1") as response:
        rows = json.load(response)
    assert len(rows) == 1
    assert rows[0]["source_seq"] == 31
    assert rows[0]["a11y_snapshot"]["tree"]["children"][0]["name"] == "Save"
    with urlopen(url + "/clicks?n=10") as response:
        assert len(json.load(response)) == 1
    with pytest.raises(HTTPError) as error:
        urlopen(url + "/events?n=bad")
    assert error.value.code == 400
    with pytest.raises(HTTPError) as error:
        urlopen(url + "/dom_at_point?x=1&y=2")
    assert error.value.code == 404


def test_atspi_service_consumed_by_recording_probe(atspi_server):
    store, url = atspi_server
    now = time.time()
    store.append(
        {
            "seq": 1,
            "ts": now,
            "event": "pointer-resolution",
            "button": "left",
            "x": 10,
            "y": 20,
            "target": {"app": "Editor", "role": "push button", "name": "Save", "bbox": [0, 0, 40, 40]},
        }
    )
    probe = VMAccessibilityProbeService(
        config=VMAccessibilityProbeConfig(
            profile="linux_atspi_v1", source="event_watch", url=url, events_poll_attempts=1
        )
    )
    try:
        sample, error = probe._http_sample_fetcher(
            probe.config, {"host_ts": now, "event_kind": "pointer_click", "point": {"x": 10, "y": 20}}
        )
        assert error is None
        assert sample["hit"]["name"] == "Save"
        assert sample["a11y_snapshot"] == store.snapshot
    finally:
        probe.stop()


def test_macos_ignores_saved_remote_preference(settings):
    app = DaemonAppFactory(settings).create()
    app.state.container.repositories.settings.set("active_capture_vm_a11y_probe", {"enabled": True})
    app = DaemonAppFactory(settings).create()
    container = app.state.container
    assert not container.vm_a11y_probe.is_enabled()
    assert not container.vm_a11y_probe_settings.update(VMA11yProbeSettingsUpdate(enabled=True)).enabled
    assert "system.macos_a11y" in {p.name for p in container.system_evidence_providers.list()}
    with TestClient(app) as client:
        assert client.get("/health").json()["data"]["recording_target"] == "macos"


def test_linux_disables_host_ax_and_browser_dom(settings):
    settings = settings.model_copy(
        update={"recording_target": "linux", "active_capture_vm_a11y_probe_profile": "linux_atspi_v1"}
    )
    app = DaemonAppFactory(settings).create()
    container = app.state.container
    assert container.vm_a11y_probe.is_enabled()
    assert "system.macos_a11y" not in {p.name for p in container.system_evidence_providers.list()}
    assert not container.source_providers.list()
    with TestClient(app) as client:
        response = client.post(
            "/v1/auth/tokens",
            headers={"X-WorkRecorder-Install-Secret": settings.install_secret},
            json={"actor_id": "linux-launcher", "display_name": "Linux launcher", "scopes": ["manage_local_settings"]},
        )
        assert response.status_code == 200
        token = response.json()["data"]["access_token"]
        result = client.put(
            "/v1/settings/vm-a11y-probe", headers={"Authorization": f"Bearer {token}"}, json={"enabled": True}
        )
        assert result.status_code == 200
        assert result.json()["data"]["enabled"] is True


def test_launcher_isolates_data_and_ignores_old_dom_config(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_URL", "http://wrong-host:7071")
    monkeypatch.setenv("WORKRECORDER_ACTIVE_CAPTURE_FULL_KEYSTROKES", "1")
    env = runtime_environment(tmp_path, 18765, 17073, 1920, 1080, 28)
    assert env["WORKRECORDER_RECORDING_TARGET"] == "linux"
    assert env["WORKRECORDER_DATABASE_PATH"] == str(tmp_path / "workrecorder.db")
    assert env["WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_URL"] == "http://127.0.0.1:17073"
    assert env["WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_PROFILE"] == "linux_atspi_v1"
    assert env["WORKRECORDER_ACTIVE_CAPTURE_FULL_KEYSTROKES"] == "0"
    assert (tmp_path / "install-secret").stat().st_mode & 0o777 == 0o600


def test_cursor_batches_do_not_skip_bursts(tmp_path):
    store = EventStore(tmp_path / "events.jsonl")
    for index in range(250):
        store.append({"seq": index, "event": "focus:"})
    first = store.rows(since=0, limit=100)
    second = store.rows(since=first[-1]["seq"], limit=100)
    third = store.rows(since=second[-1]["seq"], limit=100)
    assert [row["seq"] for row in first + second + third] == list(range(1, 251))


def test_health_supplies_geometry_for_launcher(atspi_server, tmp_path):
    _, url = atspi_server
    with urlopen(url + "/health") as response:
        health = json.load(response)
    width, height = resolve_dimensions(health, None, None)
    env = runtime_environment(tmp_path, 18765, 17073, width, height, 28)
    assert env["WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_VM_SCREEN_WIDTH"] == "2560"
    assert env["WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_VM_SCREEN_HEIGHT"] == "1440"


def test_geometry_uses_default_x_screen(monkeypatch):
    output = """default screen number: 1
screen #0:
  dimensions: 1920x1080 pixels (500x300 millimeters)
screen #1:
  dimensions: 3440x1440 pixels (800x300 millimeters)
"""

    def run(command, **kwargs):
        assert command == ["xdpyinfo"]
        assert kwargs["timeout"] == 1
        assert kwargs["env"]["LC_ALL"] == "C"
        return subprocess.CompletedProcess(command, 0, stdout=output)

    monkeypatch.setattr("apps.linux_capture.service.subprocess.run", run)
    assert desktop_geometry() == {"width": 3440, "height": 1440}


@pytest.mark.parametrize("error", [FileNotFoundError(), subprocess.TimeoutExpired("xdpyinfo", 1)])
def test_geometry_failure_allows_manual_override(monkeypatch, error):
    def run(*args, **kwargs):
        raise error

    monkeypatch.setattr("apps.linux_capture.service.subprocess.run", run)
    assert desktop_geometry() is None
    assert resolve_dimensions({"display": None}, 1920, 1080) == (1920, 1080)


@pytest.mark.parametrize(
    "display",
    [
        None,
        {},
        {"width": True, "height": 1080},
        {"width": 0, "height": 1080},
        {"width": "1920", "height": 1080},
        {"width": 20000, "height": 1080},
    ],
)
def test_launcher_rejects_missing_or_invalid_geometry(display):
    with pytest.raises(ValueError):
        resolve_dimensions({"display": display}, None, None)


def test_manual_dimensions_override_remote_and_require_pair():
    assert resolve_dimensions({"display": {"width": 2560, "height": 1440}}, 1920, 1080) == (1920, 1080)
    with pytest.raises(ValueError, match="together"):
        resolve_dimensions({}, 1920, None)
    with pytest.raises(ValueError, match="together"):
        resolve_dimensions({}, None, 1080)


@pytest.mark.parametrize(
    "output",
    [
        "",
        "default screen number: 0\nscreen #0:\n dimensions: 0x1080 pixels",
        "default screen number: 1\nscreen #0:\n dimensions: 1920x1080 pixels",
    ],
)
def test_geometry_rejects_invalid_or_missing_default_screen(monkeypatch, output):
    monkeypatch.setattr(
        "apps.linux_capture.service.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, stdout=output),
    )
    assert desktop_geometry() is None
