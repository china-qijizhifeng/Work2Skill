"""Validate the real-bundle macOS app E2E manifest.

The matrix mixes hard release checks with environment-limited cases that need a
physical lab or a separate TCC state. This verifier keeps those categories
explicit so a report cannot accidentally overclaim release readiness.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Callable, Mapping, Sequence, TypeAlias, cast

from scripts.macos_e2e_manifest_preflight import validate_release_lab_preflight_consistency

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MANIFEST = REPO_ROOT / ".qa" / "reports" / "macos-e2e" / "run-manifest-final-hardening.json"
JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = Mapping[str, JsonValue]


class CaseExpectation(StrEnum):
    """How a case is allowed to finish in this developer-machine manifest."""

    PASS_REQUIRED = "pass_required"
    EXPLICIT_LIMITATION_ALLOWED = "explicit_limitation_allowed"


@dataclass(frozen=True, slots=True)
class RequiredCase:
    """One required E2E case and its allowed status envelope.

    Attributes:
        key: Manifest ``manual_cases`` key for the row.
        expectation: Whether the case must pass or may be explicitly limited.
        accepted_statuses: Status values that are meaningful for this case.
        report_required: Whether the case needs a report/evidence pointer.
        risk_keywords: Keywords expected in ``open_risks`` for limited rows.
    """

    key: str
    expectation: CaseExpectation
    accepted_statuses: frozenset[str]
    report_required: bool = True
    risk_keywords: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ManifestFinding:
    """A manifest validation result.

    Attributes:
        severity: ``error`` blocks the verifier; ``warning`` is explicit risk.
        case_key: Case, gate, or section that produced the finding.
        message: Human-readable explanation for the finding.
    """

    severity: str
    case_key: str
    message: str


@dataclass(frozen=True, slots=True)
class ManifestArtifactRef:
    """A file reference inside one E2E manifest case.

    Attributes:
        field: Manifest field that carried the file reference.
        raw_path: File path string exactly as recorded in the manifest.
    """

    field: str
    raw_path: str


PASS_STATUSES = frozenset(
    {
        "passed",
        "passed_with_chrome_for_testing",
        "passed_no_event",
        "passed_no_side_effects",
        "passed_permission_prompt_no_event",
        "passed_automated_and_real_bundle_smoke",
        "passed_internal_shortcut_validation",
    }
)

LIMITATION_STATUSES = frozenset(
    {
        "failed_environment_extension_not_registered",
        "not_available_on_machine",
        "not_verified_requires_physical_display_matrix",
        "not_verified_no_visible_target",
        "not_verified_requires_physical_recording_matrix",
        "not_verified_requires_isolated_tcc_state",
    }
)

REQUIRED_CASES: tuple[RequiredCase, ...] = (
    RequiredCase("current_window_chrome", CaseExpectation.PASS_REQUIRED, PASS_STATUSES),
    RequiredCase("current_window_finder", CaseExpectation.PASS_REQUIRED, PASS_STATUSES),
    RequiredCase("current_window_preview", CaseExpectation.PASS_REQUIRED, PASS_STATUSES),
    RequiredCase("current_window_textedit", CaseExpectation.PASS_REQUIRED, PASS_STATUSES),
    RequiredCase("current_window_system_settings", CaseExpectation.PASS_REQUIRED, PASS_STATUSES),
    RequiredCase("workrecorder_self_foreground", CaseExpectation.PASS_REQUIRED, PASS_STATUSES),
    RequiredCase("finder_no_window", CaseExpectation.PASS_REQUIRED, PASS_STATUSES),
    RequiredCase("overlapping_windows", CaseExpectation.PASS_REQUIRED, PASS_STATUSES),
    RequiredCase("fullscreen_spaces", CaseExpectation.PASS_REQUIRED, PASS_STATUSES),
    RequiredCase("region_screenshot", CaseExpectation.PASS_REQUIRED, PASS_STATUSES),
    RequiredCase(
        "recording_region",
        CaseExpectation.EXPLICIT_LIMITATION_ALLOWED,
        PASS_STATUSES | LIMITATION_STATUSES,
        risk_keywords=("recording region", "region recording"),
    ),
    RequiredCase(
        "recording_discard",
        CaseExpectation.EXPLICIT_LIMITATION_ALLOWED,
        PASS_STATUSES | LIMITATION_STATUSES,
        risk_keywords=("recording discard", "discard"),
    ),
    RequiredCase(
        "recording_controls",
        CaseExpectation.EXPLICIT_LIMITATION_ALLOWED,
        PASS_STATUSES | LIMITATION_STATUSES,
        risk_keywords=("recording controls", "hud controls"),
    ),
    RequiredCase("screen_recording_denied", CaseExpectation.PASS_REQUIRED, PASS_STATUSES),
    RequiredCase("shortcut_persistence", CaseExpectation.PASS_REQUIRED, PASS_STATUSES),
    RequiredCase("startup_order", CaseExpectation.PASS_REQUIRED, PASS_STATUSES),
    RequiredCase("adaptive_port_conflict_current_window", CaseExpectation.PASS_REQUIRED, PASS_STATUSES),
    RequiredCase("recording_large_review_packaged_smoke", CaseExpectation.PASS_REQUIRED, PASS_STATUSES),
    RequiredCase(
        "shortcut_validation",
        CaseExpectation.PASS_REQUIRED,
        PASS_STATUSES,
        risk_keywords=("External shortcut conflict",),
    ),
    RequiredCase(
        "chrome_extension_online",
        CaseExpectation.PASS_REQUIRED,
        PASS_STATUSES,
        risk_keywords=("Stable Chrome",),
    ),
    RequiredCase(
        "stable_chrome_extension_online_retry",
        CaseExpectation.EXPLICIT_LIMITATION_ALLOWED,
        PASS_STATUSES | LIMITATION_STATUSES,
        risk_keywords=("Stable Chrome", "Chrome for Testing"),
    ),
    RequiredCase(
        "multi_display",
        CaseExpectation.EXPLICIT_LIMITATION_ALLOWED,
        PASS_STATUSES | LIMITATION_STATUSES,
        risk_keywords=("multi-display", "mixed-Retina", "negative-coordinate"),
    ),
    RequiredCase(
        "accessibility_denied",
        CaseExpectation.EXPLICIT_LIMITATION_ALLOWED,
        PASS_STATUSES | LIMITATION_STATUSES,
        risk_keywords=("Accessibility-denied", "TCC"),
    ),
    RequiredCase(
        "notes",
        CaseExpectation.EXPLICIT_LIMITATION_ALLOWED,
        PASS_STATUSES | LIMITATION_STATUSES,
        risk_keywords=("Notes",),
    ),
)

QUALITY_GATE_PREDICATES: Mapping[str, Callable[[str], bool]] = {
    "swift_test": lambda value: _is_count_pass(value),
    "python_targeted_core": lambda value: _is_count_pass(value),
    "python_sanitizer_targeted": lambda value: _is_count_pass(value),
    "shortcut_settings_swift_filter": lambda value: _is_count_pass(value),
    "ruff": lambda value: value == "clean",
    "mypy": lambda value: value.startswith("success:") or value.startswith("no issues found"),
    "pyright": lambda value: value.startswith("0 errors, 0 warnings"),
    "repo_quality_audit": lambda value: value == "0 violations, 0 warnings",
    "swift_quality_audit": lambda value: value == "passed",
    "browser_extension_npm_test": lambda value: _is_count_pass(value),
    "git_diff_check": lambda value: value == "clean",
    "package_verify": lambda value: value == "passed",
    "codesign_verify": lambda value: value == "passed",
    "codesign_strict": lambda value: value == "passed_on_non_fileprovider_staging",
    "macos_app_e2e_manifest_verifier": lambda value: value.startswith("passed with"),
    "release_lab_preflight": lambda value: value.startswith("completed"),
}

QUALITY_GATES = frozenset(QUALITY_GATE_PREDICATES)
RECORDING_PHYSICAL_CASES = frozenset({"recording_region", "recording_discard", "recording_controls"})


def build_argument_parser() -> argparse.ArgumentParser:
    """Build CLI arguments.

    Returns:
        Configured parser for the manifest verifier command.
    """

    parser = argparse.ArgumentParser(description="Validate the real-bundle macOS E2E manifest.")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--strict-release",
        action="store_true",
        help="Fail if any required case is still recorded as an environment limitation.",
    )
    parser.add_argument("--json-output", type=Path, help="Optional path for machine-readable validation output.")
    return parser


def main() -> int:
    """Run the manifest verifier.

    Returns:
        Process exit status; non-zero only when blocking errors are found.
    """

    args = build_argument_parser().parse_args()
    manifest = _load_manifest(args.manifest)
    findings = validate_manifest(manifest, strict_release=args.strict_release, report_dir=args.manifest.parent)
    payload = {
        "manifest": str(args.manifest),
        "ok": not any(f.severity == "error" for f in findings),
        "strict_release": args.strict_release,
        "findings": [asdict(finding) for finding in findings],
    }
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for finding in findings:
        stream = sys.stderr if finding.severity == "error" else sys.stdout
        print(f"{finding.severity.upper()} [{finding.case_key}] {finding.message}", file=stream)
    if payload["ok"]:
        print("macOS app E2E manifest validation passed.")
        return 0
    return 1


def validate_manifest(
    manifest: JsonObject,
    *,
    strict_release: bool,
    report_dir: Path | None = None,
) -> list[ManifestFinding]:
    """Validate required cases, quality gates, and explicit limitations.

    Args:
        manifest: Parsed run-manifest JSON object.
        strict_release: Whether environment-limited rows should become errors.
        report_dir: Directory that manifest report paths must resolve inside.

    Returns:
        Ordered validation findings. Empty or warning-only findings are passing.
    """

    findings: list[ManifestFinding] = []
    artifact_dir = report_dir or DEFAULT_MANIFEST.parent
    manual_cases = _mapping(manifest.get("manual_cases"))
    open_risks = _string_sequence(manifest.get("open_risks"))

    for required in REQUIRED_CASES:
        raw_case = manual_cases.get(required.key)
        if not isinstance(raw_case, Mapping):
            findings.append(_error(required.key, "required case is missing from manual_cases"))
            continue
        status = raw_case.get("status")
        if not isinstance(status, str):
            findings.append(_error(required.key, "case status must be a string"))
            continue
        if status not in required.accepted_statuses:
            findings.append(_error(required.key, f"unexpected status {status!r}"))
        artifact_findings = _validate_case_artifacts(
            case_key=required.key,
            case=raw_case,
            status=status,
            report_dir=artifact_dir,
        )
        findings.extend(artifact_findings)
        if required.report_required and not _has_report_or_evidence(raw_case):
            findings.append(_error(required.key, "case must include a report or evidence field"))
        if status in LIMITATION_STATUSES:
            if required.expectation is CaseExpectation.PASS_REQUIRED:
                findings.append(_error(required.key, f"release-required case is still limited: {status}"))
            elif strict_release:
                findings.append(_error(required.key, f"strict release cannot accept limitation: {status}"))
            elif not _risk_mentions(open_risks, required.risk_keywords):
                findings.append(_error(required.key, "limitation status requires a matching open_risks entry"))
            else:
                findings.append(_warning(required.key, f"accepted as explicit environment limitation: {status}"))
        if required.risk_keywords and status in PASS_STATUSES and _risk_mentions(open_risks, required.risk_keywords):
            finding = _error if strict_release else _warning
            findings.append(finding(required.key, "passed case still has a related release-lab caveat"))

    findings.extend(_validate_external_shortcut_ui(manifest, strict_release=strict_release))
    findings.extend(_validate_quality_gates(manifest))
    findings.extend(_validate_bundle_and_daemon(manifest))
    findings.extend(
        _error(case_key, message)
        for case_key, message in validate_release_lab_preflight_consistency(
            report_dir=artifact_dir,
            manifest_screens=manifest.get("screens"),
            release_lab_preflight_gate=_mapping(manifest.get("quality_gates")).get("release_lab_preflight"),
        )
    )
    return findings


def _validate_external_shortcut_ui(manifest: JsonObject, *, strict_release: bool) -> list[ManifestFinding]:
    """Validate that external shortcut conflict UI has direct evidence.

    Same-process Carbon denial tests prove the failure-state plumbing, but they
    do not prove that Workbench surfaces a conflict held by another app. Keep
    this as a direct strict-release gate so deleting an ``open_risks`` sentence
    cannot accidentally turn an unproven helper diagnostic into release-ready
    evidence.
    """

    shortcut_case = _mapping(_mapping(manifest.get("manual_cases")).get("shortcut_validation"))
    if not shortcut_case:
        return []
    external_helper_ui = shortcut_case.get("external_helper_ui")
    if external_helper_ui == "passed":
        return []
    finding = _error if strict_release else _warning
    return [
        finding(
            "external_shortcut_conflict_ui",
            "external shortcut conflict UI is not proven; helper diagnostics and same-process Carbon tests are not enough",
        )
    ]


def _validate_quality_gates(manifest: JsonObject) -> list[ManifestFinding]:
    gates = _mapping(manifest.get("quality_gates"))
    findings: list[ManifestFinding] = []
    for gate in sorted(set(gates) - QUALITY_GATES):
        findings.append(_error("quality_gates", f"unvalidated quality gate has no pass predicate: {gate}"))
    for gate in sorted(QUALITY_GATES):
        value = gates.get(gate)
        if value in {None, "", False} or not isinstance(value, str):
            findings.append(_error("quality_gates", f"missing quality gate: {gate}"))
            continue
        predicate = QUALITY_GATE_PREDICATES[gate]
        if _looks_like_failure(value) or not predicate(value):
            findings.append(_error("quality_gates", f"quality gate {gate} is not passing: {value!r}"))
    return findings


def _validate_bundle_and_daemon(manifest: JsonObject) -> list[ManifestFinding]:
    findings: list[ManifestFinding] = []
    bundle = _mapping(manifest.get("bundle"))
    daemon = _mapping(manifest.get("daemon"))
    if not str(bundle.get("path", "")).endswith("dist/WorkRecorder.app"):
        findings.append(_error("bundle", "bundle.path must point at dist/WorkRecorder.app"))
    if "valid on disk" not in str(bundle.get("codesign_verify", "")):
        findings.append(_error("bundle", "codesign_verify must show a valid bundle"))
    if "valid on disk" not in str(bundle.get("codesign_strict_staged_no_xattr", "")):
        findings.append(_error("bundle", "staged strict codesign verification is missing or failed"))
    health = _mapping(daemon.get("health"))
    if health.get("ok") is not True:
        findings.append(_error("daemon", "daemon health must be ok"))
    daemon_data = _mapping(health.get("data"))
    if daemon_data.get("service") != "workrecorder-local-daemon":
        findings.append(_error("daemon", "daemon health must identify workrecorder-local-daemon"))
    return findings


def _load_manifest(path: Path) -> JsonObject:
    if not path.exists():
        raise SystemExit(f"manifest does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise SystemExit("manifest root must be a JSON object")
    return cast(JsonObject, payload)


def _mapping(value: object) -> JsonObject:
    return cast(JsonObject, value) if isinstance(value, Mapping) else {}


def _string_sequence(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _is_count_pass(value: str) -> bool:
    parts = value.split()
    return len(parts) >= 2 and parts[0].isdigit() and parts[1] == "passed"


def _looks_like_failure(value: str) -> bool:
    lowered = value.casefold()
    failure_tokens = (
        "fail",
        "fails",
        "failed",
        "failure",
        "error",
        "errors",
        "warning",
        "warnings",
        "violation",
        "violations",
    )
    allowlist = (
        "0 errors",
        "0 warnings",
        "0 violations",
        "passed with explicit environment-limited warnings",
    )
    return any(token in lowered for token in failure_tokens) and not any(token in lowered for token in allowlist)


def _validate_case_artifacts(
    *,
    case_key: str,
    case: JsonObject,
    status: str,
    report_dir: Path,
) -> list[ManifestFinding]:
    findings: list[ManifestFinding] = []
    refs = _artifact_refs(case)
    if status in PASS_STATUSES and case_key in RECORDING_PHYSICAL_CASES:
        report = case.get("report")
        if not isinstance(report, str) or not report:
            findings.append(_error(case_key, "passed physical recording case requires a report artifact"))
    if status in PASS_STATUSES and not refs:
        findings.append(_error(case_key, "passed case requires an existing report artifact, not free-text evidence"))
        return findings
    for ref in refs:
        resolved = _resolve_report_ref(report_dir=report_dir, ref=ref)
        if resolved is None:
            findings.append(_error(case_key, f"{ref.field} must stay under report directory: {ref.raw_path}"))
        elif not resolved.exists():
            findings.append(_error(case_key, f"{ref.field} artifact does not exist: {ref.raw_path}"))
        elif case_key == "recording_large_review_packaged_smoke" and ref.field == "report":
            findings.extend(_validate_large_review_smoke_report(resolved))
        elif status in PASS_STATUSES and case_key in RECORDING_PHYSICAL_CASES and ref.field == "report":
            findings.extend(validate_recording_physical_report(case_key=case_key, path=resolved))
    return findings


def validate_recording_physical_report(*, case_key: str, path: Path) -> list[ManifestFinding]:
    """Validate the physical shortcut/HUD recording release-lab report.

    The automated packaged harness proves the backend and playback route, but
    strict release rows must prove the visible user flow: the real app bundle,
    the default recording shortcut, region confirmation, HUD/boundary state, and
    completion-sheet decision. Keep this schema tight so a future ``passed`` row
    cannot be backed by an empty smoke JSON.

    Args:
        case_key: Recording manifest case key.
        path: Report JSON path.

    Returns:
        Validation findings for the physical recording report.
    """

    findings: list[ManifestFinding] = []
    if case_key not in RECORDING_PHYSICAL_CASES:
        return [_error(case_key, f"case is not a physical recording case: {case_key}")]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [_error(case_key, f"recording physical report is not readable JSON: {exc}")]
    if not isinstance(payload, Mapping):
        return [_error(case_key, "recording physical report must be a JSON object")]

    expected_fields: Mapping[str, JsonValue] = {
        "case": case_key,
        "app_bundle": "dist/WorkRecorder.app",
        "trigger_shortcut": "⌃⌥⌘R",
        "opened_via_physical_shortcut": True,
        "region_selection_confirmed": True,
        "completion_sheet_visible": True,
        "hud_visible": True,
        "recording_boundary_visible": True,
        "privacy_check_no_storage_uri": True,
        "privacy_check_no_local_path": True,
    }
    for field, expected in expected_fields.items():
        if payload.get(field) != expected:
            findings.append(_error(case_key, f"recording report field {field} must be {expected!r}"))

    findings.extend(_require_non_empty_strings(case_key, payload, ("session_id",)))
    findings.extend(_validate_recording_report_timestamps(case_key=case_key, payload=payload))

    if case_key == "recording_region":
        findings.extend(_validate_recording_save_report(case_key=case_key, payload=payload))
    elif case_key == "recording_discard":
        findings.extend(_validate_recording_discard_report(case_key=case_key, payload=payload))
    elif case_key == "recording_controls":
        findings.extend(_validate_recording_controls_report(case_key=case_key, payload=payload))
    return findings


def _validate_recording_save_report(*, case_key: str, payload: Mapping[str, object]) -> list[ManifestFinding]:
    findings: list[ManifestFinding] = []
    expected_fields: Mapping[str, JsonValue] = {
        "save_clicked": True,
        "discard_clicked": False,
        "completion_final_status": "completed",
        "video_state": "available",
        "appears_in_recording_library": True,
        "appears_in_screenshot_library": False,
    }
    for field, expected in expected_fields.items():
        if payload.get(field) != expected:
            findings.append(_error(case_key, f"recording save report field {field} must be {expected!r}"))
    findings.extend(_require_non_empty_strings(case_key, payload, ("event_id", "video_artifact_id")))
    findings.extend(_require_positive_numbers(case_key, payload, ("duration_ms",)))
    findings.extend(_require_positive_integer_counts(case_key, payload, ("segment_count", "keyframe_count")))
    return findings


def _validate_recording_discard_report(*, case_key: str, payload: Mapping[str, object]) -> list[ManifestFinding]:
    findings: list[ManifestFinding] = []
    expected_fields: Mapping[str, JsonValue] = {
        "save_clicked": False,
        "discard_clicked": True,
        "completion_final_status": "cancelled",
        "appears_in_recording_library": False,
        "appears_in_screenshot_library": False,
        "completed_event_created": False,
        "staged_video_deleted": True,
    }
    for field, expected in expected_fields.items():
        if payload.get(field) != expected:
            findings.append(_error(case_key, f"recording discard report field {field} must be {expected!r}"))
    return findings


def _validate_recording_controls_report(*, case_key: str, payload: Mapping[str, object]) -> list[ManifestFinding]:
    findings: list[ManifestFinding] = []
    expected_fields: Mapping[str, JsonValue] = {
        "pause_clicked": True,
        "resume_clicked": True,
        "mark_clicked": True,
        "pause_stopped_capture": True,
        "resume_started_new_segment": True,
        "mark_created_keyframe": True,
        "save_clicked": True,
        "completion_final_status": "completed",
        "video_state": "available",
        "appears_in_recording_library": True,
        "appears_in_screenshot_library": False,
    }
    for field, expected in expected_fields.items():
        if payload.get(field) != expected:
            findings.append(_error(case_key, f"recording controls report field {field} must be {expected!r}"))
    findings.extend(
        _require_non_empty_strings(case_key, payload, ("event_id", "video_artifact_id", "manual_mark_keyframe_id"))
    )
    findings.extend(_require_positive_numbers(case_key, payload, ("duration_ms",)))
    findings.extend(_require_positive_integer_counts(case_key, payload, ("segment_count", "keyframe_count")))
    segment_count = payload.get("segment_count")
    if isinstance(segment_count, bool) or not isinstance(segment_count, int) or segment_count < 2:
        findings.append(_error(case_key, "recording controls report field segment_count must be at least 2"))
    return findings


def _validate_large_review_smoke_report(path: Path) -> list[ManifestFinding]:
    findings: list[ManifestFinding] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [_error("recording_large_review_packaged_smoke", f"report is not readable JSON: {exc}")]
    if not isinstance(payload, Mapping):
        return [_error("recording_large_review_packaged_smoke", "report must be a JSON object")]

    expected_fields: Mapping[str, JsonValue] = {
        "playback_loaded": True,
        "playback_file_exists": True,
        "window_visible": True,
        "playback_purpose": "workbench_large_recording_review",
        "video_state": "available",
    }
    for field, expected in expected_fields.items():
        if payload.get(field) != expected:
            findings.append(
                _error(
                    "recording_large_review_packaged_smoke",
                    f"report field {field} must be {expected!r}",
                )
            )
    for field in ("event_id", "session_id", "video_artifact_id"):
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            findings.append(_error("recording_large_review_packaged_smoke", f"report field {field} must be non-empty"))
    for field in ("duration_ms", "playback_byte_size", "step_count"):
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            findings.append(_error("recording_large_review_packaged_smoke", f"report field {field} must be positive"))
    window_frame = payload.get("window_frame")
    if not isinstance(window_frame, Mapping):
        findings.append(_error("recording_large_review_packaged_smoke", "report field window_frame must be an object"))
    else:
        for field in ("width", "height"):
            value = window_frame.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                findings.append(
                    _error("recording_large_review_packaged_smoke", f"window_frame.{field} must be positive")
                )
    return findings


def _require_non_empty_strings(
    case_key: str,
    payload: Mapping[str, object],
    fields: Sequence[str],
) -> list[ManifestFinding]:
    findings: list[ManifestFinding] = []
    for field in fields:
        value = payload.get(field)
        if not isinstance(value, str) or not value:
            findings.append(_error(case_key, f"recording report field {field} must be non-empty"))
    return findings


def _require_positive_numbers(
    case_key: str,
    payload: Mapping[str, object],
    fields: Sequence[str],
) -> list[ManifestFinding]:
    findings: list[ManifestFinding] = []
    for field in fields:
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
            findings.append(_error(case_key, f"recording report field {field} must be positive"))
    return findings


def _require_positive_integer_counts(
    case_key: str,
    payload: Mapping[str, object],
    fields: Sequence[str],
) -> list[ManifestFinding]:
    findings: list[ManifestFinding] = []
    for field in fields:
        value = payload.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            findings.append(_error(case_key, f"recording report field {field} must be a positive integer"))
    return findings


def _validate_recording_report_timestamps(
    *,
    case_key: str,
    payload: Mapping[str, object],
) -> list[ManifestFinding]:
    findings: list[ManifestFinding] = []
    started = _parse_timezone_iso_timestamp(payload.get("started_at"))
    ended = _parse_timezone_iso_timestamp(payload.get("ended_at"))
    if started is None:
        findings.append(_error(case_key, "recording report field started_at must be a timezone ISO timestamp"))
    if ended is None:
        findings.append(_error(case_key, "recording report field ended_at must be a timezone ISO timestamp"))
    if started is not None and ended is not None and ended <= started:
        findings.append(_error(case_key, "recording report field ended_at must be after started_at"))
    return findings


def _parse_timezone_iso_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _artifact_refs(case: JsonObject) -> tuple[ManifestArtifactRef, ...]:
    refs: list[ManifestArtifactRef] = []
    for field in ("report", "inspect_report", "raw_screenshot"):
        value = case.get(field)
        if isinstance(value, str) and value:
            refs.append(ManifestArtifactRef(field=field, raw_path=value))
    supporting = case.get("supporting_reports")
    if isinstance(supporting, Sequence) and not isinstance(supporting, (str, bytes)):
        for item in supporting:
            if isinstance(item, str) and item:
                refs.append(ManifestArtifactRef(field="supporting_reports", raw_path=item))
    return tuple(refs)


def _resolve_report_ref(*, report_dir: Path, ref: ManifestArtifactRef) -> Path | None:
    root = report_dir.resolve()
    raw_path = Path(ref.raw_path)
    candidate = raw_path if raw_path.is_absolute() else root / raw_path
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        return None
    return resolved


def _has_report_or_evidence(case: JsonObject) -> bool:
    for key in ("report", "evidence", "raw_screenshot"):
        value = case.get(key)
        if isinstance(value, str) and value:
            return True
    return False


def _risk_mentions(open_risks: Sequence[str], keywords: Sequence[str]) -> bool:
    if not keywords:
        return True
    lowered_keywords = tuple(keyword.casefold() for keyword in keywords)
    return any(any(keyword in risk.casefold() for keyword in lowered_keywords) for risk in open_risks)


def _error(case_key: str, message: str) -> ManifestFinding:
    return ManifestFinding(severity="error", case_key=case_key, message=message)


def _warning(case_key: str, message: str) -> ManifestFinding:
    return ManifestFinding(severity="warning", case_key=case_key, message=message)


if __name__ == "__main__":
    raise SystemExit(main())
