"""Typed contracts used inside the pluggable index layer."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from packages.contracts import (
    ArtifactType,
    DisclosureClass,
    EventStatus,
    EvidenceKind,
    EvidenceSensitivity,
    RedactionState,
    SearchFieldKind,
    SearchFilters,
)
from packages.contracts.base import ContractModel
from packages.contracts.common import JsonScalar

IndexFieldKind = SearchFieldKind


class IndexDocument(ContractModel):
    """One searchable projection chunk with full provenance references."""

    document_id: str
    chunk_id: str
    event_id: str
    evidence_id: str | None = None
    artifact_id: str | None = None
    provider_key: str | None = None
    source_uri: str | None = None
    captured_at: datetime
    observed_at: datetime | None = None
    extractor_name: str | None = None
    extractor_version: str | None = None
    policy_version: str = "artifact_policy_v2"
    disclosure_class: DisclosureClass = DisclosureClass.SAFE_METADATA
    evidence_kind: EvidenceKind | None = None
    artifact_type: ArtifactType | None = None
    sensitivity: EvidenceSensitivity = EvidenceSensitivity.INTERNAL
    redaction_state: RedactionState = RedactionState.REDACTED
    event_status: EventStatus = EventStatus.AGENT_READY
    field_kind: IndexFieldKind
    text: str
    text_hash: str
    title: str | None = None
    app_name: str | None = None
    origin: str | None = None
    sanitized_url: str | None = None
    source_type: str | None = None
    workspace_id: str | None = None
    user_id: str | None = None
    user_display_name: str | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class IndexWriteBatch(ContractModel):
    """Batch sent from daemon-owned projection services to an index backend."""

    capture_run_id: str | None = None
    event_id: str
    documents: tuple[IndexDocument, ...]
    replace_event: bool = True
    replace_chunk_prefixes: tuple[str, ...] = Field(default_factory=tuple)


class IndexReceipt(ContractModel):
    """Auditable receipt emitted after an index backend write/delete/rebuild."""

    backend: str
    backend_version: str
    event_id: str | None = None
    indexed_count: int = 0
    deleted_count: int = 0
    skipped_count: int = 0
    degraded: bool = False
    details: dict[str, JsonScalar] = Field(default_factory=dict)


class IndexQuery(ContractModel):
    """Backend-level recall query. Coordinates the documented runtime responsibility and lifecycle."""

    query: str = ""
    filters: SearchFilters = Field(default_factory=SearchFilters)
    limit: int = Field(default=20, ge=1, le=100)
    explain: bool = False


class IndexHealth(ContractModel):
    """Backend health and capability payload."""

    backend: str
    backend_version: str
    available: bool
    degraded: bool = False
    capabilities: tuple[str, ...] = ()
    details: dict[str, JsonScalar] = Field(default_factory=dict)
