"""Null keyframe timing providers used when no rich evidence adapter is available."""

from __future__ import annotations

from packages.contracts import KeyframeDiffReport, KeyframeQualityReport


class NullVisualDiffProvider:
    """Return an unknown-but-safe visual diff."""

    def compare(self, *, previous_keyframe_id: str, candidate_keyframe_id: str) -> KeyframeDiffReport:
        return KeyframeDiffReport(previous_keyframe_id=previous_keyframe_id, changed=None)


class NullTextDiffProvider:
    """Return an unknown-but-safe text diff."""

    def compare(self, *, previous_keyframe_id: str, candidate_keyframe_id: str) -> KeyframeDiffReport:
        return KeyframeDiffReport(previous_keyframe_id=previous_keyframe_id, changed=None)


class NullKeyframeQualityProvider:
    """Return a conservative default quality report."""

    def quality_for_keyframe(self, keyframe_id: str) -> KeyframeQualityReport:
        return KeyframeQualityReport(confidence=0.5, diagnostics=("quality provider unavailable",))
