from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from PIL import Image, ImageDraw

from packages.shared.config import WorkRecorderSettings
from scripts.repair_uv_editable_install import repair_macos_hidden_pth_files
from services.context_daemon.app import DaemonAppFactory

INSTALL_SECRET = "test-install-secret"
pytestmark = [
    pytest.mark.filterwarnings("ignore:websockets\\.legacy is deprecated:DeprecationWarning"),
    pytest.mark.filterwarnings("ignore:websockets\\.server\\.WebSocketServerProtocol is deprecated:DeprecationWarning"),
]


def test_cli_agent_skill_flow_hits_live_daemon_without_pythonpath(tmp_path: Path) -> None:
    with _LiveDaemon(tmp_path) as daemon:
        event_id = daemon.create_system_only_capture(note="CLI live P6 system appshot note")
        env = daemon.cli_env(home=tmp_path / "home")

        begin = _run_workrecorder(
            "agent",
            "begin",
            "--purpose",
            "p6_cli_live",
            "--question",
            "Find the live P6 appshot note",
            "--json",
            env=env,
        )
        run_id = begin["data"]["agent_run_id"]

        search = _run_workrecorder("events", "search", "P6 system appshot", "--json", env=env)
        inspect = _run_workrecorder(
            "events",
            "inspect",
            event_id,
            "--view",
            "system_appshot",
            "--view",
            "screenshot_ref",
            "--view",
            "evidence_refs",
            "--purpose",
            "agent_deep_read",
            "--json",
            env=env,
        )
        replay = _run_workrecorder("agent", "replay", "--json", env=env)

    replay_text = json.dumps(replay["data"], sort_keys=True)
    assert search["agent_run_id"] == run_id
    assert inspect["agent_run_id"] == run_id
    assert search["data"]["results"][0]["event_id"] == event_id
    assert inspect["data"]["system_appshot"]["primary_app_name"] == "TextEdit"
    assert inspect["data"]["system_appshot"]["screenshot_evidence_id"]
    assert {call["kind"] for call in replay["data"]["retrieval_calls"]}.issuperset({"search", "event_inspect"})
    assert "CLI live P6 system appshot note" in replay_text
    assert "local-artifact://" not in replay_text
    assert "storage_uri" not in replay_text


class _NoSignalUvicornServer(uvicorn.Server):
    def install_signal_handlers(self) -> None:
        return None


class _LiveDaemon(AbstractContextManager["_LiveDaemon"]):
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.port = _free_tcp_port()
        self.settings = WorkRecorderSettings(
            database_path=tmp_path / "live_cli.sqlite",
            artifact_staging_dir=tmp_path / "staging",
            artifact_vault_dir=tmp_path / "artifacts",
            install_secret=INSTALL_SECRET,
            disclosure_policy_path=None,
        )
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None

    def __enter__(self) -> "_LiveDaemon":
        app = DaemonAppFactory(self.settings).create()
        config = uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning", log_config=None)
        server = _NoSignalUvicornServer(config)
        self.server = server
        self.thread = threading.Thread(target=server.run, daemon=True)
        self.thread.start()
        self._wait_for_health()
        return self

    def __exit__(self, *_exc: object) -> None:
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None:
            self.thread.join(timeout=10)

    def cli_env(self, *, home: Path) -> dict[str, str]:
        env = dict(os.environ)
        env["HOME"] = str(home)
        env["WORKRECORDER_DAEMON_URL"] = f"http://127.0.0.1:{self.port}"
        env["WORKRECORDER_INSTALL_SECRET"] = INSTALL_SECRET
        for key in ("PYTHONPATH", "WORKRECORDER_AGENT_RUN_ID", "WORKRECORDER_ENABLE_APPLE_VISION_OCR"):
            env.pop(key, None)
        return env

    def create_system_only_capture(self, *, note: str) -> str:
        token = self._issue_token()
        staged = self.settings.artifact_staging_dir / "live-cli-capture.png"
        staged.parent.mkdir(parents=True, exist_ok=True)
        _write_test_png(staged)
        now = datetime.now(UTC).isoformat()
        selection = {"x": 80, "y": 120, "width": 480, "height": 260, "coordinate_space": "macos_global"}
        display = {
            "display_id": "display_cli_live",
            "frame": {"x": 0, "y": 0, "width": 1440, "height": 900, "coordinate_space": "macos_global"},
            "scale_factor": 2.0,
        }
        payload: dict[str, Any] = {
            "schema_version": 1,
            "trigger": {
                "trigger_id": "trg_cli_live_system_appshot",
                "trigger_type": "manual_os_region_hotkey",
                "capture_strategy": "os_region",
                "actor": {"actor_id": "test-cli", "display_name": "CLI Live Test"},
                "occurred_at": now,
                "selection": selection,
                "intent_text": note,
            },
            "selection_geometry": {"selected_region": selection, "display": display},
            "window_hints": [
                {
                    "app_name": "TextEdit",
                    "title": "P6 Live Notes",
                    "process_id": 4242,
                    "window_id": "17",
                    "frame": {"x": 20, "y": 80, "width": 760, "height": 520, "coordinate_space": "macos_global"},
                    "overlap_ratio": 0.94,
                    "confidence": 0.93,
                }
            ],
            "workspace": {"workspace_id": "cli-live", "label": "CLI Live", "auto": False},
            "actor": {"actor_id": "test-cli", "display_name": "CLI Live Test"},
            "staged_artifact": {
                "local_path": str(staged),
                "artifact_type": "screenshot",
                "content_type": "image/png",
                "filename": staged.name,
            },
            "intent_text": note,
        }
        response = httpx.post(
            f"http://127.0.0.1:{self.port}/v1/captures",
            headers={"authorization": f"Bearer {token}"},
            json=payload,
            timeout=10,
        )
        envelope = response.json()
        assert response.status_code == 200, envelope
        assert envelope["ok"] is True
        return str(envelope["data"]["event"]["event_id"])

    def _issue_token(self) -> str:
        response = httpx.post(
            f"http://127.0.0.1:{self.port}/v1/auth/tokens",
            headers={"x-workrecorder-install-secret": INSTALL_SECRET},
            json={"actor_id": "test-cli", "display_name": "CLI Live Test"},
            timeout=5,
        )
        response.raise_for_status()
        return str(response.json()["data"]["access_token"])

    def _wait_for_health(self) -> None:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            try:
                response = httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=1)
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.05)
        raise AssertionError("live daemon did not become healthy")


def _run_workrecorder(*args: str, env: dict[str, str]) -> dict[str, Any]:
    repair_macos_hidden_pth_files()
    script = Path(sys.executable).with_name("workrecorder")
    result = subprocess.run(
        [str(script), *args],
        check=False,
        capture_output=True,
        env=env,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    return payload


def _write_test_png(path: Path) -> None:
    image = Image.new("RGB", (640, 360), "#f7fbfc")
    draw = ImageDraw.Draw(image)
    draw.rectangle((44, 44, 596, 312), outline="#81d8d0", width=3)
    draw.text((72, 82), "CLI live P6 system appshot note", fill="#245b62")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])
