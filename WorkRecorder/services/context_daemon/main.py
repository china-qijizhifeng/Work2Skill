"""Console entrypoint for running the local daemon with uvicorn."""

from __future__ import annotations

import logging
import os
from ipaddress import ip_address
from urllib.parse import urlparse

import uvicorn


def _resolve_bind_address(daemon_url: str) -> tuple[str, int]:
    """Resolve the daemon bind address while keeping the dev server local-only."""

    parsed = urlparse(daemon_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8765
    if not _is_loopback_host(host):
        raise SystemExit("WORKRECORDER_DAEMON_URL must use a loopback host for the local daemon")
    return host, port


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def main() -> None:
    """Run the WorkRecorder local daemon development server."""

    log_level = os.getenv("WORKRECORDER_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    host, port = _resolve_bind_address(os.getenv("WORKRECORDER_DAEMON_URL", "http://127.0.0.1:8765"))
    uvicorn.run(
        "services.context_daemon.app:app",
        host=host,
        port=port,
        reload=False,
        log_config=None,
        log_level=log_level.lower(),
    )


if __name__ == "__main__":
    main()
