"""Narrow ports for active-capture producer input ingestion."""

from __future__ import annotations

from typing import Protocol

from packages.contracts import (
    ActionEvidenceLink,
    ActionResultObservation,
    HumanActionEvent,
    HumanDemonstrationTrace,
    KeyframeTriggerCandidate,
    KeyframeTriggerCandidateStatus,
    ProducerDecision,
    ProducerEventEnvelope,
    RecordingPauseInterval,
    RecordingVideoSegmentRef,
)


class ProducerEventRepository(Protocol):
    """Persistence boundary for trusted producer input events."""

    def append_producer_event_graph(
        self,
        *,
        event: ProducerEventEnvelope,
        decision: ProducerDecision,
    ) -> ProducerEventEnvelope: ...

    def append_producer_event_batch_graph(
        self,
        *,
        trace: HumanDemonstrationTrace | None,
        actions: tuple[HumanActionEvent, ...],
        action_links: tuple[ActionEvidenceLink, ...],
        action_observations: tuple[ActionResultObservation, ...],
        trigger_candidates: tuple[KeyframeTriggerCandidate, ...],
        producer_events: tuple[ProducerEventEnvelope, ...],
        producer_decisions: tuple[ProducerDecision, ...],
        max_producer_events_per_session: int,
        max_action_events_per_session: int,
        max_pending_trigger_candidates: int,
    ) -> tuple[ProducerEventEnvelope, ...]: ...

    def save_producer_decision(self, decision: ProducerDecision) -> ProducerDecision: ...

    def count_producer_events_for_session(self, session_id: str) -> int: ...

    def list_human_actions_for_session(
        self, session_id: str, *, limit: int | None = None
    ) -> tuple[HumanActionEvent, ...]: ...

    def count_human_actions_for_session(self, session_id: str) -> int: ...

    def list_active_trigger_candidates_for_session(
        self, session_id: str, *, limit: int | None = None
    ) -> tuple[KeyframeTriggerCandidate, ...]: ...

    def list_recent_trigger_candidates_for_session(
        self,
        session_id: str,
        *,
        statuses: tuple[KeyframeTriggerCandidateStatus, ...],
        limit: int,
    ) -> tuple[KeyframeTriggerCandidate, ...]: ...

    def list_producer_events_for_session(
        self, session_id: str, *, limit: int | None = None
    ) -> tuple[ProducerEventEnvelope, ...]: ...

    def list_recording_segments_for_session(self, session_id: str) -> tuple[RecordingVideoSegmentRef, ...]: ...

    def list_producer_decisions_for_session(
        self, session_id: str, *, limit: int | None = None
    ) -> tuple[ProducerDecision, ...]: ...
