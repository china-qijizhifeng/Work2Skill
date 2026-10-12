"""Validate release-lab preflight evidence referenced by the macOS E2E manifest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence, TypeAlias

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
PreflightFinding: TypeAlias = tuple[str, str]

PREFLIGHT_STATUSES = frozenset({"passed", "ready_to_validate", "manual_setup_required", "blocked"})
PREFLIGHT_EXPECTED_CASES: Mapping[str, str] = {
    "recording_region": "recording_region",
    "recording_discard": "recording_discard",
    "recording_controls": "recording_controls",
    "multi_display": "multi_display",
    "stable_chrome": "stable_chrome_extension_online_retry",
    "isolated_ax_denied": "accessibility_denied",
    "notes_visible_target": "notes",
    "external_shortcut_conflict_ui": "shortcut_validation",
}


def validate_release_lab_preflight_consistency(
    *,
    report_dir: Path,
    manifest_screens: object,
    release_lab_preflight_gate: object,
) -> list[PreflightFinding]:
    """Validate the release-lab preflight artifact against manifest evidence.

    Args:
        report_dir: Directory that should contain ``release-lab-preflight.json``.
        manifest_screens: Manifest ``screens`` payload used to cross-check the
            current display count.
        release_lab_preflight_gate: Human-readable quality-gate summary whose
            blocker/setup/readiness counts must match the artifact.

    Returns:
        A list of ``(case_key, message)`` findings. The manifest verifier maps
        these findings to blocking errors because stale or structurally fake
        preflight evidence can otherwise overclaim release readiness.
    """

    findings: list[PreflightFinding] = []
    preflight_path = report_dir / "release-lab-preflight.json"
    if not preflight_path.exists():
        return [("release_lab_preflight", "release_lab_preflight quality gate requires release-lab-preflight.json")]
    try:
        payload = json.loads(preflight_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [("release_lab_preflight", f"preflight report is not readable JSON: {exc}")]
    if not isinstance(payload, Mapping):
        return [("release_lab_preflight", "preflight report must be a JSON object")]
    environment = _mapping(payload.get("environment"))
    display_count = environment.get("display_count")
    if isinstance(display_count, bool) or not isinstance(display_count, int):
        return [("release_lab_preflight", "environment.display_count must be an integer")]
    findings.extend(_validate_preflight_checks(payload.get("checks"), release_lab_preflight_gate))
    manifest_screen_count = _manifest_screen_count(manifest_screens)
    if manifest_screen_count is not None and manifest_screen_count != display_count:
        findings.append(
            (
                "screens",
                (
                    "manifest screens display count "
                    f"{manifest_screen_count} disagrees with release-lab preflight display_count {display_count}"
                ),
            )
        )
    return findings


def _validate_preflight_checks(checks: object, gate_value: object) -> list[PreflightFinding]:
    findings: list[PreflightFinding] = []
    if not isinstance(checks, Sequence) or isinstance(checks, (str, bytes)) or not checks:
        findings.append(("release_lab_preflight", "preflight report checks must be a non-empty list"))
        checks = []
    status_counts: dict[str, int] = {}
    seen_keys: dict[str, str] = {}
    for index, raw_check in enumerate(checks):
        if not isinstance(raw_check, Mapping):
            findings.append(("release_lab_preflight", f"preflight check #{index + 1} must be an object"))
            continue
        findings.extend(_validate_preflight_check(index=index, raw_check=raw_check, seen_keys=seen_keys))
        status = raw_check.get("status")
        if not isinstance(status, str) or status not in PREFLIGHT_STATUSES:
            findings.append(("release_lab_preflight", f"preflight check #{index + 1} status is invalid: {status!r}"))
            continue
        status_counts[status] = status_counts.get(status, 0) + 1
    for key in sorted(set(PREFLIGHT_EXPECTED_CASES) - set(seen_keys)):
        findings.append(("release_lab_preflight", f"preflight check key {key!r} is missing"))
    findings.extend(_validate_preflight_summary(gate_value, status_counts))
    return findings


def _validate_preflight_check(
    *,
    index: int,
    raw_check: Mapping[object, object],
    seen_keys: dict[str, str],
) -> list[PreflightFinding]:
    findings: list[PreflightFinding] = []
    key = raw_check.get("key")
    manifest_case = raw_check.get("manifest_case")
    if not isinstance(key, str) or not key:
        findings.append(("release_lab_preflight", f"preflight check #{index + 1} key must be non-empty"))
        key = None
    if not isinstance(manifest_case, str) or not manifest_case:
        findings.append(("release_lab_preflight", f"preflight check #{index + 1} manifest_case must be non-empty"))
        manifest_case = None
    if isinstance(key, str) and isinstance(manifest_case, str):
        findings.extend(_validate_preflight_key_mapping(key=key, manifest_case=manifest_case, seen_keys=seen_keys))
    return findings


def _validate_preflight_key_mapping(
    *,
    key: str,
    manifest_case: str,
    seen_keys: dict[str, str],
) -> list[PreflightFinding]:
    expected_case = PREFLIGHT_EXPECTED_CASES.get(key)
    if key in seen_keys:
        finding = ("release_lab_preflight", f"preflight check key {key!r} is duplicated")
    elif expected_case is None:
        finding = ("release_lab_preflight", f"preflight check key {key!r} is unexpected")
    elif manifest_case != expected_case:
        finding = (
            "release_lab_preflight",
            f"preflight check {key!r} must map to manifest_case {expected_case!r}",
        )
    else:
        finding = None
    seen_keys[key] = manifest_case
    return [] if finding is None else [finding]


def _validate_preflight_summary(gate_value: object, status_counts: Mapping[str, int]) -> list[PreflightFinding]:
    if not isinstance(gate_value, str):
        return []
    expected = _parse_preflight_counts(gate_value)
    if expected is None:
        return [("release_lab_preflight", "release_lab_preflight gate must include blocker/setup/readiness counts")]
    actual = {
        "blocked": status_counts.get("blocked", 0),
        "manual_setup_required": status_counts.get("manual_setup_required", 0),
        "ready_to_validate": status_counts.get("ready_to_validate", 0),
    }
    if actual == expected:
        return []
    return [
        (
            "release_lab_preflight",
            f"release_lab_preflight gate counts {expected} disagree with artifact counts {actual}",
        )
    ]


def _parse_preflight_counts(value: str) -> dict[str, int] | None:
    parsed: dict[str, int] = {}
    for status in ("blocked", "manual_setup_required", "ready_to_validate"):
        before_marker, found, _ = value.partition(f" {status}")
        if not found:
            return None
        raw_count = before_marker.rsplit(" ", 1)[-1].strip(",")
        if not raw_count.isdigit():
            return None
        parsed[status] = int(raw_count)
    return parsed


def _manifest_screen_count(value: object) -> int | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return len(value)
    if isinstance(value, Mapping):
        display_count = value.get("display_count")
        if isinstance(display_count, bool) or not isinstance(display_count, int):
            return None
        return display_count
    return None


def _mapping(value: object) -> Mapping[str, JsonValue]:
    return value if isinstance(value, Mapping) else {}
