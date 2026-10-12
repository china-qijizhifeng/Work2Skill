"""Decision strategies for trusted active-capture producer events."""

from __future__ import annotations

from dataclasses import dataclass

from packages.contracts import (
    ActionPoint,
    ActiveCaptureSession,
    BoundingBox,
    HotkeySemantic,
    HumanActionKind,
    KeyCapturePolicy,
    KeyframePriorityBand,
    KeyframeTriggerKind,
    ProducerDecisionReason,
    ProducerDecisionStatus,
    ProducerEventEnvelope,
    ProducerInputEventKind,
    RecordHumanActionCommand,
    RecordingScope,
    RedactionState,
    ScrollPhase,
    SubmitKeyframeTriggerCommand,
    TypingSessionSummary,
)


@dataclass(frozen=True)
class ProducerEventPlan:
    """Internal plan derived from one producer event.

    Attributes:
        status: Final backend status for this producer event.
        reason: Typed backend reason used for audit and P7.11 review.
        action: Optional action-trace command to append.
        trigger: Optional keyframe-trigger command to submit.
        key_capture_policy: Keyboard storage policy applied to this event.
        needs_review: Whether future skill distillation should ask for review.
        diagnostics: Safe diagnostics explaining policy decisions.
    """

    status: ProducerDecisionStatus
    reason: ProducerDecisionReason
    action: RecordHumanActionCommand | None = None
    trigger: SubmitKeyframeTriggerCommand | None = None
    key_capture_policy: KeyCapturePolicy | None = None
    needs_review: bool = False
    diagnostics: tuple[str, ...] = ()


