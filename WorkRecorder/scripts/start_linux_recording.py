"""Start an isolated Mac recording session backed by a Linux AT-SPI service."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast
from urllib.request import ProxyHandler, build_opener

REPO = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def read_json(url: str) -> dict[str, Any]:
    with build_opener(ProxyHandler({})).open(url, timeout=2) as response:
        return cast(dict[str, Any], json.load(response))


def wait_health(url: str, process: subprocess.Popen[bytes], timeout: float = 25) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Process exited ({process.returncode}) before {url} became ready")
        try:
            result = read_json(url)
            if result.get("ok"):
                return result
        except (OSError, ValueError):
            pass
        time.sleep(0.2)
    raise RuntimeError(f"Health check timed out: {url}")


def resolve_dimensions(remote: dict[str, Any], width: int | None, height: int | None) -> tuple[int, int]:
    """Prefer an explicit pair, otherwise use the target desktop's advertised size."""
    if (width is None) != (height is None):
        raise ValueError("Specify --width and --height together, or omit both for automatic detection.")
    if width is None:
        display = remote.get("display")
        if not isinstance(display, dict):
            raise ValueError(
                "Linux desktop resolution is unavailable. Update the Linux service and check xdpyinfo "
                "in its desktop session, or supply --width and --height."
            )
        width, height = display.get("width"), display.get("height")
    if type(width) is not int or type(height) is not int or not (1 <= width <= 16384 and 1 <= height <= 16384):
        raise ValueError("Desktop width and height must be integers between 1 and 16384 pixels.")
    return width, height


