"""Compatibility wrapper for the WorkRecorder repository quality audit."""

from __future__ import annotations

if __package__:
    from scripts.quality_audit.cli import REPO_ROOT, build_argument_parser, format_report, main
    from scripts.quality_audit.collector import collect_repo_audit
    from scripts.quality_audit.models import AuditConfig, FindingSeverity, QualityFinding, QualityMetrics, QualityReport
else:
    from quality_audit.cli import REPO_ROOT, build_argument_parser, format_report, main
    from quality_audit.collector import collect_repo_audit
    from quality_audit.models import AuditConfig, FindingSeverity, QualityFinding, QualityMetrics, QualityReport

__all__ = [
    "AuditConfig",
    "FindingSeverity",
    "QualityFinding",
    "QualityMetrics",
    "QualityReport",
    "REPO_ROOT",
    "build_argument_parser",
    "collect_repo_audit",
    "format_report",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
