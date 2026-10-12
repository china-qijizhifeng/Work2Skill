"""Settings service for configurable VLM OCR enrichment."""

from __future__ import annotations

from pydantic import SecretStr

from packages.contracts import VisualOCRPublicSettings, VisualOCRSettings, VisualOCRSettingsUpdate
from packages.storage.settings_repository import LocalSettingsRepository

from .secret_store import SecretStore

_SETTINGS_KEY = "visual_ocr"
_KEYCHAIN_SERVICE = "WorkRecorder.VisualOCR"
_API_KEY_ACCOUNT = "WORKRECORDER_VISUAL_OCR_API_KEY"


class VisualOCRSettingsService:
    """Load and persist visual OCR settings without exposing raw secrets."""

    def __init__(self, *, repository: LocalSettingsRepository, secrets: SecretStore) -> None:
        """Create a settings service.

        Args:
            repository: SQLite-backed store for non-secret settings.
            secrets: Secret backend used for API key storage.
        """

        self.repository = repository
        self.secrets = secrets

    def get(self, *, include_secret: bool = False) -> VisualOCRSettings:
        """Return configured settings, optionally hydrating the API key.

        Args:
            include_secret: Whether the returned model should include the API
                key from the secret store.

        Returns:
            Typed OCR settings. Secret material is only present when requested.
        """

        payload = self.repository.get(_SETTINGS_KEY)
        settings = VisualOCRSettings.model_validate(payload or {})
        secret = self.secrets.get(service=_KEYCHAIN_SERVICE, account=_API_KEY_ACCOUNT) if include_secret else None
        if include_secret and secret:
            return settings.model_copy(update={"api_key": SecretStr(secret)})
        return settings.model_copy(update={"api_key": None})

    def public(self) -> VisualOCRPublicSettings:
        """Return Workbench-safe settings with the key masked.

        Returns:
            Public settings safe to send to the local app.
        """

        settings = self.get(include_secret=False)
        api_key = self.secrets.get(service=_KEYCHAIN_SERVICE, account=_API_KEY_ACCOUNT)
        return self._public(settings, api_key_configured=bool(api_key))

    def runtime_flags(self) -> VisualOCRSettings:
        """Return non-secret settings for capture hot paths.

        This intentionally avoids Keychain/env lookups so a screenshot save can
        decide whether to enqueue work without touching the secret store.
        Returns:
            Non-secret settings safe for the capture hot path.
        """

        payload = self.repository.get(_SETTINGS_KEY)
        return VisualOCRSettings.model_validate(payload or {})

    def update(self, update: VisualOCRSettingsUpdate) -> VisualOCRPublicSettings:
        """Persist settings and optionally rotate the API key.

        Args:
            update: User-provided settings update with an optional secret key.

        Returns:
            Public settings after persistence and secret-store updates.
        """

        settings = VisualOCRSettings(
            enabled=update.enabled,
            auto_run_on_capture=update.auto_run_on_capture,
            provider_kind=update.provider_kind,
            api_style=update.api_style,
            base_url=update.base_url,
            allow_insecure_remote_base_url=update.allow_insecure_remote_base_url,
            model=update.model,
            timeout_seconds=update.timeout_seconds,
            max_image_long_edge=update.max_image_long_edge,
        )
        if update.api_key is not None:
            api_key = update.api_key.get_secret_value().strip()
            if api_key:
                self.secrets.set(
                    service=_KEYCHAIN_SERVICE,
                    account=_API_KEY_ACCOUNT,
                    value=api_key,
                )
            else:
                self.secrets.delete(service=_KEYCHAIN_SERVICE, account=_API_KEY_ACCOUNT)
        self.repository.set(_SETTINGS_KEY, settings.model_dump(mode="json", exclude={"api_key"}))
        return self.public()

    def _public(self, settings: VisualOCRSettings, *, api_key_configured: bool) -> VisualOCRPublicSettings:
        return VisualOCRPublicSettings(
            enabled=settings.enabled,
            auto_run_on_capture=settings.auto_run_on_capture,
            provider_kind=settings.provider_kind,
            api_style=settings.api_style,
            base_url=settings.base_url,
            allow_insecure_remote_base_url=settings.allow_insecure_remote_base_url,
            model=settings.model,
            timeout_seconds=settings.timeout_seconds,
            max_image_long_edge=settings.max_image_long_edge,
            api_key_configured=api_key_configured,
        )
