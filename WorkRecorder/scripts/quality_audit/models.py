"""Typed report models for the WorkRecorder repository quality audit."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

from .constants import (
    DEFAULT_MAX_CLASS_LINES_WARNING,
    DEFAULT_MAX_FILE_LINES_VIOLATION,
    DEFAULT_MAX_FILE_LINES_WARNING,
    DEFAULT_MAX_FUNCTION_LINES_WARNING,
    DEFAULT_MAX_TOP_LEVEL_FUNCTIONS_VIOLATION,
    DEFAULT_MAX_TOP_LEVEL_FUNCTIONS_WARNING,
    DEFAULT_MIN_DOCSTRING_WORDS,
    DEFAULT_TOP_LONG_FILES,
)


class FindingSeverity(str, Enum):
    """Severity level emitted by the repository quality audit."""

    VIOLATION = "violation"
    WARNING = "warning"


@dataclass(slots=True, frozen=True)
class QualityFinding:
    """One repository-quality finding.

    Attributes:
        path: Repository-relative path to the affected file.
        line: One-based source line when available.
        severity: Whether the finding blocks strict mode.
        code: Stable machine-readable finding code.
        message: Human-readable explanation and suggested action.
    """

    path: str
    line: int
    severity: FindingSeverity
    code: str
    message: str


@dataclass(slots=True, frozen=True)
class QualityMetrics:
    """Summary metrics collected during a repository-quality audit.

    Attributes:
        python_file_count: Number of Python files selected for scanning.
        total_line_count: Total physical source lines across selected files.
        parsed_file_count: Number of files parsed successfully by ``ast``.
        skipped_file_count: Number of files skipped after syntax failures.
        warning_count: Number of non-blocking audit findings.
        violation_count: Number of strict-mode blocking audit findings.
    """

    python_file_count: int
    total_line_count: int
    parsed_file_count: int
    skipped_file_count: int
    warning_count: int
    violation_count: int


@dataclass(slots=True, frozen=True)
class QualityReport:
    """Structured repository-quality audit report.

    Attributes:
        repo_root: Absolute repository root scanned by the audit.
        metrics: Aggregate counters for the scan.
        findings: Stable, sorted findings emitted by all enabled rules.
    """

    repo_root: str
    metrics: QualityMetrics
    findings: tuple[QualityFinding, ...] = field(default_factory=tuple)

    @property
    def violations(self) -> tuple[QualityFinding, ...]:
        """Return all blocking findings.

        Returns:
            Findings whose severity is ``violation``.
        """

        return tuple(finding for finding in self.findings if finding.severity == FindingSeverity.VIOLATION)

    @property
    def warnings(self) -> tuple[QualityFinding, ...]:
        """Return all non-blocking findings.

        Returns:
            Findings whose severity is ``warning``.
        """

        return tuple(finding for finding in self.findings if finding.severity == FindingSeverity.WARNING)

    @property
    def has_blocking_findings(self) -> bool:
        """Report whether strict mode should fail.

        Returns:
            ``True`` when at least one violation was collected.
        """

        return bool(self.violations)

    def to_json_text(self) -> str:
        """Serialize the report as stable JSON.

        Returns:
            UTF-8 friendly JSON text suitable for CI artifacts.
        """

        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


@dataclass(slots=True, frozen=True)
class AuditConfig:
    """Thresholds and feature flags used by the quality audit.

    Attributes:
        max_file_lines_warning: File length that emits a warning.
        max_file_lines_violation: File length that blocks strict mode.
        max_class_lines_warning: Class length that suggests extraction.
        max_function_lines_warning: Function length that suggests extraction.
        max_top_level_functions_warning: Top-level function count that suggests
            extracting cohesive service classes.
        max_top_level_functions_violation: Top-level function count that blocks
            strict audits.
        min_docstring_words: Minimum meaningful docstring word count.
        require_test_docstrings: Whether test modules/helpers are documented.
        require_test_typing: Whether typing checks should include tests.
        enable_typing_checks: Whether AST-level typing drift rules run.
        top_long_files: Number of long-file findings shown in terminal output.
    """

    max_file_lines_warning: int = DEFAULT_MAX_FILE_LINES_WARNING
    max_file_lines_violation: int = DEFAULT_MAX_FILE_LINES_VIOLATION
    max_class_lines_warning: int = DEFAULT_MAX_CLASS_LINES_WARNING
    max_function_lines_warning: int = DEFAULT_MAX_FUNCTION_LINES_WARNING
    max_top_level_functions_warning: int = DEFAULT_MAX_TOP_LEVEL_FUNCTIONS_WARNING
    max_top_level_functions_violation: int = DEFAULT_MAX_TOP_LEVEL_FUNCTIONS_VIOLATION
    min_docstring_words: int = DEFAULT_MIN_DOCSTRING_WORDS
    require_test_docstrings: bool = False
    require_test_typing: bool = False
    enable_typing_checks: bool = True
    top_long_files: int = DEFAULT_TOP_LONG_FILES


def make_finding(
    repo_root: Path,
    file_path: Path,
    line: int,
    severity: FindingSeverity,
    code: str,
    message: str,
) -> QualityFinding:
    """Create one repository-relative finding record.

    Args:
        repo_root: Repository root used for relative path rendering.
        file_path: Absolute path to the affected file.
        line: One-based source line.
        severity: Finding severity.
        code: Stable machine-readable rule code.
        message: Human-readable finding detail.

    Returns:
        Structured finding with a repository-relative path.
    """

    return QualityFinding(
        path=str(file_path.relative_to(repo_root)),
        line=line,
        severity=severity,
        code=code,
        message=message,
    )
