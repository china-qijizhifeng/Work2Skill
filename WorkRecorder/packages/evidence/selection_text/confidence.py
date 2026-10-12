"""Confidence scoring for selection text projection."""

from __future__ import annotations

from packages.contracts import A11yCoverageReport

from .models import SelectionTextCandidate


class SelectionTextConfidenceScorer:
    """Compute a bounded confidence for selected text output."""

    def score(
        self,
        *,
        candidates: tuple[SelectionTextCandidate, ...],
        coverage: A11yCoverageReport,
        truncated: bool,
        overbroad_parent_only: bool,
    ) -> float:
        """Score how trustworthy the selection-text projection is.

        Args:
            candidates: Blocks that survived filtering and ordering.
            coverage: A11y provider coverage report for the selected region.
            truncated: Whether output limits removed text.
            overbroad_parent_only: Whether only broad parent nodes were available.

        Returns:
            Confidence in the ``0.0`` to ``1.0`` range.
        """

        if not candidates or overbroad_parent_only:
            return 0.0
        block_score = sum(candidate.confidence for candidate in candidates) / len(candidates)
        overlap_score = min(1.0, sum(candidate.selection_overlap_ratio for candidate in candidates) * 4.0)
        confidence = (block_score * 0.55) + (coverage.confidence * 0.25) + (overlap_score * 0.20)
        if truncated:
            confidence *= 0.82
        if any(candidate.edge_recovered for candidate in candidates):
            confidence *= 0.92
        return round(max(0.0, min(1.0, confidence)), 3)
