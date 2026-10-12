"""Agent usage event contracts for post-answer audit linkage."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit

from pydantic import Field, field_validator

from .base import ContractModel


class AgentUsageEventCreate(ContractModel):
    """Create request for one agent usage record.

    Attributes:
        bundle_id: Bundle used by the consumer agent.
        agent: Agent name such as codex or openclaw.
        purpose: Purpose claimed by the agent.
        output_ref: User-visible output reference or local run id.
    """

    bundle_id: str
    agent: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    output_ref: str = Field(min_length=1)
    agent_run_id: str | None = None
    citation_ids: tuple[str, ...] = ()
    risk_advisory_ids: tuple[str, ...] = ()
    answer_hash: str | None = None

    @field_validator("output_ref")
    @classmethod
    def _safe_output_ref(cls, value: str) -> str:
        parsed = urlsplit(value)
        if value.startswith(("/", "~/")) or parsed.scheme in {"file", "local-artifact", "vault"}:
            raise ValueError("output_ref must be an opaque id or safe URI, not a local/vault path")
        if parsed.scheme in {"http", "https"} and (parsed.query or parsed.fragment):
            raise ValueError("output_ref URL must not include query or fragment")
        return value


class AgentUsageEvent(ContractModel):
    """Persisted usage event attached to a bundle.

    Attributes:
        usage_id: Stable usage event id.
        bundle_id: Bundle used by the consumer agent.
        agent: Agent name.
        purpose: Purpose claimed by the agent.
        output_ref: User-visible output reference or local run id.
        created_at: Persistence time.
    """

    usage_id: str
    bundle_id: str
    agent: str
    purpose: str
    output_ref: str
    agent_run_id: str | None = None
    citation_ids: tuple[str, ...] = ()
    risk_advisory_ids: tuple[str, ...] = ()
    answer_id: str | None = None
    created_at: datetime
