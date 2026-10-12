#!/usr/bin/env python3
"""Revise every legacy recording first, then build every revised benchmark."""

from __future__ import annotations

import argparse
import fnmatch
import json
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
SINGLE_REVISION_SCRIPT = SCRIPT_DIR / "revise_legacy_recording_time.py"
EXPECTED_MODES = ("normal", "event_only", "click_only")


@dataclass(frozen=True)
class TaskResult:
    task: str
    status: str
    detail: str | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "videos_root",
        type=Path,
        help="Source root containing direct exports and/or three-mode task directories.",
    )
    parser.add_argument(
        "--videos-output-root",
        type=Path,
        help="Revised video root (default: sibling videos_revise_time).",
    )
    parser.add_argument(
        "--benchmark-output-root",
        type=Path,
        help="Benchmark root (default: sibling benchmark_revise_time).",
    )
    parser.add_argument(
        "--pipeline-script",
        type=Path,
        help="highlight_then_benchmark.py (default: sibling code directory).",
    )
    parser.add_argument(
        "--task",
        action="append",
        default=[],
        help="Only process task names matching this shell pattern; repeatable.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing revised-video and benchmark task directories.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the two-phase commands without writing anything.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop at the first failed task instead of continuing and reporting failures.",
    )
    parser.add_argument(
        "--skip-revision",
        action="store_true",
        help="Skip videos -> videos_revise_time and benchmark existing revised tasks.",
    )
    parser.add_argument(
        "--skip-benchmark",
        action="store_true",
        help="Only create videos_revise_time; do not build benchmark_revise_time.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    videos_root = args.videos_root.expanduser().resolve()
    if not videos_root.is_dir():
        raise SystemExit(f"videos root is not a directory: {videos_root}")

    project_root = videos_root.parent
    videos_output_root = _resolved_or_default(
        args.videos_output_root,
        project_root / "videos_revise_time",
    )
    benchmark_output_root = _resolved_or_default(
        args.benchmark_output_root,
        project_root / "benchmark_revise_time",
    )
    pipeline_script = _resolved_or_default(
        args.pipeline_script,
        project_root / "code" / "highlight_then_benchmark.py",
    )
    if not SINGLE_REVISION_SCRIPT.is_file():
        raise SystemExit(f"single-task revision script not found: {SINGLE_REVISION_SCRIPT}")
    if not args.skip_benchmark and not pipeline_script.is_file():
        raise SystemExit(f"benchmark pipeline script not found: {pipeline_script}")

    tasks, invalid = discover_tasks(videos_root, patterns=args.task)
    if not tasks:
        raise SystemExit("no matching recording tasks found")
    if invalid:
        print("Skipping unrecognized task directories:", flush=True)
        for path, reason in invalid:
            print(f"  - {path.name}: {reason}", flush=True)

    print(
        f"Found {len(tasks)} task(s). Phase 1 revises all tasks; phase 2 benchmarks all revised tasks.",
        flush=True,
    )
    revision_results: list[TaskResult] = []
    benchmark_results: list[TaskResult] = []

    if not args.skip_revision:
        print("\n=== Phase 1/2: videos -> videos_revise_time ===", flush=True)
        for task in tasks:
            destination = videos_output_root / task.name
            if destination.exists() and not args.overwrite:
                revision_results.append(TaskResult(task.name, "skipped", "destination exists"))
                print(f"[skip] {task.name}: {destination}", flush=True)
                continue
            command = revision_command(
                task=task,
                videos_output_root=videos_output_root,
                benchmark_output_root=benchmark_output_root,
                pipeline_script=pipeline_script,
                overwrite=args.overwrite,
            )
            result = run_command(command, dry_run=args.dry_run)
            revision_results.append(
                TaskResult(task.name, "planned" if args.dry_run else ("completed" if result == 0 else "failed"))
            )
            if result != 0 and args.fail_fast:
                return _finish(
                    videos_output_root=videos_output_root,
                    revision_results=revision_results,
                    benchmark_results=benchmark_results,
                    dry_run=args.dry_run,
                )
    else:
        revision_results.extend(TaskResult(task.name, "skipped", "--skip-revision") for task in tasks)

    if not args.skip_benchmark:
        print("\n=== Phase 2/2: videos_revise_time -> benchmark_revise_time ===", flush=True)
        failed_revisions = {result.task for result in revision_results if result.status == "failed"}
        for task in tasks:
            revised_task = videos_output_root / task.name
            destination = benchmark_output_root / task.name
            if task.name in failed_revisions:
                benchmark_results.append(TaskResult(task.name, "skipped", "revision failed"))
                print(f"[skip] {task.name}: revision failed", flush=True)
                continue
            if not args.dry_run and not revised_task.is_dir():
                benchmark_results.append(TaskResult(task.name, "failed", "revised task missing"))
                print(f"[fail] {task.name}: revised task missing: {revised_task}", flush=True)
                if args.fail_fast:
                    break
                continue
            if destination.exists() and not args.overwrite:
                benchmark_results.append(TaskResult(task.name, "skipped", "destination exists"))
                print(f"[skip] {task.name}: {destination}", flush=True)
                continue
            command = benchmark_command(
                revised_task=revised_task,
                benchmark_output_root=benchmark_output_root,
                pipeline_script=pipeline_script,
                overwrite=args.overwrite,
            )
            result = run_command(command, dry_run=args.dry_run)
            benchmark_results.append(
                TaskResult(task.name, "planned" if args.dry_run else ("completed" if result == 0 else "failed"))
            )
            if result != 0 and args.fail_fast:
                break

    return _finish(
        videos_output_root=videos_output_root,
        revision_results=revision_results,
        benchmark_results=benchmark_results,
        dry_run=args.dry_run,
    )


def discover_tasks(
    videos_root: Path,
    *,
    patterns: list[str],
) -> tuple[list[Path], list[tuple[Path, str]]]:
    tasks: list[Path] = []
    invalid: list[tuple[Path, str]] = []
    for child in sorted(path for path in videos_root.iterdir() if path.is_dir()):
        if patterns and not any(fnmatch.fnmatchcase(child.name, pattern) for pattern in patterns):
            continue
        if (child / "recording.json").is_file():
            tasks.append(child)
            continue
        missing = [
            mode
            for mode in EXPECTED_MODES
            if len(
                [
                    variant
                    for variant in child.iterdir()
                    if variant.is_dir()
                    and variant.name.endswith(f"+{mode}")
                    and (variant / "recording.json").is_file()
                ]
            )
            != 1
        ]
        if missing:
            invalid.append((child, f"missing or duplicate modes: {', '.join(missing)}"))
        else:
            tasks.append(child)
    return tasks, invalid


def revision_command(
    *,
    task: Path,
    videos_output_root: Path,
    benchmark_output_root: Path,
    pipeline_script: Path,
    overwrite: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(SINGLE_REVISION_SCRIPT),
        str(task),
        "--videos-output-root",
        str(videos_output_root),
        "--benchmark-output-root",
        str(benchmark_output_root),
        "--pipeline-script",
        str(pipeline_script),
        "--skip-benchmark",
    ]
    if overwrite:
        command.append("--overwrite")
    return command


def benchmark_command(
    *,
    revised_task: Path,
    benchmark_output_root: Path,
    pipeline_script: Path,
    overwrite: bool,
) -> list[str]:
    command = [
        sys.executable,
        str(pipeline_script),
        str(revised_task),
        "--output-root",
        str(benchmark_output_root),
    ]
    if overwrite:
        command.append("--overwrite")
    return command


def run_command(command: list[str], *, dry_run: bool) -> int:
    print("$ " + shlex.join(command), flush=True)
    if dry_run:
        return 0
    return subprocess.run(command, check=False).returncode


def _finish(
    *,
    videos_output_root: Path,
    revision_results: list[TaskResult],
    benchmark_results: list[TaskResult],
    dry_run: bool,
) -> int:
    payload = {
        "revision": [asdict(result) for result in revision_results],
        "benchmark": [asdict(result) for result in benchmark_results],
    }
    if not dry_run:
        videos_output_root.mkdir(parents=True, exist_ok=True)
        report_path = videos_output_root / "batch_revision_report.json"
        report_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"\nReport: {report_path}", flush=True)
    failed = [
        result
        for result in (*revision_results, *benchmark_results)
        if result.status == "failed"
    ]
    print(
        f"Done: revisions={_status_counts(revision_results)}, "
        f"benchmarks={_status_counts(benchmark_results)}",
        flush=True,
    )
    if failed:
        print("Failed tasks:", flush=True)
        for result in failed:
            print(f"  - {result.task}: {result.detail or 'command failed'}", flush=True)
    return 1 if failed else 0


def _status_counts(results: list[TaskResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    return counts


def _resolved_or_default(value: Path | None, default: Path) -> Path:
    return value.expanduser().resolve() if value is not None else default.resolve()


if __name__ == "__main__":
    raise SystemExit(main())
