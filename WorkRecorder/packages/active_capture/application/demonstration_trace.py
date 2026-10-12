"""Human demonstration trace orchestration for active capture."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from packages.active_capture.application.service_helpers import is_terminal_status
from packages.active_capture.domain.media_time import media_time_from_recording_segments
from packages.active_capture.repositories.protocol import ActiveCaptureRepository
from packages.contracts import (
    ActionEvidenceLink,
    ActionEvidenceRefInput,
    ActionResultObservation,
    ActionTargetRef,
    ActiveCapturePolicyConfig,
    ActiveCaptureSession,
    ContextKeyframe,
    HumanActionEvent,
    HumanActionKind,
    HumanDemonstrationTrace,
    HumanDemonstrationTraceStatus,
    RecordHumanActionCommand,
)
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreparedHumanActionGraph:
    """Prepared action graph rows that can be committed atomically by a caller.

    Attributes:
        trace: Demonstration trace row with the final action count.
        action: Human action row with its preallocated action id and sequence.
        links: Evidence links attached to the action.
        observation: Optional result observation attached to the action.
    """

    trace: HumanDemonstrationTrace
    action: HumanActionEvent
    links: tuple[ActionEvidenceLink, ...]
    observation: ActionResultObservation | None


class DemonstrationTraceError(ValueError):
    """Raised when a demonstration trace action is invalid."""


class ActionEvidenceValidator:
    """Validate action evidence refs against the active-capture session graph."""

    def __init__(self, repository: ActiveCaptureRepository) -> None:
        self.repository = repository

    def validate(
        self,
        *,
        session: ActiveCaptureSession,
        refs: tuple[ActionEvidenceRefInput, ...],
        target: ActionTargetRef | None,
        result_keyframe_id: str | None,
    ) -> None:
        keyframes = self.repository.list_keyframes_for_session(session.session_id)
        keyframes_by_id: dict[str, ContextKeyframe] = {keyframe.keyframe_id: keyframe for keyframe in keyframes}
        session_event_ids = {item.event_id for item in keyframes}
        if session.primary_event_id is not None:
            session_event_ids.add(session.primary_event_id)
        link_edges: dict[str, set[tuple[str | None, str | None]]] = {}
        link_evidence_ids: dict[str, set[str]] = {}
        link_artifact_ids: dict[str, set[str]] = {}
        all_evidence_ids: set[str] = set()
        all_artifact_ids: set[str] = set()
        evidence_event_ids: dict[str, set[str]] = {}
        artifact_event_ids: dict[str, set[str]] = {}
        for keyframe in keyframes:
            edges: set[tuple[str | None, str | None]] = set()
            for link in self.repository.list_evidence_links_for_keyframe(keyframe.keyframe_id):
                edges.add((link.evidence_id, link.artifact_id))
                if link.evidence_id is not None:
                    link_evidence_ids.setdefault(keyframe.keyframe_id, set()).add(link.evidence_id)
                    all_evidence_ids.add(link.evidence_id)
                    evidence_event_ids.setdefault(link.evidence_id, set()).add(keyframe.event_id)
                if link.artifact_id is not None:
                    link_artifact_ids.setdefault(keyframe.keyframe_id, set()).add(link.artifact_id)
                    all_artifact_ids.add(link.artifact_id)
                    artifact_event_ids.setdefault(link.artifact_id, set()).add(keyframe.event_id)
            link_edges[keyframe.keyframe_id] = edges
        for ref in refs:
            self._validate_ref(
                keyframe_id=ref.keyframe_id,
                event_id=ref.event_id,
                evidence_id=ref.evidence_id,
                artifact_id=ref.artifact_id,
                keyframes_by_id=keyframes_by_id,
                session_event_ids=session_event_ids,
                link_edges=link_edges,
                link_evidence_ids=link_evidence_ids,
                link_artifact_ids=link_artifact_ids,
                all_evidence_ids=all_evidence_ids,
                all_artifact_ids=all_artifact_ids,
                evidence_event_ids=evidence_event_ids,
                artifact_event_ids=artifact_event_ids,
            )
        if target is not None:
            self._validate_ref(
                keyframe_id=target.keyframe_id,
                event_id=None,
                evidence_id=target.evidence_id,
                artifact_id=target.artifact_id,
                keyframes_by_id=keyframes_by_id,
                session_event_ids=session_event_ids,
                link_edges=link_edges,
                link_evidence_ids=link_evidence_ids,
                link_artifact_ids=link_artifact_ids,
                all_evidence_ids=all_evidence_ids,
                all_artifact_ids=all_artifact_ids,
                evidence_event_ids=evidence_event_ids,
                artifact_event_ids=artifact_event_ids,
            )
        if result_keyframe_id is not None and result_keyframe_id not in keyframes_by_id:
            raise DemonstrationTraceError("action result keyframe does not belong to active capture session")

    def _validate_ref(
        self,
        *,
        keyframe_id: str | None,
        event_id: str | None,
        evidence_id: str | None,
        artifact_id: str | None,
        keyframes_by_id: dict[str, ContextKeyframe],
        session_event_ids: set[str],
        link_edges: dict[str, set[tuple[str | None, str | None]]],
        link_evidence_ids: dict[str, set[str]],
        link_artifact_ids: dict[str, set[str]],
        all_evidence_ids: set[str],
        all_artifact_ids: set[str],
        evidence_event_ids: dict[str, set[str]],
        artifact_event_ids: dict[str, set[str]],
    ) -> None:
        keyframe = keyframes_by_id.get(keyframe_id) if keyframe_id is not None else None
        if keyframe_id is not None and keyframe is None:
            raise DemonstrationTraceError("action evidence keyframe does not belong to active capture session")
        if event_id is not None and event_id not in session_event_ids:
            raise DemonstrationTraceError("action evidence event does not belong to active capture session")
        if keyframe is not None and event_id is not None and keyframe.event_id != event_id:
            raise DemonstrationTraceError("action evidence keyframe/event mismatch")
        if keyframe_id is not None and (evidence_id is not None or artifact_id is not None):
            exact_pair_exists = (evidence_id, artifact_id) in link_edges.get(keyframe_id, set())
            evidence_belongs = evidence_id is None or evidence_id in link_evidence_ids.get(keyframe_id, set())
            artifact_belongs = artifact_id is None or artifact_id in link_artifact_ids.get(keyframe_id, set())
            if not exact_pair_exists and not (evidence_belongs and artifact_belongs):
                raise DemonstrationTraceError("action evidence link does not belong to the referenced keyframe")
        if keyframe_id is None and evidence_id is not None and evidence_id not in all_evidence_ids:
            raise DemonstrationTraceError("action evidence id does not belong to active capture session")
        if keyframe_id is None and artifact_id is not None and artifact_id not in all_artifact_ids:
            raise DemonstrationTraceError("action artifact id does not belong to active capture session")
        if keyframe_id is None and event_id is not None and evidence_id is not None:
            if event_id not in evidence_event_ids.get(evidence_id, set()):
                raise DemonstrationTraceError("action evidence id does not belong to the referenced event")
        if keyframe_id is None and event_id is not None and artifact_id is not None:
            if event_id not in artifact_event_ids.get(artifact_id, set()):
                raise DemonstrationTraceError("action artifact id does not belong to the referenced event")


class ActionMediaTimeResolver:
    """Derive action media time from trusted segment clocks."""

    def __init__(self, repository: ActiveCaptureRepository) -> None:
        self.repository = repository

    def resolve(self, *, session_id: str, occurred_at_monotonic_ms: int | None) -> int | None:
        return media_time_from_recording_segments(
            occurred_at_monotonic_ms=occurred_at_monotonic_ms,
            segments=self.repository.list_recording_segments_for_session(session_id),
        )


class HumanDemonstrationService:
    """Append low-sensitive action events and traceable evidence links."""

    def __init__(
        self,
        *,
        repository: ActiveCaptureRepository,
        ids: IdFactory,
        clock: Clock,
        config: ActiveCapturePolicyConfig,
    ) -> None:
        self.repository = repository
        self.ids = ids
        self.clock = clock
        self.config = config
        self.evidence_validator = ActionEvidenceValidator(repository)
        self.media_time_resolver = ActionMediaTimeResolver(repository)

    def record_action(
        self,
        *,
        session: ActiveCaptureSession,
        command: RecordHumanActionCommand,
    ) -> HumanActionEvent:
        """Record one human action with semantic, coordinate, and evidence refs."""

        if not self.config.action_trace_enabled:
            raise DemonstrationTraceError("active capture action trace is disabled")
        if is_terminal_status(session.status):
            raise DemonstrationTraceError("cannot record action for terminal active capture session")
        if (
            self.config.record_action_coordinates
            and command.kind in {HumanActionKind.CLICK, HumanActionKind.DRAG}
            and command.coordinates is None
            and command.target is None
        ):
            raise DemonstrationTraceError("action trace requires coordinates or a target reference")
        trace = self._trace_for_session(session)
        existing_count = len(self.repository.list_human_actions_for_session(session.session_id))
        if existing_count >= self.config.max_action_events_per_session:
            raise DemonstrationTraceError("active capture action trace budget exceeded")
        graph = self.prepare_action_graph(
            session=session,
            command=command,
            trace=trace,
            sequence_index=existing_count,
            now=self.clock.now(),
        )
        saved = self.repository.append_human_action_graph(
            action=graph.action,
            links=graph.links,
            observation=graph.observation,
            trace=graph.trace,
        )
        logger.info(
            "active capture human action recorded",
            extra={"session_id": session.session_id, "trace_id": trace.trace_id, "action_id": saved.action_id},
        )
        return saved

    def prepare_trace_for_session(self, session: ActiveCaptureSession) -> HumanDemonstrationTrace:
        """Return an existing trace or an unsaved trace for batch atomic writes."""

        trace = self.repository.get_demonstration_trace_for_session(session.session_id)
        if trace is not None:
            return trace
        now = self.clock.now()
        return HumanDemonstrationTrace(
            trace_id=self.ids.new("hdt"),
            session_id=session.session_id,
            status=HumanDemonstrationTraceStatus.ACTIVE,
            started_at=session.started_at or now,
            policy_version=self.config.policy_version,
        )

    def prepare_action_graph(
        self,
        *,
        session: ActiveCaptureSession,
        command: RecordHumanActionCommand,
        trace: HumanDemonstrationTrace,
        sequence_index: int,
        now: datetime,
        occurred_at: datetime | None = None,
    ) -> PreparedHumanActionGraph:
        """Build action rows without committing them, for producer batch transactions."""

        if not self.config.action_trace_enabled:
            raise DemonstrationTraceError("active capture action trace is disabled")
        if is_terminal_status(session.status):
            raise DemonstrationTraceError("cannot record action for terminal active capture session")
        if (
            self.config.record_action_coordinates
            and command.kind in {HumanActionKind.CLICK, HumanActionKind.DRAG}
            and command.coordinates is None
            and command.target is None
        ):
            raise DemonstrationTraceError("action trace requires coordinates or a target reference")
        self.evidence_validator.validate(
            session=session,
            refs=command.evidence_refs,
            target=command.target,
            result_keyframe_id=command.result.result_keyframe_id if command.result is not None else None,
        )
        action = HumanActionEvent(
            action_id=self.ids.new("act"),
            trace_id=trace.trace_id,
            session_id=session.session_id,
            sequence_index=sequence_index,
            kind=command.kind,
            occurred_at=occurred_at or now,
            occurred_at_monotonic_ms=command.occurred_at_monotonic_ms,
            media_time_ms=self.media_time_resolver.resolve(
                session_id=session.session_id,
                occurred_at_monotonic_ms=command.occurred_at_monotonic_ms,
            ),
            scope=command.scope or session.scope,
            coordinates=command.coordinates,
            target=command.target,
            semantic_hint=command.semantic_hint,
            hotkey_semantic=command.hotkey_semantic,
            scroll_delta_x=command.scroll_delta_x,
            scroll_delta_y=command.scroll_delta_y,
            policy_version=self.config.policy_version,
            metadata=command.metadata,
        )
        links = tuple(
            ActionEvidenceLink(
                link_id=self.ids.new("ael"),
                action_id=action.action_id,
                role=ref.role,
                keyframe_id=ref.keyframe_id,
                event_id=ref.event_id,
                evidence_id=ref.evidence_id,
                artifact_id=ref.artifact_id,
                created_at=now,
                metadata=ref.metadata,
            )
            for ref in command.evidence_refs
        )
        observation = None
        if command.result is not None:
            observation = ActionResultObservation(
                observation_id=self.ids.new("aob"),
                action_id=action.action_id,
                status=command.result.status,
                observed_at=now,
                observed_at_monotonic_ms=command.result.observed_at_monotonic_ms,
                result_keyframe_id=command.result.result_keyframe_id,
                summary=command.result.summary,
                metadata=command.result.metadata,
            )
            action = action.model_copy(update={"result_observation": observation})
        updated_trace = trace.model_copy(update={"action_count": sequence_index + 1})
        return PreparedHumanActionGraph(trace=updated_trace, action=action, links=links, observation=observation)

    def finalize_trace(self, session: ActiveCaptureSession) -> HumanDemonstrationTrace | None:
        """Mark an active trace ready when a recording session finalizes."""

        trace = self.repository.get_demonstration_trace_for_session(session.session_id)
        if trace is None:
            return None
        status = (
            HumanDemonstrationTraceStatus.COMPLETED_WITH_WARNINGS
            if session.warnings
            else HumanDemonstrationTraceStatus.READY
        )
        finalized = trace.model_copy(update={"status": status, "ended_at": session.ended_at or self.clock.now()})
        return self.repository.save_demonstration_trace(finalized)

    def _trace_for_session(self, session: ActiveCaptureSession) -> HumanDemonstrationTrace:
        trace = self.repository.get_demonstration_trace_for_session(session.session_id)
        if trace is not None:
            return trace
        now = self.clock.now()
        return self.repository.save_demonstration_trace(
            HumanDemonstrationTrace(
                trace_id=self.ids.new("hdt"),
                session_id=session.session_id,
                status=HumanDemonstrationTraceStatus.ACTIVE,
                started_at=session.started_at or now,
                policy_version=self.config.policy_version,
            )
        )