class ProducerEventDecisionPolicy:
    """Map privacy-checked producer events to action traces and keyframe triggers."""

    def __init__(
        self,
        *,
        typing_milestone_keyframes_enabled: bool = True,
        typing_milestone_min_chars: int = 8,
        typing_milestone_min_events: int = 8,
    ) -> None:
        self.typing_milestone_keyframes_enabled = typing_milestone_keyframes_enabled
        self.typing_milestone_min_chars = typing_milestone_min_chars
        self.typing_milestone_min_events = typing_milestone_min_events

    def plan(self, *, session: ActiveCaptureSession, event: ProducerEventEnvelope) -> ProducerEventPlan:
        """Return the backend decision plan for a producer event."""

        if event.redaction_state in {RedactionState.BLOCKED, RedactionState.QUARANTINED}:
            return ProducerEventPlan(
                status=ProducerDecisionStatus.BLOCKED,
                reason=ProducerDecisionReason.SENSITIVE_TARGET,
                key_capture_policy=self._key_capture_policy(event),
                needs_review=True,
                diagnostics=("producer event blocked by redaction state",),
            )
        if not self._matches_session_scope(session=session, event=event):
            return ProducerEventPlan(
                status=ProducerDecisionStatus.DROPPED,
                reason=ProducerDecisionReason.SCOPE_LOST,
                key_capture_policy=self._key_capture_policy(event),
                needs_review=True,
                diagnostics=("producer event outside active capture session scope",),
            )
        match event.event_kind:
            case ProducerInputEventKind.POINTER_CLICK:
                return self._click_plan(event)
            case ProducerInputEventKind.POINTER_DRAG:
                return self._drag_plan(event)
            case ProducerInputEventKind.SCROLL:
                return self._scroll_plan(event)
            case ProducerInputEventKind.HOTKEY:
                return self._hotkey_plan(event)
            case ProducerInputEventKind.KEY_DOWN | ProducerInputEventKind.KEY_UP:
                return self._raw_key_plan(event)
            case ProducerInputEventKind.TYPING_PAUSE:
                return self._typing_plan(event)
            case ProducerInputEventKind.WINDOW_FOCUS:
                return self._focus_plan(event, HumanActionKind.WINDOW_SWITCH, KeyframeTriggerKind.FOCUS_CHANGE)
            case ProducerInputEventKind.TAB_SWITCH:
                return self._focus_plan(event, HumanActionKind.TAB_SWITCH, KeyframeTriggerKind.SURFACE_CHANGE)
            case _:
                return ProducerEventPlan(
                    status=ProducerDecisionStatus.DROPPED,
                    reason=ProducerDecisionReason.UNSUPPORTED_EVENT,
                    key_capture_policy=self._key_capture_policy(event),
                    diagnostics=("producer event stored without action or trigger",),
                )

    def _click_plan(self, event: ProducerEventEnvelope) -> ProducerEventPlan:
        assert event.pointer is not None
        return ProducerEventPlan(
            status=ProducerDecisionStatus.ACCEPTED,
            reason=ProducerDecisionReason.CLICK_SETTLED,
            action=RecordHumanActionCommand(
                kind=HumanActionKind.CLICK,
                occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
                scope=event.scope,
                coordinates=event.pointer.coordinates,
                target=event.pointer.target,
                metadata={
                    "producer_event_id": event.producer_event_id,
                    "button": event.pointer.button.value,
                    "click_count": event.pointer.click_count,
                },
            ),
            trigger=SubmitKeyframeTriggerCommand(
                trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
                occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
                scope=event.scope,
                metadata={"producer_event_id": event.producer_event_id},
            ),
        )

    def _drag_plan(self, event: ProducerEventEnvelope) -> ProducerEventPlan:
        assert event.pointer is not None
        metadata = {"producer_event_id": event.producer_event_id}
        metadata.update(event.metadata)
        return ProducerEventPlan(
            status=ProducerDecisionStatus.ACCEPTED,
            reason=ProducerDecisionReason.DRAG_SETTLED,
            action=RecordHumanActionCommand(
                kind=HumanActionKind.DRAG,
                occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
                scope=event.scope,
                coordinates=event.pointer.coordinates,
                target=event.pointer.target,
                metadata=metadata,
            ),
            trigger=SubmitKeyframeTriggerCommand(
                trigger_kind=KeyframeTriggerKind.ACTION_RESULT_SETTLE,
                occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
                scope=event.scope,
                metadata={"producer_event_id": event.producer_event_id},
            ),
        )

    def _scroll_plan(self, event: ProducerEventEnvelope) -> ProducerEventPlan:
        assert event.scroll is not None
        action = RecordHumanActionCommand(
            kind=HumanActionKind.SCROLL,
            occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
            scope=event.scope,
            coordinates=event.scroll.coordinates,
            target=event.scroll.target,
            scroll_delta_x=event.scroll.delta_x,
            scroll_delta_y=event.scroll.delta_y,
        )
        if event.scroll.phase not in {ScrollPhase.ENDED, ScrollPhase.CANCELLED}:
            return ProducerEventPlan(
                status=ProducerDecisionStatus.ACTION_ONLY,
                reason=ProducerDecisionReason.SCROLL_STOPPED,
                action=action,
                diagnostics=("scroll phase stored as action-only until terminal stop",),
            )
        return ProducerEventPlan(
            status=ProducerDecisionStatus.ACCEPTED,
            reason=ProducerDecisionReason.SCROLL_STOPPED,
            action=action,
            trigger=SubmitKeyframeTriggerCommand(
                trigger_kind=KeyframeTriggerKind.SCROLL_STOP,
                occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
                scope=event.scope,
                metadata={"producer_event_id": event.producer_event_id},
            ),
        )

    def _hotkey_plan(self, event: ProducerEventEnvelope) -> ProducerEventPlan:
        assert event.keyboard is not None
        semantic = event.keyboard.hotkey_semantic or HotkeySemantic.UNKNOWN
        if semantic == HotkeySemantic.UNKNOWN:
            return ProducerEventPlan(
                status=ProducerDecisionStatus.ACTION_ONLY,
                reason=ProducerDecisionReason.UNSUPPORTED_EVENT,
                action=RecordHumanActionCommand(
                    kind=HumanActionKind.HOTKEY,
                    occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
                    scope=event.scope,
                    target=event.keyboard.target,
                    hotkey_semantic=semantic,
                ),
                key_capture_policy=event.keyboard.capture_policy,
                needs_review=True,
                diagnostics=("unknown hotkey semantic stored without keyframe trigger",),
            )
        trigger_kind = (
            KeyframeTriggerKind.COMMAND_SUBMITTED
            if semantic in {HotkeySemantic.SUBMIT, HotkeySemantic.SEARCH}
            else KeyframeTriggerKind.HOTKEY_SETTLE
        )
        reason = (
            ProducerDecisionReason.COMMAND_SUBMITTED
            if trigger_kind == KeyframeTriggerKind.COMMAND_SUBMITTED
            else ProducerDecisionReason.HOTKEY_SETTLED
        )
        return ProducerEventPlan(
            status=ProducerDecisionStatus.ACCEPTED,
            reason=reason,
            action=RecordHumanActionCommand(
                kind=HumanActionKind.HOTKEY,
                occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
                scope=event.scope,
                target=event.keyboard.target,
                hotkey_semantic=semantic,
            ),
            trigger=SubmitKeyframeTriggerCommand(
                trigger_kind=trigger_kind,
                priority=KeyframePriorityBand.HIGH,
                occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
                scope=event.scope,
                metadata={"producer_event_id": event.producer_event_id},
            ),
            key_capture_policy=event.keyboard.capture_policy,
        )

    def _raw_key_plan(self, event: ProducerEventEnvelope) -> ProducerEventPlan:
        assert event.keyboard is not None
        action_kind = (
            HumanActionKind.KEY_DOWN
            if event.event_kind == ProducerInputEventKind.KEY_DOWN
            else HumanActionKind.KEY_UP
        )
        return ProducerEventPlan(
            status=ProducerDecisionStatus.ACTION_ONLY,
            reason=ProducerDecisionReason.RAW_KEYSTROKE_CAPTURED,
            action=RecordHumanActionCommand(
                kind=action_kind,
                occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
                scope=event.scope,
                target=event.keyboard.target,
            ),
            key_capture_policy=event.keyboard.capture_policy,
            diagnostics=("full-content keyboard capture enabled",),
        )

    def _typing_plan(self, event: ProducerEventEnvelope) -> ProducerEventPlan:
        assert event.keyboard is not None
        if event.keyboard.capture_policy == KeyCapturePolicy.BLOCKED:
            return ProducerEventPlan(
                status=ProducerDecisionStatus.BLOCKED,
                reason=ProducerDecisionReason.SENSITIVE_TARGET,
                key_capture_policy=event.keyboard.capture_policy,
                needs_review=True,
                diagnostics=("typing pause blocked by producer capture policy",),
            )
        submitted_by_enter = (
            event.keyboard.typing_summary.submitted_by_enter if event.keyboard.typing_summary is not None else False
        )
        action = RecordHumanActionCommand(
            kind=HumanActionKind.TYPING_PAUSE,
            occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
            scope=event.scope,
            target=event.keyboard.target or (event.keyboard.typing_summary.target if event.keyboard.typing_summary else None),
        )
        if not submitted_by_enter:
            if self._should_capture_typing_milestone(event.keyboard.typing_summary):
                metadata = {"producer_event_id": event.producer_event_id}
                if event.keyboard.typing_summary is not None:
                    metadata.update(
                        {
                            "typing_char_count": event.keyboard.typing_summary.character_count,
                            "typing_event_count": event.keyboard.typing_summary.event_count,
                            "typing_capture_reason": "typing_milestone",
                        }
                    )
                return ProducerEventPlan(
                    status=ProducerDecisionStatus.ACCEPTED,
                    reason=ProducerDecisionReason.TYPING_SETTLED,
                    action=action,
                    trigger=SubmitKeyframeTriggerCommand(
                        trigger_kind=KeyframeTriggerKind.TYPING_SETTLE,
                        priority=KeyframePriorityBand.HIGH,
                        occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
                        scope=event.scope,
                        metadata=metadata,
                    ),
                    key_capture_policy=event.keyboard.capture_policy,
                    diagnostics=("meaningful typing milestone stored with result keyframe",),
                )
            return ProducerEventPlan(
                status=ProducerDecisionStatus.ACTION_ONLY,
                reason=ProducerDecisionReason.TYPING_SETTLED,
                action=action,
                key_capture_policy=event.keyboard.capture_policy,
                diagnostics=("typing pause stored as trace-only; no keyframe trigger",),
            )
        return ProducerEventPlan(
            status=ProducerDecisionStatus.ACCEPTED,
            reason=ProducerDecisionReason.COMMAND_SUBMITTED,
            action=action,
            trigger=SubmitKeyframeTriggerCommand(
                trigger_kind=KeyframeTriggerKind.COMMAND_SUBMITTED,
                priority=KeyframePriorityBand.HIGH,
                occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
                scope=event.scope,
                metadata={"producer_event_id": event.producer_event_id},
            ),
            key_capture_policy=event.keyboard.capture_policy,
        )

    def _should_capture_typing_milestone(self, summary: TypingSessionSummary | None) -> bool:
        if not self.typing_milestone_keyframes_enabled or summary is None:
            return False
        if summary.character_count >= self.typing_milestone_min_chars:
            return True
        return summary.text_event_count >= self.typing_milestone_min_events or summary.event_count >= self.typing_milestone_min_events

    def _focus_plan(
        self,
        event: ProducerEventEnvelope,
        action_kind: HumanActionKind,
        trigger_kind: KeyframeTriggerKind,
    ) -> ProducerEventPlan:
        return ProducerEventPlan(
            status=ProducerDecisionStatus.ACCEPTED,
            reason=ProducerDecisionReason.FOCUS_CHANGED,
            action=RecordHumanActionCommand(
                kind=action_kind,
                occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
                scope=event.scope,
            ),
            trigger=SubmitKeyframeTriggerCommand(
                trigger_kind=trigger_kind,
                priority=KeyframePriorityBand.HIGH,
                occurred_at_monotonic_ms=event.occurred_at_monotonic_ms,
                scope=event.scope,
                metadata={"producer_event_id": event.producer_event_id},
            ),
        )

    def _key_capture_policy(self, event: ProducerEventEnvelope) -> KeyCapturePolicy | None:
        if event.keyboard is None:
            return None
        return event.keyboard.capture_policy

    def _matches_session_scope(self, *, session: ActiveCaptureSession, event: ProducerEventEnvelope) -> bool:
        session_scope = session.scope
        if session_scope is None:
            return True
        strict_identity = self._requires_observed_scope_identity(event)
        if strict_identity:
            if not self._has_observed_scope_identity(session_scope):
                return False
            if event.scope is None or not self._has_observed_scope_identity(event.scope):
                return False
            if not self._scope_field_matches(
                expected=session_scope.window_id,
                observed=event.scope.window_id,
                strict=True,
            ):
                return False
            if not self._scope_field_matches(
                expected=session_scope.process_id,
                observed=event.scope.process_id,
                strict=True,
            ):
                return False
            if not self._scope_field_matches(
                expected=session_scope.bundle_id,
                observed=event.scope.bundle_id,
                strict=True,
            ):
                return False
            return True
        if event.scope is not None:
            if not self._scope_field_matches(
                expected=session_scope.window_id,
                observed=event.scope.window_id,
                strict=False,
            ):
                return False
            if not self._scope_field_matches(
                expected=session_scope.process_id,
                observed=event.scope.process_id,
                strict=False,
            ):
                return False
            if not self._scope_field_matches(
                expected=session_scope.bundle_id,
                observed=event.scope.bundle_id,
                strict=False,
            ):
                return False
        elif event.pointer is None:
            return False
        if event.pointer is None or event.pointer.coordinates.screen_abs is None:
            return True
        bounds = session_scope.bounds or session_scope.selection_region
        if bounds is None:
            return True
        return self._point_inside_bounds(event.pointer.coordinates.screen_abs, bounds)

    def _requires_observed_scope_identity(self, event: ProducerEventEnvelope) -> bool:
        return event.event_kind in {
            ProducerInputEventKind.SCROLL,
            ProducerInputEventKind.HOTKEY,
            ProducerInputEventKind.TYPING_PAUSE,
            ProducerInputEventKind.WINDOW_FOCUS,
            ProducerInputEventKind.TAB_SWITCH,
        }

    def _has_observed_scope_identity(self, scope: RecordingScope) -> bool:
        return scope.window_id is not None or scope.process_id is not None or scope.bundle_id is not None

    def _scope_field_matches(self, *, expected: object | None, observed: object | None, strict: bool) -> bool:
        if expected is None:
            return True
        if observed is None:
            return not strict
        return observed == expected

    def _point_inside_bounds(self, point: ActionPoint, bounds: BoundingBox) -> bool:
        margin = 2.0
        return (
            float(bounds.x) - margin <= point.x <= float(bounds.x + bounds.width) + margin
            and float(bounds.y) - margin <= point.y <= float(bounds.y + bounds.height) + margin
        )
