"""Run the macOS recording release matrix without faking physical evidence.

This runner is the release orchestration layer for the recording UX. It runs
the gates that can be reproduced from CI/local automation, gathers release-lab
readiness, validates physical recording reports already attached to the
manifest, and writes a single timestamped evidence directory.

It deliberately does not mark physical cases as passed. Rows such as real
``⌃⌥⌘R`` recording controls, multi-display, isolated TCC, and external hotkey
conflicts must still be proven by their dedicated report helpers.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Mapping, Sequence, cast

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.macos_recording_release_manifest_inputs import (
    prepare_manifest_validation_inputs,
    write_release_lab_preflight,
)
from scripts.macos_recording_release_matrix_support import (
    JsonValue,
    _dedupe_strings,
    _display_command,
    _display_path,
    _redact_file,
    _redact_release_artifacts,
    _redact_text,
    _sanitize_json,
    _write_json,
)
from scripts.verify_macos_app_e2e_manifest import (
    DEFAULT_MANIFEST,
    JsonObject,
    validate_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_ROOT = REPO_ROOT / ".qa" / "reports" / "macos-e2e"
DEFAULT_WORKBENCH_ROOT = REPO_ROOT / ".qa" / "workbench"
DEFAULT_RECORDING_UI_ROOT = REPO_ROOT / ".qa" / "recording-ui"
APP_BUNDLE = REPO_ROOT / "dist" / "WorkRecorder.app"


class MatrixStepKey(StrEnum):
    """Stable identifiers for automated release-matrix steps."""

    PACKAGE_APP = "package_app"
    SWIFT_TESTS = "swift_tests"
    RECORDING_UI_SNAPSHOTS = "recording_ui_snapshots"
    RECORDING_UI_SNAPSHOT_VERIFY = "recording_ui_snapshot_verify"
    WORKBENCH_SNAPSHOTS = "workbench_snapshots"
    WORKBENCH_SNAPSHOT_VERIFY = "workbench_snapshot_verify"
    SWIFT_QUALITY_AUDIT = "swift_quality_audit"
    PYTHON_QUALITY_GATE = "python_quality_gate"
    RELEASE_LAB_PREFLIGHT = "release_lab_preflight"
    MANIFEST_VERIFY = "manifest_verify"
    MANIFEST_STRICT_VERIFY = "manifest_strict_verify"


class StepStatus(StrEnum):
    """Execution status for one matrix step."""

    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """One subprocess step in the release matrix.

    Attributes:
        key: Stable step identifier.
        label: Human-readable label for reports.
        command: Command vector executed by ``subprocess``.
        cwd: Working directory for the command.
        env: Extra environment variables merged into the inherited environment.
    """

    key: MatrixStepKey
    label: str
    command: tuple[str, ...]
    cwd: Path = REPO_ROOT
    env: Mapping[str, str] | None = None


@dataclass(frozen=True, slots=True)
class StepResult:
    """Sanitized execution result for one release matrix step.

    Attributes:
        key: Stable step identifier.
        label: Human-readable label for reports.
        status: Passed, failed, or skipped.
        exit_code: Process exit code, or ``None`` for skipped steps.
        duration_seconds: Wall-clock duration for the step.
        log: Relative command log path inside the evidence directory.
    """

    key: MatrixStepKey
    label: str
    status: StepStatus
    exit_code: int | None
    duration_seconds: float
    log: str | None


@dataclass(frozen=True, slots=True)
class BuildIdentity:
    """Build identity captured for the release report.

    Attributes:
        git_sha: Current repository commit SHA.
        git_status: Redacted short git status.
        app_bundle: Redacted path to the tested app bundle.
        app_bundle_exists: Whether the bundle exists after packaging.
        app_bundle_mtime: Last modification time for the bundle when present.
    """

    git_sha: str
    git_status: str
    app_bundle: str
    app_bundle_exists: bool
    app_bundle_mtime: str | None


@dataclass(frozen=True, slots=True)
class ReleaseMatrixReport:
    """Top-level JSON report written by the matrix runner.

    Attributes:
        generated_at: ISO timestamp for this matrix run.
        repo_root: Redacted repository root.
        manifest: Redacted manifest path.
        build: Build identity for the tested app.
        steps: Automated gate results.
        release_lab_preflight: Host readiness and physical-evidence status.
        manifest_findings: Non-strict manifest findings.
        strict_manifest_findings: Strict release manifest findings.
        blockers: Deduplicated release blockers.
        strict_release_passed: Whether automated gates and strict manifest both passed.
    """

    generated_at: str
    repo_root: str
    manifest: str
    build: BuildIdentity
    steps: tuple[StepResult, ...]
    release_lab_preflight: JsonValue | None
    manifest_findings: tuple[dict[str, JsonValue], ...]
    strict_manifest_findings: tuple[dict[str, JsonValue], ...]
    blockers: tuple[str, ...]
    strict_release_passed: bool


def build_argument_parser() -> argparse.ArgumentParser:
    """Build CLI parser for the recording release matrix runner.

    Returns:
        Configured argument parser.
    """

    parser = argparse.ArgumentParser(description="Run the WorkRecorder recording release matrix.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_REPORT_ROOT)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--skip-package", action="store_true")
    parser.add_argument("--skip-swift", action="store_true")
    parser.add_argument("--skip-python", action="store_true")
    parser.add_argument("--skip-snapshots", action="store_true")
    parser.add_argument("--skip-quality-audit", action="store_true")
    parser.add_argument(
        "--strict-release",
        action="store_true",
        help="Compatibility flag; strict exit is the default unless --allow-blockers is set.",
    )
    parser.add_argument(
        "--allow-blockers",
        action="store_true",
        help="Write evidence and exit zero even while strict release blockers remain.",
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Stop automated gates after the first failed subprocess.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write the command plan and current blockers without running subprocesses.",
    )
    return parser


def main() -> int:
    """Run the release matrix and return a process status.

    Returns:
        Zero only when strict release passes, unless ``--allow-blockers`` is
        explicitly set for evidence collection on a non-release workstation.
    """

    args = build_argument_parser().parse_args()
    output_dir = _matrix_output_dir(output_root=args.output_root, run_id=args.run_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    command_dir = output_dir / "commands"
    command_dir.mkdir(parents=True, exist_ok=True)

    command_specs = _command_specs(args=args, output_dir=output_dir)
    steps = _run_automation_steps(args=args, command_specs=command_specs, command_dir=command_dir)

    manifest = _load_manifest(args.manifest)
    release_lab_payload = write_release_lab_preflight(
        manifest=manifest,
        manifest_path=args.manifest,
        output_dir=output_dir,
    )
    validation_manifest, validation_report_dir = prepare_manifest_validation_inputs(
        manifest=manifest,
        manifest_path=args.manifest,
        release_lab_payload=release_lab_payload,
        output_dir=output_dir,
    )
    manifest_started = time.monotonic()
    manifest_findings = validate_manifest(
        manifest=validation_manifest,
        strict_release=False,
        report_dir=validation_report_dir,
    )
    manifest_duration = round(time.monotonic() - manifest_started, 3)
    _write_manifest_verifier_payload(
        output_dir / "manifest-verify.json",
        manifest_path=output_dir / "run-manifest-draft.json",
        findings=manifest_findings,
        strict_release=False,
    )
    steps.append(
        _manifest_step_result(
            key=MatrixStepKey.MANIFEST_VERIFY,
            label="Manifest verifier",
            findings=manifest_findings,
            duration_seconds=manifest_duration,
            artifact="manifest-verify.json",
        )
    )
    strict_started = time.monotonic()
    strict_findings = validate_manifest(
        manifest=validation_manifest,
        strict_release=True,
        report_dir=validation_report_dir,
    )
    strict_duration = round(time.monotonic() - strict_started, 3)
    _write_manifest_verifier_payload(
        output_dir / "manifest-strict-verify.json",
        manifest_path=output_dir / "run-manifest-draft.json",
        findings=strict_findings,
        strict_release=True,
    )
    steps.append(
        _manifest_step_result(
            key=MatrixStepKey.MANIFEST_STRICT_VERIFY,
            label="Strict release manifest verifier",
            findings=strict_findings,
            duration_seconds=strict_duration,
            artifact="manifest-strict-verify.json",
        )
    )
    blockers = _blockers_from_findings(strict_findings, release_lab_payload)
    report = ReleaseMatrixReport(
        generated_at=_now_iso(),
        repo_root=str(REPO_ROOT),
        manifest=str(args.manifest),
        build=_build_identity(),
        steps=tuple(steps),
        release_lab_preflight=cast(JsonValue, release_lab_payload),
        manifest_findings=tuple(_finding_payload(finding) for finding in manifest_findings),
        strict_manifest_findings=tuple(_finding_payload(finding) for finding in strict_findings),
        blockers=tuple(blockers),
        strict_release_passed=_strict_release_passed(steps=steps, blockers=blockers),
    )
    _write_json(output_dir / "summary.json", _report_payload(report))
    _write_review(output_dir=output_dir, report=report)
    _redact_release_artifacts(output_dir)
    print(f"Recording release matrix report: {output_dir}")
    if report.strict_release_passed:
        print("Strict release matrix passed.")
        return 0
    print("Strict release matrix has blockers. See review.md and summary.json.", file=sys.stderr)
    if args.allow_blockers and _allow_blockers_exit_success(steps=steps, blockers=blockers):
        return 0
    return 1


def _run_automation_steps(
    *,
    args: argparse.Namespace,
    command_specs: Sequence[CommandSpec],
    command_dir: Path,
) -> list[StepResult]:
    steps: list[StepResult] = []
    if args.dry_run:
        return _skipped_steps(command_specs, duration=0.0)
    for index, spec in enumerate(command_specs):
        if _should_skip_spec(spec, args=args):
            steps.append(_skipped_step(spec, duration=0.0))
            continue
        result = _run_command(spec=spec, command_dir=command_dir)
        steps.append(result)
        if args.stop_on_failure and result.status is StepStatus.FAILED:
            remaining = command_specs[index + 1 :]
            steps.extend(_skipped_steps(remaining, duration=0.0))
            break
    return steps


def _command_specs(*, args: argparse.Namespace, output_dir: Path) -> tuple[CommandSpec, ...]:
    specs: list[CommandSpec] = []
    swift_package = REPO_ROOT / "apps" / "macos_capture"
    specs.append(
        CommandSpec(
            key=MatrixStepKey.PACKAGE_APP,
            label="Build and verify dist/WorkRecorder.app",
            command=(sys.executable, "scripts/package_workrecorder_app.py", "--dev", "--verify"),
        )
    )
    specs.append(
        CommandSpec(
            key=MatrixStepKey.SWIFT_TESTS,
            label="Swift unit and integration tests",
            command=("swift", "test"),
            cwd=swift_package,
        )
    )
    specs.extend(
        (
            CommandSpec(
                key=MatrixStepKey.RECORDING_UI_SNAPSHOTS,
                label="Recording UI state snapshots",
                command=("swift", "test", "--filter", "RecordingUISnapshotTests"),
                cwd=swift_package,
                env={"WORKRECORDER_WRITE_RECORDING_UI_SNAPSHOTS": "1"},
            ),
            CommandSpec(
                key=MatrixStepKey.RECORDING_UI_SNAPSHOT_VERIFY,
                label="Recording UI snapshot visual verifier",
                command=(
                    sys.executable,
                    "-m",
                    "scripts.verify_recording_ui_snapshots",
                    "--root",
                    str(DEFAULT_RECORDING_UI_ROOT),
                    "--json",
                    str(output_dir / "recording-ui-snapshot-facts.json"),
                ),
            ),
            CommandSpec(
                key=MatrixStepKey.WORKBENCH_SNAPSHOTS,
                label="Workbench recording and large-review snapshots",
                command=(
                    "swift",
                    "test",
                    "--filter",
                    (
                        "WorkbenchRuntimeTests/workbenchSnapshotsRenderPrimaryPages|"
                        "WorkbenchRuntimeTests/"
                        "recordingReviewWindowSnapshotsCoverLargeReviewScenarios|"
                        "WorkbenchRuntimeTests/"
                        "recordingReviewWindowLoadedPlaybackSnapshotUsesLargeReviewRoute"
                    ),
                ),
                cwd=swift_package,
                env={"WORKRECORDER_WRITE_WORKBENCH_SNAPSHOTS": "1"},
            ),
            CommandSpec(
                key=MatrixStepKey.WORKBENCH_SNAPSHOT_VERIFY,
                label="Workbench snapshot visual verifier",
                command=(
                    sys.executable,
                    "-m",
                    "scripts.verify_workbench_snapshots",
                    "--root",
                    str(DEFAULT_WORKBENCH_ROOT),
                    "--json",
                    str(output_dir / "workbench-snapshot-facts.json"),
                ),
            ),
        )
    )
    specs.append(
        CommandSpec(
            key=MatrixStepKey.SWIFT_QUALITY_AUDIT,
            label="Swift quality audit",
            command=(
                sys.executable,
                "-m",
                "scripts.audit_swift_quality",
                "--root",
                "apps/macos_capture",
                "--max-file-lines",
                "700",
                "--max-type-lines",
                "450",
                "--max-function-lines",
                "120",
                "--json-output",
                str(output_dir / "swift-quality.json"),
            ),
        )
    )
    specs.append(
        CommandSpec(
            key=MatrixStepKey.PYTHON_QUALITY_GATE,
            label="Python quality gate without Swift duplicate",
            command=(sys.executable, "scripts/quality_gate.py", "--skip-swift", "--report-dir", str(output_dir)),
        )
    )
    return tuple(specs)


def _should_skip_spec(spec: CommandSpec, *, args: argparse.Namespace) -> bool:
    if spec.key is MatrixStepKey.PACKAGE_APP:
        return bool(args.skip_package)
    if spec.key is MatrixStepKey.SWIFT_TESTS:
        return bool(args.skip_swift)
    if spec.key in {
        MatrixStepKey.RECORDING_UI_SNAPSHOTS,
        MatrixStepKey.RECORDING_UI_SNAPSHOT_VERIFY,
        MatrixStepKey.WORKBENCH_SNAPSHOTS,
        MatrixStepKey.WORKBENCH_SNAPSHOT_VERIFY,
    }:
        return bool(args.skip_snapshots)
    if spec.key is MatrixStepKey.SWIFT_QUALITY_AUDIT:
        return bool(args.skip_quality_audit)
    if spec.key is MatrixStepKey.PYTHON_QUALITY_GATE:
        return bool(args.skip_python)
    return False


def _run_command(*, spec: CommandSpec, command_dir: Path) -> StepResult:
    started = time.monotonic()
    log_path = command_dir / f"{spec.key.value}.log"
    env = os.environ.copy()
    if spec.env:
        env.update(spec.env)
    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(f"$ {_display_command(spec.command)}\n")
        log_file.write(f"cwd={_display_path(spec.cwd)}\n\n")
        log_file.flush()
        completed = subprocess.run(
            spec.command,
            cwd=spec.cwd,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            check=False,
        )
    _redact_file(log_path)
    duration = round(time.monotonic() - started, 3)
    return StepResult(
        key=spec.key,
        label=spec.label,
        status=StepStatus.PASSED if completed.returncode == 0 else StepStatus.FAILED,
        exit_code=completed.returncode,
        duration_seconds=duration,
        log=str(log_path.relative_to(command_dir.parent)),
    )


def _manifest_step_result(
    *,
    key: MatrixStepKey,
    label: str,
    findings: Sequence[object],
    duration_seconds: float,
    artifact: str,
) -> StepResult:
    errors = [finding for finding in findings if getattr(finding, "severity", "") == "error"]
    return StepResult(
        key=key,
        label=label,
        status=StepStatus.FAILED if errors else StepStatus.PASSED,
        exit_code=1 if errors else 0,
        duration_seconds=duration_seconds,
        log=artifact,
    )


def _write_manifest_verifier_payload(
    path: Path,
    *,
    manifest_path: Path,
    findings: Sequence[object],
    strict_release: bool,
) -> None:
    payload: dict[str, JsonValue] = {
        "manifest": str(manifest_path),
        "ok": not any(getattr(finding, "severity", "") == "error" for finding in findings),
        "strict_release": strict_release,
        "findings": [_finding_payload(finding) for finding in findings],
    }
    _write_json(path, payload)


def _skipped_steps(specs: Sequence[CommandSpec], *, duration: float) -> list[StepResult]:
    return [_skipped_step(spec, duration=duration) for spec in specs]


def _skipped_step(spec: CommandSpec, *, duration: float) -> StepResult:
    return StepResult(
        key=spec.key,
        label=spec.label,
        status=StepStatus.SKIPPED,
        exit_code=None,
        duration_seconds=duration,
        log=None,
    )


def _load_manifest(path: Path) -> JsonObject:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Cannot read manifest {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit(f"Manifest must be a JSON object: {path}")
    return cast(JsonObject, payload)


def _build_identity() -> BuildIdentity:
    status = _git(["status", "--short"])
    mtime = None
    if APP_BUNDLE.exists():
        mtime = datetime.fromtimestamp(APP_BUNDLE.stat().st_mtime, tz=UTC).isoformat()
    return BuildIdentity(
        git_sha=_git(["rev-parse", "HEAD"]).strip(),
        git_status=status.strip(),
        app_bundle=str(APP_BUNDLE),
        app_bundle_exists=APP_BUNDLE.exists(),
        app_bundle_mtime=mtime,
    )


def _git(args: Sequence[str]) -> str:
    completed = subprocess.run(
        ("git", *args),
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return f"git error: {_redact_text(completed.stderr.strip())}"
    return _redact_text(completed.stdout)


def _blockers_from_findings(findings: Sequence[object], preflight: Mapping[str, JsonValue]) -> list[str]:
    blockers = [
        f"{getattr(finding, 'case_key', 'unknown')}: {getattr(finding, 'message', '')}"
        for finding in findings
        if getattr(finding, "severity", "") == "error"
    ]
    checks = preflight.get("checks", [])
    if isinstance(checks, list):
        for raw_check in checks:
            if not isinstance(raw_check, dict):
                continue
            status = raw_check.get("status")
            if status in {"blocked", "manual_setup_required"}:
                blockers.append(
                    f"{raw_check.get('key', 'release_lab')}: {raw_check.get('next_step', 'needs release-lab action')}"
                )
    return _dedupe_strings(blockers)


def _finding_payload(finding: object) -> dict[str, JsonValue]:
    payload = {
        "severity": getattr(finding, "severity", ""),
        "case_key": getattr(finding, "case_key", ""),
        "message": _redact_text(str(getattr(finding, "message", ""))),
    }
    return cast(dict[str, JsonValue], payload)


def _report_payload(report: ReleaseMatrixReport) -> dict[str, JsonValue]:
    payload = asdict(report)
    return cast(dict[str, JsonValue], _sanitize_json(cast(JsonValue, payload)))


def _strict_release_passed(*, steps: Sequence[StepResult], blockers: Sequence[str]) -> bool:
    return not blockers and all(step.status is StepStatus.PASSED for step in steps)


def _allow_blockers_exit_success(*, steps: Sequence[StepResult], blockers: Sequence[str]) -> bool:
    if not blockers:
        return False
    for step in steps:
        if step.key is MatrixStepKey.MANIFEST_STRICT_VERIFY:
            continue
        if step.status is not StepStatus.PASSED:
            return False
    return True


def _write_review(*, output_dir: Path, report: ReleaseMatrixReport) -> None:
    lines = [
        "# WorkRecorder Recording Release Matrix",
        "",
        f"- Generated: `{report.generated_at}`",
        f"- Git SHA: `{report.build.git_sha}`",
        f"- App bundle: `{_redact_text(report.build.app_bundle)}`",
        f"- Strict release passed: `{str(report.strict_release_passed).lower()}`",
        "",
        "## Automated Steps",
        "",
    ]
    for step in report.steps:
        log = f" ({step.log})" if step.log else ""
        lines.append(f"- `{step.key.value}`: `{step.status.value}` exit={step.exit_code}{log}")
    lines.extend(["", "## Release Blockers", ""])
    if report.blockers:
        lines.extend(f"- {blocker}" for blocker in report.blockers)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Physical Evidence Rule",
            "",
            (
                "This runner only records validated evidence. Physical cases must be captured with "
                "`scripts/create_macos_recording_physical_report.py` and validated with "
                "`scripts/validate_macos_recording_physical_report.py`; this file is not a substitute "
                "for real shortcut/HUD/multi-display/TCC observation."
            ),
            "",
        ]
    )
    (output_dir / "review.md").write_text("\n".join(lines), encoding="utf-8")


def _matrix_output_dir(*, output_root: Path, run_id: str) -> Path:
    suffix = run_id.strip() or datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    return output_root / f"recording-release-{suffix}"


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
