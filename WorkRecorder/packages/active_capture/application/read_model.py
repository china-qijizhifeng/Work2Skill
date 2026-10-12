"""Unified active-capture read model and visibility projection."""

from __future__ import annotations

from dataclasses import dataclass, field

from packages.active_capture.repositories.protocol import ActiveCaptureProjectionReadRepository
from packages.contracts import (
    ActionEvidenceLink,
    ActionResultObservation,
    ActionTargetRef,
    ActiveCaptureProjectionConfig,
    ActiveCaptureSession,
    ClickTargetResolution,
    ContextKeyframe,
    HumanActionEvent,
    KeyframeEvidenceLink,
    ProducerDecision,
    ProducerEventEnvelope,
    RecordingControlEvent,
    RecordingTimelineManifest,
    RecordingVideoSegmentRef,
)


@dataclass(frozen=True)
class RecordingSessionGraph:
    """Loaded active-capture graph used by safe projections.

    Attributes:
        session: Active-capture session owner.
        keyframes: Ordered context keyframes in the session.
        actions: Ordered human action trace rows.
        controls: Recording control events such as pause/resume/user mark.
        timeline: Optional keyframe/video alignment manifest.
        keyframe_links: Evidence links attached to keyframes.
        action_links: Evidence links attached to actions.
        action_observations: Result observations attached to actions.
        target_resolutions: Safe semantic click targets attached to actions.
        producer_events: Native producer events for action/trigger derivation.
        producer_decisions: Backend decisions linking producer events to outputs.
        segments: Recording video segments used to align input events to video media time.
        total_keyframe_count: Total keyframes in storage before projection limits.
        total_action_count: Total actions in storage before projection limits.
        total_control_count: Total controls in storage before projection limits.
        total_producer_event_count: Total producer events before projection limits.
    """

    session: ActiveCaptureSession
    keyframes: tuple[ContextKeyframe, ...]
    actions: tuple[HumanActionEvent, ...]
    controls: tuple[RecordingControlEvent, ...]
    timeline: RecordingTimelineManifest | None
    keyframe_links: tuple[KeyframeEvidenceLink, ...]
    action_links: tuple[ActionEvidenceLink, ...]
    action_observations: tuple[ActionResultObservation, ...]
    target_resolutions: tuple[ClickTargetResolution, ...]
    producer_events: tuple[ProducerEventEnvelope, ...]
    producer_decisions: tuple[ProducerDecision, ...]
    segments: tuple[RecordingVideoSegmentRef, ...] = field(default_factory=tuple)
    total_keyframe_count: int = 0
    total_action_count: int = 0
    total_control_count: int = 0
    total_producer_event_count: int = 0


class RecordingSessionGraphReader:
    """Load active-capture projection inputs with bounded repository calls."""

    def __init__(
        self,
        *,
        repository: ActiveCaptureProjectionReadRepository,
        projection_config: ActiveCaptureProjectionConfig | None = None,
    ) -> None:
        self.repository = repository
        self.projection_config = projection_config

    def load_for_event(self, event_id: str) -> RecordingSessionGraph | None:
        """Resolve and load the active-capture graph associated with an event."""

        session_id = self._session_id_for_event(event_id)
        if session_id is None:
            return None
        return self.load_for_session(session_id)

    def load_for_session(self, session_id: str) -> RecordingSessionGraph | None:
        """Load a session graph by id."""

        session = self.repository.get_session(session_id)
        if session is None:
            return None
        config = self.projection_config
        keyframe_limit = config.max_timeline_steps if config is not None else None
        action_limit = config.max_actions if config is not None else None
        control_limit = config.max_timeline_steps if config is not None else None
        producer_limit = config.max_producer_diagnostics if config is not None else None
        keyframes = self.repository.list_keyframes_for_session(session_id, limit=keyframe_limit)
        actions = self.repository.list_human_actions_for_session(session_id, limit=action_limit)
        controls = self.repository.list_control_events_for_session(session_id, limit=control_limit)
        keyframe_ids = tuple(keyframe.keyframe_id for keyframe in keyframes)
        keyframe_id_set = set(keyframe_ids)
        action_ids = tuple(action.action_id for action in actions)
        timeline = self.repository.get_timeline_manifest(session_id)
        if timeline is not None:
            timeline = timeline.model_copy(
                update={"entries": tuple(entry for entry in timeline.entries if entry.keyframe_id in keyframe_id_set)}
            )
        return RecordingSessionGraph(
            session=session,
            keyframes=keyframes,
            actions=actions,
            controls=controls,
            timeline=timeline,
            keyframe_links=self.repository.list_evidence_links_for_keyframes(keyframe_ids),
            action_links=self.repository.list_action_evidence_links_for_actions(action_ids),
            action_observations=self.repository.list_action_observations_for_actions(action_ids),
            target_resolutions=self.repository.list_click_target_resolutions_for_actions(action_ids),
            producer_events=self.repository.list_producer_events_for_session(session_id, limit=producer_limit),
            producer_decisions=self.repository.list_producer_decisions_for_session(session_id, limit=producer_limit),
            segments=self.repository.list_recording_segments_for_session(session_id),
            total_keyframe_count=self.repository.count_keyframes_for_session(session_id),
            total_action_count=self.repository.count_human_actions_for_session(session_id),
            total_control_count=self.repository.count_control_events_for_session(session_id),
            total_producer_event_count=self.repository.count_producer_events_for_session(session_id),
        )

    def _session_id_for_event(self, event_id: str) -> str | None:
        keyframes = self.repository.list_keyframes_for_event(event_id)
        if keyframes:
            return keyframes[0].session_id
        bundle = self.repository.get_bundle_for_event(event_id)
        if bundle is not None:
            return bundle.session_id
        return None


