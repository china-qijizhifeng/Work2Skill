from __future__ import annotations

from datetime import UTC, datetime

import pytest

from packages.active_capture.application.inspect.timeline import RecordingTimelineProjector
from packages.active_capture.keyframes.domain.policies import (
    ActionBoundaryPolicy,
    ActionKeyframePlanner,
    AdaptiveSettlePolicy,
    QualityKeepDropPolicy,
    ScrollMilestonePolicy,
)
from packages.active_capture.keyframes.polling.domain import SettleStabilityStateMachine
from packages.contracts import (
    ActionCoordinates,
    ActionEvidenceLink,
    ActionPoint,
    ActiveCapturePolicyConfig,
    AdaptiveSettleWindow,
    ApplyRecordingControlCommand,
    BoundingBox,
    ClickTargetConfidenceBand,
    ClickTargetResolutionStatus,
    CoordinateSpace,
    ContextKeyframe,
    HumanActionEvent,
    HumanActionEvidenceRole,
    HumanActionKind,
    KeyframeDiffReport,
    KeyframeDropReason,
    KeyframeKeepReason,
    KeyframePriorityBand,
    KeyframeQualityReport,
    KeyframeRole,
    KeyframeSignalEnvelope,
    KeyframeTimingConfig,
    KeyframeTriggerKind,
    ProducerInputEventKind,
    RecordingActionSummaryView,
    RecordingControlKind,
    RecordingControlEvent,
    RecordingControlSource,
    RecordingSegmentState,
    RecordingTimelineManifest,
    RecordingVideoSegmentRef,
    RecordingScope,
    RecordingScopeKind,
    RecordingTimelineStepFoldReason,
    RecordingTimelineStepVisibilityClass,
    RedactionState,
    SettleAuditRecord,
    SettleDecisionStatus,
    SettlePollingPlan,
    SettleSample,
    SettleSampleStatus,
    SettleSignalKind,
    SettleStopReason,
    SubmitKeyframeTriggerCommand,
    TextDiffMethod,
    TextDiffSummary,
    TimelineAlignmentConfidence,
    TimelineAlignmentStatus,
    TimelineKeyframeEntry,
    TypingSessionAggregateView,
    VisualProbeMode,
)
from packages.contracts.common import JsonScalar


def test_keyframe_timing_config_derives_from_active_capture_policy() -> None:
    policy = ActiveCapturePolicyConfig(
        before_action_freshness_ms=2_250,
        adaptive_settle_min_delay_ms=300,
        adaptive_settle_max_wait_ms=2_800,
        settle_live_polling_enabled=True,
        settle_probe_strategy="text_provider_only",
        settle_sample_budget=7,
        settle_visual_diff_enabled=False,
        settle_text_diff_enabled=True,
        settle_provider_readiness_enabled=True,
        settle_timeout_capture_enabled=False,
        scroll_milestone_screen_fraction=1.25,
        quality_min_information_gain=0.2,
    )

    config = KeyframeTimingConfig.from_active_capture_policy(policy)

    assert config.before_action_freshness_ms == 2_250
    assert config.settle_min_delay_ms == 300
    assert config.settle_max_wait_ms == 2_800
    assert config.settle_live_polling_enabled is True
    assert config.settle_probe_strategy == VisualProbeMode.TEXT_PROVIDER_ONLY
    assert config.settle_sample_budget == 7
    assert config.settle_visual_diff_enabled is False
    assert config.settle_timeout_capture_enabled is False
    assert config.scroll_milestone_screen_fraction == 1.25
    assert config.quality_min_information_gain == 0.2


