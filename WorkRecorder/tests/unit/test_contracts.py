from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.contracts import (
    CaptureSaveRequest,
    KeyboardShortcut,
    ShortcutCommandBinding,
    ShortcutCommandKind,
    ShortcutModifier,
    ShortcutSettings,
    TriggerEnvelope,
)


def test_trigger_envelope_rejects_unknown_trigger(event_create):
    payload = event_create.trigger.model_dump(mode="json")
    payload["trigger_type"] = "manual_region_hotkey"
    with pytest.raises(ValidationError):
        TriggerEnvelope.model_validate(payload)


def test_context_event_create_round_trips(event_create):
    encoded = event_create.model_dump_json()
    decoded = type(event_create).model_validate_json(encoded)
    assert decoded.trigger.trigger_id == "trg_test"
    assert decoded.source_binding.source_ref.title == "ACME Pricing Dashboard"


def test_capture_save_request_round_trips(capture_save_request):
    encoded = capture_save_request.model_dump_json()
    decoded = CaptureSaveRequest.model_validate_json(encoded)
    assert decoded.selection_geometry.display.display_id == "display_main"
    assert decoded.workspace.workspace_id == "auto"
    assert decoded.staged_artifact.artifact_type == capture_save_request.staged_artifact.artifact_type


def test_keyboard_shortcut_requires_strong_modifier() -> None:
    with pytest.raises(ValidationError):
        KeyboardShortcut(key_code=0, key_label="A", modifiers=(ShortcutModifier.SHIFT,))


def test_keyboard_shortcut_rejects_modifier_only_key() -> None:
    with pytest.raises(ValidationError):
        KeyboardShortcut(key_code=55, key_label="Command", modifiers=(ShortcutModifier.COMMAND,))


def test_shortcut_settings_reject_duplicate_enabled_commands() -> None:
    duplicate = KeyboardShortcut(
        key_code=19, key_label="2", modifiers=(ShortcutModifier.CONTROL, ShortcutModifier.COMMAND)
    )
    with pytest.raises(ValidationError):
        ShortcutSettings(
            bindings=(
                ShortcutCommandBinding(command=ShortcutCommandKind.CURRENT_APPSHOT, shortcut=duplicate),
                ShortcutCommandBinding(command=ShortcutCommandKind.REGION_SCREENSHOT, shortcut=duplicate),
            )
        )
