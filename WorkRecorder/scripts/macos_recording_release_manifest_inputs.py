"""Prepare manifest inputs for macOS recording release validation."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Mapping, Sequence, cast

from scripts.check_macos_app_release_lab import collect_environment, evaluate_release_lab
from scripts.macos_recording_release_matrix_support import JsonValue, _write_json
from scripts.verify_macos_app_e2e_manifest import JsonObject, validate_recording_physical_report


def write_release_lab_preflight(*, manifest: JsonObject, manifest_path: Path, output_dir: Path) -> dict[str, JsonValue]:
    """Write current-machine release-lab preflight facts for this matrix run.

    Args:
        manifest: Parsed E2E manifest.
        manifest_path: Source manifest location, used to resolve existing reports.
        output_dir: Run-local evidence directory.

    Returns:
        Sanitized preflight payload that was written to the evidence directory.
    """

    environment = collect_environment()
    checks = evaluate_release_lab(manifest=manifest, environment=environment, report_dir=manifest_path.parent)
    manual_cases = _manual_cases(manifest)
    payload: dict[str, JsonValue] = {
        "manifest": str(manifest_path),
        "environment": cast(JsonValue, asdict(environment)),
        "checks": [
            {
                "key": check.key.value,
                "status": check.status.value,
                "manifest_case": check.manifest_case,
                "evidence": check.evidence,
                "next_step": check.next_step,
                **_physical_report_provenance(
                    case_key=check.manifest_case,
                    case=manual_cases.get(check.manifest_case, {}),
                    report_dir=manifest_path.parent,
                ),
            }
            for check in checks
        ],
    }
    _write_json(output_dir / "release-lab-preflight.json", payload)
    return payload


def prepare_manifest_validation_inputs(
    *,
    manifest: JsonObject,
    manifest_path: Path,
    release_lab_payload: Mapping[str, JsonValue],
    output_dir: Path,
) -> tuple[JsonObject, Path]:
    """Create a run-local manifest draft and copy referenced evidence artifacts.

    Args:
        manifest: Parsed source manifest.
        manifest_path: Source manifest path.
        release_lab_payload: Current-machine release-lab preflight facts.
        output_dir: Run-local evidence directory.

    Returns:
        A run-local manifest draft plus the report directory to use for validation.
    """

    draft = json.loads(json.dumps(manifest))
    if isinstance(draft, dict):
        _refresh_manifest_preflight_fields(draft, release_lab_payload)
        _strip_raw_screenshot_refs(draft)
        _copy_manifest_artifacts(
            manifest=cast(JsonObject, draft), source_dir=manifest_path.parent, output_dir=output_dir
        )
    _write_json(output_dir / "release-lab-preflight.json", cast(JsonValue, dict(release_lab_payload)))
    _write_json(output_dir / "run-manifest-draft.json", cast(JsonValue, draft))
    return cast(JsonObject, draft), output_dir


def _refresh_manifest_preflight_fields(manifest: dict[str, JsonValue], preflight: Mapping[str, JsonValue]) -> None:
    environment = preflight.get("environment")
    display_count = environment.get("display_count") if isinstance(environment, dict) else None
    if isinstance(display_count, int) and not isinstance(display_count, bool):
        manifest["screens"] = {
            "source": "recording_release_matrix_preflight",
            "display_count": display_count,
            "note": "Current release-matrix preflight display count; physical multi-display cases still require report artifacts.",
        }
        _refresh_multi_display_case(manifest, display_count=display_count, preflight=preflight)
    quality_gates = manifest.get("quality_gates")
    if not isinstance(quality_gates, dict):
        quality_gates = {}
        manifest["quality_gates"] = quality_gates
    quality_gates["release_lab_preflight"] = _preflight_summary(preflight)


def _refresh_multi_display_case(
    manifest: dict[str, JsonValue], *, display_count: int, preflight: Mapping[str, JsonValue]
) -> None:
    preflight_status = _preflight_check_status(preflight, key="multi_display")
    evidence = (
        f"Current release-matrix preflight detected {display_count} display"
        f"{'' if display_count == 1 else 's'} and marks multi_display {preflight_status or 'unknown'}; "
        "physical negative-coordinate/mixed-Retina validation still needs the strict matrix rerun."
    )
    manual_cases = manifest.get("manual_cases")
    if isinstance(manual_cases, dict):
        multi_display = manual_cases.get("multi_display")
        if isinstance(multi_display, dict):
            multi_display["evidence"] = evidence
    open_risks = manifest.get("open_risks")
    if isinstance(open_risks, list):
        manifest["open_risks"] = [
            (
                evidence
                if isinstance(item, str)
                and ("multi-display" in item or "mixed-Retina" in item or "negative-coordinate" in item)
                else item
            )
            for item in open_risks
        ]


def _preflight_check_status(preflight: Mapping[str, JsonValue], *, key: str) -> str | None:
    checks = preflight.get("checks")
    if not isinstance(checks, list):
        return None
    for raw_check in checks:
        if not isinstance(raw_check, dict):
            continue
        if raw_check.get("key") == key:
            status = raw_check.get("status")
            return status if isinstance(status, str) else None
    return None


def _strip_raw_screenshot_refs(manifest: dict[str, JsonValue]) -> None:
    manual_cases = manifest.get("manual_cases")
    if not isinstance(manual_cases, dict):
        return
    for raw_case in manual_cases.values():
        if isinstance(raw_case, dict):
            raw_case.pop("raw_screenshot", None)


def _preflight_summary(preflight: Mapping[str, JsonValue]) -> str:
    counts = {"blocked": 0, "manual_setup_required": 0, "ready_to_validate": 0}
    checks = preflight.get("checks")
    if isinstance(checks, list):
        for raw_check in checks:
            if not isinstance(raw_check, dict):
                continue
            status = raw_check.get("status")
            if status in counts:
                counts[status] += 1
    return (
        "completed current-machine profile: "
        f"{counts['blocked']} blocked, "
        f"{counts['manual_setup_required']} manual_setup_required, "
        f"{counts['ready_to_validate']} ready_to_validate"
    )


def _manual_cases(manifest: JsonObject) -> Mapping[str, object]:
    manual_cases = manifest.get("manual_cases")
    return manual_cases if isinstance(manual_cases, Mapping) else {}


def _copy_manifest_artifacts(*, manifest: JsonObject, source_dir: Path, output_dir: Path) -> None:
    for raw_case in _manual_cases(manifest).values():
        if not isinstance(raw_case, Mapping):
            continue
        for ref in _case_artifact_refs(raw_case):
            source_path = _resolve_source_artifact(source_dir=source_dir, ref=ref)
            target_path = output_dir / ref
            if source_path is None or not source_path.exists() or target_path.exists():
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)


def _case_artifact_refs(case: Mapping[object, object]) -> tuple[Path, ...]:
    refs: list[Path] = []
    for field in ("report", "inspect_report"):
        value = case.get(field)
        if isinstance(value, str) and value:
            refs.append(Path(value))
    supporting = case.get("supporting_reports")
    if isinstance(supporting, Sequence) and not isinstance(supporting, (str, bytes)):
        refs.extend(Path(item) for item in supporting if isinstance(item, str) and item)
    return tuple(ref for ref in refs if not ref.is_absolute())


def _resolve_source_artifact(*, source_dir: Path, ref: Path) -> Path | None:
    candidate = (source_dir / ref).resolve()
    try:
        candidate.relative_to(source_dir.resolve())
    except ValueError:
        return None
    return candidate


def _physical_report_provenance(
    *,
    case_key: str,
    case: object,
    report_dir: Path,
) -> dict[str, JsonValue]:
    if case_key not in {"recording_region", "recording_discard", "recording_controls"}:
        return {}
    if not isinstance(case, Mapping):
        return {}
    report = case.get("report")
    if not isinstance(report, str) or not report:
        return {}
    report_path = _resolve_source_artifact(source_dir=report_dir, ref=Path(report))
    if report_path is None or not report_path.exists():
        return {"report": report, "report_validation": "missing"}
    findings = validate_recording_physical_report(case_key=case_key, path=report_path)
    validation_errors = [finding.message for finding in findings if finding.severity == "error"]
    return {
        "report": report,
        "report_sha256": _file_sha256(report_path),
        "report_validation": "passed" if not validation_errors else "failed",
        "report_validation_errors": cast(JsonValue, validation_errors),
    }


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
