"""Settings service for the active-capture VM DOM hit probe."""

from __future__ import annotations

from pydantic import Field

from packages.active_capture.application.vm_a11y_probe import VMAccessibilityProbeService
from packages.contracts.base import ContractModel
from packages.storage.settings_repository import LocalSettingsRepository

_SETTINGS_KEY = "active_capture_vm_a11y_probe"


class VMA11yProbeSettings(ContractModel):
    """Workbench-safe settings for the VM DOM hit probe."""

    enabled: bool = True
    profile: str = Field(min_length=1)
    source: str = Field(min_length=1)
    url: str = Field(min_length=1)
    click_log_url: str | None = None
    click_log_path: str | None = None
    click_log_ssh: dict[str, object] | None = None
    last_error: str | None = None


class VMA11yProbeSettingsUpdate(ContractModel):
    """Mutable user preferences for the VM DOM hit probe."""

    enabled: bool = True


class VMA11yProbeSettingsService:
    """Load and persist VM DOM hit probe settings."""

    def __init__(
        self, *, repository: LocalSettingsRepository, probe: VMAccessibilityProbeService, allowed: bool = True
    ) -> None:
        self.allowed = allowed
        self.repository = repository
        self.probe = probe
        persisted = self.repository.get(_SETTINGS_KEY)
        if persisted is not None and isinstance(persisted.get("enabled"), bool):
            self.probe.set_enabled(allowed and bool(persisted["enabled"]))

        if not allowed:
            self.probe.set_enabled(False)

    def public(self) -> VMA11yProbeSettings:
        snapshot = self.probe.latest_snapshot()
        last_error = snapshot.get("last_error")
        return VMA11yProbeSettings(
            enabled=self.probe.is_enabled(),
            profile=self.probe.config.profile,
            source=self.probe.config.source,
            url=self.probe.config.url,
            click_log_url=self.probe.config.click_log_url,
            click_log_path=self.probe.config.click_log_path,
            click_log_ssh={
                "enabled": self.probe.config.click_log_ssh_enabled,
                "jump_host": self.probe.config.click_log_ssh_jump_host,
                "host": self.probe.config.click_log_ssh_host,
                "port": self.probe.config.click_log_ssh_port,
                "user": self.probe.config.click_log_ssh_user,
                "guest_path": self.probe.config.click_log_ssh_guest_path,
            },
            last_error=last_error if isinstance(last_error, str) else None,
        )

    def update(self, update: VMA11yProbeSettingsUpdate) -> VMA11yProbeSettings:
        enabled = self.allowed and update.enabled
        self.probe.set_enabled(enabled)
        self.repository.set(_SETTINGS_KEY, {"enabled": enabled})
        return self.public()
