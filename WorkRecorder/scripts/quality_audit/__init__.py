"""Reusable building blocks for the WorkRecorder repository quality audit."""

from .cli import build_argument_parser, format_report, main
from .collector import collect_repo_audit
from .models import AuditConfig, FindingSeverity, QualityFinding, QualityMetrics, QualityReport

__all__ = [
    "AuditConfig",
    "FindingSeverity",
    "QualityFinding",
    "QualityMetrics",
    "QualityReport",
    "build_argument_parser",
    "collect_repo_audit",
    "format_report",
    "main",
]