def test_keyframe_timing_contract_rejects_sensitive_metadata() -> None:
    with pytest.raises(ValueError, match="forbidden sensitive metadata"):
        KeyframeSignalEnvelope(
            session_id="acs_test",
            signal_id="pev_test",
            occurred_at=_now(),
            action_kind=HumanActionKind.CLICK,
            metadata={"rawText": "SHOULD_NOT_LEAK"},
        )
    with pytest.raises(ValueError, match="forbidden sensitive metadata"):
        SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.ERROR_SURFACE_DETECTED,
            metadata={"storageUri": "local-artifact://raw"},
        )
    with pytest.raises(ValueError, match="forbidden sensitive metadata"):
        ApplyRecordingControlCommand(
            kind=RecordingControlKind.PAUSE,
            metadata={"localPath": "/Users/example/private"},
        )
    with pytest.raises(ValueError, match="forbidden sensitive metadata"):
        SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.TARGET_RESOLUTION_PROBE,
            metadata={"a11yLabel": "SHOULD_NOT_LEAK"},
        )
    with pytest.raises(ValueError, match="forbidden sensitive metadata"):
        SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.TARGET_RESOLUTION_PROBE,
            metadata={"ocrLines": "SHOULD_NOT_LEAK"},
        )
    with pytest.raises(ValueError, match="forbidden sensitive metadata"):
        SettleSample(
            sample_id="kfs_sensitive",
            plan_id="stlp_test",
            candidate_id="kfc_test",
            session_id="acs_test",
            sampled_at=_now(),
            status=SettleSampleStatus.OBSERVED,
            signal_kind=SettleSignalKind.TEXT,
            metadata={"selector": "#password"},
        )
    with pytest.raises(ValueError, match="forbidden sensitive metadata"):
        SettleAuditRecord(
            audit_id="stla_sensitive",
            plan_id="stlp_test",
            candidate_id="kfc_test",
            session_id="acs_test",
            status=SettleDecisionStatus.OBSERVING,
            stop_reason=SettleStopReason.NOT_DUE,
            decision=SettleStabilityStateMachine.default(KeyframeTimingConfig()).decide(
                plan=_settle_plan(), samples=(), now_monotonic_ms=1_000
            ),
            created_at=_now(),
            metadata={"localPath": "/tmp/raw-probe.png"},
        )


def test_settle_state_machine_waits_until_min_delay() -> None:
    machine = SettleStabilityStateMachine.default(KeyframeTimingConfig())

    decision = machine.decide(plan=_settle_plan(), samples=(), now_monotonic_ms=1_100)

    assert decision.status == SettleDecisionStatus.OBSERVING
    assert decision.ready_to_capture is False
    assert decision.stop_reason == SettleStopReason.NOT_DUE


def test_settle_state_machine_captures_after_meaningful_change_and_stability() -> None:
    config = KeyframeTimingConfig(settle_required_stable_samples=2, quality_min_information_gain=0.12)
    machine = SettleStabilityStateMachine.default(config)
    samples = (
        _settle_sample("kfs_changed", 1_300, SettleSampleStatus.CHANGED, text_delta=0.45),
        _settle_sample("kfs_stable_1", 1_450, SettleSampleStatus.STABLE, text_delta=0.0),
        _settle_sample("kfs_stable_2", 1_600, SettleSampleStatus.STABLE, text_delta=0.0),
    )

    decision = machine.decide(plan=_settle_plan(required_stable_samples=2), samples=samples, now_monotonic_ms=1_600)

    assert decision.status == SettleDecisionStatus.READY_TO_CAPTURE
    assert decision.ready_to_capture is True
    assert decision.stop_reason == SettleStopReason.STABLE_AFTER_CHANGE
    assert decision.stable_sample_count == 2
    assert decision.diff is not None
    assert decision.diff.changed is True


def test_settle_state_machine_times_out_with_review_marker() -> None:
    machine = SettleStabilityStateMachine.default(KeyframeTimingConfig(settle_timeout_capture_enabled=True))

    decision = machine.decide(
        plan=_settle_plan(deadline_monotonic_ms=1_800),
        samples=(_settle_sample("kfs_observed", 1_650, SettleSampleStatus.OBSERVED),),
        now_monotonic_ms=1_900,
    )

    assert decision.status == SettleDecisionStatus.TIMEOUT_CAPTURE
    assert decision.ready_to_capture is True
    assert decision.stop_reason == SettleStopReason.TIMEOUT
    assert decision.needs_review is True


