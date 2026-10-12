"""Typed policy-before-index contracts for safe searchable projections.

These models form the cross-module boundary between feature-specific text
collectors and the indexing service, keeping suppression decisions, redaction
state, source metadata, and audit summaries explicit instead of passing loose
text dictionaries into search backends.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from packages.contracts import (
    AgentVisibleField,
    ArtifactType,
    ContextEvent,
    DisclosureClass,
    EventStatus,
    EvidenceKind,
    EvidenceSensitivity,
    IndexPolicyDecisionStatus,
    IndexSuppressionReason,
    RedactionState,
    SearchFieldKind,
    SensitiveSurfaceType,
)
from packages.contracts.base import ContractModel
from packages.contracts.common import JsonScalar


class IndexableTextSource(ContractModel):
    """One candidate text source before policy-before-index processing."""

    event: ContextEvent
    field_kind: SearchFieldKind
    text: str
    captured_at: datetime
    evidence_id: str | None = None
    artifact_id: str | None = None
    provider_key: str | None = None
    source_uri: str | None = None
    observed_at: datetime | None = None
    extractor_name: str | None = None
    extractor_version: str | None = None
    disclosure_class: DisclosureClass = DisclosureClass.SAFE_METADATA
    evidence_kind: EvidenceKind | None = None
    artifact_type: ArtifactType | None = None
    sensitivity: EvidenceSensitivity = EvidenceSensitivity.INTERNAL
    redaction_state: RedactionState = RedactionState.REDACTED
    event_status: EventStatus = EventStatus.AGENT_READY
    sensitive_surface_type: SensitiveSurfaceType = SensitiveSurfaceType.NONE
    workspace_id: str | None = None
    agent_visible_fields: tuple[AgentVisibleField, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class SafeIndexPolicyConfig(ContractModel):
    """Runtime knobs for policy-before-index projections."""

    policy_version: str = Field(default="index_policy_v1", min_length=1)
    max_text_chars: int = Field(default=256_000, ge=1, le=10_000_000)
    sensitive_title_fragments: tuple[str, ...] = (
        "password",
        "secret",
        "token",
        "credential",
        "private browsing",
        "incognito",
        "keychain",
        "security",
    )


class IndexPolicyDecision(ContractModel):
    """Auditable decision for one candidate text source."""

    decision_id: str
    status: IndexPolicyDecisionStatus
    suppression_reason: IndexSuppressionReason = IndexSuppressionReason.NONE
    sensitive_surface_type: SensitiveSurfaceType = SensitiveSurfaceType.NONE
    source_text_hash: str
    output_text_hash: str | None = None
    redaction_state: RedactionState = RedactionState.REDACTED
    agent_visible_fields: tuple[AgentVisibleField, ...] = Field(default_factory=tuple)
    policy_version: str = "index_policy_v1"
    details: dict[str, JsonScalar] = Field(default_factory=dict)


class SafeIndexProjection(ContractModel):
    """Policy-approved or suppressed index projection for one source."""

    source: IndexableTextSource
    decision: IndexPolicyDecision
    text: str = ""


class IndexPolicyAuditSummary(ContractModel):
    """Compact aggregate result for logs and receipts."""

    allowed_count: int = Field(default=0, ge=0)
    redacted_count: int = Field(default=0, ge=0)
    suppressed_count: int = Field(default=0, ge=0)
    policy_version: str = "index_policy_v1"


class SafeIndexProjectionBatch(ContractModel):
    """Batch consumed by the index service after policy-before-index."""

    event_id: str
    capture_run_id: str | None = None
    projections: tuple[SafeIndexProjection, ...] = Field(default_factory=tuple)
    replace_event: bool = True
    replace_chunk_prefixes: tuple[str, ...] = Field(default_factory=tuple)
    audit: IndexPolicyAuditSummary = Field(default_factory=IndexPolicyAuditSummary)
