"""Provider factory for visual OCR model adapters."""

from __future__ import annotations

from packages.contracts import VisualOCRProviderKind, VisualOCRSettings

from .apple_vision import AppleVisionVisualOCRProvider, apple_vision_unavailable_reason
from .openai_compatible import OpenAICompatibleVisualOCRProvider
from .ports import VisualOCRProvider
from .prompt import VisualOCRPromptBuilder


class VisualOCRProviderFactory:
    """Construct visual OCR providers behind a stable registry boundary."""

    def __init__(self, *, prompt_builder: VisualOCRPromptBuilder) -> None:
        self.prompt_builder = prompt_builder

    def create(self, settings: VisualOCRSettings) -> VisualOCRProvider:
        """Return the provider configured by typed settings.

        Args:
            settings: Persisted visual OCR settings that select provider kind,
                API style, endpoint, model, and secret material.

        Returns:
            A provider implementation that can execute visual OCR requests.

        Raises:
            ValueError: If the configured provider kind is not registered.
        """

        effective_settings = self._effective_settings(settings)
        if effective_settings.provider_kind == VisualOCRProviderKind.APPLE_VISION:
            return AppleVisionVisualOCRProvider(settings=effective_settings)
        if effective_settings.provider_kind == VisualOCRProviderKind.OPENAI_COMPATIBLE:
            return OpenAICompatibleVisualOCRProvider(settings=effective_settings, prompt_builder=self.prompt_builder)
        raise ValueError(f"unsupported visual OCR provider kind: {effective_settings.provider_kind.value}")

    def unavailable_reason(self, settings: VisualOCRSettings) -> str | None:
        """Return a stable reason when the selected OCR provider cannot run.

        Args:
            settings: Persisted visual OCR settings used to choose the provider
                and inspect required credentials or local runtime state.

        Returns:
            ``None`` when the selected provider is runnable; otherwise a stable
            reason code that can be recorded on skipped OCR jobs.
        """

        effective_settings = self._effective_settings(settings)
        if effective_settings.provider_kind == VisualOCRProviderKind.APPLE_VISION:
            return apple_vision_unavailable_reason()
        if (
            effective_settings.provider_kind == VisualOCRProviderKind.OPENAI_COMPATIBLE
            and effective_settings.api_key is None
        ):
            return "config_required"
        return None

    def _effective_settings(self, settings: VisualOCRSettings) -> VisualOCRSettings:
        if settings.provider_kind != VisualOCRProviderKind.OPENAI_COMPATIBLE or settings.api_key is not None:
            return settings
        if apple_vision_unavailable_reason() is not None:
            return settings
        return settings.model_copy(update={"provider_kind": VisualOCRProviderKind.APPLE_VISION})
