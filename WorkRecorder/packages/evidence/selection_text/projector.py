"""Project a11y blocks into daemon-owned selection text."""

from __future__ import annotations

import logging

from packages.contracts import (
    A11ySnapshot,
    EvidenceKind,
    SelectionTextBlock,
    SelectionTextProjection,
    SelectionTextSourceMethod,
)
from packages.evidence.redaction import SensitiveTextRedactor

from .confidence import SelectionTextConfidenceScorer
from .dedup import SelectionTextDeduper
from .filters import BROAD_PARENT_ROLES, SelectionTextFilter
from .models import SelectionTextCandidate, SelectionTextProjectionConfig
from .ordering import SelectionTextOrdering

logger = logging.getLogger(__name__)


class SelectionTextProjectionService:
    """Build a safe, bounded text projection for the user's capture bbox."""

    def __init__(
        self,
        *,
        config: SelectionTextProjectionConfig | None = None,
        redactor: SensitiveTextRedactor | None = None,
    ) -> None:
        self.config = config or SelectionTextProjectionConfig()
        self.redactor = redactor or SensitiveTextRedactor()
        self.filter = SelectionTextFilter(self.config)
        self.deduper = SelectionTextDeduper()
        self.ordering = SelectionTextOrdering(self.config)
        self.scorer = SelectionTextConfidenceScorer()

    def project(self, snapshot: A11ySnapshot) -> SelectionTextProjection:
        """Return daemon-owned text for a capture selection.

        Args:
            snapshot: A11y snapshot containing selection geometry and text blocks.

        Returns:
            Bounded, redacted selection-text projection with block provenance.
        """

        selection = snapshot.selection
        raw_candidates = tuple(
            candidate
            for block in snapshot.text_blocks
            if (candidate := self.filter.candidate_for(block, selection=selection)) is not None
        )
        overbroad_parent_only = (
            bool(snapshot.text_blocks)
            and not raw_candidates
            and all(block.role in BROAD_PARENT_ROLES or not block.is_leaf_text for block in snapshot.text_blocks)
        )
        deduped = self.deduper.dedup(raw_candidates)
        ordered = self.ordering.sort(deduped)
        limited, truncated, reason = self._limit(ordered)
        text_parts: list[str] = []
        blocks: list[SelectionTextBlock] = []
        for candidate in limited:
            redacted = self.redactor.redact(candidate.text).strip()
            if not redacted:
                continue
            text_parts.append(redacted)
            blocks.append(
                SelectionTextBlock(
                    text=redacted,
                    source_block_id=candidate.block.block_id,
                    role=candidate.block.role,
                    frame=candidate.frame,
                    selection_overlap_ratio=candidate.selection_overlap_ratio,
                    element_overlap_ratio=candidate.element_overlap_ratio,
                    confidence=round(candidate.confidence, 3),
                    edge_recovered=candidate.edge_recovered,
                )
            )
        text = "\n".join(text_parts)
        confidence = self.scorer.score(
            candidates=tuple(limited),
            coverage=snapshot.coverage,
            truncated=truncated,
            overbroad_parent_only=overbroad_parent_only,
        )
        logger.info(
            "selection text projected source_blocks=%s admitted=%s text_chars=%s confidence=%s truncated=%s",
            len(snapshot.text_blocks),
            len(blocks),
            len(text),
            confidence,
            truncated,
            extra={
                "evidence_kind": EvidenceKind.SELECTION_TEXT.value,
                "source_block_count": len(snapshot.text_blocks),
                "block_count": len(blocks),
                "text_chars": len(text),
                "confidence": confidence,
                "truncated": truncated,
                "overbroad_parent_only": overbroad_parent_only,
            },
        )
        return SelectionTextProjection(
            text=text,
            source_method=SelectionTextSourceMethod.A11Y_BLOCKS,
            selection=selection,
            blocks=tuple(blocks),
            confidence=confidence,
            truncated=truncated,
            truncation_reason=reason,
            overbroad_parent_only=overbroad_parent_only,
            block_count=len(blocks),
            source_block_count=len(snapshot.text_blocks),
        )

    def _limit(
        self, candidates: tuple[SelectionTextCandidate, ...]
    ) -> tuple[tuple[SelectionTextCandidate, ...], bool, str | None]:
        limited: list[SelectionTextCandidate] = []
        total_chars = 0
        for candidate in candidates:
            if len(limited) >= self.config.max_blocks:
                return tuple(limited), True, "max_blocks"
            next_chars = total_chars + len(candidate.text) + (1 if limited else 0)
            if next_chars > self.config.max_text_chars:
                return tuple(limited), True, "max_text_chars"
            limited.append(candidate)
            total_chars = next_chars
        return tuple(limited), False, None
