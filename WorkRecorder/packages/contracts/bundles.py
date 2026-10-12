"""Retrieval, search, and context bundle contracts for consumer agents."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import ContractModel
from .common import JsonScalar, UserFilter
from .enums import (
    EventStatus,
    EvidenceKind,
    EvidenceSensitivity,
    RetrievalMode,
    SearchFieldKind,
    SearchMatchReason,
    SearchSort,
    SourceType,
)
from .evidence import EvidenceRef


class SearchFilters(ContractModel):
    """Structured filters shared by CLI, daemon API, and index backends."""

    since: datetime | None = None
    until: datetime | None = None
    workspace: str | None = None
    app: str | None = None
    domain: str | None = None
    origin: str | None = None
    source: SourceType | None = None
    provider: str | None = None
    event_type: str | None = None
    evidence_kind: EvidenceKind | None = None
    status: EventStatus | None = None
    sensitivity: EvidenceSensitivity | None = None
    entity: str | None = None
    project: str | None = None
    user: UserFilter | None = None


class SearchCursor(ContractModel):
    """Opaque pagination cursor returned by search APIs."""

    cursor: str | None = None
    has_more: bool = False


class SearchExplain(ContractModel):
    """Safe explanation for why an event matched a search."""

    event_id: str
    backend: str
    score: float
    matched_fields: tuple[SearchFieldKind, ...] = Field(default_factory=tuple)
    match_reason: SearchMatchReason = SearchMatchReason.METADATA
    degraded: bool = False
    details: dict[str, JsonScalar] = Field(default_factory=dict)


class SearchQuery(ContractModel):
    """Agent-facing search request sent to the daemon."""

    query: str = Field(default="", max_length=500)
    mode: RetrievalMode = RetrievalMode.KEYWORD
    filters: SearchFilters = Field(default_factory=SearchFilters)
    limit: int = Field(default=20, ge=1, le=100)
    cursor: str | None = None
    sort: SearchSort = SearchSort.SCORE
    explain: bool = False


class IndexHit(ContractModel):
    """Public-safe hit reference returned by index-backed recall."""

    event_id: str
    chunk_id: str | None = None
    evidence_id: str | None = None
    artifact_id: str | None = None
    backend: str
    score: float
    matched_fields: tuple[SearchFieldKind, ...] = Field(default_factory=tuple)
    match_reason: SearchMatchReason = SearchMatchReason.METADATA
    explain: SearchExplain | None = None


class RetrievalQuery(ContractModel):
    """Typed search query used by CLI and daemon retrieval.

    Attributes:
        query: User or agent search text.
        mode: Retrieval mode, currently keyword or hybrid.
        entity: Optional entity filter such as ACME.
        limit: Maximum results to return.
    """

    query: str = ""
    mode: RetrievalMode = RetrievalMode.KEYWORD
    entity: str | None = None
    limit: int = Field(default=20, ge=1, le=100)

    def to_search_query(self) -> SearchQuery:
        """Return the richer P3.3 search query shape.

        Returns:
            Search query contract preserving the legacy retrieval request fields.
        """

        return SearchQuery(
            query=self.query,
            mode=self.mode,
            filters=SearchFilters(entity=self.entity),
            limit=self.limit,
        )


class BundleRequest(ContractModel):
    """Request to build a retrieval-time context bundle.

    Attributes:
        query: Task query the bundle should support.
        purpose: Purpose used by policy and audit.
        entity: Optional entity filter.
        max_tokens: Soft budget for future packing.
    """

    query: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    entity: str | None = None
    max_tokens: int = Field(default=8000, ge=512, le=64000)


class ContextBundleItem(ContractModel):
    """One evidence-backed claim inside a context bundle.

    Attributes:
        event_id: Source event id.
        claim: Short fact or summary claim.
        citations: Evidence refs that support the claim.
    """

    event_id: str
    claim: str
    citations: tuple[EvidenceRef, ...] = Field(default_factory=tuple)
    citation_ids: tuple[str, ...] = Field(default_factory=tuple)


class ContextBundle(ContractModel):
    """Context package returned to consumer agents.

    Attributes:
        bundle_id: Stable bundle id.
        query: Query used to build the bundle.
        purpose: Purpose used by policy and audit.
        items: Evidence-backed bundle items.
        degraded: Whether retrieval fell back from a richer mode.
        created_at: Persistence time.
    """

    bundle_id: str
    query: str
    purpose: str
    items: tuple[ContextBundleItem, ...]
    degraded: bool
    created_at: datetime
    agent_run_id: str | None = None
    context_query_id: str | None = None
    retrieval_call_id: str | None = None
