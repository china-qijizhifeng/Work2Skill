"""Ports used by evidence-aware keyframe timing services."""

from __future__ import annotations

from typing import Protocol

from packages.contracts import (
    ContextKeyframe,
    KeyframeDiffReport,
    KeyframeQualityReport,
)


class KeyframeTimingReadPort(Protocol):
    """Read-only session graph boundary for timing decisions."""

    def get_latest_keyframe_before(
        self, *, session_id: str, occurred_at_monotonic_ms: int | None
    ) -> ContextKeyframe | None: ...


class VisualDiffPort(Protocol):
    """Optional visual-diff provider used by quality decisions."""

    def compare(self, *, previous_keyframe_id: str, candidate_keyframe_id: str) -> KeyframeDiffReport: ...


class TextDiffPort(Protocol):
    """Optional text-diff provider used by quality decisions."""

    def compare(self, *, previous_keyframe_id: str, candidate_keyframe_id: str) -> KeyframeDiffReport: ...


class KeyframeQualityPort(Protocol):
    """Optional quality provider for persisted keyframes."""

    def quality_for_keyframe(self, keyframe_id: str) -> KeyframeQualityReport: ...