def test_settle_state_machine_keeps_high_value_timeout_without_signal() -> None:
    machine = SettleStabilityStateMachine.default(KeyframeTimingConfig(settle_timeout_capture_enabled=True))

    decision = machine.decide(
        plan=_settle_plan(
            deadline_monotonic_ms=1_800,
            trigger_kind=KeyframeTriggerKind.COMMAND_SUBMITTED,
        ),
        samples=(),
        now_monotonic_ms=1_900,
    )

    assert decision.status == SettleDecisionStatus.TIMEOUT_CAPTURE
    assert decision.ready_to_capture is True
    assert decision.stop_reason == SettleStopReason.TIMEOUT


def test_settle_state_machine_suppresses_target_probe_timeout() -> None:
    machine = SettleStabilityStateMachine.default(KeyframeTimingConfig(settle_timeout_capture_enabled=True))

    decision = machine.decide(
        plan=_settle_plan(
            deadline_monotonic_ms=1_800,
            trigger_kind=KeyframeTriggerKind.TARGET_RESOLUTION_PROBE,
            timeout_capture_enabled=False,
        ),
        samples=(_settle_sample("kfs_probe_observed", 1_650, SettleSampleStatus.OBSERVED),),
        now_monotonic_ms=1_900,
    )

    assert decision.status == SettleDecisionStatus.SUPPRESSED
    assert decision.ready_to_capture is False
    assert decision.stop_reason == SettleStopReason.TIMEOUT


def test_settle_state_machine_keeps_explicit_typing_milestone_timeout() -> None:
    machine = SettleStabilityStateMachine.default(KeyframeTimingConfig(settle_timeout_capture_enabled=True))

    decision = machine.decide(
        plan=_settle_plan(
            deadline_monotonic_ms=1_800,
            trigger_kind=KeyframeTriggerKind.TYPING_SETTLE,
            timeout_capture_enabled=True,
        ),
        samples=(_settle_sample("kfs_typing_observed", 1_650, SettleSampleStatus.OBSERVED),),
        now_monotonic_ms=1_900,
    )

    assert decision.status == SettleDecisionStatus.TIMEOUT_CAPTURE
    assert decision.ready_to_capture is True
    assert decision.stop_reason == SettleStopReason.TIMEOUT


def test_settle_state_machine_respects_exact_sample_budget_after_readiness_checks() -> None:
    config = KeyframeTimingConfig(settle_sample_budget=2, settle_required_stable_samples=1)
    machine = SettleStabilityStateMachine.default(config)

    ready = machine.decide(
        plan=_settle_plan(sample_budget=2, required_stable_samples=1),
        samples=(
            _settle_sample("kfs_budget_changed", 1_300, SettleSampleStatus.CHANGED, text_delta=0.45),
            _settle_sample("kfs_budget_stable", 1_450, SettleSampleStatus.STABLE, text_delta=0.0),
        ),
        now_monotonic_ms=1_450,
    )
    exhausted = machine.decide(
        plan=_settle_plan(sample_budget=2, required_stable_samples=1),
        samples=(
            _settle_sample("kfs_budget_observed_1", 1_300, SettleSampleStatus.OBSERVED),
            _settle_sample("kfs_budget_observed_2", 1_450, SettleSampleStatus.OBSERVED),
        ),
        now_monotonic_ms=1_450,
    )

    assert ready.status == SettleDecisionStatus.READY_TO_CAPTURE
    assert ready.stop_reason == SettleStopReason.STABLE_AFTER_CHANGE
    assert exhausted.status == SettleDecisionStatus.TIMEOUT_CAPTURE
    assert exhausted.stop_reason == SettleStopReason.BUDGET_EXCEEDED


