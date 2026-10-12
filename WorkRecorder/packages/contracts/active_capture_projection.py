"""Shared projection-budget contracts for active capture read models."""

from __future__ import annotations

from pydantic import Field

from .base import ContractModel


class ActiveCaptureProjectionConfig(ContractModel):
    """Budget knobs for bounded active-capture read projections."""

    max_timeline_steps: int = Field(default=500, ge=1, le=10_000)
    max_actions: int = Field(default=20_000, ge=1, le=100_000)
    max_safe_text_blocks: int = Field(default=128, ge=0, le=10_000)
    max_safe_text_chars: int = Field(default=256_000, ge=0, le=10_000_000)
    max_producer_diagnostics: int = Field(default=1_000, ge=0, le=100_000)


class ProjectionTruncationSummary(ContractModel):
    """Typed truncation receipt emitted by large active-capture projections."""

    truncated: bool = False
    truncated_counts: dict[str, int] = Field(default_factory=dict)
    next_cursor: str | None = Field(default=None, min_length=1, max_length=240)
