"""Single-desktop, loopback-only AT-SPI evidence service (no browser DOM)."""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import ProxyHandler, build_opener

PROFILE = "linux_atspi_v1"


def desktop_geometry() -> dict[str, int] | None:
    """Read the current X11 screen extent in pixels from the desktop session."""
    try:
        result = subprocess.run(
            ["xdpyinfo"],
            capture_output=True,
            text=True,
            timeout=1,
            check=True,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    screen = re.search(r"default screen number:\s*(\d+)", result.stdout)
    if screen is None:
        return None
    section = re.search(rf"screen #\s*{screen.group(1)}:\s*(.*?)(?=\nscreen #|\Z)", result.stdout, re.S)
    match = re.search(r"dimensions:\s*(\d+)x(\d+)\s+pixels", section.group(1)) if section else None
    if match is None:
        return None
    width, height = map(int, match.groups())
    return {"width": width, "height": height} if width > 0 and height > 0 else None


class EventStore:
    """Keep a bounded transport buffer and append a complete local event archive."""

    def __init__(self, output: Path, max_events: int = 5000) -> None:
        self.output = output
        self.events: collections.deque[dict[str, Any]] = collections.deque(maxlen=max_events)
        self.lock = threading.Lock()
        self.sequence = 0
        self.snapshot: dict[str, Any] | None = None

    def append(self, event: dict[str, Any]) -> None:
        with self.lock:
            self.sequence += 1
            row = dict(event)
            row["source_seq"] = row.get("seq")
            row.update(seq=self.sequence, source_profile=PROFILE, received_at=time.time())
            # Snapshot time is explicit: this is nearby context, not an exact click-time tree.
            if self.snapshot is not None:
                row["a11y_snapshot"] = self.snapshot
            with self.output.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.events.append(row)

    def rows(self, *, since: int | None = None, limit: int = 100, clicks: bool = False) -> list[dict[str, Any]]:
        with self.lock:
            rows = [e for e in self.events if since is None or e["seq"] > since]
            if clicks:
                rows = [e for e in rows if e.get("button") is not None or str(e.get("event", "")).startswith("pointer")]
            count = max(1, min(limit, 5000))
            return rows[:count] if since is not None else rows[-count:]


def tree_request(port: int, path: str) -> dict[str, Any]:
    """Call only the supervised loopback tree collector, without system proxies."""
    with build_opener(ProxyHandler({})).open(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
        return cast(dict[str, Any], json.load(response))


def make_handler(
    store: EventStore,
    tree_port: int,
    healthy: Callable[[], bool],
    tree_state: dict[str, Any],
    geometry: Callable[[], dict[str, int] | None] = desktop_geometry,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            pass

        def do_GET(self) -> None:
            url = urlsplit(self.path)
            query = parse_qs(url.query)
            code = 200
            result: Any
            try:
                if url.path == "/health":
                    display = geometry()
                    ok = healthy()
                    code = 200 if ok else 503
                    result = {
                        "ok": ok,
                        "profile": PROFILE,
                        "time": time.time(),
                        "tree_status": dict(tree_state),
                        "event_count": store.sequence,
                        "display": display,
                    }
                elif url.path in {"/events", "/clicks"}:
                    since = int(query["since_seq"][0]) if "since_seq" in query else None
                    result = store.rows(
                        since=since, limit=int(query.get("n", ["100"])[0]), clicks=url.path == "/clicks"
                    )
                elif url.path in {"/a11y", "/at_point"}:
                    allowed = {
                        k: v[0]
                        for k, v in query.items()
                        if k in {"depth", "max_nodes", "all_windows", "x", "y", "scope"}
                    }
                    result = tree_request(tree_port, url.path + "?" + urlencode(allowed))
                else:
                    code, result = 404, {"error": "unknown endpoint"}
            except ValueError:
                code, result = 400, {"error": "invalid numeric query parameter"}
            except (OSError, TimeoutError) as exc:
                code, result = 503, {"error": str(exc)}
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return Handler


def follow_events(path: Path, store: EventStore, stop: threading.Event) -> None:
    with path.open(encoding="utf-8") as handle:
        pending = ""
        while not stop.is_set():
            chunk = handle.readline()
            if not chunk:
                stop.wait(0.05)
                continue
            pending += chunk
            if not pending.endswith("\n"):
                continue
            try:
                row = json.loads(pending)
                if isinstance(row, dict):
                    store.append(row)
            except json.JSONDecodeError:
                pass
            pending = ""


def sample_trees(
    port: int,
    store: EventStore,
    output: Path,
    stop: threading.Event,
    interval: float,
    depth: int,
    max_nodes: int,
    state: dict[str, Any],
) -> None:
    while not stop.is_set():
        try:
            started = time.time()
            tree = tree_request(port, f"/a11y?depth={depth}&max_nodes={max_nodes}")
            snapshot = {"started_at": started, "completed_at": time.time(), "tree": tree}
            with output.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
            with store.lock:
                store.snapshot = snapshot
            state.update(ok=True, last_error=None)
        except (OSError, ValueError, TimeoutError) as exc:
            state.update(ok=False, last_error=str(exc))
        stop.wait(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=7073)
    parser.add_argument("--tree-port", type=int, default=7070)
    parser.add_argument("--output", type=Path, default=Path.home() / ".local/share/workrecorder/linux")
    parser.add_argument("--tree-interval", type=float, default=2.0)
    parser.add_argument("--tree-depth", type=int, default=6)
    parser.add_argument("--tree-max-nodes", type=int, default=400)
    args = parser.parse_args()
    if sys.platform != "linux" or os.environ.get("XDG_SESSION_TYPE") == "wayland":
        parser.error("Run in the Linux X11/Xorg desktop session being recorded.")
    if not os.environ.get("DISPLAY") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        parser.error("DISPLAY and DBUS_SESSION_BUS_ADDRESS must come from the target desktop session.")
    if not (1 <= args.port <= 65535 and 1 <= args.tree_port <= 65535) or args.port == args.tree_port:
        parser.error("Choose distinct valid loopback ports.")
    if args.tree_interval < 0.2 or not 1 <= args.tree_depth <= 32 or not 1 <= args.tree_max_nodes <= 20000:
        parser.error("Invalid tree sampling limits.")
    os.umask(0o077)
    import tempfile

    args.output.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix=time.strftime("%Y%m%d-%H%M%S-"), dir=args.output))
    raw = output / "raw-events.jsonl"
    raw.touch()
    store = EventStore(output / "events.jsonl")
    state = {"ok": False, "last_error": "starting"}
    stop = threading.Event()
    collectors = Path(__file__).parent / "collectors"
    children: list[subprocess.Popen[bytes]] = []

    def healthy() -> bool:
        return len(children) == 2 and all(p.poll() is None for p in children) and bool(state["ok"])

    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(store, args.tree_port, healthy, state))
    server.timeout = 0.2
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    workers: list[threading.Thread] = []
    try:
        env = dict(os.environ, EVENT_OUT=str(raw), WORKRECORDER_TREE_PORT=str(args.tree_port))
        for name in ["a11y_daemon.py", "event_watch.py"]:
            with (output / f"{name}.log").open("a") as log:
                children.append(
                    subprocess.Popen(
                        [sys.executable, str(collectors / name)],
                        env=env,
                        stdout=log,
                        stderr=log,
                        start_new_session=True,
                    )
                )
        workers = [
            threading.Thread(target=follow_events, args=(raw, store, stop), daemon=True),
            threading.Thread(
                target=sample_trees,
                args=(
                    args.tree_port,
                    store,
                    output / "trees.jsonl",
                    stop,
                    args.tree_interval,
                    args.tree_depth,
                    args.tree_max_nodes,
                    state,
                ),
                daemon=True,
            ),
        ]
        for worker in workers:
            worker.start()
        print(f"AT-SPI service: http://127.0.0.1:{args.port}; evidence: {output}", flush=True)
        while not stop.is_set():
            server.handle_request()
            if any(p.poll() is not None for p in children):
                raise SystemExit(f"Collector exited; inspect logs in {output}")
    finally:
        stop.set()
        server.server_close()
        for child in children:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for child in children:
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        for worker in workers:
            worker.join(timeout=6)


if __name__ == "__main__":
    main()
