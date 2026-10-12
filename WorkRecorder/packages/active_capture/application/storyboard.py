"""Safe recording card and storyboard projections."""

from __future__ import annotations

from datetime import datetime

from packages.active_capture.application.read_model import RecordingSessionGraphReader
from packages.active_capture.click_targets.domain.scoring import ClickTargetScoringPolicy
from packages.active_capture.repositories.protocol import ActiveCaptureRepository
from packages.contracts import (
    ActiveCaptureProjectionConfig,
    ActiveCaptureSession,
    ClickTargetPublicView,
    ClickTargetResolution,
    ClickTargetResolverConfig,
    ContextKeyframe,
    HumanActionEvent,
    HumanActionKind,
    KeyframeRole,
    ProjectionTruncationSummary,
    RecordingAvailableField,
    RecordingCardSummary,
    RecordingControlKind,
    RecordingHiddenMaterial,
    RecordingStoryboardProjection,
    StoryboardActionItem,
    StoryboardControlItem,
    StoryboardKeyframeItem,
    VideoArtifactState,
)
from packages.contracts.active_capture_storyboard import RecordingStoryboardItem
from packages.shared.time import Clock


class RecordingStoryboardService:
    """Build safe projections without exposing raw media or raw action metadata."""

    _available_fields = (
        RecordingAvailableField.ACTIVE_CAPTURE_SUMMARY,
        RecordingAvailableField.RECORDING_TIMELINE,
        RecordingAvailableField.KEYFRAME_REFS,
        RecordingAvailableField.VIDEO_REF,
        RecordingAvailableField.HUMAN_DEMO_SUMMARY,
    )
    _hidden_materials = (
        RecordingHiddenMaterial.RAW_KEYFRAME_IMAGES,
        RecordingHiddenMaterial.RECORDING_VIDEO,
        RecordingHiddenMaterial.RAW_DOM,
        RecordingHiddenMaterial.RAW_A11Y_TREE,
        RecordingHiddenMaterial.OCR_BOXES,
        RecordingHiddenMaterial.ACTION_RAW_METADATA,
    )

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

    def build(self, session: ActiveCaptureSession) -> RecordingStoryboardProjection:
        """Return a product-facing backend projection for future UI and agent views."""

        graph = self.graph_reader.load_for_session(session.session_id)
        if graph is None:
            raise ValueError("active capture session not found")
        keyframes = graph.keyframes
        actions = graph.actions[: self.projection_config.max_actions]
        controls = graph.controls
        keyframe_links = graph.keyframe_links
        action_links = graph.action_links
        timeline = graph.timeline
        video_state = timeline.video.state if timeline is not None else VideoArtifactState.NOT_RECORDED
        card = RecordingCardSummary(
            session_id=session.session_id,
            primary_event_id=session.primary_event_id,
            status=session.status,
            app_name=None,
            title=None,
            started_at=session.started_at,
            ended_at=session.ended_at,
            duration_ms=timeline.duration_ms if timeline is not None else None,
            keyframe_count=len(keyframes),
            action_count=len(actions),
            video_state=video_state,
            available_fields=self._available_fields,
            hidden_materials=self._hidden_materials,
            warnings=tuple(warning.message for warning in session.warnings),
        )
        items: list[RecordingStoryboardItem] = []
        timeline_by_keyframe = {entry.keyframe_id: entry for entry in timeline.entries} if timeline is not None else {}
        evidence_count_by_keyframe: dict[str, int] = {}
        for keyframe_link in keyframe_links:
            evidence_count_by_keyframe[keyframe_link.keyframe_id] = (
                evidence_count_by_keyframe.get(keyframe_link.keyframe_id, 0) + 1
            )
        action_keyframe_accumulator: dict[str, list[str]] = {}
        for link in action_links:
            if link.keyframe_id is not None:
                action_keyframe_accumulator.setdefault(link.action_id, []).append(link.keyframe_id)
        action_keyframes_by_action = {
            action_id: tuple(dict.fromkeys(keyframe_ids))
            for action_id, keyframe_ids in action_keyframe_accumulator.items()
        }
        target_resolutions_by_action = self._target_resolutions_by_action(graph.target_resolutions)
        action_target_by_action = {
            action_id: public_target
            for action_id, public_target in (
                (
                    action.action_id,
                    self._public_target(
                        target_resolutions_by_action.get(action.action_id),
                        has_coordinates=action.coordinates is not None,
                    ),
                )
                for action in actions
            )
            if public_target is not None
        }
        for keyframe in keyframes:
            entry = timeline_by_keyframe.get(keyframe.keyframe_id)
            items.append(
                StoryboardKeyframeItem(
                    item_id=f"sb_kf_{keyframe.keyframe_id}",
                    keyframe_id=keyframe.keyframe_id,
                    role=keyframe.role,
                    trigger_kind=keyframe.trigger_kind,
                    sequence_index=keyframe.sequence_index,
                    captured_at=keyframe.captured_at,
                    media_time_ms=entry.media_time_ms if entry is not None else keyframe.media_time_ms,
                    caption=self._keyframe_caption(keyframe),
                    screenshot_artifact_id=keyframe.screenshot_artifact_id,
                    evidence_count=evidence_count_by_keyframe.get(keyframe.keyframe_id, 0),
                )
            )
        for action in actions:
            public_target = action_target_by_action.get(action.action_id)
            items.append(
                StoryboardActionItem(
                    item_id=f"sb_act_{action.action_id}",
                    action_id=action.action_id,
                    action_kind=action.kind,
                    sequence_index=action.sequence_index,
                    occurred_at=action.occurred_at,
                    media_time_ms=action.media_time_ms,
                    caption=self._action_caption(action, target=public_target),
                    evidence_keyframe_ids=action_keyframes_by_action.get(action.action_id, ()),
                    target=public_target,
                    target_label=public_target.display_label if public_target is not None else None,
                )
            )
        for control in controls:
            items.append(
                StoryboardControlItem(
                    item_id=f"sb_ctl_{control.control_id}",
                    control_id=control.control_id,
                    control_kind=control.kind,
                    occurred_at=control.occurred_at,
                    caption=self._control_caption(control.kind),
                )
            )
        sorted_items = tuple(sorted(items, key=self._sort_key))
        truncation = self._truncation(
            total_keyframes=graph.total_keyframe_count,
            returned_keyframes=len(keyframes),
            total_actions=graph.total_action_count,
            returned_actions=len(actions),
            total_controls=graph.total_control_count,
            returned_controls=len(controls),
            last_item=sorted_items[-1] if sorted_items else None,
        )
        return RecordingStoryboardProjection(
            session_id=session.session_id,
            card=card,
            items=sorted_items,
            projection=truncation,
            generated_at=self.clock.now(),
        )

    def _truncation(
        self,
        *,
        total_keyframes: int,
        returned_keyframes: int,
        total_actions: int,
        returned_actions: int,
        total_controls: int,
        returned_controls: int,
        last_item: RecordingStoryboardItem | None,
    ) -> ProjectionTruncationSummary:
        truncated_counts = {}
        if total_keyframes > returned_keyframes:
            truncated_counts["keyframes"] = total_keyframes - returned_keyframes
        if total_actions > returned_actions:
            truncated_counts["actions"] = total_actions - returned_actions
        if total_controls > returned_controls:
            truncated_counts["controls"] = total_controls - returned_controls
        if not truncated_counts:
            return ProjectionTruncationSummary()
        return ProjectionTruncationSummary(
            truncated=True,
            truncated_counts=truncated_counts,
            next_cursor=self._cursor_for_item(last_item),
        )

    def _keyframe_caption(self, keyframe: ContextKeyframe) -> str:
        if keyframe.role == KeyframeRole.START:
            return "开始录制"
        if keyframe.role == KeyframeRole.FINAL:
            return "结束录制"
        if keyframe.role == KeyframeRole.USER_MARK:
            return "手动标记"
        return "关键帧"

    def _action_caption(self, action: HumanActionEvent, *, target: ClickTargetPublicView | None) -> str:
        if action.kind == HumanActionKind.CLICK:
            if target is None:
                return "点击（目标待确认）"
            if target.needs_review:
                return f"点击（{target.display_label}）"
            return f"点击「{target.display_label}」"
        if action.kind == HumanActionKind.DRAG:
            return "拖拽"
        if action.kind == HumanActionKind.HOTKEY and action.hotkey_semantic is not None:
            return f"快捷键：{action.hotkey_semantic.value}"
        if action.kind == HumanActionKind.SCROLL:
            return "滚动"
        if action.kind == HumanActionKind.TYPING_PAUSE:
            return "输入暂停"
        return action.kind.value

    def _control_caption(self, control_kind: RecordingControlKind) -> str:
        if control_kind == RecordingControlKind.START_SEGMENT:
            return "开始片段"
        if control_kind == RecordingControlKind.END_SEGMENT:
            return "结束片段"
        if control_kind == RecordingControlKind.PAUSE:
            return "暂停"
        if control_kind == RecordingControlKind.RESUME:
            return "继续"
        if control_kind == RecordingControlKind.STOP:
            return "结束录制"
        if control_kind == RecordingControlKind.AUTO_STOP:
            return "自动结束"
        if control_kind == RecordingControlKind.SCOPE_LOST:
            return "录制区域变化"
        if control_kind == RecordingControlKind.USER_MARK:
            return "手动标记"
        return "录制控制"

    def _public_target(
        self,
        target: ClickTargetResolution | None,
        *,
        has_coordinates: bool,
    ) -> ClickTargetPublicView | None:
        if target is None:
            return None
        return self.target_scoring.public_view(target, has_coordinates=has_coordinates)

    def _target_resolutions_by_action(
        self, targets: tuple[ClickTargetResolution, ...]
    ) -> dict[str, ClickTargetResolution]:
        return {target.action_id: target for target in targets}

    def _sort_key(self, item: RecordingStoryboardItem) -> tuple[int, str]:
        media_time = getattr(item, "media_time_ms", None)
        timestamp = self._timestamp(item)
        return (media_time if isinstance(media_time, int) else 1_000_000_000_000, timestamp.isoformat())

    def _cursor_for_item(self, item: RecordingStoryboardItem | None) -> str | None:
        if item is None:
            return None
        media_time = getattr(item, "media_time_ms", None)
        sequence_index = getattr(item, "sequence_index", None)
        media_token = media_time if isinstance(media_time, int) else "none"
        sequence_token = sequence_index if isinstance(sequence_index, int) else "none"
        return f"{media_token}:{sequence_token}:{item.item_id}"

    def _timestamp(self, item: RecordingStoryboardItem) -> datetime:
        if isinstance(item, StoryboardKeyframeItem):
            return item.captured_at
        if isinstance(item, StoryboardActionItem):
            return item.occurred_at
        return item.occurred_at
