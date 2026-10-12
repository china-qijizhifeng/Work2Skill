"""Read-time disclosure policy contracts.

These models describe what a caller may see after capture evidence has already
been persisted and policy-stamped. They intentionally do not replace ingest
policy; they build consumer views such as search cards, event inspection, and
raw artifact gates.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .active_capture import KeyframeInspectSummary
from .active_capture_inspect import ActiveCaptureInspectView
from .base import ContractModel
from .common import BoundingBox, JsonScalar
from .enums import (
    AccessScope,
    ArtifactRole,
    ArtifactType,
    DisclosureClass,
    DisclosureDecisionStatus,
    DisclosureField,
    DisclosureView,
    EvidenceKind,
    ProviderCaptureOutcomeStatus,
    ProviderKind,
    ProviderRouteRole,
    SourceType,
)
from .responses import SearchResultSource
from .system import SystemAppshotSnapshot


class DisclosureRule(ContractModel):
    """One SDK-configurable rule inside a disclosure profile."""

    rule_id: str = Field(min_length=1)
    view: DisclosureView
    disclosure_class: DisclosureClass
    artifact_types: tuple[ArtifactType, ...] = Field(default_factory=tuple)
    artifact_roles: tuple[ArtifactRole, ...] = Field(default_factory=tuple)
    evidence_kinds: tuple[EvidenceKind, ...] = Field(default_factory=tuple)
    allowed_scopes: tuple[AccessScope, ...] = Field(default_factory=tuple)
    max_chars: int | None = Field(default=None, ge=1)
    allow_raw: bool = False
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class DisclosureProfile(ContractModel):
    """Developer-facing disclosure SDK profile for an app/provider/source."""

    profile_key: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    version: str = Field(default="disclosure_policy_v1", min_length=1)
    provider_keys: tuple[str, ...] = Field(default_factory=tuple)
    app_names: tuple[str, ...] = Field(default_factory=tuple)
    source_types: tuple[SourceType, ...] = Field(default_factory=tuple)
    policy_tags: tuple[str, ...] = Field(default_factory=tuple)
    rules: tuple[DisclosureRule, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class DisclosureProfileOverride(ContractModel):
    """Workspace-owned disclosure profile override.

    Overrides are intentionally narrower than daemon code. A workspace may
    inherit a built-in profile, replace or add bounded text rules, and bind the
    profile to apps/providers. The daemon registry still sanitizes the result
    before it can affect reads.
    """

    profile_key: str = Field(min_length=1)
    extends_profile_key: str = Field(default="default.context_capture", min_length=1)
    display_name: str | None = None
    version: str = Field(default="workspace_disclosure_policy_v1", min_length=1)
    provider_keys: tuple[str, ...] | None = None
    app_names: tuple[str, ...] | None = None
    source_types: tuple[SourceType, ...] | None = None
    policy_tags: tuple[str, ...] | None = None
    replace_rules: bool = False
    rules: tuple[DisclosureRule, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class WorkspaceDisclosureConfig(ContractModel):
    """Workspace disclosure override file loaded by the daemon."""

    schema_version: int = Field(default=1, ge=1)
    profiles: tuple[DisclosureProfileOverride, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class HiddenArtifactSummary(ContractModel):
    """A hidden artifact disclosed only as safe metadata."""

    artifact_id: str | None = None
    artifact_type: ArtifactType
    role: ArtifactRole | str
    disclosure_class: DisclosureClass
    reason: str


class ArtifactDisclosureRef(ContractModel):
    """Safe artifact reference returned by event inspection views."""

    artifact_id: str
    citation_id: str | None = None
    artifact_type: ArtifactType
    role: ArtifactRole | str
    content_type: str | None = None
    byte_size: int | None = None
    sha256: str | None = None
    evidence_id: str | None = None
    disclosure_class: DisclosureClass
    requires_scope: AccessScope


class ReadableEvidenceView(ContractModel):
    """Bounded redacted text evidence returned by event inspection."""

    artifact_id: str
    citation_id: str | None = None
    artifact_type: ArtifactType
    role: ArtifactRole | str
    evidence_id: str | None = None
    disclosure_class: DisclosureClass
    text: str
    text_truncated: bool = False
    confidence: float | None = None


class DisclosureDecision(ContractModel):
    """Decision returned by DisclosurePolicyService."""

    decision_id: str
    status: DisclosureDecisionStatus
    view: DisclosureView
    profile_key: str
    resource_type: str
    resource_id: str | None = None
    allowed_scopes: tuple[AccessScope, ...] = Field(default_factory=tuple)
    delivered_fields: tuple[DisclosureField, ...] = Field(default_factory=tuple)
    hidden_artifacts: tuple[HiddenArtifactSummary, ...] = Field(default_factory=tuple)
    reason: str | None = None
    policy_version: str = "disclosure_policy_v1"
    details: dict[str, JsonScalar] = Field(default_factory=dict)


class EventSourceContributionView(ContractModel):
    """User-facing source/provider contribution inside an inspected event."""

    role: ProviderRouteRole
    app_name: str | None = None
    title: str | None = None
    source_kind: str | None = None
    provider_key: str | None = None
    provider_kind: ProviderKind | None = None
    status: ProviderCaptureOutcomeStatus | None = None
    surface_id: str | None = None
    rank: int | None = Field(default=None, ge=1)
    overlap_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_count: int = Field(default=0, ge=0)
    reason_code: str | None = None


class EventInspectView(ContractModel):
    """Policy-built event detail for explicit event_id inspection."""

    event_id: str
    captured_at: datetime
    source: SearchResultSource
    selection_bbox: BoundingBox | None = None
    system_appshot: SystemAppshotSnapshot | None = None
    canonical_text: str = ""
    canonical_text_truncated: bool = False
    clean_page_text: str = ""
    clean_page_text_truncated: bool = False
    source_contributions: tuple[EventSourceContributionView, ...] = Field(default_factory=tuple)
    keyframes: tuple[KeyframeInspectSummary, ...] = Field(default_factory=tuple)
    active_capture: ActiveCaptureInspectView | None = None
    readable_evidence: tuple[ReadableEvidenceView, ...] = Field(default_factory=tuple)
    raw_artifacts: tuple[ArtifactDisclosureRef, ...] = Field(default_factory=tuple)
    hidden_artifacts: tuple[HiddenArtifactSummary, ...] = Field(default_factory=tuple)
    disclosure_decision: DisclosureDecision


class RawArtifactResponse(ContractModel):
    """Raw artifact payload returned only by the explicit raw gate."""

    artifact_id: str
    event_id: str
    artifact_type: ArtifactType
    content_type: str | None = None
    byte_size: int
    sha256: str | None = None
    content_base64: str
    disclosure_decision: DisclosureDecision
