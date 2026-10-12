"""Agent run ledger contracts for replayable context usage."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from .active_capture_inspect import ActiveCaptureCitationTarget
from .base import ContractModel
from .common import ActorRef, BoundingBox, JsonScalar, TextRange
from .enums import (
    AgentRunOrigin,
    AgentRunStatus,
    CitationUseState,
    CoordinateSpace,
    RetrievalCallKind,
    RiskActionState,
    RiskAdvisoryCategory,
    RiskSeverity,
    SnapshotKind,
)


class AgentRunBeginRequest(ContractModel):
    """Request to explicitly begin an agent context run."""

    agent: str = Field(default="codex", min_length=1, max_length=160)
    purpose: str = Field(default="agent_context", min_length=1, max_length=160)
    user_question: str | None = Field(default=None, max_length=4000)
    workspace_id: str | None = Field(default=None, max_length=160)
    origin: AgentRunOrigin = AgentRunOrigin.API_EXPLICIT


class AgentRun(ContractModel):
    """One agent answer/retrieval run."""

    agent_run_id: str
    actor: ActorRef
    agent: str
    purpose: str
    origin: AgentRunOrigin
    status: AgentRunStatus = AgentRunStatus.ACTIVE
    workspace_id: str | None = None
    user_question: str | None = None
    user_question_hash: str | None = None
    started_at: datetime
    last_seen_at: datetime
    completed_at: datetime | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class ContextQuery(ContractModel):
    """User question or retrieval intent attached to an agent run."""

    context_query_id: str
    agent_run_id: str
    query_text: str
    query_hash: str
    purpose: str
    workspace_id: str | None = None
    created_at: datetime
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class RetrievalCall(ContractModel):
    """One agent-facing API/CLI read operation."""

    retrieval_call_id: str
    agent_run_id: str
    context_query_id: str | None
    request_id: str
    kind: RetrievalCallKind
    resource_type: str
    resource_id: str | None = None
    purpose: str
    request_hash: str
    response_hash: str | None = None
    status: str = "succeeded"
    created_at: datetime
    completed_at: datetime | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class DeliveredContextItem(ContractModel):
    """One event/evidence/artifact/citation reference delivered to the agent."""

    item_id: str
    snapshot_id: str
    event_id: str | None = None
    evidence_id: str | None = None
    artifact_id: str | None = None
    citation_id: str | None = None
    field_path: str
    disclosure_class: str | None = None
    text_hash: str | None = None
    byte_size: int | None = None
    truncated: bool = False
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class DeliveredContextSnapshot(ContractModel):
    """Safe replay snapshot of what the daemon actually returned."""

    snapshot_id: str
    agent_run_id: str
    retrieval_call_id: str
    context_query_id: str | None = None
    kind: SnapshotKind
    payload_hash: str
    payload_json: dict[str, object] = Field(default_factory=dict)
    delivered_fields: tuple[str, ...] = Field(default_factory=tuple)
    byte_size: int = 0
    item_count: int = 0
    created_at: datetime
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class CitationRecord(ContractModel):
    """Stable citation id for one delivered evidence reference."""

    citation_id: str
    agent_run_id: str
    event_id: str
    evidence_id: str | None = None
    artifact_id: str | None = None
    chunk_id: str | None = None
    evidence_ref: str | None = None
    text_range: TextRange | None = None
    bbox: BoundingBox | None = None
    coordinate_space: CoordinateSpace = CoordinateSpace.SCREEN_PX
    active_capture_target: ActiveCaptureCitationTarget | None = None
    state: CitationUseState = CitationUseState.DELIVERED
    created_at: datetime
    source_snapshot_id: str | None = None
    source_retrieval_call_id: str | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class CitationResolveResponse(ContractModel):
    """Safe citation lookup payload."""

    citation: CitationRecord
    text: str = ""
    text_truncated: bool = False


class AnswerRecord(ContractModel):
    """Final answer pointer/hash attached to an agent run."""

    answer_id: str
    agent_run_id: str
    output_ref: str
    answer_hash: str | None = None
    citation_ids: tuple[str, ...] = Field(default_factory=tuple)
    bundle_ids: tuple[str, ...] = Field(default_factory=tuple)
    created_at: datetime
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class RiskAdvisoryRecord(ContractModel):
    """High-risk suggestion or action proposal emitted by an agent."""

    risk_advisory_id: str
    agent_run_id: str
    category: RiskAdvisoryCategory = RiskAdvisoryCategory.UNKNOWN
    severity: RiskSeverity = RiskSeverity.MEDIUM
    action_state: RiskActionState = RiskActionState.SUGGESTED_ONLY
    summary: str
    citation_ids: tuple[str, ...] = Field(default_factory=tuple)
    created_at: datetime
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class AgentUsageEventV2Create(ContractModel):
    """Create request for the final usage ledger cover record."""

    bundle_id: str | None = None
    bundle_ids: tuple[str, ...] = Field(default_factory=tuple)
    agent_run_id: str | None = None
    agent: str = Field(default="codex", min_length=1)
    purpose: str = Field(min_length=1)
    output_ref: str = Field(min_length=1)
    citation_ids: tuple[str, ...] = Field(default_factory=tuple)
    risk_advisory_ids: tuple[str, ...] = Field(default_factory=tuple)
    answer_hash: str | None = None

    @field_validator("output_ref")
    @classmethod
    def _safe_output_ref(cls, value: str) -> str:
        return _safe_output_ref(value)


class AgentUsageEventV2(ContractModel):
    """Final usage cover that points at detailed agent-run ledger rows."""

    usage_id: str
    agent_run_id: str
    context_query_ids: tuple[str, ...] = Field(default_factory=tuple)
    retrieval_call_ids: tuple[str, ...] = Field(default_factory=tuple)
    snapshot_ids: tuple[str, ...] = Field(default_factory=tuple)
    bundle_ids: tuple[str, ...] = Field(default_factory=tuple)
    citation_ids: tuple[str, ...] = Field(default_factory=tuple)
    answer_id: str | None = None
    risk_advisory_ids: tuple[str, ...] = Field(default_factory=tuple)
    agent: str
    purpose: str
    output_ref: str
    created_at: datetime
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class AgentRunReplay(ContractModel):
    """Replay view for one agent run."""

    agent_run: AgentRun
    context_queries: tuple[ContextQuery, ...] = Field(default_factory=tuple)
    retrieval_calls: tuple[RetrievalCall, ...] = Field(default_factory=tuple)
    snapshots: tuple[DeliveredContextSnapshot, ...] = Field(default_factory=tuple)
    snapshot_items: tuple[DeliveredContextItem, ...] = Field(default_factory=tuple)
    citations: tuple[CitationRecord, ...] = Field(default_factory=tuple)
    answers: tuple[AnswerRecord, ...] = Field(default_factory=tuple)
    risk_advisories: tuple[RiskAdvisoryRecord, ...] = Field(default_factory=tuple)
    usage_events: tuple[AgentUsageEventV2, ...] = Field(default_factory=tuple)


def _safe_output_ref(value: str) -> str:
    parsed = urlsplit(value)
    if value.startswith(("/", "~/")) or parsed.scheme in {"file", "local-artifact", "vault"}:
        raise ValueError("output_ref must be an opaque id or safe URI, not a local/vault path")
    if parsed.scheme in {"http", "https"} and (parsed.query or parsed.fragment):
        raise ValueError("output_ref URL must not include query or fragment")
    return value
