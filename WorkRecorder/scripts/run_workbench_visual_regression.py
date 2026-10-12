"""Run repeated Workbench snapshot generation and visual-fact verification."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.verify_workbench_snapshots import verify


def _run(cmd: list[str], *, cwd: Path, env: dict[str, str]) -> None:
    """Run one required subprocess for the Workbench visual regression loop.

    Args:
        cmd: Command vector to execute.
        cwd: Working directory for the subprocess.
        env: Environment variables passed to the subprocess.

    Raises:
        subprocess.CalledProcessError: If the subprocess exits non-zero.
    """

    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def main() -> None:
    """Run repeated Workbench snapshot generation and verification.

    The loop is a stability/regression harness rather than a design-round
    counter. Each iteration renders the Workbench snapshots, verifies visual
    facts, copies artifacts to a numbered output folder, and writes a manifest.

    Raises:
        subprocess.CalledProcessError: If Swift snapshot generation fails.
        SystemExit: If the verifier rejects the generated screenshots.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--workbench-root", type=Path, default=Path(".qa/workbench"))
    parser.add_argument("--output", type=Path, default=Path(".qa/workbench-regression"))
    args = parser.parse_args()

    repo = Path.cwd()
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, object]] = []
    env = os.environ.copy()
    env["WORKRECORDER_WRITE_WORKBENCH_SNAPSHOTS"] = "1"

    for index in range(1, args.rounds + 1):
        started = time.time()
        _run(
            [
                "swift",
                "test",
                "--package-path",
                "apps/macos_capture",
                "--filter",
                "WorkbenchRuntimeTests/workbenchSnapshotsRenderPrimaryPages",
            ],
            cwd=repo,
            env=env,
        )
        _run(
            [
                "swift",
                "test",
                "--package-path",
                "apps/macos_capture",
                "--filter",
                (
                    "WorkbenchRuntimeTests/"
                    "recordingReviewWindowSnapshotsCoverLargeReviewScenarios|"
                    "WorkbenchRuntimeTests/"
                    "recordingReviewWindowLoadedPlaybackSnapshotUsesLargeReviewRoute"
                ),
            ],
            cwd=repo,
            env=env,
        )
        facts = verify(args.workbench_root)
        round_dir = output / f"round-{index:02d}"
        if round_dir.exists():
            shutil.rmtree(round_dir)
        shutil.copytree(args.workbench_root, round_dir)
        fact_payload = [fact.__dict__ for fact in facts]
        (round_dir / "facts.json").write_text(json.dumps(fact_payload, indent=2), encoding="utf-8")
        manifest.append(
            {
                "round": index,
                "duration_seconds": round(time.time() - started, 3),
                "snapshot_count": len(facts),
                "overview_selected": next(
                    (item for item in fact_payload if item["file"] == "overview-selected.png"),
                    None,
                ),
            }
        )

    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Completed {args.rounds} Workbench visual regression rounds in {output}")


if __name__ == "__main__":
    main()
