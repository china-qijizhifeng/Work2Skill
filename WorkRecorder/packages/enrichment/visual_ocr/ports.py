"""Provider ports for visual OCR enrichment."""

from __future__ import annotations

from typing import Protocol

from packages.contracts import VisualOCRRequest, VisualOCRResult


class VisualOCRProvider(Protocol):
    """Provider contract for one VLM OCR model adapter."""

    async def run(self, request: VisualOCRRequest) -> VisualOCRResult:
        """Run visual OCR for one screenshot selection.

        Args:
            request: Typed screenshot OCR request.

        Returns:
            Typed OCR result containing text, GUI elements, and quality data.
        """
        ...
