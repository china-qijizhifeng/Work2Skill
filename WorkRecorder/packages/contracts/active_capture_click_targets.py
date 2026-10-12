"""Contracts for safe semantic click target resolution."""

from __future__ import annotations

import re
from datetime import datetime

from pydantic import Field, field_validator, model_validator

from .base import ContractModel
from .common import BoundingBox, JsonScalar
from .enums import (
    ClickTargetConfidenceBand,
    ClickTargetResolutionStatus,
    ClickTargetSemanticKind,
    ClickTargetSourceKind,
    ClickTargetSuppressionReason,
)

_SENSITIVE_LABEL_PATTERN = re.compile(
    r"(should_not_leak|password|passwd|secret|token|bearer|api[_-]?key|"
    r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}|https?://\S*[?#]\S+)",
    re.IGNORECASE,
)


class ClickTargetResolverConfig(ContractModel):
    """Runtime knobs for click target resolution."""

    enabled: bool = True
    high_confidence_threshold: float = Field(default=0.78, ge=0.0, le=1.0)
    review_confidence_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    max_candidates: int = Field(default=8, ge=1, le=32)
    max_safe_label_chars: int = Field(default=80, ge=8, le=200)
    enabled_source_kinds: tuple[ClickTargetSourceKind, ...] = (
        ClickTargetSourceKind.A11Y_SNAPSHOT,
        ClickTargetSourceKind.WEB_DOM,
        ClickTargetSourceKind.OCR_BOX,
        ClickTargetSourceKind.COORDINATE_FALLBACK,
    )
    resolver_version: str = Field(default="click_target_resolver_v1", min_length=1)
    policy_version: str = Field(default="click_target_policy_v1", min_length=1)


class ClickTargetEvidenceAnchor(ContractModel):
    """Visible evidence pointer used to justify one target candidate."""

    keyframe_id: str | None = None
    event_id: str | None = None
    evidence_id: str | None = None
    artifact_id: str | None = None
    provider_key: str | None = None
    bbox: BoundingBox | None = None


class ClickTargetCandidate(ContractModel):
    """One bounded, sanitized candidate considered by the resolver."""

    candidate_id: str
    resolution_id: str
    action_id: str
    session_id: str
    source_kind: ClickTargetSourceKind
    semantic_kind: ClickTargetSemanticKind = ClickTargetSemanticKind.UNKNOWN
    safe_label: str | None = Field(default=None, max_length=200)
    label_fingerprint: str | None = None
    locator_fingerprint: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_band: ClickTargetConfidenceBand
    evidence_anchor: ClickTargetEvidenceAnchor | None = None
    bbox: BoundingBox | None = None
    suppression_reason: ClickTargetSuppressionReason | None = None
    diagnostics: dict[str, JsonScalar] = Field(default_factory=dict)
    created_at: datetime
    policy_version: str = Field(min_length=1)

    @field_validator("safe_label")
    @classmethod
    def reject_sensitive_safe_label(cls, value: str | None) -> str | None:
        if value is not None and _SENSITIVE_LABEL_PATTERN.search(value):
            raise ValueError("click target safe_label contains sensitive text")
        return value


class ClickTargetResolution(ContractModel):
    """Winning safe semantic target resolution for one action/version."""

    resolution_id: str
    action_id: str
    session_id: str
    status: ClickTargetResolutionStatus
    semantic_kind: ClickTargetSemanticKind = ClickTargetSemanticKind.UNKNOWN
    source_kind: ClickTargetSourceKind = ClickTargetSourceKind.COORDINATE_FALLBACK
    display_label: str | None = Field(default=None, max_length=200)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_band: ClickTargetConfidenceBand = ClickTargetConfidenceBand.UNAVAILABLE
    evidence_anchor: ClickTargetEvidenceAnchor | None = None
    bbox: BoundingBox | None = None
    candidate_ids: tuple[str, ...] = Field(default_factory=tuple)
    needs_review: bool = True
    suppression_reason: ClickTargetSuppressionReason | None = None
    input_fingerprint: str = Field(min_length=1)
    resolver_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    created_at: datetime
    updated_at: datetime
    diagnostics: dict[str, JsonScalar] = Field(default_factory=dict)

    @field_validator("display_label")
    @classmethod
    def reject_sensitive_display_label(cls, value: str | None) -> str | None:
        if value is not None and _SENSITIVE_LABEL_PATTERN.search(value):
            raise ValueError("click target display_label contains sensitive text")
        return value

    @model_validator(mode="after")
    def require_suppression_reason(self) -> "ClickTargetResolution":
        if self.status == ClickTargetResolutionStatus.SUPPRESSED and self.suppression_reason is None:
            raise ValueError("suppressed click target resolution requires suppression_reason")
        return self


class ClickTargetPublicView(ContractModel):
    """Safe target view consumable by Workbench, inspect, and skill projections."""

    resolution_id: str | None = None
    status: ClickTargetResolutionStatus = ClickTargetResolutionStatus.PENDING
    display_label: str = Field(default="目标待确认", min_length=1, max_length=80)
    semantic_kind: ClickTargetSemanticKind = ClickTargetSemanticKind.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_band: ClickTargetConfidenceBand = ClickTargetConfidenceBand.UNAVAILABLE
    source_badges: tuple[ClickTargetSourceKind, ...] = Field(default_factory=tuple)
    needs_review: bool = True
    evidence_keyframe_ids: tuple[str, ...] = Field(default_factory=tuple)
    has_coordinates: bool = False
    suppression_reason: ClickTargetSuppressionReason | None = None

    @field_validator("display_label")
    @classmethod
    def reject_sensitive_public_label(cls, value: str) -> str:
        if _SENSITIVE_LABEL_PATTERN.search(value):
            raise ValueError("click target public display_label contains sensitive text")
        return value
