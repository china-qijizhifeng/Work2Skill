"""Repository protocols for active capture services."""

from __future__ import annotations

from typing import Protocol

from packages.contracts import (
    ActionEvidenceLink,
    ActionResultObservation,
    ActiveCaptureSession,
    Artifact,
    ClickTargetCandidate,
    ClickTargetResolution,
    ContextKeyframe,
    HumanActionEvent,
    HumanDemonstrationTrace,
    KeyframeCaptureDecision,
    KeyframeContextBundle,
    KeyframeEvidenceLink,
    KeyframeRole,
    KeyframeTriggerCandidate,
    KeyframeTriggerCandidateStatus,
    KeyframeTriggerKind,
    ProducerDecision,
    ProducerEventEnvelope,
    RecordingControlEvent,
    RecordingPauseInterval,
    RecordingTimelineManifest,
    RecordingVideoSegmentRef,
    SettleAuditRecord,
)


class ActiveCaptureSessionRepository(Protocol):
    """Persistence boundary for active-capture session state."""

    def save_session(self, session: ActiveCaptureSession) -> ActiveCaptureSession: ...

    def get_session(self, session_id: str) -> ActiveCaptureSession | None: ...

    def list_sessions(
        self,
        *,
        mode: str | None = None,
        limit: int | None = None,
        require_primary_event: bool = False,
    ) -> tuple[ActiveCaptureSession, ...]: ...


class ActiveCaptureKeyframeRepository(Protocol):
    """Persistence boundary for keyframes and keyframe evidence."""

    def get_session(self, session_id: str) -> ActiveCaptureSession | None: ...

    def save_keyframe(self, keyframe: ContextKeyframe) -> ContextKeyframe: ...

    def save_keyframe_graph(
        self,
        *,
        keyframe: ContextKeyframe,
        links: tuple[KeyframeEvidenceLink, ...],
        decision: KeyframeCaptureDecision,
        session: ActiveCaptureSession | None = None,
        bundle: KeyframeContextBundle | None = None,
    ) -> ContextKeyframe: ...

    def append_keyframe_graph(
        self,
        *,
        keyframe: ContextKeyframe,
        links: tuple[KeyframeEvidenceLink, ...],
        decision: KeyframeCaptureDecision,
        session: ActiveCaptureSession,
    ) -> ContextKeyframe: ...

    def get_keyframe(self, keyframe_id: str) -> ContextKeyframe | None: ...

    def find_keyframe(
        self,
        *,
        session_id: str,
        event_id: str,
        role: KeyframeRole,
        trigger_kind: KeyframeTriggerKind,
    ) -> ContextKeyframe | None: ...

    def list_keyframes_for_session(
        self, session_id: str, *, limit: int | None = None
    ) -> tuple[ContextKeyframe, ...]: ...

    def get_latest_keyframe_before(
        self, *, session_id: str, occurred_at_monotonic_ms: int | None
    ) -> ContextKeyframe | None: ...

    def list_keyframes_for_event(self, event_id: str) -> tuple[ContextKeyframe, ...]: ...

    def count_keyframes_for_session(self, session_id: str) -> int: ...

    def save_evidence_links(self, links: tuple[KeyframeEvidenceLink, ...]) -> tuple[KeyframeEvidenceLink, ...]: ...

    def list_evidence_links_for_keyframe(self, keyframe_id: str) -> tuple[KeyframeEvidenceLink, ...]: ...

    def list_evidence_links_for_session(self, session_id: str) -> tuple[KeyframeEvidenceLink, ...]: ...

    def list_evidence_links_for_keyframes(self, keyframe_ids: tuple[str, ...]) -> tuple[KeyframeEvidenceLink, ...]: ...

    def save_capture_decision(self, decision: KeyframeCaptureDecision) -> KeyframeCaptureDecision: ...

    def save_bundle(self, bundle: KeyframeContextBundle) -> KeyframeContextBundle: ...

    def get_bundle_for_session(self, session_id: str) -> KeyframeContextBundle | None: ...

    def get_bundle_for_event(self, event_id: str) -> KeyframeContextBundle | None: ...


class ActiveCaptureTimelineRepository(Protocol):
    """Persistence boundary for timeline manifests."""

    def save_timeline_manifest(self, manifest: RecordingTimelineManifest) -> RecordingTimelineManifest: ...

    def complete_session_graph(
        self,
        *,
        session: ActiveCaptureSession,
        timeline: RecordingTimelineManifest,
        bundle: KeyframeContextBundle,
        artifacts: tuple[Artifact, ...] = (),
    ) -> ActiveCaptureSession: ...

    def get_timeline_manifest(self, session_id: str) -> RecordingTimelineManifest | None: ...


class ActiveCaptureRecordingRepository(Protocol):
    """Persistence boundary for recording controls and segments."""

    def save_control_event(self, event: RecordingControlEvent) -> RecordingControlEvent: ...

    def list_control_events_for_session(
        self, session_id: str, *, limit: int | None = None
    ) -> tuple[RecordingControlEvent, ...]: ...

    def count_control_events_for_session(self, session_id: str) -> int: ...

    def save_recording_segment(self, segment: RecordingVideoSegmentRef) -> RecordingVideoSegmentRef: ...

    def save_recording_segment_graph(
        self,
        *,
        segment: RecordingVideoSegmentRef,
        artifacts: tuple[Artifact, ...] = (),
    ) -> RecordingVideoSegmentRef: ...

    def get_recording_segment(self, segment_id: str) -> RecordingVideoSegmentRef | None: ...

    def list_recording_segments_for_session(self, session_id: str) -> tuple[RecordingVideoSegmentRef, ...]: ...

    def save_pause_interval(self, interval: RecordingPauseInterval) -> RecordingPauseInterval: ...

    def list_pause_intervals_for_session(self, session_id: str) -> tuple[RecordingPauseInterval, ...]: ...


