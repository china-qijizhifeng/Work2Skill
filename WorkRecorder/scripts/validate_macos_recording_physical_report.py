"""Validate one physical macOS recording release-lab report."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from scripts.create_macos_recording_physical_report import PhysicalRecordingCase
from scripts.verify_macos_app_e2e_manifest import validate_recording_physical_report


def build_argument_parser() -> argparse.ArgumentParser:
    """Build CLI arguments.

    Returns:
        Configured parser for single-report validation.
    """

    parser = argparse.ArgumentParser(description="Validate one physical recording E2E report JSON.")
    parser.add_argument("--case", choices=[case.value for case in PhysicalRecordingCase], required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--json-output", type=Path)
    return parser


def main() -> int:
    """Run validation for one physical recording report.

    Returns:
        Process exit status.
    """

    args = build_argument_parser().parse_args()
    findings = validate_recording_physical_report(case_key=args.case, path=args.report)
    payload = {
        "case": args.case,
        "report": str(args.report),
        "ok": not any(finding.severity == "error" for finding in findings),
        "findings": [asdict(finding) for finding in findings],
    }
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for finding in findings:
        stream = sys.stderr if finding.severity == "error" else sys.stdout
        print(f"{finding.severity.upper()} [{finding.case_key}] {finding.message}", file=stream)
    if payload["ok"]:
        print("physical recording report validation passed.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
