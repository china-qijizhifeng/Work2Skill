from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest

from scripts.create_macos_recording_physical_report import build_argument_parser, build_report
from scripts.validate_macos_recording_physical_report import main as validate_physical_recording_report_main
from scripts.verify_macos_app_e2e_manifest import QUALITY_GATES, REQUIRED_CASES, JsonValue, validate_manifest


def test_manifest_verifier_accepts_explicit_environment_limitations(tmp_path: Path) -> None:
    findings = validate_manifest(_manifest(tmp_path), strict_release=False, report_dir=tmp_path)

    assert not [finding for finding in findings if finding.severity == "error"]
    assert {finding.case_key for finding in findings if finding.severity == "warning"} >= {
        "accessibility_denied",
        "multi_display",
        "notes",
        "recording_controls",
        "recording_discard",
        "recording_region",
        "stable_chrome_extension_online_retry",
    }


def test_manifest_verifier_strict_release_rejects_environment_limitations(tmp_path: Path) -> None:
    findings = validate_manifest(_manifest(tmp_path), strict_release=True, report_dir=tmp_path)

    errors = [finding for finding in findings if finding.severity == "error"]
    assert {finding.case_key for finding in errors} >= {
        "accessibility_denied",
        "external_shortcut_conflict_ui",
        "multi_display",
        "notes",
        "recording_controls",
        "recording_discard",
        "recording_region",
        "stable_chrome_extension_online_retry",
    }


def test_manifest_verifier_rejects_pass_required_limited_case(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    _manual_cases(manifest)["current_window_chrome"]["status"] = "not_available_on_machine"

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "current_window_chrome"
        and "release-required case is still limited" in finding.message
        for finding in findings
    )


def test_manifest_verifier_rejects_missing_case(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    del _manual_cases(manifest)["region_screenshot"]

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "region_screenshot"
        and "required case is missing" in finding.message
        for finding in findings
    )


def test_manifest_verifier_rejects_nonexistent_pass_report(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    (tmp_path / "current_window_chrome.json").unlink()

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "current_window_chrome"
        and "artifact does not exist" in finding.message
        for finding in findings
    )


def test_manifest_verifier_rejects_broken_large_review_smoke_report(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    (tmp_path / "recording_large_review_packaged_smoke.json").write_text(
        '{"playback_loaded": false}\n',
        encoding="utf-8",
    )

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "recording_large_review_packaged_smoke"
        and "playback_loaded" in finding.message
        for finding in findings
    )


