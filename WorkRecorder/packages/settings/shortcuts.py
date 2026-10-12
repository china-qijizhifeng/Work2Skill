"""Settings service for local capture shortcut bindings."""

from __future__ import annotations

from packages.contracts import ShortcutSettings
from packages.storage.settings_repository import LocalSettingsRepository

_SETTINGS_KEY = "shortcuts"


class ShortcutSettingsService:
    """Load and persist non-secret shortcut settings."""

    def __init__(self, *, repository: LocalSettingsRepository) -> None:
        self.repository = repository

    def get(self) -> ShortcutSettings:
        payload = self.repository.get(_SETTINGS_KEY)
        return ShortcutSettings.model_validate(payload or {}).merged_with_defaults()

    def update(self, settings: ShortcutSettings) -> ShortcutSettings:
        merged = settings.merged_with_defaults()
        self.repository.set(_SETTINGS_KEY, merged.model_dump(mode="json"))
        return merged
