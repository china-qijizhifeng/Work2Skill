"""Command-line interface for the repository quality audit."""

from __future__ import annotations

import argparse
from pathlib import Path

from .collector import collect_repo_audit
from .constants import (
    DEFAULT_MAX_CLASS_LINES_WARNING,
    DEFAULT_MAX_FILE_LINES_VIOLATION,
    DEFAULT_MAX_FILE_LINES_WARNING,
    DEFAULT_MAX_FINDINGS,
    DEFAULT_MAX_FUNCTION_LINES_WARNING,
    DEFAULT_MAX_TOP_LEVEL_FUNCTIONS_VIOLATION,
    DEFAULT_MAX_TOP_LEVEL_FUNCTIONS_WARNING,
    DEFAULT_MIN_DOCSTRING_WORDS,
    DEFAULT_PATHS,
    DEFAULT_TOP_LONG_FILES,
)
from .models import AuditConfig, FindingSeverity, QualityReport

REPO_ROOT = Path(__file__).resolve().parents[2]


def format_report(report: QualityReport, *, top_long_files: int = 15, max_findings: int = DEFAULT_MAX_FINDINGS) -> str:
    """Format an audit report for terminal output.

    Args:
        report: Structured report returned by ``collect_repo_audit``.
        top_long_files: Maximum number of long-file findings to show.
        max_findings: Maximum number of detailed findings to print. Use ``0``
            to print every finding.

    Returns:
        Human-readable report text.
    """

    lines = [
        "WorkRecorder repository quality audit",
        f"repo: {report.repo_root}",
        (
            "metrics: "
            f"{report.metrics.python_file_count} files, "
            f"{report.metrics.total_line_count} lines, "
            f"{report.metrics.violation_count} violation(s), "
            f"{report.metrics.warning_count} warning(s)"
        ),
    ]
    long_file_findings = [
        finding
        for finding in report.findings
        if finding.code in {"module.too_long.warning", "module.too_long.violation"}
    ][:top_long_files]
    if long_file_findings:
        lines.extend(["", "Longest file findings:"])
        lines.extend(f"- {finding.path}: {finding.message}" for finding in long_file_findings)
    if report.findings:
        lines.extend(["", "Findings:"])
        printed_findings = report.findings if max_findings == 0 else report.findings[:max_findings]
        for finding in printed_findings:
            location = f"{finding.path}:{finding.line}" if finding.line else finding.path
            lines.append(f"- [{finding.severity.value}] {finding.code} {location} - {finding.message}")
        omitted_count = len(report.findings) - len(printed_findings)
        if omitted_count > 0:
            lines.append(
                f"... {omitted_count} more finding(s) omitted from terminal output. "
                "Use --max-findings 0 or --json-output for the full report."
            )
    else:
        lines.extend(["", "No quality findings. Tiny confetti, very professional."])
    return "\n".join(lines)


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the repository-quality audit CLI parser.

    Returns:
        Configured argument parser.
    """

    parser = argparse.ArgumentParser(
        description=(
            "Scan WorkRecorder Python code for oversized modules, thin docstrings, missing "
            "Args/Returns/Attributes detail, broad exception handlers without "
            "logging, typing drift, and TODO/FIXME debt."
        )
    )
    parser.add_argument("paths", nargs="*", default=list(DEFAULT_PATHS), help="Repo-relative paths to scan.")
    parser.add_argument("--json-output", type=Path, default=None, help="Optional JSON artifact path.")
    parser.add_argument("--strict", action="store_true", help="Exit with status 1 when violations are found.")
    parser.add_argument(
        "--include-tests-docstrings", action="store_true", help="Apply public API docstring checks to tests."
    )
    parser.add_argument("--include-tests-typing", action="store_true", help="Apply typing checks to tests.")
    parser.add_argument("--disable-typing-checks", action="store_true", help="Skip AST-level typing checks.")
    parser.add_argument("--max-file-lines-warning", type=int, default=DEFAULT_MAX_FILE_LINES_WARNING)
    parser.add_argument("--max-file-lines-violation", type=int, default=DEFAULT_MAX_FILE_LINES_VIOLATION)
    parser.add_argument("--max-class-lines-warning", type=int, default=DEFAULT_MAX_CLASS_LINES_WARNING)
    parser.add_argument("--max-function-lines-warning", type=int, default=DEFAULT_MAX_FUNCTION_LINES_WARNING)
    parser.add_argument("--max-top-level-functions-warning", type=int, default=DEFAULT_MAX_TOP_LEVEL_FUNCTIONS_WARNING)
    parser.add_argument(
        "--max-top-level-functions-violation", type=int, default=DEFAULT_MAX_TOP_LEVEL_FUNCTIONS_VIOLATION
    )
    parser.add_argument("--min-docstring-words", type=int, default=DEFAULT_MIN_DOCSTRING_WORDS)
    parser.add_argument("--top-long-files", type=int, default=DEFAULT_TOP_LONG_FILES)
    parser.add_argument(
        "--max-findings",
        type=int,
        default=DEFAULT_MAX_FINDINGS,
        help="Maximum detailed findings to print; 0 prints all.",
    )
    return parser


def main() -> int:
    """Run the repository-quality audit command.

    Returns:
        Process exit status. Strict mode fails only on violations so teams can
        burn down warnings incrementally.
    """

    args = build_argument_parser().parse_args()
    config = AuditConfig(
        max_file_lines_warning=args.max_file_lines_warning,
        max_file_lines_violation=args.max_file_lines_violation,
        max_class_lines_warning=args.max_class_lines_warning,
        max_function_lines_warning=args.max_function_lines_warning,
        max_top_level_functions_warning=args.max_top_level_functions_warning,
        max_top_level_functions_violation=args.max_top_level_functions_violation,
        min_docstring_words=args.min_docstring_words,
        require_test_docstrings=args.include_tests_docstrings,
        require_test_typing=args.include_tests_typing,
        enable_typing_checks=not args.disable_typing_checks,
        top_long_files=args.top_long_files,
    )
    report = collect_repo_audit(REPO_ROOT, paths=tuple(args.paths), config=config)
    print(format_report(report, top_long_files=config.top_long_files, max_findings=args.max_findings))
    if args.json_output is not None:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(report.to_json_text(), encoding="utf-8")
    return 1 if args.strict and report.has_blocking_findings else 0