def test_action_boundary_policy_reuses_fresh_prior_frame() -> None:
    config = KeyframeTimingConfig(before_action_freshness_ms=1_500)
    signal = _signal(
        action_kind=HumanActionKind.CLICK,
        occurred_at_monotonic_ms=2_000,
        last_keyframe_id="kf_before",
        last_keyframe_monotonic_ms=1_100,
    )

    assert ActionBoundaryPolicy(config).plan(signal) == ()

    post_action_signal = _signal(
        action_kind=HumanActionKind.CLICK,
        occurred_at_monotonic_ms=4_000,
        last_keyframe_id="kf_old",
        last_keyframe_monotonic_ms=1_000,
    )
    dropped = ActionBoundaryPolicy(config).plan(post_action_signal)

    assert len(dropped) == 1
    assert dropped[0].drop_reason == KeyframeDropReason.PRE_ACTION_UNAVAILABLE

    capture_signal = _signal(
        action_kind=HumanActionKind.CLICK,
        occurred_at_monotonic_ms=4_000,
        last_keyframe_id="kf_old",
        last_keyframe_monotonic_ms=1_000,
        metadata={"native_event_phase": "pre_action"},
    )
    planned = ActionBoundaryPolicy(config).plan(capture_signal)

    assert len(planned) == 1
    assert planned[0].trigger_kind == KeyframeTriggerKind.ACTION_BEFORE
    assert planned[0].role == KeyframeRole.BEFORE_ACTION
    assert planned[0].keep_reason == KeyframeKeepReason.BEFORE_ACTION_CONTEXT


def test_adaptive_settle_policy_expands_command_boundaries() -> None:
    config = KeyframeTimingConfig(settle_min_delay_ms=250, settle_max_wait_ms=1_000)
    signal = _signal(
        action_kind=HumanActionKind.HOTKEY,
        producer_event_kind=ProducerInputEventKind.HOTKEY,
        occurred_at_monotonic_ms=5_000,
    )

    planned = AdaptiveSettlePolicy(config).plan(signal, base_trigger=KeyframeTriggerKind.COMMAND_SUBMITTED)

    assert len(planned) == 1
    assert planned[0].trigger_kind == KeyframeTriggerKind.COMMAND_SUBMITTED
    assert planned[0].keep_reason == KeyframeKeepReason.COMMAND_BOUNDARY
    assert planned[0].settle_window is not None
    assert planned[0].settle_window.min_delay_ms >= 350
    assert planned[0].settle_window.max_wait_ms >= 2_000
    assert planned[0].debounce_until_monotonic_ms == 5_350


def test_adaptive_settle_policy_allows_plain_typing_milestone_result() -> None:
    config = KeyframeTimingConfig(settle_min_delay_ms=250, settle_max_wait_ms=1_000)
    signal = _signal(
        action_kind=HumanActionKind.TYPING_PAUSE,
        producer_event_kind=ProducerInputEventKind.TYPING_PAUSE,
        occurred_at_monotonic_ms=6_000,
    )

    planned = AdaptiveSettlePolicy(config).plan(signal, base_trigger=KeyframeTriggerKind.TYPING_SETTLE)

    assert len(planned) == 1
    assert planned[0].trigger_kind == KeyframeTriggerKind.TYPING_SETTLE
    assert planned[0].action_evidence_role == HumanActionEvidenceRole.AFTER_KEYFRAME
    assert planned[0].settle_window is not None
    assert planned[0].debounce_until_monotonic_ms == 6_350


def test_scroll_milestone_policy_keeps_representative_long_scroll() -> None:
    config = KeyframeTimingConfig(scroll_milestone_screen_fraction=0.75)
    signal = _signal(
        action_kind=HumanActionKind.SCROLL,
        occurred_at_monotonic_ms=7_000,
        scroll_delta_y=700,
        scope=RecordingScope(
            kind=RecordingScopeKind.REGION,
            display_id="display_main",
            selection_region=BoundingBox(x=0, y=0, width=800, height=800),
        ),
    )

    planned = ScrollMilestonePolicy(config).plan(signal)

    assert len(planned) == 1
    assert planned[0].trigger_kind == KeyframeTriggerKind.SCROLL_MILESTONE
    assert planned[0].keep_reason == KeyframeKeepReason.SCROLL_MILESTONE


