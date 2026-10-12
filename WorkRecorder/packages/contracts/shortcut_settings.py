"""Typed local shortcut settings shared by daemon and macOS Workbench."""

from __future__ import annotations

from pydantic import Field, model_validator

from .base import ContractModel
from .enums import ShortcutCommandKind, ShortcutModifier, ShortcutRegistrationState


class KeyboardShortcut(ContractModel):
    """A platform-neutral keyboard shortcut binding.

    The daemon stores these settings for Workbench sync and diagnostics, while
    the macOS shell remains responsible for translating the key code and
    modifier tuple into a native Carbon registration.
    """

    key_code: int = Field(ge=0, le=255)
    key_label: str = Field(min_length=1, max_length=24)
    modifiers: tuple[ShortcutModifier, ...] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def _validate_shortcut_policy(self) -> "KeyboardShortcut":
        strong_modifiers = {
            ShortcutModifier.CONTROL,
            ShortcutModifier.COMMAND,
            ShortcutModifier.OPTION,
        }
        modifier_only_key_codes = {54, 55, 56, 58, 59, 60, 61, 62}
        if strong_modifiers.isdisjoint(self.modifiers):
            raise ValueError("shortcut must include control, command, or option")
        if self.key_code in modifier_only_key_codes:
            raise ValueError("shortcut key cannot be a modifier-only key")
        return self


class ShortcutCommandBinding(ContractModel):
    """One command-to-shortcut binding.

    Bindings are persisted as a list so clients can preserve display order and
    the service can merge missing commands with current defaults during schema
    evolution.
    """

    command: ShortcutCommandKind
    shortcut: KeyboardShortcut
    enabled: bool = True


class ShortcutRegistrationStatusView(ContractModel):
    """Workbench-safe native registration status.

    The macOS shell owns real registration and conflict detection. This view is
    kept intentionally non-secret so Workbench can display conflict diagnostics
    without returning local paths, tokens, or raw event payloads.
    """

    command: ShortcutCommandKind
    shortcut: KeyboardShortcut
    state: ShortcutRegistrationState
    os_status: int | None = None
    message: str = Field(min_length=1, max_length=160)


class ShortcutSettings(ContractModel):
    """Persisted local shortcut settings.

    Settings are local to the device, non-secret, and safe to round-trip through
    the daemon. Unknown or missing command rows are filled from defaults rather
    than causing older clients to lose newer command bindings.
    """

    bindings: tuple[ShortcutCommandBinding, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _validate_no_duplicate_enabled_bindings(self) -> "ShortcutSettings":
        owners: dict[tuple[int, tuple[ShortcutModifier, ...]], ShortcutCommandKind] = {}
        for binding in self.bindings:
            if not binding.enabled:
                continue
            key = (binding.shortcut.key_code, tuple(sorted(binding.shortcut.modifiers, key=lambda item: item.value)))
            existing = owners.get(key)
            if existing is not None and existing != binding.command:
                raise ValueError("shortcut bindings must not duplicate enabled commands")
            owners[key] = binding.command
        return self

    @classmethod
    def defaults(cls) -> "ShortcutSettings":
        return cls(
            bindings=(
                ShortcutCommandBinding(
                    command=ShortcutCommandKind.CURRENT_APPSHOT,
                    shortcut=KeyboardShortcut(
                        key_code=19,
                        key_label="2",
                        modifiers=(ShortcutModifier.CONTROL, ShortcutModifier.COMMAND),
                    ),
                    enabled=True,
                ),
                ShortcutCommandBinding(
                    command=ShortcutCommandKind.REGION_SCREENSHOT,
                    shortcut=KeyboardShortcut(
                        key_code=20,
                        key_label="3",
                        modifiers=(ShortcutModifier.CONTROL, ShortcutModifier.COMMAND),
                    ),
                    enabled=True,
                ),
                ShortcutCommandBinding(
                    command=ShortcutCommandKind.REGION_RECORDING,
                    shortcut=KeyboardShortcut(
                        key_code=15,
                        key_label="R",
                        modifiers=(ShortcutModifier.CONTROL, ShortcutModifier.OPTION, ShortcutModifier.COMMAND),
                    ),
                    enabled=True,
                ),
            )
        )

    def merged_with_defaults(self) -> "ShortcutSettings":
        existing = {binding.command: binding for binding in self.bindings}
        defaults = {binding.command: binding for binding in self.defaults().bindings}
        defaults.update(existing)
        return ShortcutSettings(bindings=tuple(defaults[command] for command in ShortcutCommandKind))