def runtime_environment(
    data: Path, daemon_port: int, gateway_port: int, width: int, height: int, title_bar: float
) -> dict[str, str]:
    """Do not inherit a different recording mode or old VM/DOM settings."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("WORKRECORDER_")}
    env.update(
        {
            "WORKRECORDER_RECORDING_TARGET": "linux",
            "WORKRECORDER_REPO_ROOT": str(REPO),
            "WORKRECORDER_APP_DATA_ROOT": str(data),
            "WORKRECORDER_DATABASE_PATH": str(data / "workrecorder.db"),
            "WORKRECORDER_ARTIFACT_STAGING_DIR": str(data / "staging"),
            "WORKRECORDER_ARTIFACT_VAULT_DIR": str(data / "artifacts"),
            "WORKRECORDER_DAEMON_URL": f"http://127.0.0.1:{daemon_port}",
            "WORKRECORDER_EXTERNAL_DAEMON": "1",
            "WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_ENABLED": "true",
            "WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_PROFILE": "linux_atspi_v1",
            "WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_SOURCE": "event_watch",
            "WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_URL": f"http://127.0.0.1:{gateway_port}",
            "WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_A11Y_PATH": "/at_point",
            "WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_EVENTS_PATH": "/events",
            "WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_CLICK_LOG_URL": f"http://127.0.0.1:{gateway_port}/clicks?n=5000",
            "WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_VM_SCREEN_WIDTH": str(width),
            "WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_VM_SCREEN_HEIGHT": str(height),
            "WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_TITLE_BAR_PT": str(title_bar),
            "WORKRECORDER_ACTIVE_CAPTURE_FULL_KEYSTROKES": "0",
        }
    )
    for key, filename, prefix in [
        ("INSTALL", "install-secret", "workrecorder_"),
        ("PROVIDER_REGISTRATION", "provider-registration-secret", "workrecorder_provider_"),
        ("NATIVE_CAPTURE", "native-capture-secret", "workrecorder_native_"),
    ]:
        path = data / filename
        if not path.exists():
            path.write_text(prefix + secrets.token_urlsafe(32))
            path.chmod(0o600)
        env[f"WORKRECORDER_{key}_SECRET"] = path.read_text().strip()
    return env


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ssh", required=True, help="SSH host/alias that reaches the Linux desktop's loopback service")
    parser.add_argument("--remote-port", type=int, default=7073)
    parser.add_argument("--width", type=int, help="Override detected desktop width in pixels (requires --height)")
    parser.add_argument("--height", type=int, help="Override detected desktop height in pixels (requires --width)")
    parser.add_argument(
        "--title-bar", type=float, default=28, help="Mac remote-viewer title bar height in points; 0 for borderless"
    )
    parser.add_argument("--app", type=Path, default=REPO / "dist/WorkRecorder.app")
    parser.add_argument("--data-dir", type=Path)
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("Run this launcher on the recording Mac.")
    if args.ssh.startswith("-") or any(c.isspace() for c in args.ssh):
        parser.error("Use a single SSH host or configured alias.")
    if not 1 <= args.remote_port <= 65535:
        parser.error("Invalid port.")
    if args.width is not None or args.height is not None:
        try:
            resolve_dimensions({}, args.width, args.height)
        except ValueError as exc:
            parser.error(str(exc))
    if not 0 <= args.title_bar <= 200:
        parser.error("Title bar height must be between 0 and 200 points.")
    executable = args.app.expanduser().resolve() / "Contents/MacOS/WorkRecorder"
    python = REPO / ".venv/bin/python"
    if not executable.is_file() or not python.is_file():
        parser.error("Run uv sync --extra dev and build dist/WorkRecorder.app first (see README).")
    os.umask(0o077)
    host_id = hashlib.sha256(args.ssh.encode()).hexdigest()[:12]
    data = (args.data_dir or Path.home() / ".workrecorder/linux" / host_id).expanduser().resolve()
    data.mkdir(parents=True, exist_ok=True)
    lock = (data / "launcher.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        parser.error("A Linux recording launcher already owns this data directory.")
    gateway_port, daemon_port = free_port(), free_port()
    while daemon_port == gateway_port:
        daemon_port = free_port()
    children: list[subprocess.Popen[bytes]] = []

    def interrupted(*_args: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        tunnel = subprocess.Popen(
            [
                "ssh",
                "-N",
                "-T",
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "ServerAliveCountMax=3",
                "-L",
                f"127.0.0.1:{gateway_port}:127.0.0.1:{args.remote_port}",
                args.ssh,
            ]
        )
        children.append(tunnel)
        remote = wait_health(f"http://127.0.0.1:{gateway_port}/health", tunnel)
        if remote.get("profile") != "linux_atspi_v1":
            raise RuntimeError("The remote endpoint is not the WorkRecorder AT-SPI service.")
        if abs(time.time() - float(remote["time"])) > 2:
            raise RuntimeError("Mac and Linux clocks differ by over 2 seconds; synchronize them before recording.")
        width, height = resolve_dimensions(remote, args.width, args.height)
        print(f"Linux desktop: {width}x{height} ({'manual' if args.width is not None else 'detected'}).")
        env = runtime_environment(data, daemon_port, gateway_port, width, height, args.title_bar)
        with (data / "daemon.log").open("a") as log:
            daemon = subprocess.Popen(
                [str(python), "-m", "services.context_daemon.main"], cwd=REPO, env=env, stdout=log, stderr=log
            )
        children.append(daemon)
        local = wait_health(f"http://127.0.0.1:{daemon_port}/health", daemon)
        if local.get("data", {}).get("recording_target") != "linux":
            raise RuntimeError("Daemon did not start in Linux mode.")
        # A persisted opt-out must not silently override an explicit Linux launch.
        from urllib.request import Request

        opener = build_opener(ProxyHandler({}))
        token_req = Request(
            f"http://127.0.0.1:{daemon_port}/v1/auth/tokens",
            data=json.dumps(
                {"actor_id": "linux-launcher", "display_name": "Linux launcher", "scopes": ["manage_local_settings"]}
            ).encode(),
            headers={
                "Content-Type": "application/json",
                "X-WorkRecorder-Install-Secret": env["WORKRECORDER_INSTALL_SECRET"],
            },
        )
        with opener.open(token_req, timeout=3) as response:
            token = json.load(response)["data"]["access_token"]
        setting_req = Request(
            f"http://127.0.0.1:{daemon_port}/v1/settings/vm-a11y-probe",
            method="PUT",
            data=b'{"enabled":true}',
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        )
        with opener.open(setting_req, timeout=3) as response:
            if not json.load(response)["data"]["enabled"]:
                raise RuntimeError("Linux evidence collection is disabled.")
        print(
            f"Linux recording ready. Data: {data}\nConnect your remote desktop viewer, then press Control+Option+Command+R."
        )
        app = subprocess.Popen([str(executable)], cwd=REPO, env=env)
        children.append(app)
        while app.poll() is None:
            if tunnel.poll() is not None or daemon.poll() is not None:
                raise RuntimeError("Tunnel or daemon stopped; finish the recording and restart the launcher.")
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
        lock.close()


if __name__ == "__main__":
    main()
