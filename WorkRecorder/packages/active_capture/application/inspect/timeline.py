"""Agent-safe active-capture timeline projection."""

from __future__ import annotations

from collections.abc import Mapping

from packages.active_capture.click_targets.domain.scoring import ClickTargetScoringPolicy
from packages.active_capture.domain.media_time import media_time_from_recording_segments
from packages.contracts import (
    ActionEvidenceLink,
    ActionResultObservation,
    ActiveCaptureCitationKind,
    ActiveCaptureCitationRef,
    ActiveCaptureCitationTarget,
    ClickTargetPublicView,
    ClickTargetResolution,
    ClickTargetResolverConfig,
    ContextKeyframe,
    HumanActionEvent,
    HumanActionEvidenceRole,
    HumanActionKind,
    HotkeySemantic,
    HumanActionOutcomeStatus,
    KeyframeRole,
    KeyframeTriggerKind,
    ProducerDecision,
    ProducerEventEnvelope,
    RecordingActionSummaryView,
    RecordingControlEvent,
    RecordingStoryboardItemKind,
    RecordingTimelineInspectView,
    RecordingTimelineManifest,
    RecordingTimelineStepFoldReason,
    RecordingTimelineStepView,
    RecordingTimelineStepVisibilityClass,
    SkillReadinessState,
    SkillReadinessSummary,
    TimelineKeyframeEntry,
    TypingSessionAggregateView,
    TypingSessionSummary,
)

from .batch_loader import RecordingInspectGraph


