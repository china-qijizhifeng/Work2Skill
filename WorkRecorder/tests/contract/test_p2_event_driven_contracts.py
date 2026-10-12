from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from packages.contracts import A11ySnapshot, CollectEvidenceCommand, DomCaptureMode, ProviderSessionRegistration

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "golden"


def test_provider_session_registration_fixture_contains_no_evidence_payload():
    payload = _fixture("provider_session_registration.json")
    registration = ProviderSessionRegistration.model_validate(payload)

    assert registration.provider_key == "web.browser_extension"
    assert registration.provider_kind == "source"
    assert "evidence" not in payload
    assert "dom" not in payload


def test_collect_evidence_command_fixture_requests_full_dom():
    command = CollectEvidenceCommand.model_validate(_fixture("collect_evidence_command.json"))

    assert command.provider_key == "web.browser_extension"
    assert command.dom_capture_mode == DomCaptureMode.FULL
    assert command.attempt.selection_geometry.selected_region.coordinate_space == "macos_global"


def test_a11y_snapshot_fixture_is_typed_and_text_bearing():
    snapshot = A11ySnapshot.model_validate(_fixture("a11y_snapshot.json"))

    assert snapshot.permission_state == "granted"
    assert snapshot.full_text == "ACME Pricing Dashboard Budget variance +18%"
    assert snapshot.coverage.text_block_count == 1
    assert snapshot.text_blocks[0].block_id == "a11y_block_0"
    assert snapshot.text_blocks[0].node_path == "0/0"
    assert snapshot.text_blocks[0].role_path == ("AXGroup", "AXStaticText")
    assert snapshot.text_blocks[0].is_leaf_text is True


def test_a11y_permission_denied_fixture_is_typed_failure():
    snapshot = A11ySnapshot.model_validate(_fixture("a11y_snapshot_permission_denied.json"))

    assert snapshot.permission_state == "denied"
    assert snapshot.full_text == ""
    assert snapshot.coverage.error_message == "macOS Accessibility permission is not granted"


def _fixture(name: str) -> dict[str, object]:
    payload = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AssertionError(f"Golden fixture {name} must contain a JSON object")
    return cast(dict[str, object], payload)