def test_planner_adds_target_probe_for_low_confidence_click() -> None:
    planner = ActionKeyframePlanner.default(KeyframeTimingConfig())
    signal = _signal(
        action_kind=HumanActionKind.CLICK,
        click_target_status=ClickTargetResolutionStatus.LOW_CONFIDENCE,
        click_target_confidence_band=ClickTargetConfidenceBand.LOW,
    )

    plan = planner.plan(signal=signal, base_trigger=KeyframeTriggerKind.CLICK_SETTLE)

    kinds = {trigger.trigger_kind for trigger in plan.triggers}
    assert KeyframeTriggerKind.TARGET_RESOLUTION_PROBE in kinds
    assert KeyframeTriggerKind.CLICK_SETTLE in kinds
    probe = next(
        trigger for trigger in plan.triggers if trigger.trigger_kind == KeyframeTriggerKind.TARGET_RESOLUTION_PROBE
    )
    assert probe.settle_window is not None
    assert probe.metadata["settle_live_polling_state"] == "pending"
    assert probe.metadata["settle_timeout_capture_enabled"] is False
    assert probe.debounce_until_monotonic_ms == probe.settle_window.execute_after_monotonic_ms


def test_planner_marks_sensitive_error_surface_for_review_without_capture() -> None:
    planner = ActionKeyframePlanner.default(KeyframeTimingConfig())
    signal = _signal(
        action_kind=HumanActionKind.CLICK,
        redaction_state=RedactionState.BLOCKED,
        metadata={"surface_signal_kind": "error_banner"},
    )

    plan = planner.plan(signal=signal, base_trigger=KeyframeTriggerKind.CLICK_SETTLE)

    assert plan.triggers == ()
    assert plan.needs_review is True
    assert any("dropped:error_surface_detected:sensitive_surface" in item for item in plan.diagnostics)


def test_quality_policy_drops_low_information_gain_and_keeps_required() -> None:
    policy = QualityKeepDropPolicy(KeyframeTimingConfig(quality_min_information_gain=0.2))

    dropped = policy.decide(
        trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
        priority=KeyframePriorityBand.NORMAL,
        diff=KeyframeDiffReport(visual_delta=0.01, text_delta=0.01),
        quality=KeyframeQualityReport(confidence=0.1),
    )
    kept = policy.decide(
        trigger_kind=KeyframeTriggerKind.RECORDING_STOP,
        priority=KeyframePriorityBand.REQUIRED,
        diff=None,
        quality=None,
    )

    assert dropped.kept is False
    assert dropped.drop_reason == KeyframeDropReason.LOW_INFORMATION_GAIN
    assert kept.kept is True
    assert kept.keep_reason == KeyframeKeepReason.REQUIRED_BOUNDARY


def test_adaptive_settle_window_rejects_invalid_deadline() -> None:
    with pytest.raises(ValueError, match="deadline"):
        AdaptiveSettleWindow(
            min_delay_ms=500,
            max_wait_ms=1_000,
            poll_interval_ms=100,
            required_stable_samples=2,
            execute_after_monotonic_ms=1_000,
            deadline_monotonic_ms=900,
        )


def test_inspect_action_summary_projects_target_evidence_keyframes() -> None:
    projector = RecordingTimelineProjector()
    action = HumanActionEvent(
        action_id="act_click",
        trace_id="trace_test",
        session_id="acs_test",
        sequence_index=1,
        kind=HumanActionKind.CLICK,
        occurred_at=_now(),
        coordinates=ActionCoordinates(
            screen_abs=ActionPoint(x=120, y=80, coordinate_space=CoordinateSpace.MACOS_GLOBAL)
        ),
    )
    links = (
        ActionEvidenceLink(
            link_id="ael_target",
            action_id=action.action_id,
            role=HumanActionEvidenceRole.TARGET_EVIDENCE,
            keyframe_id="kf_probe",
            created_at=_now(),
        ),
    )

    summary = projector._action_summary(  # noqa: SLF001 - targeted projection contract regression.
        action=action,
        decision=None,
        producer_event=None,
        links=links,
        observation=None,
        target=None,
    )

    assert summary.target_evidence_keyframe_ids == ("kf_probe",)


