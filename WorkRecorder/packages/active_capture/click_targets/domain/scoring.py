"""Candidate scoring and public projection policies."""

from __future__ import annotations

from packages.contracts import (
    ClickTargetCandidate,
    ClickTargetConfidenceBand,
    ClickTargetPublicView,
    ClickTargetResolution,
    ClickTargetResolutionStatus,
    ClickTargetResolverConfig,
    ClickTargetSemanticKind,
    ClickTargetSourceKind,
    ClickTargetSuppressionReason,
)


class ClickTargetScoringPolicy:
    """Choose a winning click target candidate from provider outputs."""

    def __init__(self, *, config: ClickTargetResolverConfig) -> None:
        self.config = config

    def confidence_band(self, confidence: float) -> ClickTargetConfidenceBand:
        if confidence >= self.config.high_confidence_threshold:
            return ClickTargetConfidenceBand.HIGH
        if confidence >= self.config.review_confidence_threshold:
            return ClickTargetConfidenceBand.MEDIUM
        if confidence > 0.0:
            return ClickTargetConfidenceBand.LOW
        return ClickTargetConfidenceBand.UNAVAILABLE

    def status_for(
        self, *, confidence: float, candidate_count: int, suppressed: bool = False
    ) -> ClickTargetResolutionStatus:
        if suppressed:
            return ClickTargetResolutionStatus.SUPPRESSED
        if candidate_count == 0:
            return ClickTargetResolutionStatus.LOW_CONFIDENCE
        if confidence >= self.config.high_confidence_threshold:
            return ClickTargetResolutionStatus.RESOLVED
        if confidence >= self.config.review_confidence_threshold:
            return (
                ClickTargetResolutionStatus.AMBIGUOUS
                if candidate_count > 1
                else ClickTargetResolutionStatus.LOW_CONFIDENCE
            )
        return ClickTargetResolutionStatus.LOW_CONFIDENCE

    def choose_winner(self, candidates: tuple[ClickTargetCandidate, ...]) -> ClickTargetCandidate | None:
        if not candidates:
            return None
        ranked = sorted(
            candidates,
            key=lambda item: (
                item.source_kind != ClickTargetSourceKind.COORDINATE_FALLBACK,
                item.confidence,
                item.safe_label is not None,
            ),
            reverse=True,
        )
        return ranked[0]

    def public_view(self, resolution: ClickTargetResolution, *, has_coordinates: bool) -> ClickTargetPublicView:
        evidence_keyframe_ids: tuple[str, ...] = ()
        if resolution.evidence_anchor is not None and resolution.evidence_anchor.keyframe_id is not None:
            evidence_keyframe_ids = (resolution.evidence_anchor.keyframe_id,)
        return ClickTargetPublicView(
            resolution_id=resolution.resolution_id,
            status=resolution.status,
            display_label=resolution.display_label or self._public_fallback(resolution),
            semantic_kind=resolution.semantic_kind,
            confidence=resolution.confidence,
            confidence_band=resolution.confidence_band,
            source_badges=(resolution.source_kind,),
            needs_review=resolution.needs_review,
            evidence_keyframe_ids=evidence_keyframe_ids,
            has_coordinates=has_coordinates,
            suppression_reason=resolution.suppression_reason,
        )

    def _public_fallback(self, resolution: ClickTargetResolution) -> str:
        if resolution.suppression_reason == ClickTargetSuppressionReason.SENSITIVE_LABEL:
            return "敏感目标"
        if resolution.semantic_kind == ClickTargetSemanticKind.BUTTON:
            return "按钮"
        if resolution.semantic_kind == ClickTargetSemanticKind.INPUT:
            return "输入框"
        if resolution.semantic_kind == ClickTargetSemanticKind.SEARCH_FIELD:
            return "搜索框"
        return "目标待确认"
