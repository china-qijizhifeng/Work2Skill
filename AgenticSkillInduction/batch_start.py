"""Run the GUI skill extractor across a benchmark directory."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
HARNESS_NAME = "agentic_skill_induction"
MANIFEST_SCHEMA_VERSION = "1.0"


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract skills from every benchmark run directory.")
    parser.add_argument("benchmark_root", type=Path, help="Directory containing benchmark run directories.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=PROJECT_ROOT / "generated_skills" / HARNESS_NAME,
        help="Parent directory for per-run outputs.",
    )
    parser.add_argument("--output-suffix", default="-image-prompt", help="Suffix appended to each run name.")
    parser.add_argument("--config", type=Path, default=SCRIPT_DIR / "agent.yaml", help="Extractor agent YAML.")
    parser.add_argument("--env-file", type=Path, default=PROJECT_ROOT / ".env", help="Extractor credential file.")
    parser.add_argument(
        "--reasoning-effort",
        choices=("low", "medium", "high", "xhigh"),
        default="high",
        help="Reasoning effort passed to every extraction subprocess.",
    )
    parser.add_argument("--rerun-completed", action="store_true", help="Run tasks even when valid output already exists.")
    parser.add_argument("--nested-only", action="store_true", help="Only process runs below a task subdirectory.")
    parser.add_argument(
        "--nested-prefix",
        help="For nested runs, only process subdirectories whose name starts with this prefix; top-level runs remain included.",
    )
    parser.add_argument("--jobs", type=int, default=1, help="Number of extraction subprocesses to run concurrently.")
    return parser


def discover_runs(benchmark_root: Path) -> list[Path]:
    return sorted(manifest.parent for manifest in benchmark_root.rglob("run_manifest.json"))


def output_name(benchmark_root: Path, run_dir: Path, suffix: str) -> str:
    return "-".join(run_dir.relative_to(benchmark_root).parts) + suffix


def select_runs(
    benchmark_root: Path,
    runs: list[Path],
    *,
    nested_only: bool = False,
    nested_prefix: str | None = None,
) -> list[Path]:
    selected: list[Path] = []
    for run in runs:
        relative_parts = run.relative_to(benchmark_root).parts
        is_nested = len(relative_parts) > 1
        if nested_only and not is_nested:
            continue
        if is_nested and nested_prefix is not None and not run.name.startswith(nested_prefix):
            continue
        selected.append(run)
    return selected


def is_completed(output_dir: Path) -> bool:
    summary_path = output_dir / "run-summary.json"
    manifest_path = output_dir / "extraction-manifest.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    if not isinstance(summary, dict) or not isinstance(manifest, dict):
        return False
    summary_provenance = summary.get("provenance")
    manifest_provenance = manifest.get("provenance")
    if not isinstance(summary_provenance, dict) or not isinstance(manifest_provenance, dict):
        return False
    if (
        summary.get("status") != "completed"
        or summary.get("finalized") is not True
        or summary_provenance.get("harness") != HARNESS_NAME
        or manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or manifest_provenance.get("harness") != HARNESS_NAME
        or manifest_provenance != summary_provenance
    ):
        return False

    generated_skills = manifest.get("generated_skills")
    if not isinstance(generated_skills, list) or not generated_skills:
        return False
    resolved_output = output_dir.resolve(strict=False)
    skill_set_rows: list[str] = []
    for entry in generated_skills:
        if not isinstance(entry, dict):
            return False
        relative_path = entry.get("path")
        expected_hash = entry.get("sha256")
        if not isinstance(relative_path, str) or not isinstance(expected_hash, str):
            return False
        skill_path = (resolved_output / relative_path).resolve(strict=False)
        if not skill_path.is_relative_to(resolved_output) or not skill_path.is_file():
            return False
        if hashlib.sha256(skill_path.read_bytes()).hexdigest() != expected_hash:
            return False
        skill_set_rows.append(f"{relative_path}:{expected_hash}")
    actual_skill_set_hash = hashlib.sha256("\n".join(skill_set_rows).encode("utf-8")).hexdigest()
    if manifest.get("skill_set_sha256") != actual_skill_set_hash:
        return False
    return True


def run_extraction(
    run_dir: Path,
    output_dir: Path,
    config_path: Path,
    env_file: Path,
    reasoning_effort: str,
) -> int:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_DIR / "start.py"),
            str(run_dir),
            "--output-dir",
            str(output_dir),
            "--config",
            str(config_path),
            "--env-file",
            str(env_file),
            "--reasoning-effort",
            reasoning_effort,
        ],
        check=False,
    )
    return result.returncode


def main(argv: Sequence[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    benchmark_root = args.benchmark_root.expanduser().resolve(strict=True)
    output_root = args.output_root.expanduser().resolve(strict=False)
    config_path = args.config.expanduser().resolve(strict=True)
    env_file = args.env_file.expanduser().resolve(strict=True)
    runs = select_runs(
        benchmark_root,
        discover_runs(benchmark_root),
        nested_only=args.nested_only,
        nested_prefix=args.nested_prefix,
    )
    if not runs:
        raise RuntimeError(f"No benchmark runs containing run_manifest.json found under {benchmark_root}.")
    if args.jobs < 1:
        raise ValueError("--jobs must be at least 1.")

    completed: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    pending: list[tuple[int, Path, Path, str]] = []
    for index, run_dir in enumerate(runs, start=1):
        run_name = run_dir.relative_to(benchmark_root).as_posix()
        output_dir = output_root / output_name(benchmark_root, run_dir, args.output_suffix)
        if not args.rerun_completed and is_completed(output_dir):
            skipped.append(run_name)
            print(f"[{index}/{len(runs)}] Skip completed {run_name}", flush=True)
            continue

        pending.append((index, run_dir, output_dir, run_name))

    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures: dict[Future[int], tuple[int, Path, str]] = {}
        for index, run_dir, output_dir, run_name in pending:
            print(f"[{index}/{len(runs)}] Extract {run_name} -> {output_dir}", flush=True)
            future = executor.submit(
                run_extraction,
                run_dir,
                output_dir,
                config_path,
                env_file,
                args.reasoning_effort,
            )
            futures[future] = (index, output_dir, run_name)
        for future in as_completed(futures):
            index, output_dir, run_name = futures[future]
            returncode = future.result()
            if returncode == 0 and is_completed(output_dir):
                completed.append(run_name)
                print(f"[{index}/{len(runs)}] Completed {run_name}", flush=True)
            else:
                failed.append(run_name)
                print(f"[{index}/{len(runs)}] Failed {run_name} (exit {returncode})", flush=True)

    print(
        json.dumps(
            {
                "completed": sorted(completed),
                "skipped": sorted(skipped),
                "failed": sorted(failed),
                "total": len(runs),
            },
            ensure_ascii=True,
            indent=2,
        ),
        flush=True,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