def test_inspect_projector_folds_plain_typing_and_keeps_safe_text_refs() -> None:
    projector = RecordingTimelineProjector()
    action = HumanActionEvent(
        action_id="act_typing",
        trace_id="trace_test",
        session_id="acs_test",
        sequence_index=1,
        kind=HumanActionKind.TYPING_PAUSE,
        occurred_at=_now(),
    )
    summary = RecordingActionSummaryView(
        action_id=action.action_id,
        action_kind=action.kind,
        typing_summary=TypingSessionAggregateView(
            event_count=8,
            text_event_count=6,
            character_count=6,
            submitted_by_enter=False,
        ),
    )

    visibility, fold_reason = projector._action_visibility(  # noqa: SLF001 - typed projection contract regression.
        action=action,
        action_summary=summary,
    )
    refs = projector._action_safe_text_ref_ids(summary)  # noqa: SLF001 - typed projection contract regression.

    assert visibility == RecordingTimelineStepVisibilityClass.FOLDED
    assert fold_reason == RecordingTimelineStepFoldReason.TYPING_TRACE_ONLY
    assert refs == ()


def test_inspect_projector_keeps_typing_milestone_with_result_keyframe_visible() -> None:
    projector = RecordingTimelineProjector()
    action = HumanActionEvent(
        action_id="act_typing",
        trace_id="trace_test",
        session_id="acs_test",
        sequence_index=1,
        kind=HumanActionKind.TYPING_PAUSE,
        occurred_at=_now(),
    )
    summary = RecordingActionSummaryView(
        action_id=action.action_id,
        action_kind=action.kind,
        typing_summary=TypingSessionAggregateView(
            event_count=14,
            text_event_count=13,
            character_count=13,
            submitted_by_enter=False,
        ),
        after_keyframe_ids=("kf_after",),
    )

    visibility, fold_reason = projector._action_visibility(  # noqa: SLF001 - typed projection contract regression.
        action=action,
        action_summary=summary,
    )
    caption = projector._action_caption(  # noqa: SLF001 - typed projection contract regression.
        action,
        action_summary=summary,
    )

    assert visibility == RecordingTimelineStepVisibilityClass.VISIBLE
    assert fold_reason is None
    assert caption == "文本输入 · 约 13 字"


def test_inspect_projector_derives_action_media_time_from_linked_keyframe() -> None:
    projector = RecordingTimelineProjector()
    action = HumanActionEvent(
        action_id="act_submit",
        trace_id="trace_test",
        session_id="acs_test",
        sequence_index=1,
        kind=HumanActionKind.HOTKEY,
        hotkey_semantic="submit",
        occurred_at=_now(),
    )
    summary = RecordingActionSummaryView(
        action_id=action.action_id,
        action_kind=action.kind,
        after_keyframe_ids=("kf_after",),
    )
    entry = TimelineKeyframeEntry(
        keyframe_id="kf_after",
        role=KeyframeRole.RESULT,
        trigger_kind=KeyframeTriggerKind.COMMAND_SUBMITTED,
        sequence_index=2,
        captured_at_wall_time=_now(),
        media_time_ms=5_416,
        alignment_confidence=TimelineAlignmentConfidence.EXACT,
        alignment_status=TimelineAlignmentStatus.ALIGNED,
    )

    media_time = projector._action_media_time_ms(  # noqa: SLF001 - projection regression helper.
        action=action,
        action_summary=summary,
        timeline_entries={entry.keyframe_id: entry},
        timeline=None,
    )

    assert media_time == 5_416


