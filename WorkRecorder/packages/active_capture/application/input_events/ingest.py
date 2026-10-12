"""Application service for trusted active-capture input producer events."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from packages.active_capture.application.demonstration_trace import HumanDemonstrationService, PreparedHumanActionGraph
from packages.active_capture.application.keyframe_triggers import KeyframeTriggerScheduler
from packages.active_capture.application.recording_projection import RecordingPublicProjector
from packages.active_capture.application.service_helpers import is_terminal_status
from packages.active_capture.application.vm_a11y_probe import VMAccessibilityProbePort
from packages.active_capture.application.vm_coordinate_mapping import VMDisplayGeometry, build_vm_display_mapping
from packages.active_capture.domain.input_events.decision_policy import ProducerEventDecisionPolicy, ProducerEventPlan
from packages.active_capture.keyframes.application.orchestrator import KeyframeTimingOrchestrator
from packages.active_capture.ports.input_events import ProducerEventRepository
from packages.active_capture.ports.telemetry import ActiveCaptureTelemetryPort, NullActiveCaptureTelemetry
from packages.contracts import (
    ActionPoint,
    ActiveCaptureMetricName,
    ActiveCapturePolicyConfig,
    ActiveCaptureSession,
    HumanActionEvent,
    HumanDemonstrationTrace,
    KeyframeDropReason,
    KeyframePriorityBand,
    KeyframeTriggerCandidate,
    KeyframeTriggerCandidateStatus,
    KeyframeTriggerKind,
    ProducerDecision,
    ProducerDecisionPublicSummary,
    ProducerDecisionReason,
    ProducerDecisionStatus,
    ProducerEventEnvelope,
    ProducerEventIngestBatchResult,
    ProducerEventIngestResult,
    ProducerEventPublicSummary,
    ProducerInputEventKind,
    RecordingScope,
    RecordingVideoSegmentRef,
    RecordProducerInputBatchCommand,
    RecordProducerInputEventCommand,
    SubmitKeyframeTriggerCommand,
)
from packages.contracts.common import JsonScalar
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

logger = logging.getLogger(__name__)

_VM_A11Y_PROBE_EVENT_KINDS = {
    ProducerInputEventKind.POINTER_CLICK,
    ProducerInputEventKind.POINTER_DRAG,
}


@dataclass(frozen=True)
class _BatchPlan:
    trace: HumanDemonstrationTrace | None
    action_graphs: tuple[PreparedHumanActionGraph, ...]
    trigger_candidates: tuple[KeyframeTriggerCandidate, ...]
    rows: tuple[
        tuple[
            ProducerEventEnvelope,
            ProducerDecision,
            HumanActionEvent | None,
            tuple[KeyframeTriggerCandidate, ...],
        ],
        ...,
    ]


class ProducerEventIngestService:
    """Persist producer events and fan them out to action trace and triggers."""

    def __init__(
        self,
        *,
        repository: ProducerEventRepository,
        demonstrations: HumanDemonstrationService,
        triggers: KeyframeTriggerScheduler,
        projector: RecordingPublicProjector,
        ids: IdFactory,
        clock: Clock,
        config: ActiveCapturePolicyConfig,
        timing_orchestrator: KeyframeTimingOrchestrator,
        decision_policy: ProducerEventDecisionPolicy | None = None,
        telemetry: ActiveCaptureTelemetryPort | None = None,
        vm_a11y_probe: VMAccessibilityProbePort | None = None,
        vm_display: VMDisplayGeometry | None = None,
    ) -> None:
        self.repository = repository
        self.demonstrations = demonstrations
        self.triggers = triggers
        self.projector = projector
        self.ids = ids
        self.clock = clock
        self.config = config
        self.decision_policy = decision_policy or ProducerEventDecisionPolicy(
            typing_milestone_keyframes_enabled=config.typing_milestone_keyframes_enabled,
            typing_milestone_min_chars=config.typing_milestone_min_chars,
            typing_milestone_min_events=config.typing_milestone_min_events,
        )
        self.timing_orchestrator = timing_orchestrator
        self.telemetry = telemetry or NullActiveCaptureTelemetry()
        self.vm_a11y_probe = vm_a11y_probe
        self.vm_display = vm_display

    def ingest_batch(
        self,
        *,
        session: ActiveCaptureSession,
        command: RecordProducerInputBatchCommand,
    ) -> ProducerEventIngestBatchResult:
        """Ingest one or more trusted producer events."""

        if is_terminal_status(session.status):
            raise ValueError("cannot ingest producer event for terminal active capture session")
        existing_count = self.repository.count_producer_events_for_session(session.session_id)
        if existing_count + len(command.events) > self.config.max_producer_events_per_session:
            raise ValueError("active capture producer event budget exceeded")
        results = self._plan_batch(session=session, command=command)
        self.repository.append_producer_event_batch_graph(
            trace=results.trace,
            actions=tuple(graph.action for graph in results.action_graphs),
            action_links=tuple(link for graph in results.action_graphs for link in graph.links),
            action_observations=tuple(
                graph.observation for graph in results.action_graphs if graph.observation is not None
            ),
            trigger_candidates=tuple(candidate for candidate in results.trigger_candidates),
            producer_events=tuple(event for event, _decision, _action, _trigger in results.rows),
            producer_decisions=tuple(decision for _event, decision, _action, _trigger in results.rows),
            max_producer_events_per_session=self.config.max_producer_events_per_session,
            max_action_events_per_session=self.config.max_action_events_per_session,
            max_pending_trigger_candidates=self.config.max_pending_trigger_candidates,
        )
        payload = tuple(
            ProducerEventIngestResult(
                event=self._public_event(event=event, decision=decision),
                decision=self._public_decision(decision),
                action=self.projector.to_public_human_action(action) if action is not None else None,
                trigger=(
                    self.projector.to_trigger_submission(primary)
                    if (primary := self._primary_candidate(triggers)) is not None
                    else None
                ),
                triggers=tuple(self.projector.to_trigger_submission(trigger) for trigger in triggers),
            )
            for event, decision, action, triggers in results.rows
        )
        self._notify_vm_a11y_probe(session=session, rows=results.rows)
        for event, decision, _action, _triggers in results.rows:
            self.telemetry.increment(
                ActiveCaptureMetricName.PRODUCER_INGEST,
                tags={
                    "event_kind": event.event_kind.value,
                    "decision": decision.status.value,
                    "reason": decision.reason.value,
                },
            )
            logger.info(
                "active capture producer event ingested",
                extra={
                    "session_id": session.session_id,
                    "producer_event_id": event.producer_event_id,
                    "event_kind": event.event_kind.value,
                    "decision": decision.status.value,
                    "reason": decision.reason.value,
                },
            )
        results_payload = payload
        return ProducerEventIngestBatchResult(results=results_payload)

    def _notify_vm_a11y_probe(
        self,
        *,
        session: ActiveCaptureSession,
        rows: tuple[
            tuple[
                ProducerEventEnvelope,
                ProducerDecision,
                HumanActionEvent | None,
                tuple[KeyframeTriggerCandidate, ...],
            ],
            ...,
        ],
    ) -> None:
        if self.vm_a11y_probe is None or not rows:
            return
        for event, _decision, _action, _triggers in rows:
            if event.event_kind not in _VM_A11Y_PROBE_EVENT_KINDS:
                continue
            try:
                point = event.pointer.coordinates.screen_abs if event.pointer is not None else None
                probe_x, probe_y, space = self._vm_probe_point(session=session, point=point)
                self.vm_a11y_probe.notify_local_operation(
                    session_id=session.session_id,
                    event_kind=event.event_kind.value,
                    occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
                    point_x=probe_x,
                    point_y=probe_y,
                    coordinate_space=space,
                )
            except Exception:
                logger.warning("VM DOM hit probe notification failed", exc_info=True)

    def _vm_probe_point(
        self,
        *,
        session: ActiveCaptureSession,
        point: ActionPoint | None,
    ) -> tuple[float | None, float | None, str | None]:
        """Map a macOS click point into VM screen coordinates for DOM hit probing.

        Falls back to the raw macOS point when VM screen geometry is not configured,
        and drops the point (window-level sample only) when the click lands outside
        the VM display so the probe never resolves a wrong element.
        """

        if point is None:
            return None, None, None
        scope = session.scope
        if self.vm_display is None or scope is None or scope.bounds is None:
            return point.x, point.y, point.coordinate_space.value
        mapping = build_vm_display_mapping(
            window_bounds=scope.bounds,
            vm_width=self.vm_display.vm_width,
            vm_height=self.vm_display.vm_height,
            title_bar_pt=self.vm_display.title_bar_pt,
        )
        if mapping is None:
            return point.x, point.y, point.coordinate_space.value
        vm_point = mapping.map_point(point.x, point.y)
        if vm_point is None:
            return None, None, "vm_unmapped"
        return vm_point[0], vm_point[1], "vm_screen"

    def ingest(
        self,
        *,
        session: ActiveCaptureSession,
        command: RecordProducerInputEventCommand,
    ) -> ProducerEventIngestResult:
        """Ingest one trusted producer event and emit derived graph rows."""

        return self.ingest_batch(
            session=session,
            command=RecordProducerInputBatchCommand(events=(command,)),
        ).results[0]

    def _plan_batch(self, *, session: ActiveCaptureSession, command: RecordProducerInputBatchCommand) -> "_BatchPlan":
        now = self.clock.now()
        trace: HumanDemonstrationTrace | None = None
        action_count = self.repository.count_human_actions_for_session(session.session_id)
        existing_candidates = list(
            self.repository.list_recent_trigger_candidates_for_session(
                session.session_id,
                statuses=(
                    KeyframeTriggerCandidateStatus.RECEIVED,
                    KeyframeTriggerCandidateStatus.ACCEPTED,
                    KeyframeTriggerCandidateStatus.CAPTURED,
                ),
                limit=max(self.config.max_pending_trigger_candidates * 4, 128),
            )
        )
        action_graphs: list[PreparedHumanActionGraph] = []
        trigger_candidates: list[KeyframeTriggerCandidate] = []
        rows: list[
            tuple[
                ProducerEventEnvelope, ProducerDecision, HumanActionEvent | None, tuple[KeyframeTriggerCandidate, ...]
            ]
        ] = []
        planned_events: list[ProducerEventEnvelope] = []
        for item in command.events:
            event = self._event_from_command(session=session, command=item)
            plan = self.decision_policy.plan(session=session, event=event)
            plan = self._maybe_upgrade_typing_milestone_plan(
                session=session,
                event=event,
                plan=plan,
                existing_candidates=tuple(existing_candidates),
                planned_events=tuple(planned_events),
            )
            decision = ProducerDecision(
                decision_id=self.ids.new("ped"),
                producer_event_id=event.producer_event_id,
                session_id=session.session_id,
                status=plan.status,
                reason=plan.reason,
                native_status=item.native_status,
                native_reason=item.native_reason,
                action_kind=plan.action.kind if plan.action is not None else None,
                trigger_kind=plan.trigger.trigger_kind if plan.trigger is not None else None,
                key_capture_policy=plan.key_capture_policy,
                redaction_state=event.redaction_state,
                needs_review=plan.needs_review,
                created_at=now,
                diagnostics=plan.diagnostics,
            )
            action: HumanActionEvent | None = None
            action_graph: PreparedHumanActionGraph | None = None
            if plan.action is not None and plan.status != ProducerDecisionStatus.BLOCKED:
                if action_count >= self.config.max_action_events_per_session:
                    raise ValueError("active capture action trace budget exceeded")
                if trace is None:
                    trace = self.demonstrations.prepare_trace_for_session(session)
                action_graph = self.demonstrations.prepare_action_graph(
                    session=session,
                    command=plan.action,
                    trace=trace,
                    sequence_index=action_count,
                    now=now,
                    occurred_at=event.occurred_at,
                )
                trace = action_graph.trace
                action = action_graph.action
                action_count += 1
                decision = decision.model_copy(update={"action_id": action.action_id})
            event_candidates: list[KeyframeTriggerCandidate] = []
            if plan.trigger is not None and plan.status != ProducerDecisionStatus.BLOCKED:
                timing = self.timing_orchestrator.prepare_for_producer_event(
                    session=session,
                    event=event,
                    action=action,
                    base_trigger=plan.trigger,
                    now=now,
                )
                if action_graph is not None and timing.before_action_link is not None:
                    action_graph = replace(action_graph, links=(*action_graph.links, timing.before_action_link))
                trigger_commands = timing.trigger_commands or (plan.trigger,)
                for trigger_command in trigger_commands:
                    candidate = self.triggers.prepare_candidate(
                        session=session,
                        command=trigger_command,
                        existing=tuple(existing_candidates),
                        pending_action_ids=frozenset({action.action_id} if action is not None else ()),
                    )
                    existing_candidates.append(candidate)
                    trigger_candidates.append(candidate)
                    event_candidates.append(candidate)
                primary = self._primary_candidate(tuple(event_candidates))
                if primary is not None:
                    decision = decision.model_copy(
                        update={
                            "status": self._decision_status_for_candidate(primary),
                            "reason": self._decision_reason_for_candidate(primary, fallback=decision.reason),
                            "candidate_id": primary.candidate_id,
                            "trigger_kind": primary.trigger_kind,
                            "debounce_until_monotonic_ms": primary.debounce_until_monotonic_ms,
                            "needs_review": decision.needs_review or timing.plan.needs_review,
                            "diagnostics": tuple(
                                dict.fromkeys(
                                    (
                                        *decision.diagnostics,
                                        *timing.plan.diagnostics,
                                        *(
                                            diagnostic
                                            for candidate in event_candidates
                                            for diagnostic in candidate.diagnostics
                                        ),
                                    )
                                )
                            ),
                        }
                    )
            if action_graph is not None:
                action_graphs.append(action_graph)
            rows.append((event, decision, action, tuple(event_candidates)))
            planned_events.append(event)
        return _BatchPlan(
            trace=trace,
            action_graphs=tuple(action_graphs),
            trigger_candidates=tuple(trigger_candidates),
            rows=tuple(rows),
        )

    def _maybe_upgrade_typing_milestone_plan(
        self,
        *,
        session: ActiveCaptureSession,
        event: ProducerEventEnvelope,
        plan: ProducerEventPlan,
        existing_candidates: tuple[KeyframeTriggerCandidate, ...],
        planned_events: tuple[ProducerEventEnvelope, ...],
    ) -> ProducerEventPlan:
        if (
            not self.config.typing_milestone_keyframes_enabled
            or event.event_kind != ProducerInputEventKind.TYPING_PAUSE
            or event.keyboard is None
            or event.keyboard.typing_summary is None
            or event.keyboard.typing_summary.submitted_by_enter
            or plan.trigger is not None
            or plan.action is None
            or plan.status != ProducerDecisionStatus.ACTION_ONLY
        ):
            return plan
        totals = self._coalesced_typing_totals(session=session, event=event, planned_events=planned_events)
        if totals is None:
            return plan
        character_count, event_count = totals
        if (
            character_count < self.config.typing_milestone_min_chars
            and event_count < self.config.typing_milestone_min_events
        ):
            return plan
        if self._has_recent_typing_materialization(
            current_event=event,
            existing_candidates=existing_candidates,
        ):
            return plan
        metadata: dict[str, JsonScalar] = {
            "producer_event_id": event.producer_event_id,
            "typing_char_count": character_count,
            "typing_event_count": event_count,
            "typing_capture_reason": "coalesced_typing_milestone",
        }
        return replace(
            plan,
            status=ProducerDecisionStatus.ACCEPTED,
            trigger=SubmitKeyframeTriggerCommand(
                trigger_kind=KeyframeTriggerKind.TYPING_SETTLE,
                priority=KeyframePriorityBand.HIGH,
                occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
                scope=event.scope,
                metadata=metadata,
            ),
            diagnostics=(
                *plan.diagnostics,
                "coalesced typing milestone stored with result keyframe",
                f"coalesced_typing_chars={character_count}",
                f"coalesced_typing_events={event_count}",
            ),
        )

    def _coalesced_typing_totals(
        self,
        *,
        session: ActiveCaptureSession,
        event: ProducerEventEnvelope,
        planned_events: tuple[ProducerEventEnvelope, ...],
    ) -> tuple[int, int] | None:
        if event.occurred_at_monotonic_ms is None:
            return None
        stored_events = self.repository.list_producer_events_for_session(session.session_id)
        recent_events = (*stored_events[-128:], *planned_events, event)
        character_count = 0
        event_count = 0
        window_ms = self.config.typing_milestone_coalesce_window_ms
        for candidate in reversed(recent_events):
            if candidate.occurred_at_monotonic_ms is None:
                continue
            if event.occurred_at_monotonic_ms - candidate.occurred_at_monotonic_ms > window_ms:
                break
            if candidate.event_kind != ProducerInputEventKind.TYPING_PAUSE:
                break
            if candidate.keyboard is None or candidate.keyboard.typing_summary is None:
                break
            if candidate.keyboard.typing_summary.submitted_by_enter:
                break
            if not self._same_typing_scope(event.scope, candidate.scope):
                break
            summary = candidate.keyboard.typing_summary
            character_count += summary.character_count
            event_count += max(summary.text_event_count, summary.event_count)
        if event_count <= 0 and character_count <= 0:
            return None
        return character_count, event_count

    def _has_recent_typing_materialization(
        self,
        *,
        current_event: ProducerEventEnvelope,
        existing_candidates: tuple[KeyframeTriggerCandidate, ...],
    ) -> bool:
        if current_event.occurred_at_monotonic_ms is None:
            return False
        lower_bound = max(0, current_event.occurred_at_monotonic_ms - self.config.typing_milestone_coalesce_window_ms)
        materializing_kinds = {
            KeyframeTriggerKind.TYPING_SETTLE,
            KeyframeTriggerKind.COMMAND_SUBMITTED,
        }
        return any(
            candidate.trigger_kind in materializing_kinds
            and candidate.occurred_at_monotonic_ms is not None
            and candidate.occurred_at_monotonic_ms >= lower_bound
            for candidate in existing_candidates
        )

    @staticmethod
    def _same_typing_scope(expected: RecordingScope | None, observed: RecordingScope | None) -> bool:
        if expected is None or observed is None:
            return True
        for field in ("bundle_id", "process_id", "window_id"):
            left = getattr(expected, field)
            right = getattr(observed, field)
            if left is not None and right is not None and left != right:
                return False
        return True

    def _primary_candidate(
        self,
        candidates: tuple[KeyframeTriggerCandidate, ...],
    ) -> KeyframeTriggerCandidate | None:
        if not candidates:
            return None
        preferred = (
            KeyframeTriggerKind.CLICK_SETTLE,
            KeyframeTriggerKind.COMMAND_SUBMITTED,
            KeyframeTriggerKind.HOTKEY_SETTLE,
            KeyframeTriggerKind.TYPING_SETTLE,
            KeyframeTriggerKind.SCROLL_STOP,
            KeyframeTriggerKind.NAVIGATION_COMMITTED,
            KeyframeTriggerKind.ACTION_RESULT_SETTLE,
            KeyframeTriggerKind.ERROR_SURFACE_DETECTED,
            KeyframeTriggerKind.SCROLL_MILESTONE,
            KeyframeTriggerKind.TARGET_RESOLUTION_PROBE,
            KeyframeTriggerKind.ACTION_BEFORE,
        )
        for kind in preferred:
            for candidate in candidates:
                if candidate.trigger_kind == kind:
                    return candidate
        return candidates[0]

    def _event_from_command(
        self,
        *,
        session: ActiveCaptureSession,
        command: RecordProducerInputEventCommand,
    ) -> ProducerEventEnvelope:
        now = self.clock.now()
        occurred_at = self._event_occurred_at(session=session, command=command, fallback=now)
        return ProducerEventEnvelope(
            producer_event_id=self.ids.new("pev"),
            session_id=session.session_id,
            event_kind=command.event_kind,
            producer_kind=command.producer_kind,
            producer_version=command.producer_version,
            occurred_at=occurred_at,
            occurred_at_wall_time=command.occurred_at_wall_time,
            occurred_at_monotonic_ms=command.occurred_at_monotonic_ms,
            scope=command.scope,
            pointer=command.pointer,
            scroll=command.scroll,
            keyboard=command.keyboard,
            redaction_state=command.redaction_state,
            policy_version=self.config.policy_version,
            metadata=command.metadata,
        )

    def _event_occurred_at(
        self,
        *,
        session: ActiveCaptureSession,
        command: RecordProducerInputEventCommand,
        fallback: datetime,
    ) -> datetime:
        if command.occurred_at_wall_time is not None:
            return command.occurred_at_wall_time
        derived = self._event_occurred_at_from_segments(
            session=session,
            occurred_at_monotonic_ms=command.occurred_at_monotonic_ms,
        )
        return derived or fallback

    def _event_occurred_at_from_segments(
        self,
        *,
        session: ActiveCaptureSession,
        occurred_at_monotonic_ms: int | None,
    ) -> datetime | None:
        if occurred_at_monotonic_ms is None:
            return None
        segments = self.repository.list_recording_segments_for_session(session.session_id)
        for segment in sorted(segments, key=lambda item: item.sequence_index):
            if not _segment_covers_monotonic(segment, occurred_at_monotonic_ms):
                continue
            return segment.started_at + timedelta(
                milliseconds=occurred_at_monotonic_ms - (segment.started_at_monotonic_ms or 0)
            )
        return None

    def _public_event(
        self,
        *,
        event: ProducerEventEnvelope,
        decision: ProducerDecision,
    ) -> ProducerEventPublicSummary:
        return ProducerEventPublicSummary(
            producer_event_id=event.producer_event_id,
            session_id=event.session_id,
            event_kind=event.event_kind,
            occurred_at=event.occurred_at,
            occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
            redaction_state=event.redaction_state,
            needs_review=decision.needs_review,
        )

    def _public_decision(self, decision: ProducerDecision) -> ProducerDecisionPublicSummary:
        return ProducerDecisionPublicSummary(
            decision_id=decision.decision_id,
            producer_event_id=decision.producer_event_id,
            session_id=decision.session_id,
            status=decision.status,
            reason=decision.reason,
            action_kind=decision.action_kind,
            trigger_kind=decision.trigger_kind,
            action_id=decision.action_id,
            candidate_id=decision.candidate_id,
            keyframe_id=decision.keyframe_id,
            debounce_until_monotonic_ms=decision.debounce_until_monotonic_ms,
            key_capture_policy=decision.key_capture_policy,
            redaction_state=decision.redaction_state,
            needs_review=decision.needs_review,
            diagnostics=decision.diagnostics,
        )

    def _decision_status_for_candidate(self, candidate: KeyframeTriggerCandidate) -> ProducerDecisionStatus:
        if candidate.status == KeyframeTriggerCandidateStatus.ACCEPTED:
            return ProducerDecisionStatus.ACCEPTED
        if candidate.status == KeyframeTriggerCandidateStatus.DEBOUNCED:
            return ProducerDecisionStatus.DEBOUNCED
        if candidate.status == KeyframeTriggerCandidateStatus.DROPPED:
            return ProducerDecisionStatus.DROPPED
        return ProducerDecisionStatus.ACTION_ONLY

    def _decision_reason_for_candidate(
        self,
        candidate: KeyframeTriggerCandidate,
        *,
        fallback: ProducerDecisionReason,
    ) -> ProducerDecisionReason:
        if candidate.drop_reason == KeyframeDropReason.TOO_SOON:
            return ProducerDecisionReason.TOO_SOON
        if candidate.drop_reason == KeyframeDropReason.BUDGET_EXCEEDED:
            return ProducerDecisionReason.BUDGET_EXCEEDED
        if candidate.drop_reason == KeyframeDropReason.LOW_DELTA:
            return ProducerDecisionReason.LOW_DELTA
        return fallback


def _segment_covers_monotonic(segment: RecordingVideoSegmentRef, occurred_at_monotonic_ms: int) -> bool:
    if segment.started_at_monotonic_ms is None:
        return False
    if occurred_at_monotonic_ms < segment.started_at_monotonic_ms:
        return False
    end = segment.ended_at_monotonic_ms
    if end is None and segment.duration_ms is not None:
        end = segment.started_at_monotonic_ms + segment.duration_ms
    return end is None or occurred_at_monotonic_ms <= end
