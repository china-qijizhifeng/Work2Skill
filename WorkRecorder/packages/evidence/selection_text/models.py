"""Internal models for bbox selection text projection."""

from __future__ import annotations

from dataclasses import dataclass

from packages.contracts import A11yTextBlock, BoundingBox


@dataclass(frozen=True, slots=True)
class SelectionTextProjectionConfig:
    """Tuning constants for selection-text extraction.

    Attributes:
        edge_recovery_min_px: Minimum expansion used to recover clipped edge text.
        edge_recovery_max_px: Maximum expansion used to avoid pulling extra context.
        edge_recovery_ratio: Selection-relative edge expansion ratio.
        min_element_overlap_ratio: Minimum overlap with the element bbox.
        min_selection_overlap_ratio: Minimum overlap with the user selection.
        max_parent_area_multiplier: Largest parent-node area allowed versus selection.
        max_leaf_area_multiplier: Largest leaf-node area allowed versus selection.
        max_blocks: Maximum number of text blocks in the projection.
        max_block_chars: Maximum characters per source block.
        max_text_chars: Maximum total output characters.
        line_y_tolerance_px: Vertical tolerance used by reading-order sorting.
    """

    edge_recovery_min_px: float = 8.0
    edge_recovery_max_px: float = 24.0
    edge_recovery_ratio: float = 0.03
    min_element_overlap_ratio: float = 0.12
    min_selection_overlap_ratio: float = 0.001
    max_parent_area_multiplier: float = 4.0
    max_leaf_area_multiplier: float = 4.0
    max_blocks: int = 80
    max_block_chars: int = 1000
    max_text_chars: int = 4000
    line_y_tolerance_px: float = 10.0


@dataclass(frozen=True, slots=True)
class SelectionTextCandidate:
    """A11y block admitted for selection text projection.

    Attributes:
        block: Source a11y text block.
        text: Normalized candidate text.
        frame: Candidate frame used for ordering and citations.
        selection_overlap_ratio: Fraction of the selection covered by the block.
        element_overlap_ratio: Fraction of the block covered by the selection.
        confidence: Candidate-level confidence after edge recovery penalties.
        edge_recovered: Whether the candidate entered through edge recovery.
    """

    block: A11yTextBlock
    text: str
    frame: BoundingBox | None
    selection_overlap_ratio: float
    element_overlap_ratio: float
    confidence: float
    edge_recovered: bool
