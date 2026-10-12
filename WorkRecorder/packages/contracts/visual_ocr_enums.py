"""Visual OCR-specific enum contracts.

This module keeps VLM OCR state and provider vocabularies close to the
``visual_ocr`` contracts while ``packages.contracts.enums`` re-exports the
names for backwards-compatible imports.
"""

from __future__ import annotations

from enum import StrEnum


class VisualOCRProviderKind(StrEnum):
    """Supported VLM OCR provider adapters."""

    APPLE_VISION = "apple_vision"
    OPENAI_COMPATIBLE = "openai_compatible"


class VisualOCRAPIStyle(StrEnum):
    """OpenAI-compatible request protocol variants."""

    RESPONSES = "responses"
    CHAT_COMPLETIONS = "chat_completions"


class VisualOCRStatus(StrEnum):
    """User-facing visual OCR enrichment state."""

    DISABLED = "disabled"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class VisualOCRElementRole(StrEnum):
    """Normalized GUI element role names emitted by visual OCR."""

    BUTTON = "button"
    INPUT = "input"
    TAB = "tab"
    LINK = "link"
    LABEL = "label"
    TABLE = "table"
    ROW = "row"
    CELL = "cell"
    MENU = "menu"
    CHECKBOX = "checkbox"
    IMAGE = "image"
    OTHER = "other"


class EventChangeType(StrEnum):
    """Typed long-poll change categories emitted for Workbench refresh."""

    VISUAL_OCR = "visual_ocr"