class ActiveCaptureVisibilityProjector:
    """Fail-closed visibility projection over the loaded session graph."""

    def project(self, *, graph: RecordingSessionGraph, visible_event_ids: set[str]) -> RecordingSessionGraph:
        """Return a graph containing only references backed by visible events."""

        keyframes = tuple(keyframe for keyframe in graph.keyframes if keyframe.event_id in visible_event_ids)
        keyframe_ids = {keyframe.keyframe_id for keyframe in keyframes}
        keyframe_links = tuple(link for link in graph.keyframe_links if link.keyframe_id in keyframe_ids)
        visible_evidence_ids = {link.evidence_id for link in keyframe_links if link.evidence_id is not None}
        visible_artifact_ids = {link.artifact_id for link in keyframe_links if link.artifact_id is not None}
        visible_artifact_ids.update(
            keyframe.screenshot_artifact_id for keyframe in keyframes if keyframe.screenshot_artifact_id is not None
        )
        visible_action_links = tuple(
            link
            for link in graph.action_links
            if (link.event_id is None or link.event_id in visible_event_ids)
            and (link.keyframe_id is None or link.keyframe_id in keyframe_ids)
            and (link.evidence_id is None or link.evidence_id in visible_evidence_ids)
            and (link.artifact_id is None or link.artifact_id in visible_artifact_ids)
        )
        links_by_action: dict[str, list[ActionEvidenceLink]] = {}
        for link in graph.action_links:
            links_by_action.setdefault(link.action_id, []).append(link)
        visible_action_ids = {
            action.action_id
            for action in graph.actions
            if self._action_visible(
                action=action,
                keyframe_ids=keyframe_ids,
                visible_event_ids=visible_event_ids,
                visible_evidence_ids=visible_evidence_ids,
                visible_artifact_ids=visible_artifact_ids,
                primary_event_visible=graph.session.primary_event_id in visible_event_ids,
                original_links=tuple(links_by_action.get(action.action_id, ())),
            )
        }
        action_observations = tuple(
            observation
            for observation in graph.action_observations
            if observation.action_id in visible_action_ids
            and (observation.result_keyframe_id is None or observation.result_keyframe_id in keyframe_ids)
        )
        actions = tuple(
            action.model_copy(
                update={
                    "target": self._visible_target(
                        action.target,
                        keyframe_ids=keyframe_ids,
                        evidence_ids=visible_evidence_ids,
                        artifact_ids=visible_artifact_ids,
                    )
                }
            )
            for action in graph.actions
            if action.action_id in visible_action_ids
        )
        target_resolutions = tuple(
            resolution
            for resolution in graph.target_resolutions
            if resolution.action_id in visible_action_ids
            and self._target_resolution_visible(
                resolution,
                keyframe_ids=keyframe_ids,
                visible_event_ids=visible_event_ids,
                visible_evidence_ids=visible_evidence_ids,
                visible_artifact_ids=visible_artifact_ids,
            )
        )
        timeline = (
            graph.timeline.model_copy(
                update={
                    "entries": tuple(entry for entry in graph.timeline.entries if entry.keyframe_id in keyframe_ids)
                }
            )
            if graph.timeline is not None
            else None
        )
        producer_decisions = tuple(
            decision
            for decision in graph.producer_decisions
            if (decision.action_id is not None and decision.action_id in visible_action_ids)
            or (decision.keyframe_id is not None and decision.keyframe_id in keyframe_ids)
        )
        visible_producer_event_ids = {decision.producer_event_id for decision in producer_decisions}
        return RecordingSessionGraph(
            session=graph.session,
            keyframes=keyframes,
            actions=actions,
            controls=graph.controls,
            timeline=timeline,
            keyframe_links=keyframe_links,
            action_links=tuple(link for link in visible_action_links if link.action_id in visible_action_ids),
            action_observations=action_observations,
            target_resolutions=target_resolutions,
            producer_events=tuple(
                event for event in graph.producer_events if event.producer_event_id in visible_producer_event_ids
            ),
            producer_decisions=producer_decisions,
            segments=graph.segments,
            total_keyframe_count=graph.total_keyframe_count,
            total_action_count=graph.total_action_count,
            total_control_count=graph.total_control_count,
            total_producer_event_count=graph.total_producer_event_count,
        )

    def _action_visible(
        self,
        *,
        action: HumanActionEvent,
        keyframe_ids: set[str],
        visible_event_ids: set[str],
        visible_evidence_ids: set[str],
        visible_artifact_ids: set[str],
        primary_event_visible: bool,
        original_links: tuple[ActionEvidenceLink, ...],
    ) -> bool:
        if action.target is not None and not self._target_visible(
            action.target,
            keyframe_ids=keyframe_ids,
            evidence_ids=visible_evidence_ids,
            artifact_ids=visible_artifact_ids,
        ):
            return False
        if not original_links:
            return primary_event_visible
        for link in original_links:
            if link.keyframe_id is not None and link.keyframe_id not in keyframe_ids:
                continue
            if link.event_id is not None and link.event_id not in visible_event_ids:
                continue
            if link.evidence_id is not None and link.evidence_id not in visible_evidence_ids:
                continue
            if link.artifact_id is not None and link.artifact_id not in visible_artifact_ids:
                continue
            return True
        return False

    def _visible_target(
        self,
        target: ActionTargetRef | None,
        *,
        keyframe_ids: set[str],
        evidence_ids: set[str],
        artifact_ids: set[str],
    ) -> ActionTargetRef | None:
        if target is None:
            return None
        if self._target_visible(
            target,
            keyframe_ids=keyframe_ids,
            evidence_ids=evidence_ids,
            artifact_ids=artifact_ids,
        ):
            return target
        return None

    def _target_visible(
        self,
        target: ActionTargetRef,
        *,
        keyframe_ids: set[str],
        evidence_ids: set[str],
        artifact_ids: set[str],
    ) -> bool:
        if target.keyframe_id is not None and target.keyframe_id not in keyframe_ids:
            return False
        if target.evidence_id is not None and target.evidence_id not in evidence_ids:
            return False
        if target.artifact_id is not None and target.artifact_id not in artifact_ids:
            return False
        return True

    def _target_resolution_visible(
        self,
        resolution: ClickTargetResolution,
        *,
        keyframe_ids: set[str],
        visible_event_ids: set[str],
        visible_evidence_ids: set[str],
        visible_artifact_ids: set[str],
    ) -> bool:
        anchor = resolution.evidence_anchor
        if anchor is None:
            return True
        if anchor.keyframe_id is not None and anchor.keyframe_id not in keyframe_ids:
            return False
        if anchor.event_id is not None and anchor.event_id not in visible_event_ids:
            return False
        if anchor.evidence_id is not None and anchor.evidence_id not in visible_evidence_ids:
            return False
        if anchor.artifact_id is not None and anchor.artifact_id not in visible_artifact_ids:
            return False
        return True
