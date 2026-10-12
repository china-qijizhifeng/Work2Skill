"""Shared policy-before-index helpers for safe search writes.

The package exposes typed contracts and reusable projection services so
capture-specific features can add searchable text without bypassing redaction,
sensitive-surface suppression, or auditable index policy decisions.
"""

from .contracts import (
    IndexableTextSource,
    IndexPolicyAuditSummary,
    IndexPolicyDecision,
    SafeIndexPolicyConfig,
    SafeIndexProjection,
    SafeIndexProjectionBatch,
)
from .service import (
    SafeIndexProjectionService,
    SafeTextProjectionBuilder,
    SensitiveSurfaceDetector,
    SuppressionPolicy,
    TextRedactionStrategy,
)

__all__ = [
    "IndexPolicyAuditSummary",
    "IndexPolicyDecision",
    "IndexableTextSource",
    "SafeIndexProjection",
    "SafeIndexProjectionBatch",
    "SafeIndexPolicyConfig",
    "SafeIndexProjectionService",
    "SafeTextProjectionBuilder",
    "SensitiveSurfaceDetector",
    "SuppressionPolicy",
    "TextRedactionStrategy",
]
