"""Local and configurable visual OCR enrichment for screenshot evidence."""

from .apple_vision import AppleVisionVisualOCRProvider
from .image_preparer import PreparedVisualOCRImage, VisualOCRImagePreparationError, VisualOCRImagePreparer
from .openai_compatible import OpenAICompatibleVisualOCRProvider
from .prompt import VisualOCRPromptBuilder
from .providers import VisualOCRProviderFactory
from .service import VisualOCRService
from .worker import VisualOCRJobRunner

__all__ = [
    "AppleVisionVisualOCRProvider",
    "OpenAICompatibleVisualOCRProvider",
    "PreparedVisualOCRImage",
    "VisualOCRImagePreparationError",
    "VisualOCRImagePreparer",
    "VisualOCRJobRunner",
    "VisualOCRPromptBuilder",
    "VisualOCRProviderFactory",
    "VisualOCRService",
]
