"""Spatial reading-order sort for selection text."""

from __future__ import annotations

from .models import SelectionTextCandidate, SelectionTextProjectionConfig


class SelectionTextOrdering:
    """Sort blocks by spatial reading order with table and multi-column handling."""

    def __init__(self, config: SelectionTextProjectionConfig) -> None:
        self.config = config

    def sort(self, candidates: tuple[SelectionTextCandidate, ...]) -> tuple[SelectionTextCandidate, ...]:
        """Sort candidates into human reading order.

        Args:
            candidates: Deduplicated selection-text candidates.

        Returns:
            Candidates ordered row-major, with simple multi-column handling.
        """

        framed = [candidate for candidate in candidates if candidate.frame is not None]
        unframed = [candidate for candidate in candidates if candidate.frame is None]
        if not framed:
            return tuple(sorted(candidates, key=lambda c: c.block.order_index or 0))
        if self._looks_like_table(framed):
            ordered = self._row_major(tuple(framed))
        else:
            columns = self._columns(framed)
            ordered = []
            for column in columns:
                ordered.extend(self._row_major(tuple(column)))
        ordered.extend(sorted(unframed, key=lambda c: c.block.order_index or 0))
        return tuple(ordered)

    def _looks_like_table(self, candidates: list[SelectionTextCandidate]) -> bool:
        return any("AXTable" in candidate.block.role_path for candidate in candidates)

    def _columns(self, candidates: list[SelectionTextCandidate]) -> tuple[tuple[SelectionTextCandidate, ...], ...]:
        sorted_by_x = sorted(candidates, key=lambda candidate: candidate.frame.x if candidate.frame else 0)
        if len(sorted_by_x) < 4:
            return (tuple(candidates),)
        gaps: list[tuple[float, int]] = []
        for index, (left, right) in enumerate(zip(sorted_by_x, sorted_by_x[1:], strict=False)):
            assert left.frame is not None and right.frame is not None
            gap = right.frame.x - (left.frame.x + left.frame.width)
            gaps.append((gap, index))
        largest_gap, split_index = max(gaps, key=lambda item: item[0])
        total_width = max(
            candidate.frame.x + candidate.frame.width for candidate in sorted_by_x if candidate.frame
        ) - min(candidate.frame.x for candidate in sorted_by_x if candidate.frame)
        if largest_gap < max(60.0, total_width * 0.18):
            return (tuple(candidates),)
        left_column = tuple(sorted_by_x[: split_index + 1])
        right_column = tuple(sorted_by_x[split_index + 1 :])
        return (left_column, right_column)

    def _row_major(self, candidates: tuple[SelectionTextCandidate, ...]) -> list[SelectionTextCandidate]:
        rows: list[list[SelectionTextCandidate]] = []
        for candidate in sorted(candidates, key=lambda c: (c.frame.y if c.frame else 0, c.frame.x if c.frame else 0)):
            frame = candidate.frame
            if frame is None:
                continue
            matched = False
            for row in rows:
                row_y = sum(item.frame.y for item in row if item.frame) / max(len(row), 1)
                if abs(frame.y - row_y) <= self.config.line_y_tolerance_px:
                    row.append(candidate)
                    matched = True
                    break
            if not matched:
                rows.append([candidate])
        ordered: list[SelectionTextCandidate] = []
        for row in rows:
            ordered.extend(sorted(row, key=lambda c: (c.frame.x if c.frame else 0, c.block.order_index or 0)))
        return ordered