def test_manifest_verifier_rejects_large_review_bool_numeric_proof(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    report = _large_review_smoke_report()
    report["duration_ms"] = True
    report["window_frame"] = {"height": 720, "width": True}
    (tmp_path / "recording_large_review_packaged_smoke.json").write_text(
        json.dumps(report, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "recording_large_review_packaged_smoke"
        and "duration_ms" in finding.message
        for finding in findings
    )
    assert any(
        finding.severity == "error"
        and finding.case_key == "recording_large_review_packaged_smoke"
        and "window_frame.width" in finding.message
        for finding in findings
    )


def test_manifest_verifier_rejects_broken_physical_recording_report(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    recording_case = _manual_cases(manifest)["recording_region"]
    recording_case["status"] = "passed"
    recording_case["report"] = "recording_region.json"
    (tmp_path / "recording_region.json").write_text(
        json.dumps(
            {
                "case": "recording_region",
                "opened_via_physical_shortcut": False,
                "save_clicked": True,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "recording_region"
        and "opened_via_physical_shortcut" in finding.message
        for finding in findings
    )


def test_manifest_verifier_accepts_valid_physical_recording_reports(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    for case_key in ("recording_region", "recording_discard", "recording_controls"):
        recording_case = _manual_cases(manifest)[case_key]
        recording_case["status"] = "passed"
        recording_case["report"] = f"{case_key}.json"
        (tmp_path / f"{case_key}.json").write_text(
            json.dumps(_physical_recording_report(case_key), sort_keys=True) + "\n",
            encoding="utf-8",
        )

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert not [
        finding for finding in findings if finding.severity == "error" and finding.case_key.startswith("recording_")
    ]


def test_manifest_verifier_scopes_recording_open_risks_to_matching_case(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    for case_key in ("recording_region", "recording_discard"):
        recording_case = _manual_cases(manifest)[case_key]
        recording_case["status"] = "passed"
        recording_case["report"] = f"{case_key}.json"
        (tmp_path / f"{case_key}.json").write_text(
            json.dumps(_physical_recording_report(case_key), sort_keys=True) + "\n",
            encoding="utf-8",
        )
    manifest["open_risks"] = [
        "Recording controls physical recording matrix remains pending for the final HUD controls pass.",
    ]

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert not [
        finding
        for finding in findings
        if finding.case_key in {"recording_region", "recording_discard"}
        and "related release-lab caveat" in finding.message
    ]
    assert any(
        finding.severity == "warning"
        and finding.case_key == "recording_controls"
        and "accepted as explicit environment limitation" in finding.message
        for finding in findings
    )


def test_manifest_verifier_rejects_physical_recording_pass_without_report_even_with_screenshot(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    recording_case = _manual_cases(manifest)["recording_region"]
    recording_case["status"] = "passed"
    recording_case.pop("report", None)
    recording_case["raw_screenshot"] = "recording_region.png"
    (tmp_path / "recording_region.png").write_text("not a report\n", encoding="utf-8")

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "recording_region"
        and "requires a report artifact" in finding.message
        for finding in findings
    )


def test_physical_recording_report_rejects_bool_numeric_proof(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    recording_case = _manual_cases(manifest)["recording_region"]
    recording_case["status"] = "passed"
    recording_case["report"] = "recording_region.json"
    report = _physical_recording_report("recording_region")
    report["duration_ms"] = True
    report["segment_count"] = True
    report["keyframe_count"] = True
    (tmp_path / "recording_region.json").write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error" and finding.case_key == "recording_region" and "duration_ms" in finding.message
        for finding in findings
    )
    assert any(
        finding.severity == "error" and finding.case_key == "recording_region" and "segment_count" in finding.message
        for finding in findings
    )


@pytest.mark.parametrize(
    ("started_at", "ended_at", "expected"),
    [
        ("2026-06-02T08:03:00", "2026-06-02T08:03:05Z", "started_at"),
        ("2026-06-02T08:03:10Z", "2026-06-02T08:03:05Z", "ended_at must be after"),
    ],
)
def test_physical_recording_report_requires_timezone_ordered_timestamps(
    tmp_path: Path,
    started_at: str,
    ended_at: str,
    expected: str,
) -> None:
    manifest = _manifest(tmp_path)
    recording_case = _manual_cases(manifest)["recording_region"]
    recording_case["status"] = "passed"
    recording_case["report"] = "recording_region.json"
    report = _physical_recording_report("recording_region")
    report["started_at"] = started_at
    report["ended_at"] = ended_at
    (tmp_path / "recording_region.json").write_text(json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error" and finding.case_key == "recording_region" and expected in finding.message
        for finding in findings
    )


@pytest.mark.parametrize("case_key", ["recording_region", "recording_discard", "recording_controls"])
def test_physical_recording_report_helper_outputs_manifest_verifiable_reports(
    tmp_path: Path,
    case_key: str,
) -> None:
    manifest = _manifest(tmp_path)
    recording_case = _manual_cases(manifest)[case_key]
    recording_case["status"] = "passed"
    recording_case["report"] = f"{case_key}.json"
    (tmp_path / f"{case_key}.json").write_text(
        json.dumps(_generated_physical_report(case_key), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert not [finding for finding in findings if finding.severity == "error" and finding.case_key == case_key]


def test_physical_recording_report_helper_defaults_do_not_accidentally_pass(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    recording_case = _manual_cases(manifest)["recording_region"]
    recording_case["status"] = "passed"
    recording_case["report"] = "recording_region.json"
    parser = build_argument_parser()
    args = parser.parse_args(
        [
            "--case",
            "recording_region",
            "--output",
            str(tmp_path / "recording_region.json"),
            "--session-id",
            "acs_test",
            "--started-at",
            "2026-06-02T08:03:00Z",
            "--ended-at",
            "2026-06-02T08:03:05Z",
            "--operator-note",
            "Draft report without confirmations.",
        ]
    )
    (tmp_path / "recording_region.json").write_text(
        json.dumps(build_report(args), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "recording_region"
        and "opened_via_physical_shortcut" in finding.message
        for finding in findings
    )


def test_physical_recording_report_validator_cli_accepts_generated_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "recording_region.json"
    report.write_text(
        json.dumps(_generated_physical_report("recording_region"), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "validation.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "validate_macos_recording_physical_report.py",
            "--case",
            "recording_region",
            "--report",
            str(report),
            "--json-output",
            str(output),
        ],
    )

    exit_code = validate_physical_recording_report_main()

    assert exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["ok"] is True


def test_physical_recording_report_validator_cli_rejects_unconfirmed_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report = tmp_path / "recording_region.json"
    report.write_text('{"case": "recording_region"}\n', encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        [
            "validate_macos_recording_physical_report.py",
            "--case",
            "recording_region",
            "--report",
            str(report),
        ],
    )

    exit_code = validate_physical_recording_report_main()

    assert exit_code == 1


def test_manifest_verifier_rejects_nonexistent_supporting_report(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    chrome = _manual_cases(manifest)["current_window_chrome"]
    chrome["supporting_reports"] = ["missing-supporting-report.json"]

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "current_window_chrome"
        and "supporting_reports artifact does not exist" in finding.message
        for finding in findings
    )


def test_manifest_verifier_rejects_report_path_outside_report_dir(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    outside = tmp_path.parent / "outside-report.json"
    outside.write_text("{}\n", encoding="utf-8")
    _manual_cases(manifest)["current_window_chrome"]["report"] = "../outside-report.json"

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "current_window_chrome"
        and "must stay under report directory" in finding.message
        for finding in findings
    )


def test_manifest_verifier_rejects_release_lab_display_count_mismatch(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["screens"] = [
        {"index": 0, "scale": 2.0},
        {"index": 1, "scale": 2.0},
        {"index": 2, "scale": 2.0},
    ]
    _write_release_lab_preflight(tmp_path, display_count=1)

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "screens"
        and "disagrees with release-lab preflight" in finding.message
        for finding in findings
    )


def test_manifest_verifier_requires_release_lab_preflight_artifact(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    (tmp_path / "release-lab-preflight.json").unlink()

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "release_lab_preflight"
        and "requires release-lab-preflight.json" in finding.message
        for finding in findings
    )


def test_manifest_verifier_rejects_release_lab_preflight_summary_mismatch(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    _quality_gates(manifest)[
        "release_lab_preflight"
    ] = "completed current-machine profile: 1 blocked, 2 manual_setup_required, 5 ready_to_validate"

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "release_lab_preflight"
        and "disagree with artifact counts" in finding.message
        for finding in findings
    )


def test_manifest_verifier_rejects_fake_release_lab_preflight_keys_with_matching_counts(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    fake_checks: list[JsonValue] = [
        _preflight_check(f"fake_ready_{index}", "ready_to_validate", manifest_case="region_screenshot")
        for index in range(6)
    ]
    fake_checks.extend(
        _preflight_check(f"fake_setup_{index}", "manual_setup_required", manifest_case="shortcut_validation")
        for index in range(2)
    )
    (tmp_path / "release-lab-preflight.json").write_text(
        json.dumps(
            {
                "checks": fake_checks,
                "environment": {
                    "display_count": 3,
                    "hotkey_helper_available": True,
                    "notes_installed": True,
                    "stable_chrome_installed": True,
                },
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error" and finding.case_key == "release_lab_preflight" and "unexpected" in finding.message
        for finding in findings
    )
    assert any(
        finding.severity == "error" and finding.case_key == "release_lab_preflight" and "missing" in finding.message
        for finding in findings
    )


def test_manifest_verifier_rejects_free_text_evidence_only_pass(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    chrome = _manual_cases(manifest)["current_window_chrome"]
    chrome.pop("report")
    chrome["evidence"] = "trust me"

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "current_window_chrome"
        and "not free-text evidence" in finding.message
        for finding in findings
    )


@pytest.mark.parametrize(
    ("gate", "value"),
    [
        ("ruff", "FAILED with 12 violations"),
        ("swift_test", "FAILED before 106 passed"),
        ("python_targeted_core", "138 passed, 1 failed"),
        ("pyright", "0 errors, 1 warning"),
        ("repo_quality_audit", "0 violations, 1 warning"),
        ("swift_quality_audit", "passed with warnings"),
        ("codesign_strict", "failed_on_fileprovider_but_passed_elsewhere"),
    ],
)
def test_manifest_verifier_rejects_failed_quality_gate_family(tmp_path: Path, gate: str, value: str) -> None:
    manifest = _manifest(tmp_path)
    _quality_gates(manifest)[gate] = value

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error" and finding.case_key == "quality_gates" and gate in finding.message
        for finding in findings
    )


def test_manifest_verifier_rejects_unknown_quality_gate(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    _quality_gates(manifest)["new_unvalidated_gate"] = "trust me"

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "quality_gates"
        and "unvalidated quality gate" in finding.message
        for finding in findings
    )


def test_manifest_verifier_strict_release_rejects_passed_case_with_open_risk(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    for key in ("stable_chrome_extension_online_retry", "multi_display", "accessibility_denied", "notes"):
        _manual_cases(manifest)[key]["status"] = "passed"

    findings = validate_manifest(manifest, strict_release=True, report_dir=tmp_path)

    assert {finding.case_key for finding in findings if finding.severity == "error"} >= {
        "stable_chrome_extension_online_retry",
        "multi_display",
        "accessibility_denied",
        "notes",
    }


def test_manifest_verifier_warns_when_external_shortcut_ui_is_unproven(tmp_path: Path) -> None:
    findings = validate_manifest(_manifest(tmp_path), strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "warning"
        and finding.case_key == "external_shortcut_conflict_ui"
        and "not proven" in finding.message
        for finding in findings
    )


def test_manifest_verifier_strict_release_rejects_unproven_external_shortcut_ui_without_open_risk(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path)
    for key in ("stable_chrome_extension_online_retry", "multi_display", "accessibility_denied", "notes"):
        _manual_cases(manifest)[key]["status"] = "passed"
    manifest["open_risks"] = []

    findings = validate_manifest(manifest, strict_release=True, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "external_shortcut_conflict_ui"
        and "not proven" in finding.message
        for finding in findings
    )


def test_manifest_verifier_rejects_legacy_external_shortcut_pass_status(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    _manual_cases(manifest)["shortcut_validation"][
        "status"
    ] = "passed_automated_carbon_conflict_plus_manual_internal_validation"

    findings = validate_manifest(manifest, strict_release=False, report_dir=tmp_path)

    assert any(
        finding.severity == "error"
        and finding.case_key == "shortcut_validation"
        and "unexpected status" in finding.message
        for finding in findings
    )


def _manifest(report_dir: Path) -> dict[str, JsonValue]:
    _write_release_lab_preflight(report_dir)
    manual_cases = {required.key: {"status": "passed", "report": f"{required.key}.json"} for required in REQUIRED_CASES}
    for required in REQUIRED_CASES:
        report_path = report_dir / f"{required.key}.json"
        if required.key == "recording_large_review_packaged_smoke":
            report_path.write_text(json.dumps(_large_review_smoke_report(), sort_keys=True) + "\n", encoding="utf-8")
        else:
            report_path.write_text("{}\n", encoding="utf-8")
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
            "Accessibility-denied while Screen Recording is granted needs isolated TCC fixture.",
            "Notes did not produce a stable visible target in this desktop session.",
            "External shortcut conflict remains a release-lab caveat.",
            "Physical recording matrix remains pending for shortcut-driven region recording, discard, and HUD controls.",
        ],
        "quality_gates": cast(JsonValue, _passing_quality_gates()),
        "bundle": {
            "path": "/tmp/repo/dist/WorkRecorder.app",
            "codesign_verify": "dist/WorkRecorder.app: valid on disk",
            "codesign_strict_staged_no_xattr": "/tmp/WorkRecorder.app: valid on disk",
        },
        "daemon": {
            "health": {
                "ok": True,
                "data": {
                    "service": "workrecorder-local-daemon",
                },
            },
        },
    }


def _manual_cases(manifest: dict[str, JsonValue]) -> dict[str, dict[str, JsonValue]]:
    return cast(dict[str, dict[str, JsonValue]], manifest["manual_cases"])


def _quality_gates(manifest: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], manifest["quality_gates"])


def _passing_quality_gates() -> dict[str, str]:
    return {
        gate: {
            "browser_extension_npm_test": "9 passed",
            "codesign_strict": "passed_on_non_fileprovider_staging",
            "codesign_verify": "passed",
            "git_diff_check": "clean",
            "macos_app_e2e_manifest_verifier": "passed with explicit environment-limited warnings",
            "mypy": "success: no issues found in 291 source files",
            "package_verify": "passed",
            "python_sanitizer_targeted": "15 passed",
            "python_targeted_core": "138 passed",
            "pyright": "0 errors, 0 warnings, 0 informations",
            "repo_quality_audit": "0 violations, 0 warnings",
            "release_lab_preflight": "completed current-machine profile: 0 blocked, 2 manual_setup_required, 6 ready_to_validate",
            "ruff": "clean",
            "shortcut_settings_swift_filter": "11 passed including same-process Carbon registration-denial coverage",
            "swift_quality_audit": "passed",
            "swift_test": "106 passed",
        }[gate]
        for gate in QUALITY_GATES
    }


def _large_review_smoke_report() -> dict[str, JsonValue]:
    return {
        "duration_ms": 1500,
        "event_id": "evt_test",
        "playback_byte_size": 2048,
        "playback_file_exists": True,
        "playback_loaded": True,
        "playback_purpose": "workbench_large_recording_review",
        "session_id": "acs_test",
        "step_count": 4,
        "video_artifact_id": "art_test",
        "video_state": "available",
        "window_frame": {"height": 800, "width": 1200, "x": 0, "y": 0},
        "window_visible": True,
    }


def _write_release_lab_preflight(report_dir: Path, *, display_count: int = 3) -> None:
    payload: dict[str, JsonValue] = {
        "environment": {
            "display_count": display_count,
            "hotkey_helper_available": True,
            "notes_installed": True,
            "stable_chrome_installed": True,
        },
        "checks": [
            _preflight_check("recording_region", "ready_to_validate"),
            _preflight_check("recording_discard", "ready_to_validate"),
            _preflight_check("recording_controls", "ready_to_validate"),
            _preflight_check("multi_display", "ready_to_validate"),
            _preflight_check(
                "stable_chrome", "ready_to_validate", manifest_case="stable_chrome_extension_online_retry"
            ),
            _preflight_check("isolated_ax_denied", "manual_setup_required", manifest_case="accessibility_denied"),
            _preflight_check("notes_visible_target", "ready_to_validate", manifest_case="notes"),
            _preflight_check(
                "external_shortcut_conflict_ui", "manual_setup_required", manifest_case="shortcut_validation"
            ),
        ],
    }
    (report_dir / "release-lab-preflight.json").write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _preflight_check(key: str, status: str, *, manifest_case: str | None = None) -> dict[str, JsonValue]:
    return {
        "evidence": f"{key} evidence",
        "key": key,
        "manifest_case": manifest_case or key,
        "next_step": f"Validate {key}",
        "status": status,
    }


def _physical_recording_report(case_key: str) -> dict[str, JsonValue]:
    base: dict[str, JsonValue] = {
        "app_bundle": "dist/WorkRecorder.app",
        "case": case_key,
        "completion_sheet_visible": True,
        "ended_at": "2026-06-02T08:03:10Z",
        "hud_visible": True,
        "opened_via_physical_shortcut": True,
        "privacy_check_no_local_path": True,
        "privacy_check_no_storage_uri": True,
        "recording_boundary_visible": True,
        "region_selection_confirmed": True,
        "session_id": "acs_test",
        "started_at": "2026-06-02T08:03:00Z",
        "trigger_shortcut": "⌃⌥⌘R",
    }
    if case_key == "recording_region":
        base.update(
            {
                "appears_in_recording_library": True,
                "appears_in_screenshot_library": False,
                "completion_final_status": "completed",
                "discard_clicked": False,
                "duration_ms": 3500,
                "event_id": "evt_recording",
                "keyframe_count": 3,
                "save_clicked": True,
                "segment_count": 1,
                "video_artifact_id": "art_video",
                "video_state": "available",
            }
        )
    elif case_key == "recording_discard":
        base.update(
            {
                "appears_in_recording_library": False,
                "appears_in_screenshot_library": False,
                "completed_event_created": False,
                "completion_final_status": "cancelled",
                "discard_clicked": True,
                "save_clicked": False,
                "staged_video_deleted": True,
            }
        )
    elif case_key == "recording_controls":
        base.update(
            {
                "appears_in_recording_library": True,
                "appears_in_screenshot_library": False,
                "completion_final_status": "completed",
                "duration_ms": 5200,
                "event_id": "evt_recording_controls",
                "keyframe_count": 4,
                "manual_mark_keyframe_id": "kf_mark",
                "mark_clicked": True,
                "mark_created_keyframe": True,
                "pause_clicked": True,
                "pause_stopped_capture": True,
                "resume_clicked": True,
                "resume_started_new_segment": True,
                "save_clicked": True,
                "segment_count": 2,
                "video_artifact_id": "art_video_controls",
                "video_state": "available",
            }
        )
    return base


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
    if case_key == "recording_region":
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
    if case_key == "recording_discard":
        return [
            *common,
            "--discard-clicked",
            "--completion-final-status",
            "cancelled",
            "--staged-video-deleted",
        ]
    return [
        *common,
        "--pause-clicked",
        "--resume-clicked",
        "--mark-clicked",
        "--pause-stopped-capture",
        "--resume-started-new-segment",
        "--mark-created-keyframe",
        "--save-clicked",
        "--completion-final-status",
        "completed",
        "--video-state",
        "available",
        "--appears-in-recording-library",
        "--event-id",
        "evt_recording_controls",
        "--video-artifact-id",
        "art_video_controls",
        "--manual-mark-keyframe-id",
        "kf_mark",
        "--duration-ms",
        "5200",
        "--segment-count",
        "2",
        "--keyframe-count",
        "4",
    ]
