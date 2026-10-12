"""Deduplication for bbox text blocks."""

from __future__ import annotations

from .models import SelectionTextCandidate


class SelectionTextDeduper:
    """Deduplicate identical node/attribute/frame emissions without dropping repeats."""

    def dedup(self, candidates: tuple[SelectionTextCandidate, ...]) -> tuple[SelectionTextCandidate, ...]:
        """Remove duplicate emissions without dropping repeated visible labels.

        Args:
            candidates: Candidate text blocks after role and overlap filtering.

        Returns:
            Deduplicated candidates preserving distinct frames and repeated labels.
        """

        seen: set[str] = set()
        output: list[SelectionTextCandidate] = []
        for candidate in candidates:
            key = self._key(candidate)
            if key in seen:
                continue
            related_index = self._related_duplicate_index(output, candidate)
            if related_index is not None:
                existing = output[related_index]
                if candidate.block.is_leaf_text and not existing.block.is_leaf_text:
                    output[related_index] = candidate
                continue
            seen.add(key)
            output.append(candidate)
        return tuple(output)

    def _key(self, candidate: SelectionTextCandidate) -> str:
        block = candidate.block
        frame = candidate.frame
        frame_key = (
            "noframe"
            if frame is None
            else f"{round(frame.x / 4)}:{round(frame.y / 4)}:{round(frame.width / 4)}:{round(frame.height / 4)}"
        )
        text = " ".join(candidate.text.casefold().split())
        return "|".join(
            [
                block.node_path or "",
                block.text_source or "",
                frame_key,
                text,
            ]
        )

    def _related_duplicate_index(
        self, candidates: list[SelectionTextCandidate], candidate: SelectionTextCandidate
    ) -> int | None:
        key = self._frame_text_key(candidate)
        candidate_path = candidate.block.node_path or ""
        for index, existing in enumerate(candidates):
            if self._frame_text_key(existing) != key:
                continue
            existing_path = existing.block.node_path or ""
            if self._is_related_path(existing_path, candidate_path):
                return index
        return None

    def _frame_text_key(self, candidate: SelectionTextCandidate) -> str:
        frame = candidate.frame
        frame_key = (
            "noframe"
            if frame is None
            else f"{round(frame.x / 4)}:{round(frame.y / 4)}:{round(frame.width / 4)}:{round(frame.height / 4)}"
        )
        text = " ".join(candidate.text.casefold().split())
        return f"{frame_key}|{text}"

    def _is_related_path(self, left: str, right: str) -> bool:
        if not left or not right or left == right:
            return left == right
        return right.startswith(f"{left}/") or left.startswith(f"{right}/")
