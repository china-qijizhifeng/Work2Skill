"""Typed API success payloads returned inside the stable envelope."""

from __future__ import annotations

from datetime import datetime

from .base import ContractModel
from .bundles import ContextBundle, SearchCursor, SearchExplain
from .common import BoundingBox
from .enums import DisclosureView, SearchMatchReason
from .events import ContextEvent
from .policy import AgentRunToken


class SearchResultSource(ContractModel):
    """Safe source fields shown in default search cards."""

    app_name: str | None = None
    title: str
    origin: str | None = None
    sanitized_url: str | None = None


class SearchResultCard(ContractModel):
    """Default context preview returned to agents for one matched event."""

    event_id: str
    event_type: str
    captured_at: datetime
    source: SearchResultSource
    selection_bbox: BoundingBox | None = None
    user_note: str | None = None
    user_note_truncated: bool = False
    selection_text: str = ""
    selection_text_snippet: str = ""
    selection_text_truncated: bool = False
    canonical_text_snippet: str = ""
    canonical_text_truncated: bool = False
    preview_evidence_id: str | None = None
    preview_citation_id: str | None = None
    preview_confidence: float = 0.0
    match_reason: SearchMatchReason = SearchMatchReason.METADATA
    hidden_artifacts: tuple[str, ...] = ()
    provider_contributions: tuple[str, ...] = ()
    provider_diagnostics_count: int = 0
    source_kind: str | None = None
    disclosure_view: DisclosureView = DisclosureView.SUMMARY_CARD
    disclosure_policy_version: str = "disclosure_policy_v1"


class HealthResponse(ContractModel):
    """Daemon health payload.

    Attributes:
        service: Stable local service marker for app bundle endpoint probes.
        status: Human-readable runtime status.
        database_path: SQLite database path used by the daemon.
    """

    recording_target: str = "macos"
    service: str = "workrecorder-local-daemon"
    status: str
    database_path: str


class TokenIssueResponse(ContractModel):
    """Payload returned after a local CLI token exchange.

    Attributes:
        access_token: Encoded bearer token.
        claims: Decoded token claims for observability and contract tests.
    """

    access_token: str
    claims: AgentRunToken


class EventListResponse(ContractModel):
    """Payload for event listing responses.

    Attributes:
        events: Events visible to the caller.
    """

    events: tuple[ContextEvent, ...]


class SearchResponse(ContractModel):
    """Payload for event search responses.

    Attributes:
        events: Events returned by retrieval.
        results: Safe default preview cards returned by retrieval.
        degraded: Whether the requested mode fell back to a simpler implementation.
    """

    events: tuple[ContextEvent, ...]
    results: tuple[SearchResultCard, ...] = ()
    degraded: bool
    explain: tuple[SearchExplain, ...] = ()
    cursor: SearchCursor = SearchCursor()
    backend: str = "unknown"


class BundleListResponse(ContractModel):
    """Reserved typed payload for future bundle collection endpoints."""

    bundles: tuple[ContextBundle, ...]
