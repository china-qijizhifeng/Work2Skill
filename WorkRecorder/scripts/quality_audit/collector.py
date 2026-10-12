"""Repository-wide collection entry point for the quality audit."""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path

from .ast_helpers import module_line_count
from .checks import (
    line_count_findings,
    logging_findings,
    module_docstring_findings,
    public_api_docstring_findings,
    todo_findings,
    top_level_function_findings,
)
from .constants import DEFAULT_PATHS
from .discovery import iter_python_files
from .models import AuditConfig, FindingSeverity, QualityFinding, QualityMetrics, QualityReport, make_finding
from .typing_rules import typing_findings


def collect_repo_audit(
    repo_root: Path,
    *,
    paths: Sequence[str] = DEFAULT_PATHS,
    config: AuditConfig | None = None,
) -> QualityReport:
    """Collect maintainability and documentation findings for a repository.

    Args:
        repo_root: Repository root used for path discovery and reporting.
        paths: Relative paths to scan. Missing paths are ignored so the script
            can be reused in trimmed CI checkouts.
        config: Optional audit thresholds and feature flags.

    Returns:
        Structured report containing metrics and stable findings.
    """

    resolved_config = config or AuditConfig()
    python_files = tuple(iter_python_files(repo_root, paths=paths))
    findings: list[QualityFinding] = []
    total_lines = 0
    parsed_files = 0
    skipped_files = 0

    for file_path in python_files:
        text = file_path.read_text(encoding="utf-8")
        lines = text.splitlines()
        total_lines += len(lines)
        try:
            tree = ast.parse(text, filename=str(file_path))
        except SyntaxError as exc:
            findings.extend(line_count_findings(repo_root, file_path, len(lines), resolved_config))
            skipped_files += 1
            findings.append(
                make_finding(
                    repo_root,
                    file_path,
                    exc.lineno or 1,
                    FindingSeverity.VIOLATION,
                    "python.syntax_error",
                    f"Python parser failed: {exc.msg}.",
                )
            )
            continue
        parsed_files += 1
        effective_lines = module_line_count(tree, len(lines))
        findings.extend(line_count_findings(repo_root, file_path, effective_lines, resolved_config))
        findings.extend(module_docstring_findings(repo_root, file_path, tree, resolved_config))
        findings.extend(top_level_function_findings(repo_root, file_path, tree, resolved_config))
        findings.extend(public_api_docstring_findings(repo_root, file_path, tree, lines, resolved_config))
        findings.extend(typing_findings(repo_root, file_path, tree, lines, resolved_config))
        findings.extend(logging_findings(repo_root, file_path, tree))
        findings.extend(todo_findings(repo_root, file_path, lines))

    sorted_findings = tuple(sorted(findings, key=lambda item: (item.path, item.line, item.severity.value, item.code)))
    metrics = QualityMetrics(
        python_file_count=len(python_files),
        total_line_count=total_lines,
        parsed_file_count=parsed_files,
        skipped_file_count=skipped_files,
        warning_count=sum(1 for finding in sorted_findings if finding.severity == FindingSeverity.WARNING),
        violation_count=sum(1 for finding in sorted_findings if finding.severity == FindingSeverity.VIOLATION),
    )
    return QualityReport(repo_root=str(repo_root), metrics=metrics, findings=sorted_findings)
