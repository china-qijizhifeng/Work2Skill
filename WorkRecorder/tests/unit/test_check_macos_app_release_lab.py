from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from scripts.check_macos_app_release_lab import LabEnvironment, LabReadinessStatus, evaluate_release_lab
from scripts.create_macos_recording_physical_report import build_argument_parser, build_report
from scripts.verify_macos_app_e2e_manifest import REQUIRED_CASES, JsonValue


def test_release_lab_preflight_reports_current_machine_blockers() -> None:
    checks = evaluate_release_lab(
        manifest=_manifest(),
        environment=LabEnvironment(
            display_count=1,
            stable_chrome_installed=True,
            notes_installed=True,
            hotkey_helper_available=True,
        ),
    )

    statuses = {check.key.value: check.status for check in checks}
    next_steps = {check.key.value: check.next_step for check in checks}
    assert statuses["multi_display"] == LabReadinessStatus.BLOCKED
    assert statuses["recording_region"] == LabReadinessStatus.READY_TO_VALIDATE
    assert statuses["recording_discard"] == LabReadinessStatus.READY_TO_VALIDATE
    assert statuses["recording_controls"] == LabReadinessStatus.READY_TO_VALIDATE
    assert statuses["stable_chrome"] == LabReadinessStatus.READY_TO_VALIDATE
    assert statuses["isolated_ax_denied"] == LabReadinessStatus.MANUAL_SETUP_REQUIRED
    assert statuses["notes_visible_target"] == LabReadinessStatus.READY_TO_VALIDATE
    assert statuses["external_shortcut_conflict_ui"] == LabReadinessStatus.READY_TO_VALIDATE
    assert "do not mark this passed from helper output alone" in next_steps["external_shortcut_conflict_ui"]


def test_release_lab_preflight_marks_passed_cases_complete() -> None:
    manifest = _manifest()
    for key in (
        "recording_region",
        "recording_discard",
        "recording_controls",
        "multi_display",
        "stable_chrome_extension_online_retry",
        "accessibility_denied",
        "notes",
    ):
        _manual_cases(manifest)[key]["status"] = "passed"
    _manual_cases(manifest)["stable_chrome_extension_online_retry"]["browser"] = "stable_chrome"
    _manual_cases(manifest)["shortcut_validation"]["external_helper_ui"] = "passed"
    manifest["open_risks"] = []

    checks = evaluate_release_lab(
        manifest=manifest,
        environment=LabEnvironment(
            display_count=2,
            stable_chrome_installed=True,
            notes_installed=True,
            hotkey_helper_available=True,
        ),
    )

    assert {check.status for check in checks} == {LabReadinessStatus.PASSED}


