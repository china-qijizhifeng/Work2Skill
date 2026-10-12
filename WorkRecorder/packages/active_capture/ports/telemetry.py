"""Telemetry ports for active-capture services."""

from __future__ import annotations

from collections import Counter
from typing import Protocol

from packages.contracts import ActiveCaptureMetricName
from packages.contracts.common import JsonScalar


class ActiveCaptureTelemetryPort(Protocol):
    """Low-cardinality telemetry sink that must not receive raw user data."""

    def increment(
        self,
        name: ActiveCaptureMetricName,
        *,
        tags: dict[str, JsonScalar] | None = None,
        value: int = 1,
    ) -> None: ...


class NullActiveCaptureTelemetry:
    """No-op telemetry sink for production paths without a metrics backend."""

    def increment(
        self,
        name: ActiveCaptureMetricName,
        *,
        tags: dict[str, JsonScalar] | None = None,
        value: int = 1,
    ) -> None:
        return None


class InMemoryActiveCaptureTelemetry:
    """Test telemetry sink that records metric counts by name."""

    def __init__(self) -> None:
        self.counts: Counter[str] = Counter()

    def increment(
        self,
        name: ActiveCaptureMetricName,
        *,
        tags: dict[str, JsonScalar] | None = None,
        value: int = 1,
    ) -> None:
        self.counts[name.value] += value
