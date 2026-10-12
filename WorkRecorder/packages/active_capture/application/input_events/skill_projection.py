"""Safe P7.11-ready projections over demonstration traces."""

from __future__ import annotations

from packages.active_capture.application.read_model import RecordingSessionGraphReader
from packages.active_capture.click_targets.domain.scoring import ClickTargetScoringPolicy
from packages.active_capture.repositories.protocol import ActiveCaptureRepository
from packages.contracts import (
    ActionEvidenceLink,
    ActionResultObservation,
    ActionTargetRef,
    ActiveCaptureProjectionConfig,
    ActiveCaptureSession,
    ClickTargetResolution,
    ClickTargetResolverConfig,
    HumanActionTargetKind,
    KeyChord,
    ProducerEventEnvelope,
    ProjectionTruncationSummary,
    SkillDistillationInputView,
    SkillDistillationStepView,
    SkillDistillationTargetView,
    TypingSessionAggregateView,
)
from packages.shared.time import Clock


class SkillDistillationInputProjector:
    """Build ordered action steps, including opted-in full-content keystrokes."""

    def __init__(
        self,
        *,
        repository: ActiveCaptureRepository,
        clock: Clock,
        projection_config: ActiveCaptureProjectionConfig | None = None,
    ) -> None:
        self.repository = repository
        self.clock = clock
        self.projection_config = projection_config or ActiveCaptureProjectionConfig()
        self.graph_reader = RecordingSessionGraphReader(repository=repository, projection_config=self.projection_config)
        self.target_scoring = ClickTargetScoringPolicy(config=ClickTargetResolverConfig())

    def build(self, session: ActiveCaptureSession) -> SkillDistillationInputView:
        """Build an action projection for one active-capture session."""

        graph = self.graph_reader.load_for_session(session.session_id)
        if graph is None:
            raise ValueError("active capture session not found")
        decisions = graph.producer_decisions
        events = graph.producer_events
        action_links = graph.action_links
        observations = graph.action_observations
        decisions_by_action = {decision.action_id: decision for decision in decisions if decision.action_id}
        events_by_id = {event.producer_event_id: event for event in events}
        links_by_action = self._links_by_action(action_links)
        observations_by_action = {observation.action_id: observation for observation in observations}
        targets_by_action = {target.action_id: target for target in graph.target_resolutions}
        steps = []
        actions = graph.actions[: self.projection_config.max_actions]
        for action in actions:
            decision = decisions_by_action.get(action.action_id)
            producer_event = events_by_id.get(decision.producer_event_id) if decision is not None else None
            step = SkillDistillationStepView(
                step_id=action.action_id,
                sequence_index=action.sequence_index,
                action_kind=action.kind,
                occurred_at=action.occurred_at,
                media_time_ms=action.media_time_ms,
                hotkey_semantic=action.hotkey_semantic,
                key_chord=self._key_chord(producer_event),
                trigger_kind=decision.trigger_kind if decision is not None else None,
                target=self._safe_target(action.target, resolved=targets_by_action.get(action.action_id)),
                typing_summary=self._typing_summary(producer_event),
                evidence_keyframe_ids=self._evidence_keyframe_ids(
                    links=tuple(links_by_action.get(action.action_id, ())),
                    observation=observations_by_action.get(action.action_id),
                ),
                needs_review=(decision.needs_review if decision is not None else True)
                or (
                    targets_by_action[action.action_id].needs_review if action.action_id in targets_by_action else False
                ),
                sensitivity_flags=(decision.reason,) if decision is not None and decision.needs_review else (),
            )
            steps.append(step)
        return SkillDistillationInputView(
            session_id=session.session_id,
            steps=tuple(steps),
            projection=self._truncation(total_actions=graph.total_action_count, returned_actions=len(actions)),
            generated_at=self.clock.now(),
            warnings=tuple(warning.message for warning in session.warnings),
        )

    def _truncation(self, *, total_actions: int, returned_actions: int) -> ProjectionTruncationSummary:
        if total_actions == returned_actions:
            return ProjectionTruncationSummary()
        return ProjectionTruncationSummary(
            truncated=True,
            truncated_counts={"actions": total_actions - returned_actions},
        )

    def _key_chord(self, event: ProducerEventEnvelope | None) -> KeyChord | None:
        if event is None or event.keyboard is None:
            return None
        return event.keyboard.key_chord

    def _typing_summary(self, event: ProducerEventEnvelope | None) -> TypingSessionAggregateView | None:
        if event is None or event.keyboard is None:
            return None
        summary = event.keyboard.typing_summary
        if summary is None:
            return None
        return TypingSessionAggregateView(
            event_count=summary.event_count,
            text_event_count=summary.text_event_count,
            character_count=summary.character_count,
            deletion_key_count=summary.deletion_key_count,
            non_text_key_count=summary.non_text_key_count,
            composition_used=summary.composition_used,
            submitted_by_enter=summary.submitted_by_enter,
            duration_ms=summary.duration_ms,
        )

    def _safe_target(
        self,
        target: ActionTargetRef | None,
        *,
        resolved: ClickTargetResolution | None,
    ) -> SkillDistillationTargetView | None:
        if target is None and resolved is None:
            return None
        public_resolved = (
            self.target_scoring.public_view(
                resolved, has_coordinates=target.coordinates is not None if target else False
            )
            if resolved is not None
            else None
        )
        return SkillDistillationTargetView(
            target_kind=(
                HumanActionTargetKind.WINDOW
                if target is not None and target.target_kind == HumanActionTargetKind.WINDOW
                else HumanActionTargetKind.UNKNOWN
            ),
            resolved_target=public_resolved,
            confidence=(
                public_resolved.confidence if public_resolved is not None else (target.confidence if target else 0.0)
            ),
            has_coordinates=(
                target.coordinates is not None
                if target
                else public_resolved.has_coordinates if public_resolved else False
            ),
        )

    def _links_by_action(self, links: tuple[ActionEvidenceLink, ...]) -> dict[str, list[ActionEvidenceLink]]:
        links_by_action: dict[str, list[ActionEvidenceLink]] = {}
        for link in links:
            links_by_action.setdefault(link.action_id, []).append(link)
        return links_by_action

    def _evidence_keyframe_ids(
        self,
        *,
        links: tuple[ActionEvidenceLink, ...],
        observation: ActionResultObservation | None,
    ) -> tuple[str, ...]:
        ids = [link.keyframe_id for link in links if link.keyframe_id is not None]
        if observation is not None and observation.result_keyframe_id is not None:
            ids.append(observation.result_keyframe_id)
        return tuple(dict.fromkeys(ids))