class RecordingTimelineProjector:
    """Build ordered timeline steps for agent inspect."""

    def __init__(self) -> None:
        self.target_scoring = ClickTargetScoringPolicy(config=ClickTargetResolverConfig())

    def build(self, graph: RecordingInspectGraph) -> RecordingTimelineInspectView:
        """Return a timeline with keyframes, actions, and controls."""

        timeline_entries = {entry.keyframe_id: entry for entry in graph.timeline.entries} if graph.timeline else {}
        decisions_by_action = {
            decision.action_id: decision for decision in graph.producer_decisions if decision.action_id
        }
        producer_events_by_id = {event.producer_event_id: event for event in graph.producer_events}
        links_by_action: dict[str, list[str]] = {}
        action_links_by_action: dict[str, list[ActionEvidenceLink]] = {action.action_id: [] for action in graph.actions}
        for link in graph.action_links:
            action_links_by_action.setdefault(link.action_id, []).append(link)
            if link.keyframe_id is not None:
                links_by_action.setdefault(link.action_id, []).append(link.keyframe_id)
        observations_by_action = {observation.action_id: observation for observation in graph.action_observations}
        targets_by_action = {target.action_id: target for target in graph.target_resolutions}
        steps: list[RecordingTimelineStepView] = []
        for keyframe in graph.keyframes:
            entry = timeline_entries.get(keyframe.keyframe_id)
            media_time_ms = self._keyframe_media_time_ms(
                keyframe=keyframe,
                entry=entry,
                timeline_duration_ms=graph.timeline.duration_ms if graph.timeline is not None else None,
            )
            step_id = f"kf:{keyframe.keyframe_id}"
            steps.append(
                RecordingTimelineStepView(
                    step_id=step_id,
                    kind=RecordingStoryboardItemKind.KEYFRAME,
                    occurred_at=keyframe.captured_at,
                    media_time_ms=media_time_ms,
                    sequence_index=keyframe.sequence_index,
                    keyframe_id=keyframe.keyframe_id,
                    keyframe_event_id=keyframe.event_id,
                    visibility_class=self._keyframe_visibility_class(keyframe.trigger_kind, keyframe.quality.metrics),
                    fold_reason=self._keyframe_fold_reason(keyframe.trigger_kind, keyframe.quality.metrics),
                    safe_text_ref_ids=tuple(
                        ref for ref in (keyframe.keyframe_id, keyframe.event_id) if ref is not None
                    ),
                    keyframe_role=keyframe.role,
                    trigger_kind=keyframe.trigger_kind,
                    safe_caption=self._keyframe_caption(keyframe.role),
                    needs_review=keyframe.quality.confidence < 0.5,
                    readiness=self._readiness(needs_review=keyframe.quality.confidence < 0.5),
                    citations=(
                        self._citation(
                            kind=ActiveCaptureCitationKind.KEYFRAME,
                            session_id=graph.session.session_id,
                            event_id=keyframe.event_id,
                            keyframe_id=keyframe.keyframe_id,
                            timeline_step_id=step_id,
                            media_time_ms=media_time_ms,
                            field_path=f"active_capture.timeline.{step_id}",
                        ),
                    ),
                )
            )
        for action in graph.actions:
            decision = decisions_by_action.get(action.action_id)
            observation = observations_by_action.get(action.action_id)
            target = targets_by_action.get(action.action_id)
            evidence_keyframes = tuple(dict.fromkeys(links_by_action.get(action.action_id, ())))
            action_summary = self._action_summary(
                action=action,
                decision=decision,
                producer_event=(
                    producer_events_by_id.get(decision.producer_event_id) if decision is not None else None
                ),
                links=tuple(action_links_by_action.get(action.action_id, ())),
                observation=observation,
                target=target,
            )
            needs_review = self._action_needs_review(
                action,
                decision_needs_review=decision.needs_review if decision is not None else True,
                evidence_keyframes=evidence_keyframes,
                has_result=observation is not None and observation.status == HumanActionOutcomeStatus.OBSERVED,
            ) or (target.needs_review if target is not None else False)
            visibility_class, fold_reason = self._action_visibility(action=action, action_summary=action_summary)
            action_media_time_ms = self._action_media_time_ms(
                action=action,
                action_summary=action_summary,
                timeline_entries=timeline_entries,
                timeline=graph.timeline,
                segments=graph.segments,
            )
            step_id = f"act:{action.action_id}"
            steps.append(
                RecordingTimelineStepView(
                    step_id=step_id,
                    kind=RecordingStoryboardItemKind.ACTION,
                    occurred_at=action.occurred_at,
                    media_time_ms=action_media_time_ms,
                    sequence_index=action.sequence_index,
                    action_id=action.action_id,
                    action_kind=action.kind,
                    action_summary=action_summary,
                    visibility_class=visibility_class,
                    fold_reason=fold_reason,
                    safe_text_ref_ids=self._action_safe_text_ref_ids(action_summary),
                    safe_caption=self._action_caption(action, target=target, action_summary=action_summary),
                    needs_review=needs_review,
                    readiness=self._readiness(needs_review=needs_review),
                    citations=(
                        self._citation(
                            kind=ActiveCaptureCitationKind.ACTION_STEP,
                            session_id=graph.session.session_id,
                            event_id=self._event_id_for_action(graph),
                            action_id=action.action_id,
                            timeline_step_id=step_id,
                            media_time_ms=action_media_time_ms,
                            field_path=f"active_capture.timeline.{step_id}",
                        ),
                    ),
                )
            )
        for control in graph.controls:
            step_id = f"ctl:{control.control_id}"
            steps.append(
                RecordingTimelineStepView(
                    step_id=step_id,
                    kind=RecordingStoryboardItemKind.CONTROL,
                    occurred_at=control.occurred_at,
                    media_time_ms=self._control_media_time_ms(
                        control=control,
                        timeline=graph.timeline,
                        segments=graph.segments,
                    ),
                    control_id=control.control_id,
                    control_kind=control.kind,
                    visibility_class=self._control_visibility_class(control.kind),
                    fold_reason=self._control_fold_reason(control.kind),
                    safe_caption=self._control_caption(control.kind),
                    readiness=self._readiness(needs_review=False),
                )
            )
        return RecordingTimelineInspectView(
            session_id=graph.session.session_id,
            duration_ms=graph.timeline.duration_ms if graph.timeline is not None else None,
            alignment_error_ms=graph.timeline.alignment_error_ms if graph.timeline is not None else None,
            steps=tuple(sorted(steps, key=self._sort_key)),
        )

    def _citation(
        self,
        *,
        kind: ActiveCaptureCitationKind,
        session_id: str,
        event_id: str,
        field_path: str,
        keyframe_id: str | None = None,
        action_id: str | None = None,
        timeline_step_id: str | None = None,
        media_time_ms: int | None = None,
    ) -> ActiveCaptureCitationRef:
        return ActiveCaptureCitationRef(
            target=ActiveCaptureCitationTarget(
                kind=kind,
                session_id=session_id,
                event_id=event_id,
                keyframe_id=keyframe_id,
                action_id=action_id,
                timeline_step_id=timeline_step_id,
                media_time_ms=media_time_ms,
                field_path=field_path,
            ),
        )

    def _keyframe_media_time_ms(
        self,
        *,
        keyframe: ContextKeyframe,
        entry: TimelineKeyframeEntry | None,
        timeline_duration_ms: int | None,
    ) -> int | None:
        if entry is not None and entry.media_time_ms is not None:
            return entry.media_time_ms
        if keyframe.media_time_ms is not None:
            return keyframe.media_time_ms
        if keyframe.role == KeyframeRole.FINAL and timeline_duration_ms is not None:
            return timeline_duration_ms
        return None

    def _action_media_time_ms(
        self,
        *,
        action: HumanActionEvent,
        action_summary: RecordingActionSummaryView,
        timeline_entries: Mapping[str, TimelineKeyframeEntry],
        timeline: RecordingTimelineManifest | None,
        segments: tuple = (),
    ) -> int | None:
        media_time_from_segments = media_time_from_recording_segments(
            occurred_at_monotonic_ms=action.occurred_at_monotonic_ms,
            segments=segments,
        )
        if media_time_from_segments is not None:
            return media_time_from_segments
        if action.media_time_ms is not None:
            return action.media_time_ms
        for keyframe_id in self._action_media_keyframe_candidates(action_summary):
            entry = timeline_entries.get(keyframe_id)
            if entry is not None and entry.media_time_ms is not None:
                return entry.media_time_ms
        if (
            timeline is not None
            and timeline.clock_origin_monotonic_ms is not None
            and action.occurred_at_monotonic_ms is not None
        ):
            media_time_ms = max(0, action.occurred_at_monotonic_ms - timeline.clock_origin_monotonic_ms)
            if timeline.duration_ms is not None:
                return min(media_time_ms, timeline.duration_ms)
            return media_time_ms
        return None

    def _action_media_keyframe_candidates(self, action_summary: RecordingActionSummaryView) -> tuple[str, ...]:
        ordered: list[str] = []
        if action_summary.result_keyframe_id is not None:
            ordered.append(action_summary.result_keyframe_id)
        ordered.extend(action_summary.after_keyframe_ids)
        ordered.extend(action_summary.target_evidence_keyframe_ids)
        ordered.extend(action_summary.before_keyframe_ids)
        return tuple(dict.fromkeys(ordered))

    def _keyframe_caption(self, role: KeyframeRole) -> str:
        if role == KeyframeRole.START:
            return "开始录制"
        if role == KeyframeRole.FINAL:
            return "结束录制"
        if role == KeyframeRole.BEFORE_ACTION:
            return "动作前"
        if role == KeyframeRole.RESULT:
            return "动作结果"
        if role == KeyframeRole.USER_MARK:
            return "手动标记"
        if role == KeyframeRole.PAUSE_BOUNDARY:
            return "暂停边界"
        if role == KeyframeRole.RESUME_BOUNDARY:
            return "继续边界"
        if role == KeyframeRole.ERROR_STATE:
            return "异常状态"
        if role == KeyframeRole.SCROLL_MILESTONE:
            return "滚动章节"
        return "关键帧"

    def _keyframe_visibility_class(
        self,
        trigger_kind: KeyframeTriggerKind,
        metrics: Mapping[str, object],
    ) -> RecordingTimelineStepVisibilityClass:
        if self._keyframe_fold_reason(trigger_kind, metrics) is not None:
            return RecordingTimelineStepVisibilityClass.FOLDED
        return RecordingTimelineStepVisibilityClass.VISIBLE

    def _keyframe_fold_reason(
        self,
        trigger_kind: KeyframeTriggerKind,
        metrics: Mapping[str, object],
    ) -> RecordingTimelineStepFoldReason | None:
        if trigger_kind == KeyframeTriggerKind.TARGET_RESOLUTION_PROBE:
            return RecordingTimelineStepFoldReason.TARGET_PROBE
        if trigger_kind == KeyframeTriggerKind.TYPING_SETTLE:
            return RecordingTimelineStepFoldReason.TYPING_TRACE_ONLY
        stop_reason = str(metrics.get("settle_stop_reason") or "").lower()
        if "timeout" in stop_reason:
            return RecordingTimelineStepFoldReason.TIMEOUT_NO_CHANGE
        drop_reason = str(metrics.get("drop_reason") or "").lower()
        if drop_reason == "low_information_gain":
            return RecordingTimelineStepFoldReason.LOW_INFORMATION_GAIN
        return None

    def _action_caption(
        self,
        action: HumanActionEvent,
        *,
        target: ClickTargetResolution | None = None,
        action_summary: RecordingActionSummaryView | None = None,
    ) -> str:
        if action.kind == HumanActionKind.CLICK:
            public_target = self._public_target(target, has_coordinates=action.coordinates is not None)
            if public_target is not None and not public_target.needs_review:
                return f"点击「{public_target.display_label}」"
            if public_target is not None:
                return f"点击（{public_target.display_label}）"
            return "点击（目标待确认）"
        if action.kind == HumanActionKind.DRAG:
            return "拖拽"
        if action.kind == HumanActionKind.HOTKEY:
            if action_summary is not None and action_summary.key_chord is not None:
                return f"按下 {self._key_chord_caption(action_summary.key_chord.normalized_key_label)}"
            if action.hotkey_semantic is not None:
                return self._hotkey_caption(action.hotkey_semantic)
        if action.kind in {HumanActionKind.KEY_DOWN, HumanActionKind.KEY_UP}:
            verb = "按下" if action.kind == HumanActionKind.KEY_DOWN else "松开"
            if action_summary is not None and action_summary.key_chord is not None:
                chord = action_summary.key_chord
                label = chord.characters or self._key_chord_caption(chord.normalized_key_label)
                return f"{verb} {label}"
            return f"{verb}按键"
        if action.kind == HumanActionKind.TYPING_PAUSE:
            if action_summary is not None and action_summary.typing_summary is not None:
                summary = action_summary.typing_summary
                return f"文本输入 · 约 {summary.character_count} 字"
            if action_summary is not None and (
                action_summary.after_keyframe_ids or action_summary.result_keyframe_id is not None
            ):
                return "输入后状态"
            return "输入摘要"
        if action.kind == HumanActionKind.SCROLL:
            return "滚动停止"
        return action.kind.value

    def _hotkey_caption(self, semantic: HotkeySemantic) -> str:
        labels = {
            HotkeySemantic.SUBMIT: "按下 Enter",
            HotkeySemantic.SEARCH: "按下搜索快捷键",
            HotkeySemantic.SAVE: "保存",
            HotkeySemantic.CLOSE: "关闭",
            HotkeySemantic.NEW_ITEM: "新建",
            HotkeySemantic.DELETE: "删除",
            HotkeySemantic.REFRESH: "刷新",
            HotkeySemantic.SELECT_ALL: "全选",
            HotkeySemantic.UNDO: "撤销",
            HotkeySemantic.REDO: "重做",
            HotkeySemantic.CUT: "剪切",
            HotkeySemantic.ESCAPE_CANCEL: "取消",
        }
        label = labels.get(semantic)
        if label is not None:
            return label
        return "快捷键"

    @staticmethod
    def _key_chord_caption(label: str) -> str:
        normalized = label.strip().lower()
        special = {
            "enter": "Enter",
            "return": "Enter",
            "escape": "Esc",
            "esc": "Esc",
            "tab": "Tab",
            "space": "Space",
            "backspace": "Backspace",
            "delete": "Delete",
        }
        return special.get(normalized, label.upper() if len(label) == 1 else label)

    def _control_media_time_ms(
        self,
        *,
        control: RecordingControlEvent,
        timeline: RecordingTimelineManifest | None,
        segments: tuple = (),
    ) -> int | None:
        value = getattr(control.kind, "value", str(control.kind))
        if value == "start_segment":
            return 0
        if timeline is not None and timeline.duration_ms is not None and value in {"end_segment", "stop", "auto_stop"}:
            return timeline.duration_ms
        media_time_from_segments = media_time_from_recording_segments(
            occurred_at_monotonic_ms=control.occurred_at_monotonic_ms,
            segments=segments,
        )
        if media_time_from_segments is not None:
            return media_time_from_segments
        if (
            timeline is not None
            and timeline.clock_origin_monotonic_ms is not None
            and control.occurred_at_monotonic_ms is not None
        ):
            media_time_ms = max(0, control.occurred_at_monotonic_ms - timeline.clock_origin_monotonic_ms)
            if timeline.duration_ms is not None:
                return min(media_time_ms, timeline.duration_ms)
            return media_time_ms
        return None

    def _action_visibility(
        self,
        *,
        action: HumanActionEvent,
        action_summary: RecordingActionSummaryView,
    ) -> tuple[RecordingTimelineStepVisibilityClass, RecordingTimelineStepFoldReason | None]:
        if (
            action.kind == HumanActionKind.TYPING_PAUSE
            and action_summary.typing_summary is not None
            and not action_summary.typing_summary.submitted_by_enter
        ):
            if action_summary.after_keyframe_ids or action_summary.result_keyframe_id is not None:
                return (RecordingTimelineStepVisibilityClass.VISIBLE, None)
            return (
                RecordingTimelineStepVisibilityClass.FOLDED,
                RecordingTimelineStepFoldReason.TYPING_TRACE_ONLY,
            )
        return (RecordingTimelineStepVisibilityClass.VISIBLE, None)

    def _action_safe_text_ref_ids(self, action_summary: RecordingActionSummaryView) -> tuple[str, ...]:
        refs: list[str] = []
        refs.extend(action_summary.after_keyframe_ids)
        refs.extend(action_summary.target_evidence_keyframe_ids)
        if action_summary.result_keyframe_id is not None:
            refs.append(action_summary.result_keyframe_id)
        return tuple(dict.fromkeys(refs))

    def _control_caption(self, kind: object) -> str:
        value = getattr(kind, "value", str(kind))
        labels = {
            "start_segment": "开始片段",
            "end_segment": "结束片段",
            "pause": "暂停",
            "resume": "继续",
            "user_mark": "手动标记",
            "stop": "完成录制",
            "auto_stop": "自动结束录制",
            "scope_lost": "录制区域变化",
        }
        return labels.get(value, "录制控制")

    def _control_visibility_class(self, kind: object) -> RecordingTimelineStepVisibilityClass:
        value = getattr(kind, "value", str(kind))
        if value in {"start_segment", "end_segment", "user_mark", "scope_lost"}:
            return RecordingTimelineStepVisibilityClass.VISIBLE
        return RecordingTimelineStepVisibilityClass.FOLDED

    def _control_fold_reason(self, kind: object) -> RecordingTimelineStepFoldReason | None:
        if self._control_visibility_class(kind) == RecordingTimelineStepVisibilityClass.FOLDED:
            return RecordingTimelineStepFoldReason.CONTROL_ONLY
        return None

    def _action_summary(
        self,
        *,
        action: HumanActionEvent,
        decision: ProducerDecision | None,
        producer_event: ProducerEventEnvelope | None,
        links: tuple[ActionEvidenceLink, ...],
        observation: ActionResultObservation | None,
        target: ClickTargetResolution | None,
    ) -> RecordingActionSummaryView:
        before_keyframes = tuple(
            link.keyframe_id
            for link in links
            if link.role == HumanActionEvidenceRole.BEFORE_KEYFRAME and link.keyframe_id is not None
        )
        after_keyframes = tuple(
            link.keyframe_id
            for link in links
            if link.role == HumanActionEvidenceRole.AFTER_KEYFRAME and link.keyframe_id is not None
        )
        target_evidence_keyframes = tuple(
            link.keyframe_id
            for link in links
            if link.role == HumanActionEvidenceRole.TARGET_EVIDENCE and link.keyframe_id is not None
        )
        keyboard = producer_event.keyboard if producer_event is not None else None
        typing_summary: TypingSessionAggregateView | None = None
        if keyboard is not None and keyboard.typing_summary is not None:
            typing_summary = self._typing_aggregate(keyboard.typing_summary)
        return RecordingActionSummaryView(
            action_id=action.action_id,
            action_kind=action.kind,
            hotkey_semantic=action.hotkey_semantic,
            key_chord=keyboard.key_chord if keyboard is not None else None,
            typing_summary=typing_summary,
            target=self._public_target(target, has_coordinates=action.coordinates is not None),
            producer_decision_status=decision.status if decision is not None else None,
            producer_decision_reason=decision.reason if decision is not None else None,
            before_keyframe_ids=before_keyframes,
            after_keyframe_ids=after_keyframes,
            target_evidence_keyframe_ids=target_evidence_keyframes,
            result_keyframe_id=observation.result_keyframe_id if observation is not None else None,
        )

    def _public_target(
        self,
        target: ClickTargetResolution | None,
        *,
        has_coordinates: bool,
    ) -> ClickTargetPublicView | None:
        if target is None:
            return None
        return self.target_scoring.public_view(target, has_coordinates=has_coordinates)

    def _typing_aggregate(self, summary: TypingSessionSummary) -> TypingSessionAggregateView:
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

    def _action_needs_review(
        self,
        action: HumanActionEvent,
        *,
        decision_needs_review: bool,
        evidence_keyframes: tuple[str, ...],
        has_result: bool,
    ) -> bool:
        if decision_needs_review:
            return True
        if not evidence_keyframes and action.kind in {HumanActionKind.CLICK, HumanActionKind.DRAG, HumanActionKind.SCROLL}:
            return True
        if action.target is not None and action.target.confidence < 0.5:
            return True
        return not has_result and action.kind in {
            HumanActionKind.CLICK,
            HumanActionKind.DRAG,
            HumanActionKind.HOTKEY,
            HumanActionKind.SCROLL,
        }

    def _readiness(self, *, needs_review: bool) -> SkillReadinessSummary:
        return SkillReadinessSummary(
            state=SkillReadinessState.NEEDS_REVIEW if needs_review else SkillReadinessState.READY,
            review_item_count=1 if needs_review else 0,
            reasons=("证据缺失或置信度较低",) if needs_review else (),
        )

    def _sort_key(self, step: RecordingTimelineStepView) -> tuple[int, str]:
        if step.media_time_ms is not None:
            return (step.media_time_ms, step.occurred_at.isoformat())
        return (1_000_000_000_000, step.occurred_at.isoformat())

    def _event_id_for_action(self, graph: RecordingInspectGraph) -> str:
        if graph.session.primary_event_id is not None:
            return graph.session.primary_event_id
        if graph.keyframes:
            return graph.keyframes[0].event_id
        return graph.session.session_id
