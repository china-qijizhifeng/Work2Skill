"""Preflight the environment needed for the strict macOS app E2E matrix."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Mapping, Sequence, cast

from scripts.verify_macos_app_e2e_manifest import (
    DEFAULT_MANIFEST,
    PASS_STATUSES,
    JsonObject,
    JsonValue,
    validate_recording_physical_report,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / ".qa" / "reports" / "macos-e2e" / "release-lab-preflight.json"
HOTKEY_HELPER = REPO_ROOT / "scripts" / "macos_hotkey_conflict_helper.swift"
STABLE_CHROME = Path("/Applications/Google Chrome.app")
NOTES_APP = Path("/System/Applications/Notes.app")


class LabRequirementKey(StrEnum):
    """Strict release-lab capability keys."""

    MULTI_DISPLAY = "multi_display"
    RECORDING_REGION = "recording_region"
    RECORDING_DISCARD = "recording_discard"
    RECORDING_CONTROLS = "recording_controls"
    STABLE_CHROME = "stable_chrome"
    ISOLATED_AX_DENIED = "isolated_ax_denied"
    NOTES_VISIBLE_TARGET = "notes_visible_target"
    EXTERNAL_SHORTCUT_CONFLICT_UI = "external_shortcut_conflict_ui"


class LabReadinessStatus(StrEnum):
    """Readiness status for one release-lab prerequisite."""

    PASSED = "passed"
    READY_TO_VALIDATE = "ready_to_validate"
    MANUAL_SETUP_REQUIRED = "manual_setup_required"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class LabEnvironment:
    """Environment facts collected before the release-lab run.

    Attributes:
        display_count: Number of displays reported by system profiler.
        stable_chrome_installed: Whether Stable Google Chrome is installed.
        notes_installed: Whether Apple's Notes app is installed.
        hotkey_helper_available: Whether the external hotkey conflict helper exists.
    """

    display_count: int
    stable_chrome_installed: bool
    notes_installed: bool
    hotkey_helper_available: bool


@dataclass(frozen=True, slots=True)
class LabCheck:
    """One release-lab preflight result.

    Attributes:
        key: Requirement key.
        status: Readiness status.
        manifest_case: Related manifest case key.
        evidence: Short evidence statement.
        next_step: Concrete action needed to move the case forward.
    """

    key: LabRequirementKey
    status: LabReadinessStatus
    manifest_case: str
    evidence: str
    next_step: str


def build_argument_parser() -> argparse.ArgumentParser:
    """Build CLI arguments.

    Returns:
        Configured argument parser for the preflight command.
    """

    parser = argparse.ArgumentParser(description="Check strict macOS app E2E release-lab prerequisites.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--fail-unready",
        action="store_true",
        help="Exit non-zero when any release-lab prerequisite is not passed or ready to validate.",
    )
    return parser


def main() -> int:
    """Run the release-lab preflight.

    Returns:
        Process exit status; ``--fail-unready`` makes blocked/manual setup rows fail.
    """

    args = build_argument_parser().parse_args()
    manifest = _load_manifest(args.manifest)
    environment = collect_environment()
    checks = evaluate_release_lab(manifest=manifest, environment=environment, report_dir=args.manifest.parent)
    payload = {
        "manifest": str(args.manifest),
        "environment": asdict(environment),
        "checks": [_lab_check_payload(check) for check in checks],
    }
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for check in checks:
        print(f"{check.status.value.upper()} [{check.key.value}] {check.evidence}")
        print(f"  next: {check.next_step}")
    if args.fail_unready and any(
        check.status not in {LabReadinessStatus.PASSED, LabReadinessStatus.READY_TO_VALIDATE} for check in checks
    ):
        return 1
    return 0


def collect_environment() -> LabEnvironment:
    """Collect host facts without mutating permissions or user data.

    Returns:
        Release-lab environment facts.
    """

    return LabEnvironment(
        display_count=_display_count(),
        stable_chrome_installed=STABLE_CHROME.exists(),
        notes_installed=NOTES_APP.exists(),
        hotkey_helper_available=HOTKEY_HELPER.exists(),
    )


def evaluate_release_lab(
    *,
    manifest: JsonObject,
    environment: LabEnvironment,
    report_dir: Path | None = None,
) -> tuple[LabCheck, ...]:
    """Evaluate strict matrix prerequisites from manifest state and host facts.

    Args:
        manifest: Parsed E2E run manifest.
        environment: Host capability facts.
        report_dir: Directory used to resolve report references when available.

    Returns:
        Ordered preflight checks.
    """

    return (
        _recording_physical_check(
            manifest=manifest,
            case_key="recording_region",
            key=LabRequirementKey.RECORDING_REGION,
            report_dir=report_dir,
        ),
        _recording_physical_check(
            manifest=manifest,
            case_key="recording_discard",
            key=LabRequirementKey.RECORDING_DISCARD,
            report_dir=report_dir,
        ),
        _recording_physical_check(
            manifest=manifest,
            case_key="recording_controls",
            key=LabRequirementKey.RECORDING_CONTROLS,
            report_dir=report_dir,
        ),
        _multi_display_check(manifest=manifest, environment=environment),
        _stable_chrome_check(manifest=manifest, environment=environment),
        _isolated_ax_check(manifest=manifest),
        _notes_check(manifest=manifest, environment=environment),
        _external_shortcut_check(manifest=manifest, environment=environment),
    )


def _recording_physical_check(
    *,
    manifest: JsonObject,
    case_key: str,
    key: LabRequirementKey,
    report_dir: Path | None,
) -> LabCheck:
    case = _case(manifest, case_key)
    status = case.get("status")
    if isinstance(status, str) and status in PASS_STATUSES:
        report = case.get("report")
        if report_dir is None:
            return _passed(key, case_key, f"{case_key} is already passed in manifest")
        if not isinstance(report, str) or not report:
            return LabCheck(
                key=key,
                status=LabReadinessStatus.MANUAL_SETUP_REQUIRED,
                manifest_case=case_key,
                evidence=f"{case_key} is marked passed but has no physical report reference",
                next_step=(
                    "Create a physical recording report with scripts/create_macos_recording_physical_report.py, "
                    "validate it, then attach it to the manifest."
                ),
            )
        report_path = _resolve_report_ref(report_dir=report_dir, raw_path=report)
        if report_path is None or not report_path.exists():
            return LabCheck(
                key=key,
                status=LabReadinessStatus.MANUAL_SETUP_REQUIRED,
                manifest_case=case_key,
                evidence=f"{case_key} report is missing or outside report directory: {report}",
                next_step="Restore the physical recording report artifact, then rerun the release-lab preflight.",
            )
        findings = validate_recording_physical_report(case_key=case_key, path=report_path)
        errors = [finding.message for finding in findings if finding.severity == "error"]
        if errors:
            return LabCheck(
                key=key,
                status=LabReadinessStatus.MANUAL_SETUP_REQUIRED,
                manifest_case=case_key,
                evidence=f"{case_key} physical report is invalid: {errors[0]}",
                next_step=(
                    "Fix the physical recording report or rerun the real "
                    "⌃⌥⌘R release-lab case before claiming strict release readiness."
                ),
            )
        return _passed(key, case_key, f"{case_key} physical report is valid")
    return LabCheck(
        key=key,
        status=LabReadinessStatus.READY_TO_VALIDATE,
        manifest_case=case_key,
        evidence=f"{case_key} is not yet backed by a physical ⌃⌥⌘R report",
        next_step=(
            "Run the real dist/WorkRecorder.app shortcut flow, create the report with "
            "scripts/create_macos_recording_physical_report.py, validate it with "
            "scripts/validate_macos_recording_physical_report.py, then update this manifest row."
        ),
    )


def _multi_display_check(*, manifest: JsonObject, environment: LabEnvironment) -> LabCheck:
    case = "multi_display"
    if _case_passed(manifest, case):
        return _passed(LabRequirementKey.MULTI_DISPLAY, case, "multi-display case is already passed in manifest")
    if environment.display_count >= 2:
        return LabCheck(
            key=LabRequirementKey.MULTI_DISPLAY,
            status=LabReadinessStatus.READY_TO_VALIDATE,
            manifest_case=case,
            evidence=f"{environment.display_count} displays detected",
            next_step="Run the current-window and region cases on negative-coordinate and mixed-Retina displays.",
        )
    return LabCheck(
        key=LabRequirementKey.MULTI_DISPLAY,
        status=LabReadinessStatus.BLOCKED,
        manifest_case=case,
        evidence=f"only {environment.display_count} display detected",
        next_step="Attach a second physical display before running the strict matrix.",
    )


def _stable_chrome_check(*, manifest: JsonObject, environment: LabEnvironment) -> LabCheck:
    case = "stable_chrome_extension_online_retry"
    if _stable_chrome_case_passed(manifest, case):
        return _passed(LabRequirementKey.STABLE_CHROME, case, "Stable Chrome extension case is already passed")
    if environment.stable_chrome_installed:
        return LabCheck(
            key=LabRequirementKey.STABLE_CHROME,
            status=LabReadinessStatus.READY_TO_VALIDATE,
            manifest_case=case,
            evidence=f"{STABLE_CHROME} exists",
            next_step="Rerun the Stable Chrome unpacked-extension diagnostics in a clean Chrome profile/policy lab.",
        )
    return LabCheck(
        key=LabRequirementKey.STABLE_CHROME,
        status=LabReadinessStatus.BLOCKED,
        manifest_case=case,
        evidence=f"{STABLE_CHROME} is missing",
        next_step="Install Stable Google Chrome before validating the Stable Chrome provider path.",
    )


def _isolated_ax_check(*, manifest: JsonObject) -> LabCheck:
    case = "accessibility_denied"
    if _case_passed(manifest, case):
        return _passed(LabRequirementKey.ISOLATED_AX_DENIED, case, "AX-denied case is already passed")
    return LabCheck(
        key=LabRequirementKey.ISOLATED_AX_DENIED,
        status=LabReadinessStatus.MANUAL_SETUP_REQUIRED,
        manifest_case=case,
        evidence="AX-denied while Screen Recording remains granted cannot be proven from the current user state",
        next_step="Use an isolated QA user or TCC fixture with Screen Recording granted and Accessibility denied.",
    )


def _notes_check(*, manifest: JsonObject, environment: LabEnvironment) -> LabCheck:
    case = "notes"
    if _case_passed(manifest, case):
        return _passed(LabRequirementKey.NOTES_VISIBLE_TARGET, case, "Notes case is already passed")
    if environment.notes_installed:
        return LabCheck(
            key=LabRequirementKey.NOTES_VISIBLE_TARGET,
            status=LabReadinessStatus.READY_TO_VALIDATE,
            manifest_case=case,
            evidence=f"{NOTES_APP} exists",
            next_step="Run Notes in a clean desktop state with no modal dialogs and a stable visible note window.",
        )
    return LabCheck(
        key=LabRequirementKey.NOTES_VISIBLE_TARGET,
        status=LabReadinessStatus.BLOCKED,
        manifest_case=case,
        evidence=f"{NOTES_APP} is missing",
        next_step="Install or restore Apple's Notes app before validating Notes current-window capture.",
    )


def _external_shortcut_check(*, manifest: JsonObject, environment: LabEnvironment) -> LabCheck:
    case = "shortcut_validation"
    if _external_shortcut_ui_passed(manifest):
        return _passed(LabRequirementKey.EXTERNAL_SHORTCUT_CONFLICT_UI, case, "external conflict UI is already passed")
    shortcut_case = _case(manifest, case)
    external_helper_ui = shortcut_case.get("external_helper_ui")
    if isinstance(external_helper_ui, str) and external_helper_ui:
        return LabCheck(
            key=LabRequirementKey.EXTERNAL_SHORTCUT_CONFLICT_UI,
            status=LabReadinessStatus.MANUAL_SETUP_REQUIRED,
            manifest_case=case,
            evidence=f"manifest records external_helper_ui={external_helper_ui!r}, not 'passed'",
            next_step=(
                "Find a reliable release-lab way to make Workbench itself report an external shortcut conflict, "
                "then update shortcut_validation.external_helper_ui to 'passed' with evidence."
            ),
        )
    if environment.hotkey_helper_available:
        return LabCheck(
            key=LabRequirementKey.EXTERNAL_SHORTCUT_CONFLICT_UI,
            status=LabReadinessStatus.READY_TO_VALIDATE,
            manifest_case=case,
            evidence=f"{HOTKEY_HELPER.relative_to(REPO_ROOT)} exists",
            next_step=(
                "Use the helper as a diagnostic only, then verify Workbench itself shows the external-conflict state. "
                "On some macOS versions a separate process can hold the same Carbon chord without forcing "
                "RegisterEventHotKey to fail, so do not mark this passed from helper output alone."
            ),
        )
    return LabCheck(
        key=LabRequirementKey.EXTERNAL_SHORTCUT_CONFLICT_UI,
        status=LabReadinessStatus.BLOCKED,
        manifest_case=case,
        evidence="external hotkey conflict helper is missing",
        next_step="Add or restore scripts/macos_hotkey_conflict_helper.swift before release-lab validation.",
    )


def _passed(key: LabRequirementKey, case: str, evidence: str) -> LabCheck:
    return LabCheck(
        key=key,
        status=LabReadinessStatus.PASSED,
        manifest_case=case,
        evidence=evidence,
        next_step="No action required unless the matrix is rerun.",
    )


def _case_passed(manifest: JsonObject, case_key: str) -> bool:
    case = _case(manifest, case_key)
    status = case.get("status")
    return isinstance(status, str) and status in PASS_STATUSES


def _stable_chrome_case_passed(manifest: JsonObject, case_key: str) -> bool:
    case = _case(manifest, case_key)
    status = case.get("status")
    browser = case.get("browser")
    return status == "passed" and browser == "stable_chrome"


def _external_shortcut_ui_passed(manifest: JsonObject) -> bool:
    shortcut_case = _case(manifest, "shortcut_validation")
    if _case_passed(manifest, "external_shortcut_conflict_ui"):
        return True
    return _case_passed(manifest, "shortcut_validation") and shortcut_case.get("external_helper_ui") == "passed"


def _case(manifest: JsonObject, case_key: str) -> JsonObject:
    manual_cases = _mapping(manifest.get("manual_cases"))
    return _mapping(manual_cases.get(case_key))


def _display_count() -> int:
    completed = subprocess.run(
        ["system_profiler", "SPDisplaysDataType", "-json"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return 0
    payload = json.loads(completed.stdout)
    if not isinstance(payload, Mapping):
        return 0
    displays = 0
    for gpu in _json_list(payload.get("SPDisplaysDataType")):
        displays += len(_json_list(gpu.get("spdisplays_ndrvs") if isinstance(gpu, Mapping) else None))
    return displays


def _load_manifest(path: Path) -> JsonObject:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise SystemExit("manifest root must be a JSON object")
    return cast(JsonObject, payload)


def _mapping(value: object) -> JsonObject:
    return cast(JsonObject, value) if isinstance(value, Mapping) else {}


def _json_list(value: object) -> tuple[JsonObject, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(cast(JsonObject, item) for item in value if isinstance(item, Mapping))


def _resolve_report_ref(*, report_dir: Path, raw_path: str) -> Path | None:
    root = report_dir.resolve()
    raw = Path(raw_path)
    candidate = raw if raw.is_absolute() else root / raw
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        return None
    return resolved


def _lab_check_payload(check: LabCheck) -> dict[str, str]:
    payload = asdict(check)
    payload["key"] = check.key.value
    payload["status"] = check.status.value
    return cast(dict[str, str], payload)


if __name__ == "__main__":
    raise SystemExit(main())
