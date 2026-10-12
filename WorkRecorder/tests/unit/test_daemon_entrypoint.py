from __future__ import annotations

import pytest

from services.context_daemon.main import _resolve_bind_address


@pytest.mark.parametrize(
    ("daemon_url", "expected"),
    [
        ("http://127.0.0.1:8765", ("127.0.0.1", 8765)),
        ("http://localhost:9000", ("localhost", 9000)),
        ("http://[::1]:8765", ("::1", 8765)),
    ],
)
def test_resolve_bind_address_allows_loopback_hosts(daemon_url: str, expected: tuple[str, int]) -> None:
    assert _resolve_bind_address(daemon_url) == expected


@pytest.mark.parametrize(
    "daemon_url",
    [
        "http://0.0.0.0:8765",
        "http://192.168.1.10:8765",
        "http://workrecorder.local:8765",
    ],
)
def test_resolve_bind_address_rejects_non_loopback_hosts(daemon_url: str) -> None:
    with pytest.raises(SystemExit, match="loopback host"):
        _resolve_bind_address(daemon_url)
