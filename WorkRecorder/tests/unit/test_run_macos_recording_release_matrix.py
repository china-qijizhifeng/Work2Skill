from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import cast

import pytest

from scripts.macos_recording_release_manifest_inputs import prepare_manifest_validation_inputs
from scripts.macos_recording_release_matrix_support import JsonValue, _redact_file, _redact_text, _sanitize_json
from scripts.run_macos_recording_release_matrix import (
    BuildIdentity,
    MatrixStepKey,
    ReleaseMatrixReport,
    StepResult,
    StepStatus,
    _allow_blockers_exit_success,
    _blockers_from_findings,
    _command_specs,
    _report_payload,
    _should_skip_spec,
    _skipped_steps,
    _strict_release_passed,
)


class _Finding:
    def __init__(self, *, severity: str, case_key: str, message: str) -> None:
        self.severity = severity
        self.case_key = case_key
        self.message = message


def test_matrix_plan_keeps_all_release_gates_even_when_flags_skip_execution(tmp_path: Path) -> None:
    args = Namespace(
        skip_package=True,
        skip_swift=True,
        skip_python=True,
        skip_snapshots=True,
        skip_quality_audit=True,
        manifest=tmp_path / "manifest.json",
    )

    specs = _command_specs(args=args, output_dir=tmp_path)
    keys = {spec.key for spec in specs}

    assert keys == {
        MatrixStepKey.PACKAGE_APP,
        MatrixStepKey.SWIFT_TESTS,
        MatrixStepKey.RECORDING_UI_SNAPSHOTS,
        MatrixStepKey.RECORDING_UI_SNAPSHOT_VERIFY,
        MatrixStepKey.WORKBENCH_SNAPSHOTS,
        MatrixStepKey.WORKBENCH_SNAPSHOT_VERIFY,
        MatrixStepKey.SWIFT_QUALITY_AUDIT,
        MatrixStepKey.PYTHON_QUALITY_GATE,
    }
    assert all(_should_skip_spec(spec, args=args) for spec in specs)


def test_matrix_plan_contains_full_automated_release_gates(tmp_path: Path) -> None:
    args = Namespace(
        skip_package=False,
        skip_swift=False,
        skip_python=False,
        skip_snapshots=False,
        skip_quality_audit=False,
        manifest=tmp_path / "manifest.json",
    )

    specs = _command_specs(args=args, output_dir=tmp_path)
    keys = {spec.key for spec in specs}

    assert MatrixStepKey.PACKAGE_APP in keys
    assert MatrixStepKey.SWIFT_TESTS in keys
    assert MatrixStepKey.RECORDING_UI_SNAPSHOTS in keys
    assert MatrixStepKey.RECORDING_UI_SNAPSHOT_VERIFY in keys
    assert MatrixStepKey.WORKBENCH_SNAPSHOT_VERIFY in keys
    assert MatrixStepKey.SWIFT_QUALITY_AUDIT in keys
    assert MatrixStepKey.PYTHON_QUALITY_GATE in keys


def test_skipped_steps_preserve_step_identity() -> None:
    args = Namespace(
        skip_package=True,
        skip_swift=True,
        skip_python=True,
        skip_snapshots=True,
        skip_quality_audit=True,
        manifest=Path("manifest.json"),
    )
    specs = _command_specs(args=args, output_dir=Path(".qa/release"))

    steps = _skipped_steps(specs, duration=0.0)

    assert {step.key for step in steps} == {spec.key for spec in specs}
    assert all(step.status is StepStatus.SKIPPED for step in steps)
    assert not _strict_release_passed(steps=steps, blockers=())
    assert not _allow_blockers_exit_success(steps=steps, blockers=("physical blocker",))


def test_allow_blockers_exit_only_tolerates_strict_manifest_failure() -> None:
    steps = (
        StepResult(
            key=MatrixStepKey.PACKAGE_APP,
            label="Package",
            status=StepStatus.PASSED,
            exit_code=0,
            duration_seconds=1.0,
            log="commands/package.log",
        ),
        StepResult(
            key=MatrixStepKey.MANIFEST_VERIFY,
            label="Manifest",
            status=StepStatus.PASSED,
            exit_code=0,
            duration_seconds=1.0,
            log="manifest-verify.json",
        ),
        StepResult(
            key=MatrixStepKey.MANIFEST_STRICT_VERIFY,
            label="Strict",
            status=StepStatus.FAILED,
            exit_code=1,
            duration_seconds=1.0,
            log="manifest-strict-verify.json",
        ),
    )
    failed_automation = (
        StepResult(
            key=MatrixStepKey.PACKAGE_APP,
            label="Package",
            status=StepStatus.FAILED,
            exit_code=1,
            duration_seconds=1.0,
            log="commands/package.log",
        ),
        *steps[1:],
    )

    assert _allow_blockers_exit_success(steps=steps, blockers=("physical blocker",))
    assert not _allow_blockers_exit_success(steps=steps, blockers=())
    assert not _allow_blockers_exit_success(steps=failed_automation, blockers=("physical blocker",))


def test_redaction_removes_home_and_runtime_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/Users/example")))
    raw = "/Users/example/.workrecorder token=workrecorder_native_abcdefghijklmnopqrstuvwxyz123456 Bearer abc.def"

    redacted = _redact_text(raw)

    assert "/Users/example" not in redacted
    assert "workrecorder_native_" not in redacted
    assert "Bearer abc.def" not in redacted
    assert "[REDACTED]" in redacted


