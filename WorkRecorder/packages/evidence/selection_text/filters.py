"""Filtering rules for a11y-to-selection-text projection."""

from __future__ import annotations

from packages.contracts import A11yTextBlock, BoundingBox

from .models import SelectionTextCandidate, SelectionTextProjectionConfig

NOISE_ROLES = {
    "AXApplication",
    "AXBrowser",
    "AXMenu",
    "AXMenuBar",
    "AXMenuBarItem",
    "AXMenuItem",
    "AXTabGroup",
    "AXToolbar",
    "AXWindow",
}

BROAD_PARENT_ROLES = {
    "AXDocument",
    "AXGroup",
    "AXScrollArea",
    "AXTable",
    "AXWebArea",
}


class SelectionTextFilter:
    """Admit only bbox-relevant leaf text blocks."""

    def __init__(self, config: SelectionTextProjectionConfig) -> None:
        self.config = config

    def candidate_for(self, block: A11yTextBlock, *, selection: BoundingBox) -> SelectionTextCandidate | None:
        """Return a projection candidate when a block belongs to the selection.

        Args:
            block: Raw a11y text block from the system provider.
            selection: User-selected screen-space bbox.

        Returns:
            Candidate with overlap/confidence metadata, or ``None`` when filtered out.
        """

        text = " ".join(block.text.split())[: self.config.max_block_chars].strip()
        if not text or self._is_noise_role(block.role):
            return None
        frame = block.frame
        if frame is None:
            return None
        selection_overlap = _overlap_ratio(frame, selection, denominator="selection")
        element_overlap = _overlap_ratio(frame, selection, denominator="element")
        if self._is_overbroad_leaf(block, selection=selection, element_overlap=element_overlap):
            return None
        expanded = _expand(selection, self._edge_px(selection))
        edge_overlap = _overlap_ratio(frame, expanded, denominator="element")
        strict = selection_overlap >= self.config.min_selection_overlap_ratio and (
            element_overlap >= self.config.min_element_overlap_ratio or block.is_leaf_text
        )
        edge_recovered = False
        if not strict:
            edge_recovered = (
                block.is_leaf_text
                and edge_overlap >= self.config.min_element_overlap_ratio
                and self._near_selection_edge(frame, selection)
            )
            if not edge_recovered:
                return None
        if self._is_broad_parent(block, selection=selection, element_overlap=element_overlap):
            return None
        confidence = min(max(block.confidence, 0.0), 1.0)
        if edge_recovered:
            confidence *= 0.72
        return SelectionTextCandidate(
            block=block,
            text=text,
            frame=frame,
            selection_overlap_ratio=selection_overlap,
            element_overlap_ratio=element_overlap if strict else edge_overlap,
            confidence=confidence,
            edge_recovered=edge_recovered,
        )

    def _is_noise_role(self, role: str | None) -> bool:
        return role in NOISE_ROLES

    def _is_broad_parent(self, block: A11yTextBlock, *, selection: BoundingBox, element_overlap: float) -> bool:
        if block.is_leaf_text:
            return False
        if block.role not in BROAD_PARENT_ROLES:
            return False
        frame = block.frame
        if frame is None:
            return True
        return _area(frame) > _area(selection) * self.config.max_parent_area_multiplier or element_overlap < 0.8

    def _is_overbroad_leaf(self, block: A11yTextBlock, *, selection: BoundingBox, element_overlap: float) -> bool:
        frame = block.frame
        return (
            block.is_leaf_text
            and frame is not None
            and _area(frame) > _area(selection) * self.config.max_leaf_area_multiplier
            and element_overlap < self.config.min_element_overlap_ratio
        )

    def _edge_px(self, selection: BoundingBox) -> float:
        return min(
            self.config.edge_recovery_max_px,
            max(
                self.config.edge_recovery_min_px,
                min(selection.width, selection.height) * self.config.edge_recovery_ratio,
            ),
        )

    def _near_selection_edge(self, frame: BoundingBox, selection: BoundingBox) -> bool:
        edge = self._edge_px(selection)
        expanded = _expand(selection, edge)
        if not _intersects(frame, expanded):
            return False
        if not _intersects(frame, selection):
            return True
        distances = (
            abs((frame.x + frame.width) - selection.x),
            abs(frame.x - (selection.x + selection.width)),
            abs((frame.y + frame.height) - selection.y),
            abs(frame.y - (selection.y + selection.height)),
        )
        return min(distances) <= edge


def _area(box: BoundingBox) -> float:
    return max(float(box.width * box.height), 1.0)


def _intersects(lhs: BoundingBox, rhs: BoundingBox) -> bool:
    left = max(lhs.x, rhs.x)
    top = max(lhs.y, rhs.y)
    right = min(lhs.x + lhs.width, rhs.x + rhs.width)
    bottom = min(lhs.y + lhs.height, rhs.y + rhs.height)
    return right > left and bottom > top


def _overlap_ratio(lhs: BoundingBox, rhs: BoundingBox, *, denominator: str) -> float:
    left = max(lhs.x, rhs.x)
    top = max(lhs.y, rhs.y)
    right = min(lhs.x + lhs.width, rhs.x + rhs.width)
    bottom = min(lhs.y + lhs.height, rhs.y + rhs.height)
    if right <= left or bottom <= top:
        return 0.0
    intersection = float((right - left) * (bottom - top))
    return intersection / (_area(rhs) if denominator == "selection" else _area(lhs))


def _expand(box: BoundingBox, px: float) -> BoundingBox:
    rounded = int(round(px))
    return box.model_copy(
        update={
            "x": box.x - rounded,
            "y": box.y - rounded,
            "width": box.width + (rounded * 2),
            "height": box.height + (rounded * 2),
        }
    )
