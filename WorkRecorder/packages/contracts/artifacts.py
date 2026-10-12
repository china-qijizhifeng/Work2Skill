"""Artifact contracts for evidence metadata and access."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import ContractModel
from .common import JsonScalar
from .enums import AccessScope, ArtifactIngestState, ArtifactRole, ArtifactType, EvidenceKind, RedactionState


class ArtifactCreate(ContractModel):
    """Metadata accepted when registering a new artifact.

    Attributes:
        event_id: Event that owns the artifact.
        artifact_type: Typed evidence artifact category.
        role: Human-readable role such as visual evidence or source text.
        storage_uri: Local vault or fixture URI.
        metadata: Small typed scalar metadata map.
    """

    event_id: str
    artifact_type: ArtifactType
    role: ArtifactRole | str = Field(min_length=1)
    storage_uri: str
    content_type: str | None = None
    byte_size: int | None = Field(default=None, ge=0)
    sha256: str | None = None
    ingest_state: ArtifactIngestState = ArtifactIngestState.QUARANTINED
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class Artifact(ContractModel):
    """Persisted artifact metadata without raw content.

    Attributes:
        artifact_id: Stable artifact id.
        event_id: Owning context event id.
        artifact_type: Evidence artifact category.
        role: Human-readable role.
        storage_uri: Local vault or fixture URI.
        redaction_state: Redaction status inherited by projections.
        allowed_scopes: Access scopes this artifact can grant after policy.
        metadata: Small typed scalar metadata map.
        created_at: Persistence time.
    """

    artifact_id: str
    event_id: str
    artifact_type: ArtifactType
    role: ArtifactRole | str
    storage_uri: str
    redaction_state: RedactionState
    allowed_scopes: tuple[AccessScope, ...]
    content_type: str | None = None
    byte_size: int | None = None
    sha256: str | None = None
    ingest_state: ArtifactIngestState = ArtifactIngestState.QUARANTINED
    metadata: dict[str, JsonScalar]
    created_at: datetime
    evidence_id: str | None = None
    capture_run_id: str | None = None
    provider_key: str | None = None
    provider_session_id: str | None = None
    command_id: str | None = None
    evidence_kind: EvidenceKind | None = None
    source_uri: str | None = None
    observed_at: datetime | None = None
    extractor_name: str | None = None
    extractor_version: str | None = None
    policy_decision_id: str | None = None
    retention_policy: str = "local_default"


class ArtifactPublicSummary(ContractModel):
    """Safe artifact metadata returned by public daemon routes."""

    artifact_id: str
    event_id: str
    artifact_type: ArtifactType
    role: ArtifactRole | str
    redaction_state: RedactionState
    allowed_scopes: tuple[AccessScope, ...]
    content_type: str | None = None
    byte_size: int | None = Field(default=None, ge=0)
    ingest_state: ArtifactIngestState = ArtifactIngestState.QUARANTINED
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)
    created_at: datetime
    evidence_id: str | None = None
    capture_run_id: str | None = None
    provider_key: str | None = None
    evidence_kind: EvidenceKind | None = None


class ArtifactIntegrityPublicSummary(ContractModel):
    """Integrity result without hash material."""

    artifact_id: str
    byte_size: int = Field(ge=0)
    ok: bool


class ArtifactManifest(ContractModel):
    """Provider-produced artifact payload ready for daemon registration.

    Attributes:
        artifact_type: Evidence artifact category.
        role: Semantic role inside the event.
        content_type: MIME type.
        content: UTF-8 text or JSON string produced by a provider.
        redaction_state: Redaction status after provider-side sanitization.
        ingest_state: Trust/processing state requested by the provider.
        allowed_scopes: Artifact scopes allowed before route-level policy.
        metadata: Small scalar metadata.
    """

    artifact_type: ArtifactType
    role: ArtifactRole
    content_type: str = Field(min_length=1)
    content: str = ""
    redaction_state: RedactionState = RedactionState.NONE
    ingest_state: ArtifactIngestState = ArtifactIngestState.QUARANTINED
    allowed_scopes: tuple[AccessScope, ...] = (AccessScope.READ_METADATA, AccessScope.READ_TEXT)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)