@pytest.mark.parametrize("prefix", ["workrecorder_", "workrecorder_provider_", "saved_native_"])
def test_redaction_handles_current_and_preexisting_credential_prefixes(prefix: str) -> None:
    secret = prefix + "abcdefghijklmnopqrstuvwxyz123456"

    assert _redact_text(secret) == "[REDACTED]"


def test_blockers_include_strict_errors_and_manual_setup_rows() -> None:
    findings = [
        _Finding(severity="warning", case_key="recording_region", message="known caveat"),
        _Finding(severity="error", case_key="recording_controls", message="not verified"),
    ]
    preflight = cast(
        dict[str, JsonValue],
        {
            "checks": [
                {
                    "key": "recording_controls",
                    "status": "ready_to_validate",
                    "next_step": "Run physical controls report.",
                },
                {
                    "key": "multi_display",
                    "status": "blocked",
                    "next_step": "Attach a second physical display.",
                },
                {
                    "key": "isolated_ax_denied",
                    "status": "manual_setup_required",
                    "next_step": "Use isolated TCC fixture.",
                },
            ]
        },
    )

    blockers = _blockers_from_findings(findings, preflight)

    assert blockers == [
        "recording_controls: not verified",
        "multi_display: Attach a second physical display.",
        "isolated_ax_denied: Use isolated TCC fixture.",
    ]


def test_report_payload_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/Users/example")))
    report = ReleaseMatrixReport(
        generated_at="2026-06-06T00:00:00+00:00",
        repo_root="/Users/example/Desktop/projects/workrecorder",
        manifest="/Users/example/Desktop/projects/workrecorder/.qa/manifest.json",
        build=BuildIdentity(
            git_sha="abc123",
            git_status="?? /Users/example/Desktop/projects/workrecorder/secret",
            app_bundle="/Users/example/Desktop/projects/workrecorder/dist/WorkRecorder.app",
            app_bundle_exists=True,
            app_bundle_mtime="2026-06-06T00:00:00+00:00",
        ),
        steps=(
            StepResult(
                key=MatrixStepKey.PACKAGE_APP,
                label="Package",
                status=StepStatus.PASSED,
                exit_code=0,
                duration_seconds=1.0,
                log="commands/package.log",
            ),
        ),
        release_lab_preflight={"token": "workrecorder_abcdefghijklmnopqrstuvwxyz1234567890"},
        manifest_findings=(),
        strict_manifest_findings=(),
        blockers=(),
        strict_release_passed=True,
    )

    payload = _report_payload(report)

    serialized = str(payload)
    assert "/Users/example" not in serialized
    assert "workrecorder_abcdefghijklmnopqrstuvwxyz1234567890" not in serialized


def test_sanitize_json_redacts_uri_key_values() -> None:
    payload = cast(
        dict[str, JsonValue],
        {
            "storage_uri": "local-artifact://recordings/raw.mp4",
            "source_url": "file:///Users/example/Desktop/private.mov",
            "display_label": "保存按钮",
        },
    )

    sanitized = _sanitize_json(payload)

    assert sanitized == {
        "storage_uri": "[REDACTED_URI]",
        "source_url": "[REDACTED_URI]",
        "display_label": "保存按钮",
    }


def test_prepare_manifest_inputs_strip_raw_screenshots_and_refresh_preflight_text(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "out"
    source_dir.mkdir()
    (source_dir / "notes-report.json").write_text("{}", encoding="utf-8")
    (source_dir / "notes-raw.png").write_bytes(b"raw image bytes")
    manifest = cast(
        dict[str, JsonValue],
        {
            "manual_cases": {
                "notes": {
                    "status": "not_verified_no_visible_target",
                    "report": "notes-report.json",
                    "raw_screenshot": "notes-raw.png",
                },
                "multi_display": {
                    "status": "not_verified_requires_physical_display_matrix",
                    "evidence": "Current release-lab preflight detected 3 displays and marks this case ready_to_validate.",
                },
            },
            "open_risks": [
                "Current release-lab preflight detected 3 displays and marks multi-display ready_to_validate."
            ],
            "quality_gates": {},
        },
    )
    preflight = cast(
        dict[str, JsonValue],
        {
            "environment": {"display_count": 1},
            "checks": [{"key": "multi_display", "status": "blocked"}],
        },
    )

    draft, _ = prepare_manifest_validation_inputs(
        manifest=manifest,
        manifest_path=source_dir / "manifest.json",
        release_lab_payload=preflight,
        output_dir=output_dir,
    )

    notes = cast(dict[str, JsonValue], cast(dict[str, JsonValue], draft["manual_cases"])["notes"])
    multi_display = cast(dict[str, JsonValue], cast(dict[str, JsonValue], draft["manual_cases"])["multi_display"])
    assert "raw_screenshot" not in notes
    assert (output_dir / "notes-report.json").exists()
    assert not (output_dir / "notes-raw.png").exists()
    assert "1 display" in str(multi_display["evidence"])
    assert "blocked" in str(multi_display["evidence"])
    assert "3 displays" not in str(draft)


def test_redact_file_sanitizes_json_diagnostics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/Users/example")))
    path = tmp_path / "diagnostic.json"
    path.write_text(
        """
        {
          "fixture_probe": {
            "stdout": "<html><input type=\\"password\\" value=\\"SHOULD_NOT_LEAK_TOKEN\\"></html>"
          },
          "local_user": "example",
          "extension_path": "/usr/local/.OCular/private"
        }
        """,
        encoding="utf-8",
    )

    _redact_file(path)

    redacted = path.read_text(encoding="utf-8")
    assert "SHOULD_NOT_LEAK" not in redacted
    assert "<html>" not in redacted
    assert "password" not in redacted
    assert "example" not in redacted
    assert "/usr/local/.OCular" not in redacted
