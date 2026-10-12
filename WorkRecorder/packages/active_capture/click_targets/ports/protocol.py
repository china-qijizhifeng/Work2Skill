"""Narrow ports for click target resolution."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from packages.contracts import (
    ClickTargetCandidate,
    ClickTargetResolution,
    ClickTargetSourceKind,
    ContextKeyframe,
    EvidenceRecord,
    HumanActionEvent,
)


class ClickActionReadPort(Protocol):
    """Read only the action rows needed by click target resolution."""

    def get_human_action(self, action_id: str) -> HumanActionEvent | None: ...


class ClickTargetResolutionRepository(Protocol):
    """Persist and batch-read safe click target resolutions."""

    def save_click_target_resolution_graph(
        self,
        *,
        resolution: ClickTargetResolution,
        candidates: tuple[ClickTargetCandidate, ...],
    ) -> ClickTargetResolution: ...

    def list_click_target_resolutions_for_actions(
        self, action_ids: tuple[str, ...]
    ) -> tuple[ClickTargetResolution, ...]: ...


class ClickTargetResolutionReadRepository(Protocol):
    """Read-only projection boundary for click target resolutions."""

    def list_click_target_resolutions_for_actions(
        self, action_ids: tuple[str, ...]
    ) -> tuple[ClickTargetResolution, ...]: ...


class ClickTargetRepository(ClickActionReadPort, ClickTargetResolutionRepository, Protocol):
    """Aggregate target repository used only by the resolver service."""


class TargetCandidateProvider(Protocol):
    """Candidate source adapter used by the resolver service."""

    source_kind: ClickTargetSourceKind

    def candidates_for(
        self,
        *,
        action: HumanActionEvent,
        keyframe: ContextKeyframe,
        evidence_records: tuple[EvidenceRecord, ...],
        resolution_id: str,
        now_id_prefix: str,
        created_at: datetime,
    ) -> tuple[ClickTargetCandidate, ...]: ...