def test_inspect_projector_derives_action_media_time_from_monotonic_clock_without_keyframe() -> None:
    projector = RecordingTimelineProjector()
    action = HumanActionEvent(
        action_id="act_debounced_click",
        trace_id="trace_test",
        session_id="acs_test",
        sequence_index=1,
        kind=HumanActionKind.CLICK,
        occurred_at=_now(),
        occurred_at_monotonic_ms=1_425,
        coordinates=ActionCoordinates(
            screen_abs=ActionPoint(x=120, y=80, coordinate_space=CoordinateSpace.MACOS_GLOBAL)
        ),
    )
    summary = RecordingActionSummaryView(
        action_id=action.action_id,
        action_kind=action.kind,
    )
    timeline = RecordingTimelineManifest(
        manifest_id="tlm_test",
        session_id="acs_test",
        clock_origin_wall_time=_now(),
        clock_origin_monotonic_ms=1_000,
        duration_ms=4_000,
        created_at=_now(),
        updated_at=_now(),
    )

    media_time = projector._action_media_time_ms(  # noqa: SLF001 - projection regression helper.
        action=action,
        action_summary=summary,
        timeline_entries={},
        timeline=timeline,
    )

    assert media_time == 425


def test_inspect_projector_prefers_segment_media_start_over_stale_action_time() -> None:
    projector = RecordingTimelineProjector()
    action = HumanActionEvent(
        action_id="act_click",
        trace_id="trace_test",
        session_id="acs_test",
        sequence_index=1,
        kind=HumanActionKind.CLICK,
        occurred_at=_now(),
        occurred_at_monotonic_ms=2_600,
        media_time_ms=2_000,
        coordinates=ActionCoordinates(
            screen_abs=ActionPoint(x=120, y=80, coordinate_space=CoordinateSpace.MACOS_GLOBAL)
        ),
    )
    segment = RecordingVideoSegmentRef(
        segment_id="rseg_1",
        session_id="acs_test",
        sequence_index=0,
        state=RecordingSegmentState.AVAILABLE,
        started_at=_now(),
        started_at_monotonic_ms=1_000,
        media_start_monotonic_ms=1_500,
        ended_at_monotonic_ms=4_000,
        duration_ms=2_500,
    )
    summary = RecordingActionSummaryView(action_id=action.action_id, action_kind=action.kind)

    media_time = projector._action_media_time_ms(  # noqa: SLF001 - projection regression helper.
        action=action,
        action_summary=summary,
        timeline_entries={},
        timeline=None,
        segments=(segment,),
    )

    assert media_time == 1_100


def test_inspect_projector_clamps_outside_duration_final_keyframe_to_video_end() -> None:
    projector = RecordingTimelineProjector()
    final_keyframe = ContextKeyframe(
        keyframe_id="kf_final",
        session_id="acs_test",
        event_id="evt_final",
        capture_run_id="cap_final",
        role=KeyframeRole.FINAL,
        trigger_kind=KeyframeTriggerKind.RECORDING_STOP,
        keep_reason=KeyframeKeepReason.REQUIRED_BOUNDARY,
        captured_at=_now(),
        sequence_index=4,
    )
    entry = TimelineKeyframeEntry(
        keyframe_id=final_keyframe.keyframe_id,
        role=KeyframeRole.FINAL,
        trigger_kind=KeyframeTriggerKind.RECORDING_STOP,
        sequence_index=4,
        captured_at_wall_time=_now(),
        media_time_ms=None,
        alignment_confidence=TimelineAlignmentConfidence.UNAVAILABLE,
        alignment_status=TimelineAlignmentStatus.OUTSIDE_VIDEO_DURATION,
    )

    media_time = projector._keyframe_media_time_ms(  # noqa: SLF001 - projection regression helper.
        keyframe=final_keyframe,
        entry=entry,
        timeline_duration_ms=14_900,
    )

    assert media_time == 14_900


