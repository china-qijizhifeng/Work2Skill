"""Auditable event capture protocol contracts.

These models are the daemon-owned ingest IR for screenshot-triggered context
capture. They intentionally sit above provider-specific payloads and below the
consumer-facing context bundle API.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import ContractModel
from .capture import ProviderRoutePlan, SelectionGeometry
from .common import BoundingBox, DetectedSurface, JsonScalar, SourceBinding, TextRange
from .enums import (
    AccessScope,
    ArtifactIngestState,
    ArtifactRole,
    ArtifactType,
    EventType,
    EvidenceKind,
    EvidencePhase,
    EvidenceSensitivity,
    EvidenceTrustState,
    ProviderCapability,
    ProviderCaptureOutcomeStatus,
    ProviderCommandStatus,
    ProviderKind,
    ProviderMode,
    ProviderRouteRole,
    RedactionState,
    SourceType,
)
from .events import ContextEvent, TriggerEnvelope
from .jobs import CaptureJob


class ExtractorRef(ContractModel):
    """Extractor or provider component that produced a payload."""

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)


class EvidenceLocator(ContractModel):
    """Stable location of evidence inside its native source and artifact."""

    source_uri: str = Field(min_length=1)
    source_type: SourceType
    coordinate_space: str | None = None
    bbox: BoundingBox | None = None
    text_range: TextRange | None = None
    selector: str | None = None
    path: str | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class EvidenceProvenance(ContractModel):
    """Provider, command, and source lineage for one evidence record."""

    provider_key: str = Field(min_length=1)
    provider_kind: ProviderKind
    provider_session_id: str | None = None
    command_id: str | None = None
    route_id: str | None = None
    source_binding_id: str | None = None
    parent_evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    input_artifact_ids: tuple[str, ...] = Field(default_factory=tuple)
    extractor: ExtractorRef


class EvidencePayloadRef(ContractModel):
    """Inline payload or persisted blob reference for evidence content."""

    content_type: str = Field(min_length=1)
    inline_content: str | None = None
    storage_uri: str | None = None
    byte_size: int | None = Field(default=None, ge=0)
    sha256: str | None = None
    payload_schema: str | None = None
    payload_version: str = "1"


class EvidenceDraft(ContractModel):
    """Provider-produced evidence claim before daemon policy stamping."""

    phase: EvidencePhase = EvidencePhase.CAPTURED
    kind: EvidenceKind
    artifact_type: ArtifactType
    role: ArtifactRole
    payload: EvidencePayloadRef
    locator: EvidenceLocator
    observed_at: datetime
    captured_at: datetime
    provenance: EvidenceProvenance
    sensitivity: EvidenceSensitivity = EvidenceSensitivity.INTERNAL
    trust_state_claim: EvidenceTrustState = EvidenceTrustState.UNTRUSTED
    redaction_state_claim: RedactionState = RedactionState.NONE
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class EvidenceRecord(ContractModel):
    """Persisted auditable evidence record owned by a context event."""

    evidence_id: str
    event_id: str
    capture_run_id: str
    phase: EvidencePhase
    kind: EvidenceKind
    artifact_id: str | None
    artifact_type: ArtifactType
    role: ArtifactRole
    payload: EvidencePayloadRef
    locator: EvidenceLocator
    observed_at: datetime
    captured_at: datetime
    ingested_at: datetime
    provenance: EvidenceProvenance
    sensitivity: EvidenceSensitivity
    trust_state: EvidenceTrustState
    ingest_state: ArtifactIngestState
    redaction_state: RedactionState
    allowed_scopes: tuple[AccessScope, ...] = Field(default_factory=tuple)
    indexable: bool = False
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class ProviderManifest(ContractModel):
    """Declarative provider SDK manifest used by registry and diagnostics."""

    provider_key: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    provider_kind: ProviderKind
    modes: tuple[ProviderMode, ...]
    source_types: tuple[SourceType, ...] = Field(default_factory=tuple)
    capabilities: tuple[ProviderCapability, ...] = Field(default_factory=tuple)
    evidence_kinds: tuple[EvidenceKind, ...] = Field(default_factory=tuple)
    policy_tags: tuple[str, ...] = Field(default_factory=tuple)
    disclosure_profile_key: str | None = None
    command_schema_version: int = Field(default=1, ge=1)
    default_deadline_ms: int = Field(default=3000, ge=100, le=30000)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class ProviderRoute(ContractModel):
    """Concrete provider route selected or skipped for one surface."""

    route_id: str
    provider_key: str
    provider_kind: ProviderKind
    role: ProviderRouteRole
    surface_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    selected: bool = False
    reason: str | None = None
    target: dict[str, JsonScalar] = Field(default_factory=dict)


class ProviderCommandRun(ContractModel):
    """Durable provider command diagnostics for accepted and failed captures."""

    command_id: str
    provider_key: str
    provider_session_id: str | None = None
    route_id: str | None = None
    status: ProviderCommandStatus
    evidence_kind: EvidenceKind
    sent_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    diagnostics: dict[str, JsonScalar] = Field(default_factory=dict)


class ProviderEvidenceBundle(ContractModel):
    """Provider command output before daemon persistence."""

    provider_key: str
    provider_session_id: str | None = None
    command_id: str
    status: ProviderCommandStatus
    evidence_kind: EvidenceKind
    source_binding: SourceBinding | None = None
    evidence: tuple[EvidenceDraft, ...] = Field(default_factory=tuple)
    diagnostics: dict[str, JsonScalar] = Field(default_factory=dict)
    completed_at: datetime


class ProviderCaptureOutcome(ContractModel):
    """Auditable outcome for one routed provider attempt."""

    route_id: str | None = None
    provider_key: str = Field(min_length=1)
    provider_kind: ProviderKind
    surface_id: str | None = None
    role: ProviderRouteRole
    status: ProviderCaptureOutcomeStatus
    reason_code: str | None = None
    command_id: str | None = None
    provider_session_id: str | None = None
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    diagnostics: dict[str, JsonScalar] = Field(default_factory=dict)


class EvidenceBundleRecord(ContractModel):
    """Persisted summary of one provider/system/derived evidence bundle."""

    bundle_id: str = Field(min_length=1)
    capture_run_id: str = Field(min_length=1)
    provider_key: str = Field(min_length=1)
    provider_kind: ProviderKind
    evidence_kind: EvidenceKind
    status: ProviderCaptureOutcomeStatus
    role: ProviderRouteRole
    route_id: str | None = None
    source_binding_id: str | None = None
    provider_session_id: str | None = None
    command_id: str | None = None
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    completed_at: datetime | None = None
    diagnostics: dict[str, JsonScalar] = Field(default_factory=dict)


class EnrichmentRecord(ContractModel):
    """Derived evidence operation with explicit inputs and outputs."""

    enrichment_id: str
    event_id: str
    capture_run_id: str
    kind: EvidenceKind
    extractor: ExtractorRef
    input_evidence_ids: tuple[str, ...]
    output_evidence_ids: tuple[str, ...]
    status: str
    policy_decision_id: str | None = None
    created_at: datetime
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class IndexManifest(ContractModel):
    """Index records created from DLP-passed evidence."""

    event_id: str
    indexed_evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    canonical_document_ids: tuple[str, ...] = Field(default_factory=tuple)
    document_chunk_ids: tuple[str, ...] = Field(default_factory=tuple)
    blocked_evidence_ids: tuple[str, ...] = Field(default_factory=tuple)


class PolicySnapshot(ContractModel):
    """Effective policy snapshot stamped during ingestion."""

    create_event_decision_id: str | None = None
    dlp_version: str = "local_dlp_v1"
    artifact_policy_version: str = "artifact_policy_v1"
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class EventCaptureEnvelope(ContractModel):
    """Canonical auditable record for one screenshot-triggered capture run."""

    schema_version: int = Field(default=2, ge=1)
    capture_run_id: str
    capture_revision: str | None = None
    event_id: str
    event_type: EventType
    trigger: TriggerEnvelope
    selection_geometry: SelectionGeometry
    detected_surfaces: tuple[DetectedSurface, ...] = Field(default_factory=tuple)
    route_plan: ProviderRoutePlan
    provider_routes: tuple[ProviderRoute, ...] = Field(default_factory=tuple)
    provider_command_runs: tuple[ProviderCommandRun, ...] = Field(default_factory=tuple)
    provider_outcomes: tuple[ProviderCaptureOutcome, ...] = Field(default_factory=tuple)
    source_bindings: tuple[SourceBinding, ...] = Field(default_factory=tuple)
    evidence_bundles: tuple[EvidenceBundleRecord, ...] = Field(default_factory=tuple)
    system_appshot_evidence_id: str | None = None
    system_evidence_bundle_ids: tuple[str, ...] = Field(default_factory=tuple)
    system_evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    app_evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    enrichment_records: tuple[EnrichmentRecord, ...] = Field(default_factory=tuple)
    evidence_records: tuple[EvidenceRecord, ...] = Field(default_factory=tuple)
    artifact_ids: tuple[str, ...] = Field(default_factory=tuple)
    index_manifest: IndexManifest
    policy_snapshot: PolicySnapshot
    audit_refs: tuple[str, ...] = Field(default_factory=tuple)
    context_event: ContextEvent | None = None
    jobs: tuple[CaptureJob, ...] = Field(default_factory=tuple)
    created_at: datetime
    updated_at: datetime