class ActiveCaptureTriggerRepository(Protocol):
    """Persistence boundary for trigger candidates."""

    def save_trigger_candidate(self, candidate: KeyframeTriggerCandidate) -> KeyframeTriggerCandidate: ...

    def save_settle_candidate_decision(
        self, *, candidate: KeyframeTriggerCandidate, now_monotonic_ms: int
    ) -> KeyframeTriggerCandidate: ...

    def claim_settle_candidate_for_capture(
        self, *, candidate_id: str, claim_id: str, now_monotonic_ms: int, lease_ms: int
    ) -> KeyframeTriggerCandidate | None: ...

    def get_trigger_candidate(self, candidate_id: str) -> KeyframeTriggerCandidate | None: ...

    def list_trigger_candidates_for_session(self, session_id: str) -> tuple[KeyframeTriggerCandidate, ...]: ...

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

    def save_settle_audit(self, record: SettleAuditRecord) -> SettleAuditRecord: ...

    def list_settle_audits_for_candidate(self, candidate_id: str) -> tuple[SettleAuditRecord, ...]: ...


class ActiveCaptureActionTraceRepository(Protocol):
    """Persistence boundary for human demonstration action traces."""

    def save_demonstration_trace(self, trace: HumanDemonstrationTrace) -> HumanDemonstrationTrace: ...

    def get_demonstration_trace_for_session(self, session_id: str) -> HumanDemonstrationTrace | None: ...

    def append_human_action_graph(
        self,
        *,
        action: HumanActionEvent,
        links: tuple[ActionEvidenceLink, ...],
        observation: ActionResultObservation | None,
        trace: HumanDemonstrationTrace,
    ) -> HumanActionEvent: ...

    def list_human_actions_for_session(
        self, session_id: str, *, limit: int | None = None
    ) -> tuple[HumanActionEvent, ...]: ...

    def count_human_actions_for_session(self, session_id: str) -> int: ...

    def list_action_evidence_links(self, action_id: str) -> tuple[ActionEvidenceLink, ...]: ...

    def list_action_evidence_links_for_session(self, session_id: str) -> tuple[ActionEvidenceLink, ...]: ...

    def list_action_evidence_links_for_actions(self, action_ids: tuple[str, ...]) -> tuple[ActionEvidenceLink, ...]: ...

    def save_action_evidence_link(self, link: ActionEvidenceLink) -> ActionEvidenceLink: ...

    def get_action_observation(self, action_id: str) -> ActionResultObservation | None: ...

    def list_action_observations_for_session(self, session_id: str) -> tuple[ActionResultObservation, ...]: ...

    def list_action_observations_for_actions(
        self, action_ids: tuple[str, ...]
    ) -> tuple[ActionResultObservation, ...]: ...

    def save_action_observation(self, observation: ActionResultObservation) -> ActionResultObservation: ...


class ActiveCaptureClickTargetReadRepository(Protocol):
    """Read-only boundary for semantic click target resolutions."""

    def list_click_target_resolutions_for_actions(
        self, action_ids: tuple[str, ...]
    ) -> tuple[ClickTargetResolution, ...]: ...


class ActiveCaptureClickTargetWriteRepository(ActiveCaptureClickTargetReadRepository, Protocol):
    """Write boundary for resolver-owned semantic click target resolutions."""

    def get_human_action(self, action_id: str) -> HumanActionEvent | None: ...

    def save_click_target_resolution_graph(
        self,
        *,
        resolution: ClickTargetResolution,
        candidates: tuple[ClickTargetCandidate, ...],
    ) -> ClickTargetResolution: ...


class ActiveCaptureProducerEventRepository(Protocol):
    """Persistence boundary for trusted producer events."""

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

    def list_producer_events_for_session(
        self, session_id: str, *, limit: int | None = None
    ) -> tuple[ProducerEventEnvelope, ...]: ...

    def list_producer_decisions_for_session(
        self, session_id: str, *, limit: int | None = None
    ) -> tuple[ProducerDecision, ...]: ...

    def get_producer_decision_by_candidate_id(
        self, *, session_id: str, candidate_id: str
    ) -> ProducerDecision | None: ...


class ActiveCaptureProjectionReadRepository(
    ActiveCaptureSessionRepository,
    ActiveCaptureKeyframeRepository,
    ActiveCaptureTimelineRepository,
    ActiveCaptureRecordingRepository,
    ActiveCaptureActionTraceRepository,
    ActiveCaptureClickTargetReadRepository,
    ActiveCaptureProducerEventRepository,
    Protocol,
):
    """Read-only projection surface used by active-capture inspect/storyboard/skill views."""


class ActiveCaptureRepository(
    ActiveCaptureSessionRepository,
    ActiveCaptureKeyframeRepository,
    ActiveCaptureTimelineRepository,
    ActiveCaptureRecordingRepository,
    ActiveCaptureTriggerRepository,
    ActiveCaptureActionTraceRepository,
    ActiveCaptureClickTargetWriteRepository,
    ActiveCaptureProducerEventRepository,
    Protocol,
):
    """Aggregate protocol kept for compatibility with older application services."""