def test_release_lab_preflight_validates_passed_physical_recording_report(tmp_path: Path) -> None:
    manifest = _manifest()
    recording_case = _manual_cases(manifest)["recording_region"]
    recording_case["status"] = "passed"
    recording_case["report"] = "recording-region.json"
    (tmp_path / "recording-region.json").write_text(
        json.dumps(_generated_physical_report("recording_region"), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    checks = evaluate_release_lab(
        manifest=manifest,
        environment=LabEnvironment(
            display_count=2,
            stable_chrome_installed=True,
            notes_installed=True,
            hotkey_helper_available=True,
        ),
        report_dir=tmp_path,
    )

    checks_by_key = {check.key.value: check for check in checks}
    assert checks_by_key["recording_region"].status == LabReadinessStatus.PASSED
    assert "physical report is valid" in checks_by_key["recording_region"].evidence


def test_release_lab_preflight_rejects_passed_physical_recording_without_valid_report(tmp_path: Path) -> None:
    manifest = _manifest()
    recording_case = _manual_cases(manifest)["recording_region"]
    recording_case["status"] = "passed"
    recording_case["report"] = "recording-region.json"
    (tmp_path / "recording-region.json").write_text('{"case": "recording_region"}\n', encoding="utf-8")

    checks = evaluate_release_lab(
        manifest=manifest,
        environment=LabEnvironment(
            display_count=2,
            stable_chrome_installed=True,
            notes_installed=True,
            hotkey_helper_available=True,
        ),
        report_dir=tmp_path,
    )

    checks_by_key = {check.key.value: check for check in checks}
    assert checks_by_key["recording_region"].status == LabReadinessStatus.MANUAL_SETUP_REQUIRED
    assert "physical report is invalid" in checks_by_key["recording_region"].evidence


def test_release_lab_preflight_does_not_treat_chrome_for_testing_as_stable_chrome() -> None:
    manifest = _manifest()
    stable_case = _manual_cases(manifest)["stable_chrome_extension_online_retry"]
    stable_case["status"] = "passed_with_chrome_for_testing"

    checks = evaluate_release_lab(
        manifest=manifest,
        environment=LabEnvironment(
            display_count=2,
            stable_chrome_installed=True,
            notes_installed=True,
            hotkey_helper_available=True,
        ),
    )

    statuses = {check.key.value: check.status for check in checks}
    assert statuses["stable_chrome"] == LabReadinessStatus.READY_TO_VALIDATE


def test_release_lab_preflight_requires_external_shortcut_ui_evidence_even_without_caveat() -> None:
    manifest = _manifest()
    manifest["open_risks"] = [risk for risk in _open_risks(manifest) if "External shortcut conflict" not in risk]

    checks = evaluate_release_lab(
        manifest=manifest,
        environment=LabEnvironment(
            display_count=2,
            stable_chrome_installed=True,
            notes_installed=True,
            hotkey_helper_available=True,
        ),
    )

    statuses = {check.key.value: check.status for check in checks}
    assert statuses["external_shortcut_conflict_ui"] == LabReadinessStatus.READY_TO_VALIDATE


def test_release_lab_preflight_downgrades_known_failed_external_helper_diagnostic() -> None:
    manifest = _manifest()
    _manual_cases(manifest)["shortcut_validation"]["external_helper_ui"] = "not_passed_helper_diagnostic_only"

    checks = evaluate_release_lab(
        manifest=manifest,
        environment=LabEnvironment(
            display_count=2,
            stable_chrome_installed=True,
            notes_installed=True,
            hotkey_helper_available=True,
        ),
    )

    checks_by_key = {check.key.value: check for check in checks}
    external_shortcut = checks_by_key["external_shortcut_conflict_ui"]
    assert external_shortcut.status == LabReadinessStatus.MANUAL_SETUP_REQUIRED
    assert "not 'passed'" in external_shortcut.evidence


def test_release_lab_preflight_blocks_missing_chrome_and_helper() -> None:
    checks = evaluate_release_lab(
        manifest=_manifest(),
        environment=LabEnvironment(
            display_count=2,
            stable_chrome_installed=False,
            notes_installed=False,
            hotkey_helper_available=False,
        ),
    )

    statuses = {check.key.value: check.status for check in checks}
    assert statuses["stable_chrome"] == LabReadinessStatus.BLOCKED
    assert statuses["notes_visible_target"] == LabReadinessStatus.BLOCKED
    assert statuses["external_shortcut_conflict_ui"] == LabReadinessStatus.BLOCKED


def _manifest() -> dict[str, JsonValue]:
    manual_cases = {required.key: {"status": "passed", "report": f"{required.key}.json"} for required in REQUIRED_CASES}
    manual_cases["stable_chrome_extension_online_retry"]["status"] = "failed_environment_extension_not_registered"
    manual_cases["multi_display"]["status"] = "not_available_on_machine"
    manual_cases["accessibility_denied"]["status"] = "not_verified_requires_isolated_tcc_state"
    manual_cases["notes"]["status"] = "not_verified_no_visible_target"
    manual_cases["recording_region"]["status"] = "not_verified_requires_physical_recording_matrix"
    manual_cases["recording_discard"]["status"] = "not_verified_requires_physical_recording_matrix"
    manual_cases["recording_controls"]["status"] = "not_verified_requires_physical_recording_matrix"
    return {
        "manual_cases": cast(JsonValue, manual_cases),
        "open_risks": [
            "Stable Chrome 148 did not register; Chrome for Testing passed.",
            "Physical multi-display negative-coordinate/mixed-Retina cases need lab hardware.",
            "Physical recording matrix remains pending for shortcut-driven region recording, discard, and HUD controls.",
            "Accessibility-denied while Screen Recording is granted needs isolated TCC fixture.",
            "Notes did not produce a stable visible target in this desktop session.",
            "External shortcut conflict remains a release-lab caveat.",
        ],
    }


def _manual_cases(manifest: dict[str, JsonValue]) -> dict[str, dict[str, JsonValue]]:
    return cast(dict[str, dict[str, JsonValue]], manifest["manual_cases"])


def _open_risks(manifest: dict[str, JsonValue]) -> list[str]:
    return cast(list[str], manifest["open_risks"])


def _generated_physical_report(case_key: str) -> dict[str, JsonValue]:
    args = build_argument_parser().parse_args(_physical_report_args(case_key))
    return build_report(args)


def _physical_report_args(case_key: str) -> list[str]:
    common = [
        "--case",
        case_key,
        "--output",
        "/unused/report.json",
        "--session-id",
        "acs_test",
        "--started-at",
        "2026-06-02T08:03:00Z",
        "--ended-at",
        "2026-06-02T08:03:05Z",
        "--operator-note",
        "Observed on the physical release-lab machine.",
        "--opened-via-physical-shortcut",
        "--region-selection-confirmed",
        "--hud-visible",
        "--recording-boundary-visible",
        "--completion-sheet-visible",
        "--privacy-check-no-storage-uri",
        "--privacy-check-no-local-path",
    ]
    return [
        *common,
        "--save-clicked",
        "--completion-final-status",
        "completed",
        "--video-state",
        "available",
        "--appears-in-recording-library",
        "--event-id",
        "evt_recording",
        "--video-artifact-id",
        "art_video",
        "--duration-ms",
        "3500",
        "--segment-count",
        "1",
        "--keyframe-count",
        "3",
    ]