def test_inspect_projector_places_recording_controls_on_video_timeline() -> None:
    projector = RecordingTimelineProjector()
    timeline = RecordingTimelineManifest(
        manifest_id="tlm_test",
        session_id="acs_test",
        clock_origin_wall_time=_now(),
        clock_origin_monotonic_ms=1_000,
        duration_ms=4_000,
        created_at=_now(),
        updated_at=_now(),
    )

    assert (
        projector._control_media_time_ms(  # noqa: SLF001 - projection regression helper.
            control=RecordingControlEvent(
                control_id="ctl_start",
                session_id="acs_test",
                kind=RecordingControlKind.START_SEGMENT,
                source=RecordingControlSource.POLICY,
                occurred_at=_now(),
            ),
            timeline=timeline,
        )
        == 0
    )
    assert (
        projector._control_media_time_ms(  # noqa: SLF001 - projection regression helper.
            control=RecordingControlEvent(
                control_id="ctl_stop",
                session_id="acs_test",
                kind=RecordingControlKind.STOP,
                source=RecordingControlSource.NATIVE_CLIENT,
                occurred_at=_now(),
                occurred_at_monotonic_ms=6_500,
            ),
            timeline=timeline,
        )
        == 4_000
    )


def _signal(
    *,
    action_kind: HumanActionKind,
    producer_event_kind: ProducerInputEventKind = ProducerInputEventKind.POINTER_CLICK,
    occurred_at_monotonic_ms: int = 1_000,
    last_keyframe_id: str | None = None,
    last_keyframe_monotonic_ms: int | None = None,
    scroll_delta_y: float | None = None,
    scope: RecordingScope | None = None,
    redaction_state: RedactionState = RedactionState.NONE,
    click_target_status: ClickTargetResolutionStatus | None = None,
    click_target_confidence_band: ClickTargetConfidenceBand | None = None,
    metadata: dict[str, JsonScalar] | None = None,
) -> KeyframeSignalEnvelope:
    return KeyframeSignalEnvelope(
        session_id="acs_test",
        signal_id="pev_test",
        action_id="act_test",
        action_kind=action_kind,
        producer_event_kind=producer_event_kind,
        occurred_at=_now(),
        occurred_at_monotonic_ms=occurred_at_monotonic_ms,
        last_keyframe_id=last_keyframe_id,
        last_keyframe_monotonic_ms=last_keyframe_monotonic_ms,
        scroll_delta_y=scroll_delta_y,
        scope=scope,
        redaction_state=redaction_state,
        click_target_status=click_target_status,
        click_target_confidence_band=click_target_confidence_band,
        metadata=metadata or {},
    )


def _settle_plan(
    *,
    required_stable_samples: int = 2,
    deadline_monotonic_ms: int = 2_500,
    sample_budget: int = 12,
    trigger_kind: KeyframeTriggerKind = KeyframeTriggerKind.CLICK_SETTLE,
    timeout_capture_enabled: bool | None = None,
) -> SettlePollingPlan:
    return SettlePollingPlan(
        plan_id="stlp_test",
        candidate_id="kfc_test",
        session_id="acs_test",
        trigger_kind=trigger_kind,
        role=KeyframeRole.RESULT,
        settle_window=AdaptiveSettleWindow(
            min_delay_ms=250,
            max_wait_ms=1_500,
            poll_interval_ms=150,
            required_stable_samples=required_stable_samples,
            execute_after_monotonic_ms=1_250,
            deadline_monotonic_ms=deadline_monotonic_ms,
        ),
        probe_strategy=VisualProbeMode.HYBRID,
        sample_budget=sample_budget,
        timeout_capture_enabled=timeout_capture_enabled,
        created_at=_now(),
    )


def _settle_sample(
    sample_id: str,
    sampled_at_monotonic_ms: int,
    status: SettleSampleStatus,
    *,
    text_delta: float | None = None,
) -> SettleSample:
    return SettleSample(
        sample_id=sample_id,
        plan_id="stlp_test",
        candidate_id="kfc_test",
        session_id="acs_test",
        sampled_at=_now(),
        sampled_at_monotonic_ms=sampled_at_monotonic_ms,
        status=status,
        signal_kind=SettleSignalKind.TEXT,
        text=TextDiffSummary(
            method=TextDiffMethod.FINGERPRINT,
            status=status,
            text_delta=text_delta,
            text_length=128,
            source_count=1,
            text_fingerprint=f"phash-{sample_id}",
        ),
    )


def _now() -> datetime:
    return datetime(2026, 6, 6, 12, 0, tzinfo=UTC)
