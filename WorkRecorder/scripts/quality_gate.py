"""Run the WorkRecorder repository quality gate."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REPORT_DIR = REPO_ROOT / ".qa" / "reports"


@dataclass(frozen=True, slots=True)
class GateStep:
    """One command in the quality gate.

    Attributes:
        name: Human-readable step name printed in terminal output.
        command: Command vector executed from the repository root.
        required: Whether a non-zero exit status should fail the full gate.
        working_dir: Directory where the command should run.
    """

    name: str
    command: tuple[str, ...]
    required: bool = True
    working_dir: Path = REPO_ROOT


def build_argument_parser() -> argparse.ArgumentParser:
    """Build CLI arguments for the quality gate.

    Returns:
        Configured argument parser.
    """

    parser = argparse.ArgumentParser(
        description="Run WorkRecorder formatting, static-site, and repository quality checks."
    )
    parser.add_argument("--fix", action="store_true", help="Run Python formatters in write mode before checks.")
    parser.add_argument("--skip-swift", action="store_true", help="Skip Swift tests for the macOS capture companion.")
    parser.add_argument(
        "--skip-node", action="store_true", help="Skip Node syntax checks for environments without Node."
    )
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    return parser


def main() -> int:
    """Run the configured quality gate.

    Returns:
        Process exit status.
    """

    args = build_argument_parser().parse_args()
    if args.fix:
        fix_status = _run_step(GateStep(name="python normalize", command=_normalize_command(check=False)))
        if fix_status != 0:
            return fix_status
    _repair_local_python_entrypoints()

    steps = _build_check_steps(report_dir=args.report_dir, skip_node=args.skip_node, skip_swift=args.skip_swift)
    failures = 0
    for step in steps:
        status = _run_step(step)
        if status != 0 and step.required:
            failures += 1
    if failures:
        print(f"\nQuality gate failed: {failures} required step(s) failed.", file=sys.stderr)
        return 1
    print("\nQuality gate passed.")
    return 0


def _build_check_steps(*, report_dir: Path, skip_node: bool, skip_swift: bool) -> tuple[GateStep, ...]:
    report_dir.mkdir(parents=True, exist_ok=True)
    steps = [
        GateStep(name="python normalize check", command=_normalize_command(check=True)),
        GateStep(
            name="python ruff check",
            command=(sys.executable, "-m", "ruff", "check", "apps", "packages", "services", "scripts", "tests"),
        ),
        GateStep(name="python mypy", command=(sys.executable, "-m", "mypy")),
        GateStep(name="python pyright", command=(sys.executable, "-m", "pyright", "-p", "pyrightconfig.json")),
        GateStep(name="python pytest", command=(sys.executable, "-m", "pytest", "-q")),
        GateStep(
            name="python quality audit",
            command=(
                sys.executable,
                "-m",
                "scripts.audit_repo_quality",
                "--strict",
                "--max-findings",
                "80",
                "--json-output",
                str(report_dir / "python-quality.json"),
            ),
        ),
        GateStep(
            name="python bytecode compile",
            command=(sys.executable, "-m", "compileall", "-q", "apps", "packages", "services", "scripts"),
        ),
    ]
    if not skip_node and shutil.which("node") and shutil.which("npm"):
        steps.append(GateStep(name="site build", command=("npm", "--prefix", "site", "run", "build")))
        steps.append(GateStep(name="site check", command=("npm", "--prefix", "site", "run", "check")))
        steps.append(
            GateStep(
                name="static site audit",
                command=(
                    sys.executable,
                    "-m",
                    "scripts.audit_static_site",
                    "--site-dir",
                    "site/dist",
                    "--json-output",
                    str(report_dir / "static-site.json"),
                ),
            )
        )
    elif not skip_node:
        missing_tool = "node" if not shutil.which("node") else "npm"
        steps.append(
            GateStep(
                name=f"site build ({missing_tool} unavailable)",
                command=("npm", "--prefix", "site", "run", "build"),
                required=False,
            )
        )
        steps.append(
            GateStep(
                name=f"site check ({missing_tool} unavailable)",
                command=("npm", "--prefix", "site", "run", "check"),
                required=False,
            )
        )
        steps.append(
            GateStep(
                name="static site audit",
                command=(
                    sys.executable,
                    "-m",
                    "scripts.audit_static_site",
                    "--site-dir",
                    "site/dist",
                    "--json-output",
                    str(report_dir / "static-site.json"),
                ),
                required=False,
            )
        )
    extension_dir = REPO_ROOT / "apps" / "browser_extension"
    if not skip_node and extension_dir.exists() and shutil.which("npm"):
        steps.append(
            GateStep(name="browser extension typecheck", command=("npm", "run", "typecheck"), working_dir=extension_dir)
        )
        steps.append(
            GateStep(name="browser extension build", command=("npm", "run", "build"), working_dir=extension_dir)
        )
        steps.append(GateStep(name="browser extension test", command=("npm", "test"), working_dir=extension_dir))
    swift_package_dir = REPO_ROOT / "apps" / "macos_capture"
    if not skip_swift and swift_package_dir.exists() and shutil.which("swift"):
        steps.append(
            GateStep(
                name="macOS Swift structure audit",
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
                    str(report_dir / "swift-quality.json"),
                ),
            )
        )
        steps.append(
            GateStep(
                name="macOS capture swift test",
                command=("swift", "test"),
                working_dir=swift_package_dir,
            )
        )
        steps.append(
            GateStep(
                name="macOS Workbench snapshots",
                command=(
                    "env",
                    "WORKRECORDER_WRITE_WORKBENCH_SNAPSHOTS=1",
                    "swift",
                    "test",
                    "--filter",
                    "WorkbenchRuntimeTests/workbenchSnapshotsRenderPrimaryPages",
                ),
                working_dir=swift_package_dir,
            )
        )
        steps.append(
            GateStep(
                name="macOS recording review snapshots",
                command=(
                    "env",
                    "WORKRECORDER_WRITE_WORKBENCH_SNAPSHOTS=1",
                    "swift",
                    "test",
                    "--filter",
                    (
                        "WorkbenchRuntimeTests/"
                        "recordingReviewWindowSnapshotsCoverLargeReviewScenarios|"
                        "WorkbenchRuntimeTests/"
                        "recordingReviewWindowLoadedPlaybackSnapshotUsesLargeReviewRoute"
                    ),
                ),
                working_dir=swift_package_dir,
            )
        )
        steps.append(
            GateStep(
                name="macOS Workbench snapshot verify",
                command=(
                    sys.executable,
                    "-m",
                    "scripts.verify_workbench_snapshots",
                    "--root",
                    str(REPO_ROOT / ".qa" / "workbench"),
                    "--json",
                    str(REPO_ROOT / ".qa" / "workbench" / "facts.json"),
                ),
            )
        )
        steps.append(
            GateStep(
                name="macOS capture HUD snapshots",
                command=(
                    "swift",
                    "run",
                    "WorkRecorderCaptureSnapshots",
                    "--output",
                    str(REPO_ROOT / ".qa" / "capture-hud"),
                ),
                working_dir=swift_package_dir,
            )
        )
        steps.append(
            GateStep(
                name="macOS capture HUD snapshot verify",
                command=(
                    sys.executable,
                    "-m",
                    "scripts.verify_capture_hud_snapshots",
                    "--root",
                    str(REPO_ROOT / ".qa" / "capture-hud"),
                ),
            )
        )
        steps.append(
            GateStep(
                name="WorkRecorder.app package verify",
                command=(sys.executable, "scripts/package_workrecorder_app.py", "--dev", "--verify"),
            )
        )
        steps.append(
            GateStep(
                name="WorkRecorder.app distribution runtime verify",
                command=(
                    sys.executable,
                    "scripts/package_workrecorder_distribution.py",
                    "--dev",
                    "--skip-app-build",
                    "--verify",
                    "--archive",
                    "none",
                ),
            )
        )
    elif not skip_swift and swift_package_dir.exists():
        steps.append(
            GateStep(
                name="macOS capture swift test",
                command=("swift", "test"),
                required=False,
                working_dir=swift_package_dir,
            )
        )
    return tuple(steps)


def _normalize_command(*, check: bool) -> tuple[str, ...]:
    command = [sys.executable, "-m", "scripts.normalize_code"]
    if check:
        command.extend(["--check", "--diff"])
    return tuple(command)


def _run_step(step: GateStep) -> int:
    print(f"\n==> {step.name}")
    print("+ " + " ".join(step.command))
    completed = subprocess.run(step.command, cwd=step.working_dir, check=False)
    if completed.returncode != 0:
        level = "required" if step.required else "optional"
        print(f"{step.name} failed ({level}) with exit code {completed.returncode}.", file=sys.stderr)
    return completed.returncode


def _repair_local_python_entrypoints() -> None:
    try:
        from scripts.repair_uv_editable_install import repair_macos_hidden_pth_files
    except ImportError:
        return
    repair_macos_hidden_pth_files(REPO_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
