"""Normalize WorkRecorder Python imports and formatting with isort and Black."""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import Sequence

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATHS = ("scripts", "apps", "packages", "services", "tests")


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the code-normalization CLI parser.

    Returns:
        Configured parser for local and CI formatting workflows.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Run isort followed by Black over WorkRecorder Python code. Use "
            "--check in CI and no --check for local auto-fix normalization."
        )
    )
    parser.add_argument("paths", nargs="*", default=list(DEFAULT_PATHS), help="Repo-relative paths to normalize.")
    parser.add_argument("--check", action="store_true", help="Check formatting without writing changes.")
    parser.add_argument("--diff", action="store_true", help="Show formatter diffs.")
    parser.add_argument("--skip-isort", action="store_true", help="Run only Black.")
    parser.add_argument("--skip-black", action="store_true", help="Run only isort.")
    return parser


def main() -> int:
    """Execute import sorting and code formatting.

    Returns:
        Process exit code from the first failing formatter, or ``0`` when all
        selected tools succeed.
    """

    return _run_from_args(build_argument_parser().parse_args())


def main_with_args_for_test(argv: Sequence[str]) -> int:
    """Run the CLI with explicit argv for unit tests.

    Args:
        argv: Argument vector without the executable name.

    Returns:
        Process exit code that would be returned by ``main``.
    """

    return _run_from_args(build_argument_parser().parse_args(list(argv)))


def _run_from_args(args: argparse.Namespace) -> int:
    paths = _existing_paths(tuple(args.paths))
    if not paths:
        print("No existing paths selected for normalization.", file=sys.stderr)
        return 1

    if not args.skip_isort:
        isort_status = run_isort(paths=paths, check=args.check, diff=args.diff)
        if isort_status != 0:
            return isort_status
    if not args.skip_black:
        black_status = run_black(paths=paths, check=args.check, diff=args.diff)
        if black_status != 0:
            return black_status
    return 0


def run_isort(*, paths: Sequence[Path], check: bool = False, diff: bool = False) -> int:
    """Run isort for selected paths.

    Args:
        paths: Existing paths to pass to isort.
        check: Whether to use isort's check-only mode.
        diff: Whether to request textual diffs.

    Returns:
        isort process exit status.
    """

    command = [sys.executable, "-m", "isort", *(_string_paths(paths))]
    if check:
        command.append("--check-only")
    if diff:
        command.append("--diff")
    return _run_formatter(command, tool_name="isort")


def run_black(*, paths: Sequence[Path], check: bool = False, diff: bool = False) -> int:
    """Run Black for selected paths.

    Args:
        paths: Existing paths to pass to Black.
        check: Whether to use Black's check-only mode.
        diff: Whether to request textual diffs.

    Returns:
        Black process exit status.
    """

    command = [sys.executable, "-m", "black", *(_string_paths(paths))]
    if check:
        command.append("--check")
    if diff:
        command.append("--diff")
    return _run_formatter(command, tool_name="black")


def _existing_paths(paths: Sequence[str]) -> tuple[Path, ...]:
    existing: list[Path] = []
    for raw_path in paths:
        path = (REPO_ROOT / raw_path).resolve()
        if path.exists():
            existing.append(path)
        else:
            print(f"Skipping missing path: {raw_path}", file=sys.stderr)
    return tuple(existing)


def _string_paths(paths: Sequence[Path]) -> list[str]:
    return [str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path) for path in paths]


def _run_formatter(command: Sequence[str], *, tool_name: str) -> int:
    if importlib.util.find_spec(tool_name) is None:
        print(_missing_tool_message(tool_name), file=sys.stderr)
        return 127
    print("+ " + " ".join(command))
    completed = subprocess.run(command, cwd=REPO_ROOT, check=False)
    if completed.returncode == 1 and tool_name in {"black", "isort"}:
        return completed.returncode
    if completed.returncode == 0:
        return 0
    return completed.returncode


def _missing_tool_message(tool_name: str) -> str:
    return (
        f"{tool_name} is not installed in this environment. Run "
        "`uv sync --extra dev` first, then retry the normalization command."
    )


if __name__ == "__main__":
    raise SystemExit(main())
