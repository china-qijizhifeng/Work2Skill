from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from packages.active_capture.application.input_events.skill_projection import SkillDistillationInputProjector
from packages.active_capture.application.input_events.ingest import ProducerEventIngestService
from packages.active_capture.application.inspect import (
    EventEvidenceInspectPort,
    EventLookupPort,
    RecordingInspectService,
)
from packages.active_capture.application.keyframe_recorder import KeyframeRecorder
from packages.active_capture.application.keyframe_triggers import KeyframeTriggerScheduler
from packages.active_capture.application.demonstration_trace import HumanDemonstrationService
from packages.active_capture.application.recording_projection import RecordingPublicProjector
from packages.active_capture.domain.input_events.decision_policy import ProducerEventDecisionPolicy
from packages.active_capture.domain.keyframe_policy import KeyframeCandidate, KeyframeCapturePolicy
from packages.active_capture.domain.scope_matcher import RecordingScopeMatcher
from packages.active_capture.domain.session_completion_policy import TerminalSessionQualityPolicy
from packages.active_capture.domain.session_state import ActiveCaptureSessionStateMachine, ActiveCaptureStateError
from packages.active_capture.domain.timeline_alignment import RecordingTimelineManifestBuilder
from packages.active_capture.keyframes.application.orchestrator import KeyframeTimingOrchestrator
from packages.artifacts.vault import ArtifactVaultError, LocalArtifactVault
from packages.contracts import (
    ActionCoordinates,
    ActionEvidenceLink,
    ActionPoint,
    ActionResultObservation,
    ActionTargetRef,
    ActiveCaptureBinding,
    ActiveCaptureMode,
    ActiveCapturePolicyConfig,
    ActiveCaptureSession,
    ActiveCaptureStatus,
    ActorRef,
    ArtifactRole,
    ArtifactType,
    BoundingBox,
    CaptureAttemptRequest,
    CaptureStrategy,
    ContextEvent,
    ContextKeyframe,
    CoordinateSpace,
    DisclosureClass,
    DisclosureDecision,
    DisclosureDecisionStatus,
    DisclosureView,
    DisplayGeometry,
    EventCaptureEnvelope,
    EventInspectSection,
    EventInspectView,
    EventStatus,
    EventType,
    HotkeySemantic,
    HumanActionEvent,
    HumanActionEvidenceRole,
    HumanActionKind,
    HumanActionOutcomeStatus,
    HumanDemonstrationTrace,
    HumanDemonstrationTraceStatus,
    IndexManifest,
    KeyboardEventKind,
    KeyboardInputClass,
    KeyboardInputPayload,
    KeyCapturePolicy,
    KeyChord,
    KeyframeBundleStatus,
    KeyframeCaptureDecision,
    KeyframeContextBundle,
    KeyframeDiffReport,
    KeyframeDropReason,
    KeyframeEvidenceLink,
    KeyframeEvidenceRole,
    KeyframeKeepReason,
    KeyframePriorityBand,
    KeyframeQualityReport,
    KeyframeRole,
    KeyframeTimingConfig,
    KeyframeTriggerCandidate,
    KeyframeTriggerCandidateStatus,
    KeyframeTriggerKind,
    ModifierKey,
    PointerButton,
    PointerInputPayload,
    PolicySnapshot,
    ProducerDecision,
    ProducerDecisionReason,
    ProducerDecisionStatus,
    ProducerEventEnvelope,
    ProducerInputEventKind,
    ProviderRoutePlan,
    ReadableEvidenceView,
    RecordHumanActionCommand,
    RecordingControlEvent,
    RecordingControlKind,
    RecordingControlSource,
    RecordingPauseInterval,
    RecordingScope,
    RecordingScopeKind,
    RecordingSegmentState,
    RecordingTimelineManifest,
    RecordingVideoContentType,
    RecordingVideoSegmentRef,
    RecordProducerInputEventCommand,
    SearchResultSource,
    SelectionGeometry,
    SourceBinding,
    SourceRef,
    SourceType,
    StagedArtifactRef,
    SubmitKeyframeTriggerCommand,
    TimelineAlignmentConfidence,
    TimelineAlignmentStatus,
    TimelineKeyframeEntry,
    TriggerEnvelope,
    TriggerType,
    TypingSessionSummary,
    VideoArtifactRef,
    VideoArtifactState,
    WindowHint,
    WorkspaceSelection,
)
from packages.indexing.safety import SafeIndexProjectionService
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from packages.storage.container import RepositoryContainer
from packages.storage.database import SQLiteDatabase


class _FixedClock(Clock):
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now


def _producer_ingest_service(
    *,
    repository,
    clock: Clock,
    ids: IdFactory,
    config: ActiveCapturePolicyConfig | None = None,
) -> ProducerEventIngestService:
    policy = config or ActiveCapturePolicyConfig()
    return ProducerEventIngestService(
        repository=repository,
        demonstrations=HumanDemonstrationService(repository=repository, ids=ids, clock=clock, config=policy),
        triggers=KeyframeTriggerScheduler(repository=repository, ids=ids, clock=clock, config=policy),
        projector=RecordingPublicProjector(),
        ids=ids,
        clock=clock,
        config=policy,
        timing_orchestrator=KeyframeTimingOrchestrator(
            repository=repository,
            ids=ids,
            clock=clock,
            config=KeyframeTimingConfig.from_active_capture_policy(policy),
        ),
    )


def test_active_capture_session_state_machine_rejects_invalid_terminal_transition() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    session = ActiveCaptureSession(
        session_id="acs_test",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.COMPLETED,
        created_at=now,
        updated_at=now,
    )

    with pytest.raises(ActiveCaptureStateError):
        ActiveCaptureSessionStateMachine().transition(session, ActiveCaptureStatus.RECORDING)


def test_active_capture_repository_round_trips_session_keyframe_and_timeline() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    with repositories.database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO context_events(event_id, status, payload, created_at, updated_at)
            VALUES ('evt_test', 'agent_ready', '{}', ?, ?)
            """,
            (now.isoformat(), now.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO capture_attempts(
              trigger_id, actor_id, workspace_id, status, occurred_at, selection_payload, payload, created_at
            )
            VALUES ('trg_test', 'actor_test', 'auto', 'accepted', ?, '{}', '{}', ?)
            """,
            (now.isoformat(), now.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO capture_runs(
              capture_run_id, trigger_id, event_id, status, envelope_payload, created_at, updated_at
            )
            VALUES ('run_test', 'trg_test', 'evt_test', 'agent_ready', '{}', ?, ?)
            """,
            (now.isoformat(), now.isoformat()),
        )
    session = ActiveCaptureSession(
        session_id="acs_test",
        mode=ActiveCaptureMode.SCREENSHOT_KEYFRAMES,
        status=ActiveCaptureStatus.COMPLETED,
        primary_event_id="evt_test",
        created_at=now,
        updated_at=now,
    )
    keyframe = ContextKeyframe(
        keyframe_id="kf_test",
        session_id=session.session_id,
        event_id="evt_test",
        capture_run_id="run_test",
        role=KeyframeRole.ANCHOR,
        trigger_kind=KeyframeTriggerKind.MANUAL_SCREENSHOT,
        keep_reason=KeyframeKeepReason.USER_ANCHOR,
        captured_at=now,
        sequence_index=0,
    )

    repositories.active_capture.save_session(session)
    repositories.active_capture.save_keyframe(keyframe)
    manifest = RecordingTimelineManifest(
        manifest_id="tlm_test",
        session_id=session.session_id,
        primary_event_id="evt_test",
        clock_origin_wall_time=now,
        created_at=now,
        updated_at=now,
    )
    repositories.active_capture.save_timeline_manifest(manifest)

    assert repositories.active_capture.get_session("acs_test") == session
    assert repositories.active_capture.list_keyframes_for_session("acs_test") == (keyframe,)
    assert repositories.active_capture.get_timeline_manifest("acs_test") == manifest


def test_timeline_builder_prefers_monotonic_time_over_client_media_hint() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    later = datetime(2026, 5, 30, 12, 1, tzinfo=UTC)
    keyframes = (
        _keyframe("kf_final", sequence_index=2, captured_at=later, captured_at_monotonic_ms=2_000),
        _keyframe("kf_start", sequence_index=0, captured_at=now, captured_at_monotonic_ms=1_000, media_time_ms=12),
    )

    manifest = RecordingTimelineManifestBuilder(ids=IdFactory(), clock=Clock()).build(
        session_id="acs_test",
        primary_event_id="evt_test",
        keyframes=keyframes,
        started_at_monotonic_ms=1_000,
        ended_at_monotonic_ms=2_250,
    )

    assert [entry.keyframe_id for entry in manifest.entries] == ["kf_start", "kf_final"]
    assert manifest.entries[0].media_time_ms == 0
    assert manifest.entries[0].alignment_confidence == TimelineAlignmentConfidence.ESTIMATED
    assert manifest.entries[0].alignment_status == TimelineAlignmentStatus.ALIGNED
    assert manifest.entries[1].media_time_ms == 1_000
    assert manifest.entries[1].alignment_confidence == TimelineAlignmentConfidence.ESTIMATED
    assert manifest.entries[1].alignment_status == TimelineAlignmentStatus.ALIGNED
    assert manifest.duration_ms == 1_250


def test_timeline_builder_uses_recording_start_as_clock_origin_before_first_keyframe() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    keyframes = (
        _keyframe("kf_first", sequence_index=0, captured_at=now, captured_at_monotonic_ms=1_500),
        _keyframe("kf_final", sequence_index=1, captured_at=now, captured_at_monotonic_ms=2_000),
    )

    manifest = RecordingTimelineManifestBuilder(ids=IdFactory(), clock=Clock()).build(
        session_id="acs_test",
        primary_event_id="evt_test",
        keyframes=keyframes,
        started_at_monotonic_ms=1_000,
        ended_at_monotonic_ms=2_250,
    )

    assert manifest.clock_origin_monotonic_ms == 1_000
    assert [entry.media_time_ms for entry in manifest.entries] == [500, 1_000]
    assert manifest.duration_ms == 1_250


def test_timeline_builder_uses_media_start_as_clock_origin_when_available() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    segment = RecordingVideoSegmentRef(
        segment_id="rseg_1",
        session_id="acs_test",
        sequence_index=0,
        state=RecordingSegmentState.AVAILABLE,
        started_at=now,
        started_at_monotonic_ms=1_000,
        media_start_monotonic_ms=1_575,
        ended_at_monotonic_ms=4_000,
        duration_ms=2_425,
        video=VideoArtifactRef(state=VideoArtifactState.AVAILABLE, artifact_id="art_video", duration_ms=2_425),
    )

    manifest = RecordingTimelineManifestBuilder(ids=IdFactory(), clock=Clock()).build(
        session_id="acs_test",
        primary_event_id="evt_test",
        keyframes=(_keyframe("kf_first", sequence_index=0, captured_at=now, captured_at_monotonic_ms=2_000),),
        started_at_monotonic_ms=1_000,
        ended_at_monotonic_ms=4_000,
        video=VideoArtifactRef(state=VideoArtifactState.AVAILABLE, artifact_id="art_video", duration_ms=2_425),
        segments=(segment,),
    )

    assert manifest.clock_origin_monotonic_ms == 1_575
    assert manifest.entries[0].media_time_ms == 425


def test_timeline_builder_rejects_native_clock_outside_video_duration() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    keyframes = (
        _keyframe("kf_start", sequence_index=0, captured_at=now, captured_at_monotonic_ms=1_000),
        _keyframe("kf_final", sequence_index=1, captured_at=now, captured_at_monotonic_ms=5_000),
    )

    manifest = RecordingTimelineManifestBuilder(ids=IdFactory(), clock=Clock()).build(
        session_id="acs_test",
        primary_event_id="evt_test",
        keyframes=keyframes,
        started_at_monotonic_ms=1_000,
        video=VideoArtifactRef(state=VideoArtifactState.AVAILABLE, artifact_id="art_video", duration_ms=1_200),
        timeline_alignment_tolerance_ms=100,
    )

    assert manifest.entries[0].media_time_ms == 0
    assert manifest.entries[0].alignment_status == TimelineAlignmentStatus.ALIGNED
    assert manifest.entries[1].media_time_ms is None
    assert manifest.entries[1].alignment_confidence == TimelineAlignmentConfidence.UNAVAILABLE
    assert manifest.entries[1].alignment_status == TimelineAlignmentStatus.OUTSIDE_VIDEO_DURATION
    assert manifest.entries[1].metadata["video_duration_ms"] == 1_200


def test_timeline_builder_marks_missing_monotonic_alignment_unavailable() -> None:
    manifest = RecordingTimelineManifestBuilder(ids=IdFactory(), clock=Clock()).build(
        session_id="acs_test",
        primary_event_id="evt_test",
        keyframes=(_keyframe("kf_no_clock", sequence_index=0),),
    )

    assert manifest.entries[0].media_time_ms is None
    assert manifest.entries[0].alignment_confidence == TimelineAlignmentConfidence.UNAVAILABLE
    assert manifest.entries[0].alignment_status == TimelineAlignmentStatus.MISSING_CLOCK


def test_timeline_builder_stitches_pause_resume_segments() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    segments = (
        RecordingVideoSegmentRef(
            segment_id="rseg_1",
            session_id="acs_test",
            sequence_index=0,
            state=RecordingSegmentState.AVAILABLE,
            started_at=now,
            ended_at=now,
            started_at_monotonic_ms=1_000,
            ended_at_monotonic_ms=2_000,
            duration_ms=1_000,
        ),
        RecordingVideoSegmentRef(
            segment_id="rseg_2",
            session_id="acs_test",
            sequence_index=1,
            state=RecordingSegmentState.AVAILABLE,
            started_at=now,
            ended_at=now,
            started_at_monotonic_ms=5_000,
            ended_at_monotonic_ms=6_500,
            duration_ms=1_500,
        ),
    )

    manifest = RecordingTimelineManifestBuilder(ids=IdFactory(), clock=Clock()).build(
        session_id="acs_test",
        primary_event_id="evt_test",
        keyframes=(
            _keyframe("kf_seg_1", sequence_index=0, captured_at=now, captured_at_monotonic_ms=1_500),
            _keyframe("kf_seg_2", sequence_index=1, captured_at=now, captured_at_monotonic_ms=5_500),
        ),
        video=VideoArtifactRef(state=VideoArtifactState.AVAILABLE, artifact_id="art_video", duration_ms=2_500),
        segments=segments,
    )

    assert manifest.entries[0].media_time_ms == 500
    assert manifest.entries[0].nearest_video_segment_id == "rseg_1"
    assert manifest.entries[0].alignment_confidence == TimelineAlignmentConfidence.EXACT
    assert manifest.entries[1].media_time_ms == 1_500
    assert manifest.entries[1].nearest_video_segment_id == "rseg_2"
    assert manifest.entries[1].alignment_confidence == TimelineAlignmentConfidence.EXACT


def test_timeline_builder_aligns_segments_from_media_start_monotonic_time() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    segment = RecordingVideoSegmentRef(
        segment_id="rseg_1",
        session_id="acs_test",
        sequence_index=0,
        state=RecordingSegmentState.AVAILABLE,
        started_at=now,
        ended_at=now,
        started_at_monotonic_ms=1_000,
        media_start_monotonic_ms=1_300,
        ended_at_monotonic_ms=2_300,
        duration_ms=1_000,
    )

    manifest = RecordingTimelineManifestBuilder(ids=IdFactory(), clock=Clock()).build(
        session_id="acs_test",
        primary_event_id="evt_test",
        keyframes=(
            _keyframe("kf_before_first_frame", sequence_index=0, captured_at=now, captured_at_monotonic_ms=1_100),
            _keyframe("kf_in_video", sequence_index=1, captured_at=now, captured_at_monotonic_ms=1_500),
        ),
        video=VideoArtifactRef(state=VideoArtifactState.AVAILABLE, artifact_id="art_video", duration_ms=1_000),
        segments=(segment,),
    )

    assert manifest.entries[0].media_time_ms == 0
    assert manifest.entries[1].media_time_ms == 200
    assert manifest.entries[1].metadata["segment_media_start_monotonic_ms"] == 1_300


def test_timeline_builder_uses_segment_video_duration_for_stitched_offsets() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    segments = (
        RecordingVideoSegmentRef(
            segment_id="rseg_1",
            session_id="acs_test",
            sequence_index=0,
            state=RecordingSegmentState.AVAILABLE,
            started_at=now,
            ended_at=now,
            started_at_monotonic_ms=1_000,
            ended_at_monotonic_ms=4_000,
            duration_ms=1_800,
            video=VideoArtifactRef(state=VideoArtifactState.AVAILABLE, artifact_id="art_seg_1", duration_ms=2_300),
        ),
        RecordingVideoSegmentRef(
            segment_id="rseg_2",
            session_id="acs_test",
            sequence_index=1,
            state=RecordingSegmentState.AVAILABLE,
            started_at=now,
            ended_at=now,
            started_at_monotonic_ms=8_000,
            ended_at_monotonic_ms=12_500,
            duration_ms=2_000,
            video=VideoArtifactRef(state=VideoArtifactState.AVAILABLE, artifact_id="art_seg_2", duration_ms=3_500),
        ),
    )

    manifest = RecordingTimelineManifestBuilder(ids=IdFactory(), clock=Clock()).build(
        session_id="acs_test",
        primary_event_id="evt_test",
        keyframes=(
            _keyframe("kf_seg_1", sequence_index=0, captured_at=now, captured_at_monotonic_ms=2_000),
            _keyframe("kf_final", sequence_index=1, captured_at=now, captured_at_monotonic_ms=12_500),
        ),
        video=VideoArtifactRef(state=VideoArtifactState.AVAILABLE, artifact_id="art_stitched", duration_ms=5_800),
        segments=segments,
    )

    assert manifest.entries[0].media_time_ms == 1_000
    assert manifest.entries[1].media_time_ms == 5_800
    assert manifest.entries[1].nearest_video_segment_id == "rseg_2"
    assert manifest.entries[1].alignment_status == TimelineAlignmentStatus.ALIGNED


def test_timeline_builder_clamps_segment_alignment_to_stitched_video_duration() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    segments = (
        RecordingVideoSegmentRef(
            segment_id="rseg_1",
            session_id="acs_test",
            sequence_index=0,
            state=RecordingSegmentState.AVAILABLE,
            started_at=now,
            ended_at=now,
            started_at_monotonic_ms=1_000,
            ended_at_monotonic_ms=2_000,
            video=VideoArtifactRef(state=VideoArtifactState.AVAILABLE, artifact_id="art_seg_1", duration_ms=2_062),
        ),
        RecordingVideoSegmentRef(
            segment_id="rseg_2",
            session_id="acs_test",
            sequence_index=1,
            state=RecordingSegmentState.AVAILABLE,
            started_at=now,
            ended_at=now,
            started_at_monotonic_ms=6_000,
            ended_at_monotonic_ms=9_300,
            video=VideoArtifactRef(state=VideoArtifactState.AVAILABLE, artifact_id="art_seg_2", duration_ms=3_292),
        ),
    )

    manifest = RecordingTimelineManifestBuilder(ids=IdFactory(), clock=Clock()).build(
        session_id="acs_test",
        primary_event_id="evt_test",
        keyframes=(_keyframe("kf_final", sequence_index=0, captured_at=now, captured_at_monotonic_ms=9_300),),
        video=VideoArtifactRef(state=VideoArtifactState.AVAILABLE, artifact_id="art_stitched", duration_ms=5_353),
        segments=segments,
        timeline_alignment_tolerance_ms=250,
    )

    entry = manifest.entries[0]
    assert entry.media_time_ms == 5_353
    assert entry.nearest_video_segment_id == "rseg_2"
    assert entry.alignment_status == TimelineAlignmentStatus.ALIGNED
    assert entry.metadata["alignment_adjustment_ms"] == 1
    assert entry.metadata["video_duration_ms"] == 5_353


def test_terminal_policy_accepts_available_segment_video_without_top_level_video() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    session = ActiveCaptureSession(
        session_id="acs_test",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.FINALIZING,
        created_at=now,
        updated_at=now,
    )
    segment = RecordingVideoSegmentRef(
        segment_id="rseg_video",
        session_id=session.session_id,
        sequence_index=0,
        state=RecordingSegmentState.AVAILABLE,
        started_at=now,
        video=VideoArtifactRef(state=VideoArtifactState.AVAILABLE, artifact_id="art_segment_video"),
    )

    decision = TerminalSessionQualityPolicy(config=ActiveCapturePolicyConfig()).evaluate(
        session=session,
        keyframes=(),
        video=VideoArtifactRef(state=VideoArtifactState.NOT_RECORDED),
        warnings=(),
        completed_at=now,
        segments=(segment,),
    )

    assert decision.status == ActiveCaptureStatus.COMPLETED_WITH_WARNINGS
    assert {warning.code.value for warning in decision.warnings} == {"keyframe_capture_failed"}


def test_keyframe_policy_records_disabled_and_budget_drop_reasons() -> None:
    disabled = KeyframeCapturePolicy(config=ActiveCapturePolicyConfig(enabled=False), ids=IdFactory(), clock=Clock())
    budget = KeyframeCapturePolicy(
        config=ActiveCapturePolicyConfig(max_keyframes_per_session=1),
        ids=IdFactory(),
        clock=Clock(),
    )

    disabled_decision = disabled.decide(_candidate(existing_keyframe_count=0))
    budget_decision = budget.decide(
        _candidate(
            role=KeyframeRole.SETTLE,
            trigger_kind=KeyframeTriggerKind.STABILITY_SETTLE,
            existing_keyframe_count=1,
        )
    )

    assert disabled_decision.kept is False
    assert disabled_decision.drop_reason == KeyframeDropReason.POLICY_DISABLED
    assert budget_decision.kept is False
    assert budget_decision.drop_reason == KeyframeDropReason.BUDGET_EXCEEDED


def test_keyframe_policy_keeps_required_boundary_even_after_budget() -> None:
    policy = KeyframeCapturePolicy(
        config=ActiveCapturePolicyConfig(max_keyframes_per_session=1),
        ids=IdFactory(),
        clock=Clock(),
    )

    start_decision = policy.decide(
        _candidate(role=KeyframeRole.START, trigger_kind=KeyframeTriggerKind.RECORDING_START, existing_keyframe_count=1)
    )
    final_decision = policy.decide(
        _candidate(role=KeyframeRole.FINAL, trigger_kind=KeyframeTriggerKind.RECORDING_STOP, existing_keyframe_count=2)
    )

    assert start_decision.kept is True
    assert start_decision.keep_reason == KeyframeKeepReason.REQUIRED_BOUNDARY
    assert final_decision.kept is True
    assert final_decision.keep_reason == KeyframeKeepReason.REQUIRED_BOUNDARY


def test_keyframe_recorder_policy_drop_closes_bound_trigger_candidate() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    _seed_event_and_run(repositories, now)
    session = ActiveCaptureSession(
        session_id="acs_test",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=now,
        updated_at=now,
    )
    repositories.active_capture.save_session(session)
    repositories.active_capture.save_keyframe(_keyframe("kf_existing", sequence_index=0, captured_at=now))
    config = ActiveCapturePolicyConfig(max_keyframes_per_session=1)
    scheduler = KeyframeTriggerScheduler(
        repository=repositories.active_capture,
        ids=IdFactory(),
        clock=Clock(),
        config=config,
    )
    candidate = scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
            role=KeyframeRole.RESULT,
            occurred_at_monotonic_ms=1_000,
        ),
    )
    recorder = KeyframeRecorder(
        repository=repositories.active_capture,
        ids=IdFactory(),
        clock=Clock(),
        config=config,
        keyframe_policy=KeyframeCapturePolicy(config=config, ids=IdFactory(), clock=Clock()),
        trigger_scheduler=scheduler,
        scope_matcher=RecordingScopeMatcher(),
        access_checker=lambda _session, _attempt: True,
    )
    event = _event(now)
    result = recorder.record_keyframe(
        session=session,
        binding=ActiveCaptureBinding(
            session_id=session.session_id,
            role=KeyframeRole.RESULT,
            trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
            candidate_id=candidate.candidate_id,
        ),
        attempt=_scope_attempt(
            selected_region=BoundingBox(x=0, y=0, width=800, height=600),
            window_hint=None,
        ),
        event=event,
        artifacts=(),
        envelope=_empty_capture_envelope(event),
    )
    stored = repositories.active_capture.get_trigger_candidate(candidate.candidate_id)
    with repositories.database.transaction() as connection:
        row = connection.execute(
            "SELECT payload FROM keyframe_capture_decisions WHERE session_id = ?",
            (session.session_id,),
        ).fetchone()
    decision = KeyframeCaptureDecision.model_validate_json(str(row["payload"]))

    assert result is None
    assert stored is not None
    assert stored.status == KeyframeTriggerCandidateStatus.DROPPED
    assert stored.drop_reason == KeyframeDropReason.BUDGET_EXCEEDED
    assert decision.candidate_id == candidate.candidate_id
    assert decision.drop_reason == KeyframeDropReason.BUDGET_EXCEEDED


def test_keyframe_recorder_rejects_late_capture_for_dropped_candidate() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    _seed_event_and_run(repositories, now)
    session = ActiveCaptureSession(
        session_id="acs_late_drop",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=now,
        updated_at=now,
    )
    repositories.active_capture.save_session(session)
    config = ActiveCapturePolicyConfig()
    scheduler = KeyframeTriggerScheduler(
        repository=repositories.active_capture,
        ids=IdFactory(),
        clock=Clock(),
        config=config,
    )
    candidate = scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
            role=KeyframeRole.RESULT,
            occurred_at_monotonic_ms=1_000,
        ),
    )
    scheduler.mark_dropped(
        candidate_id=candidate.candidate_id,
        reason=KeyframeDropReason.ADAPTIVE_TIMEOUT,
        diagnostic="test expired claim",
    )
    recorder = KeyframeRecorder(
        repository=repositories.active_capture,
        ids=IdFactory(),
        clock=Clock(),
        config=config,
        keyframe_policy=KeyframeCapturePolicy(config=config, ids=IdFactory(), clock=Clock()),
        trigger_scheduler=scheduler,
        scope_matcher=RecordingScopeMatcher(),
        access_checker=lambda _session, _attempt: True,
    )
    event = _event(now)
    result = recorder.record_keyframe(
        session=session,
        binding=ActiveCaptureBinding(
            session_id=session.session_id,
            role=KeyframeRole.RESULT,
            trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
            candidate_id=candidate.candidate_id,
        ),
        attempt=_scope_attempt(
            selected_region=BoundingBox(x=0, y=0, width=800, height=600),
            window_hint=None,
        ),
        event=event,
        artifacts=(),
        envelope=_empty_capture_envelope(event),
    )
    stored = repositories.active_capture.get_trigger_candidate(candidate.candidate_id)
    with repositories.database.transaction() as connection:
        row = connection.execute(
            "SELECT payload FROM keyframe_capture_decisions WHERE session_id = ?",
            (session.session_id,),
        ).fetchone()
    decision = KeyframeCaptureDecision.model_validate_json(str(row["payload"]))

    assert result is None
    assert repositories.active_capture.list_keyframes_for_session(session.session_id) == ()
    assert stored is not None
    assert stored.status == KeyframeTriggerCandidateStatus.DROPPED
    assert stored.drop_reason == KeyframeDropReason.ADAPTIVE_TIMEOUT
    assert decision.candidate_id == candidate.candidate_id
    assert decision.drop_reason == KeyframeDropReason.ADAPTIVE_TIMEOUT


def test_recording_scope_rejects_match_all_window_or_region() -> None:
    with pytest.raises(ValueError, match="window recording scope requires"):
        RecordingScope(kind=RecordingScopeKind.WINDOW)
    with pytest.raises(ValueError, match="region recording scope requires"):
        RecordingScope(kind=RecordingScopeKind.REGION, display_id="display_main")

    scope = RecordingScope(
        kind=RecordingScopeKind.REGION,
        display_id="display_main",
        selection_region=BoundingBox(x=0, y=0, width=100, height=100),
    )

    assert scope.kind == RecordingScopeKind.REGION


def test_region_recording_scope_allows_window_title_drift() -> None:
    scope = RecordingScope(
        kind=RecordingScopeKind.REGION,
        display_id="display_main",
        scale_factor=2.0,
        window_id="win_1",
        process_id=1234,
        bundle_id="com.example.Browser",
        app_name="Browser",
        title="openrouter - Google 搜索",
        bounds=BoundingBox(x=100, y=100, width=820, height=620, coordinate_space=CoordinateSpace.MACOS_GLOBAL),
        selection_region=BoundingBox(
            x=120, y=140, width=520, height=280, coordinate_space=CoordinateSpace.MACOS_GLOBAL
        ),
    )
    attempt = _scope_attempt(
        selected_region=BoundingBox(x=120, y=140, width=520, height=280, coordinate_space=CoordinateSpace.MACOS_GLOBAL),
        window_hint=WindowHint(
            app_name="Browser",
            title="openrouter。新的查询 - Google 搜索",
            process_id=1234,
            window_id="win_1",
            bundle_id="com.example.Browser",
            display_id="display_main",
            frame=BoundingBox(x=100, y=100, width=820, height=620, coordinate_space=CoordinateSpace.MACOS_GLOBAL),
            overlap_ratio=0.98,
            confidence=0.95,
        ),
    )

    assert RecordingScopeMatcher().matches(scope, attempt)


def test_window_recording_scope_still_rejects_title_drift() -> None:
    scope = RecordingScope(
        kind=RecordingScopeKind.WINDOW,
        display_id="display_main",
        scale_factor=2.0,
        window_id="win_1",
        process_id=1234,
        bundle_id="com.example.Browser",
        app_name="Browser",
        title="Original Title",
        bounds=BoundingBox(x=100, y=100, width=820, height=620, coordinate_space=CoordinateSpace.MACOS_GLOBAL),
    )
    attempt = _scope_attempt(
        selected_region=BoundingBox(x=100, y=100, width=820, height=620, coordinate_space=CoordinateSpace.MACOS_GLOBAL),
        window_hint=WindowHint(
            app_name="Browser",
            title="Changed Title",
            process_id=1234,
            window_id="win_1",
            bundle_id="com.example.Browser",
            display_id="display_main",
            frame=BoundingBox(x=100, y=100, width=820, height=620, coordinate_space=CoordinateSpace.MACOS_GLOBAL),
            overlap_ratio=1.0,
            confidence=0.95,
        ),
    )

    assert not RecordingScopeMatcher().matches(scope, attempt)


def test_region_recording_scope_rejects_wrong_selection_region() -> None:
    scope = RecordingScope(
        kind=RecordingScopeKind.REGION,
        display_id="display_main",
        selection_region=BoundingBox(
            x=120, y=140, width=520, height=280, coordinate_space=CoordinateSpace.MACOS_GLOBAL
        ),
    )
    attempt = _scope_attempt(
        selected_region=BoundingBox(x=900, y=700, width=120, height=100, coordinate_space=CoordinateSpace.MACOS_GLOBAL),
        window_hint=None,
    )

    assert not RecordingScopeMatcher().matches(scope, attempt)


def test_region_recording_scope_rejects_wrong_selected_display_even_if_window_hint_matches() -> None:
    scope = RecordingScope(
        kind=RecordingScopeKind.REGION,
        display_id="display_main",
        selection_region=BoundingBox(
            x=120, y=140, width=520, height=280, coordinate_space=CoordinateSpace.MACOS_GLOBAL
        ),
    )
    attempt = _scope_attempt(
        selected_region=BoundingBox(x=120, y=140, width=520, height=280, coordinate_space=CoordinateSpace.MACOS_GLOBAL),
        display_id="display_secondary",
        window_hint=WindowHint(
            app_name="Browser",
            title="Still stale",
            window_id="win_stale",
            display_id="display_main",
            frame=BoundingBox(x=120, y=140, width=520, height=280, coordinate_space=CoordinateSpace.MACOS_GLOBAL),
            overlap_ratio=1.0,
            confidence=0.95,
        ),
    )

    assert not RecordingScopeMatcher().matches(scope, attempt)


def test_video_validator_rejects_non_mp4_and_paths_outside_staging(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    vault = tmp_path / "vault"
    staging.mkdir()
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"\x00\x00\x00\x18ftypmp42test")
    wrong_magic = staging / "wrong.mp4"
    wrong_magic.write_bytes(b"not-an-mp4")
    wrong_suffix = staging / "wrong.txt"
    wrong_suffix.write_bytes(b"\x00\x00\x00\x18ftypmp42test")
    vault_service = LocalArtifactVault(staging_dir=staging, vault_dir=vault)

    with pytest.raises(ArtifactVaultError):
        vault_service.validate_staged_video_file(outside, max_bytes=1024)
    with pytest.raises(ArtifactVaultError):
        vault_service.validate_staged_video_file(wrong_magic, max_bytes=1024)
    with pytest.raises(ArtifactVaultError):
        vault_service.validate_staged_video_file(wrong_suffix, max_bytes=1024)


def test_video_copy_uses_server_parsed_mp4_duration(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    vault = tmp_path / "vault"
    staging.mkdir()
    source = staging / "recording.mp4"
    _write_mp4(source, duration_ms=1234)
    vault_service = LocalArtifactVault(staging_dir=staging, vault_dir=vault)

    promoted = vault_service.copy_video(
        staged_path=source,
        artifact_id="art_video",
        created_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
        max_bytes=1024 * 1024,
    )

    assert promoted.duration_ms == 1234
    assert promoted.sha256
    assert promoted.local_path.read_bytes()[4:8] == b"ftyp"


def test_active_capture_rows_cascade_when_primary_event_is_deleted() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    _seed_event_and_run(repositories, now)
    session = ActiveCaptureSession(
        session_id="acs_test",
        mode=ActiveCaptureMode.SCREENSHOT_KEYFRAMES,
        status=ActiveCaptureStatus.COMPLETED,
        primary_event_id="evt_test",
        created_at=now,
        updated_at=now,
    )
    keyframe = _keyframe("kf_test", sequence_index=0)

    repositories.active_capture.save_session(session)
    repositories.active_capture.save_keyframe(keyframe)
    with repositories.database.transaction() as connection:
        connection.execute("DELETE FROM context_events WHERE event_id = 'evt_test'")
        session_count = connection.execute("SELECT COUNT(*) AS count FROM active_capture_sessions").fetchone()["count"]
        keyframe_count = connection.execute("SELECT COUNT(*) AS count FROM context_keyframes").fetchone()["count"]

    assert session_count == 0
    assert keyframe_count == 0


def test_keyframe_graph_cascades_when_screenshot_evidence_is_deleted() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    _seed_event_and_run(repositories, now)
    _seed_artifact_and_evidence(
        repositories,
        now,
        artifact_id="art_screenshot",
        evidence_id="ev_screenshot",
        evidence_kind="screenshot",
    )
    session = ActiveCaptureSession(
        session_id="acs_test",
        mode=ActiveCaptureMode.SCREENSHOT_KEYFRAMES,
        status=ActiveCaptureStatus.COMPLETED,
        primary_event_id="evt_test",
        created_at=now,
        updated_at=now,
    )
    keyframe = _keyframe("kf_test", sequence_index=0).model_copy(
        update={"screenshot_artifact_id": "art_screenshot", "screenshot_evidence_id": "ev_screenshot"}
    )

    repositories.active_capture.save_session(session)
    repositories.active_capture.save_keyframe(keyframe)
    repositories.active_capture.save_bundle(
        KeyframeContextBundle(
            bundle_id="kcb_test",
            session_id=session.session_id,
            primary_event_id="evt_test",
            status=KeyframeBundleStatus.READY,
            anchor_keyframe_id=keyframe.keyframe_id,
            keyframe_count=1,
            created_at=now,
            updated_at=now,
        )
    )
    with repositories.database.transaction() as connection:
        connection.execute("DELETE FROM evidence_records WHERE evidence_id = 'ev_screenshot'")
        keyframe_count = connection.execute("SELECT COUNT(*) AS count FROM context_keyframes").fetchone()["count"]
        bundle_count = connection.execute("SELECT COUNT(*) AS count FROM keyframe_context_bundles").fetchone()["count"]

    assert keyframe_count == 0
    assert bundle_count == 0


def test_recording_timeline_cascades_when_video_artifact_is_deleted() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    _seed_event_and_run(repositories, now)
    _seed_artifact_and_evidence(
        repositories,
        now,
        artifact_id="art_video",
        evidence_id="ev_video",
        artifact_type="recording_video",
        evidence_kind="keyframe_context_text",
        role="recording_video",
    )
    session = ActiveCaptureSession(
        session_id="acs_test",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.COMPLETED,
        primary_event_id="evt_test",
        created_at=now,
        updated_at=now,
    )
    manifest = RecordingTimelineManifest(
        manifest_id="tlm_test",
        session_id=session.session_id,
        primary_event_id="evt_test",
        video=VideoArtifactRef(artifact_id="art_video", state=VideoArtifactState.AVAILABLE),
        clock_origin_wall_time=now,
        created_at=now,
        updated_at=now,
    )

    repositories.active_capture.save_session(session)
    repositories.active_capture.save_timeline_manifest(manifest)
    with repositories.database.transaction() as connection:
        connection.execute("DELETE FROM artifacts WHERE artifact_id = 'art_video'")
        timeline_count = connection.execute("SELECT COUNT(*) AS count FROM recording_timeline_manifests").fetchone()[
            "count"
        ]

    assert timeline_count == 0


def test_active_capture_repository_round_trips_controls_segments_triggers_and_demo_trace() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    _seed_event_and_run(repositories, now)
    session = ActiveCaptureSession(
        session_id="acs_test",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        primary_event_id="evt_test",
        created_at=now,
        updated_at=now,
    )
    keyframe = _keyframe("kf_action", sequence_index=0)
    control = RecordingControlEvent(
        control_id="rctl_test",
        session_id=session.session_id,
        kind=RecordingControlKind.USER_MARK,
        source=RecordingControlSource.API,
        occurred_at=now,
    )
    segment = RecordingVideoSegmentRef(
        segment_id="rseg_test",
        session_id=session.session_id,
        sequence_index=0,
        state=RecordingSegmentState.RECORDING,
        started_at=now,
        started_at_monotonic_ms=1_000,
        media_start_monotonic_ms=1_050,
    )
    pause = RecordingPauseInterval(
        pause_id="rps_test",
        session_id=session.session_id,
        started_at=now,
        started_at_monotonic_ms=2_000,
    )
    candidate = KeyframeTriggerCandidate(
        candidate_id="kfc_test",
        session_id=session.session_id,
        trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
        role=KeyframeRole.CHANGE,
        priority=KeyframePriorityBand.HIGH,
        status=KeyframeTriggerCandidateStatus.ACCEPTED,
        occurred_at=now,
    )
    trace = HumanDemonstrationTrace(
        trace_id="hdt_test",
        session_id=session.session_id,
        status=HumanDemonstrationTraceStatus.ACTIVE,
        action_count=1,
        started_at=now,
    )
    action = HumanActionEvent(
        action_id="act_test",
        trace_id=trace.trace_id,
        session_id=session.session_id,
        sequence_index=0,
        kind=HumanActionKind.CLICK,
        occurred_at=now,
        coordinates=_action_coordinates(),
        hotkey_semantic=None,
    )
    link = ActionEvidenceLink(
        link_id="ael_test",
        action_id=action.action_id,
        role=HumanActionEvidenceRole.AFTER_KEYFRAME,
        keyframe_id=keyframe.keyframe_id,
        event_id="evt_test",
        created_at=now,
    )
    observation = ActionResultObservation(
        observation_id="aob_test",
        action_id=action.action_id,
        status=HumanActionOutcomeStatus.OBSERVED,
        observed_at=now,
        result_keyframe_id=keyframe.keyframe_id,
    )
    producer_event = ProducerEventEnvelope(
        producer_event_id="pev_test",
        session_id=session.session_id,
        event_kind=ProducerInputEventKind.POINTER_CLICK,
        producer_kind="macos_capture",
        occurred_at=now,
        occurred_at_monotonic_ms=1_000,
        pointer=PointerInputPayload(coordinates=_action_coordinates()),
    )
    producer_decision = ProducerDecision(
        decision_id="ped_test",
        producer_event_id=producer_event.producer_event_id,
        session_id=session.session_id,
        status=ProducerDecisionStatus.ACCEPTED,
        reason=ProducerDecisionReason.CLICK_SETTLED,
        action_kind=HumanActionKind.CLICK,
        trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
        action_id=action.action_id,
        candidate_id=candidate.candidate_id,
        created_at=now,
    )

    repositories.active_capture.save_session(session)
    repositories.active_capture.save_keyframe(keyframe)
    repositories.active_capture.save_control_event(control)
    repositories.active_capture.save_recording_segment(segment)
    repositories.active_capture.save_pause_interval(pause)
    repositories.active_capture.save_trigger_candidate(candidate)
    repositories.active_capture.append_human_action_graph(
        action=action,
        links=(link,),
        observation=observation,
        trace=trace,
    )
    repositories.active_capture.append_producer_event_graph(event=producer_event, decision=producer_decision)

    assert repositories.active_capture.list_control_events_for_session(session.session_id) == (control,)
    assert repositories.active_capture.list_recording_segments_for_session(session.session_id) == (segment,)
    assert repositories.active_capture.list_pause_intervals_for_session(session.session_id) == (pause,)
    assert repositories.active_capture.get_trigger_candidate(candidate.candidate_id) == candidate
    assert repositories.active_capture.get_demonstration_trace_for_session(session.session_id) == trace
    assert repositories.active_capture.list_human_actions_for_session(session.session_id) == (action,)
    assert repositories.active_capture.list_action_evidence_links(action.action_id) == (link,)
    assert repositories.active_capture.get_action_observation(action.action_id) == observation
    assert repositories.active_capture.list_producer_events_for_session(session.session_id) == (producer_event,)
    assert repositories.active_capture.list_producer_decisions_for_session(session.session_id) == (producer_decision,)


def test_recording_inspect_service_builds_agent_safe_projection_and_index_batch() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    _seed_event_and_run(repositories, now)
    _seed_artifact_and_evidence(
        repositories,
        now,
        artifact_id="art_text",
        evidence_id="ev_text",
        artifact_type=ArtifactType.A11Y_SELECTION_TEXT.value,
        evidence_kind=KeyframeEvidenceRole.SELECTION_TEXT.value,
        role=ArtifactRole.SELECTION_TEXT.value,
    )
    _seed_artifact_and_evidence(
        repositories,
        now,
        artifact_id="art_video",
        evidence_id="ev_video",
        artifact_type=ArtifactType.RECORDING_VIDEO.value,
        evidence_kind="keyframe_context_text",
        role=ArtifactRole.RECORDING_VIDEO.value,
    )
    event = _event(now)
    session = ActiveCaptureSession(
        session_id="acs_test",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.COMPLETED,
        primary_event_id=event.event_id,
        started_at=now,
        ended_at=now,
        created_at=now,
        updated_at=now,
        user_note="记录支付设置复现步骤",
    )
    keyframe = _keyframe(
        "kf_test",
        sequence_index=0,
        captured_at=now,
        captured_at_monotonic_ms=1_000,
        media_time_ms=0,
    )
    trace = HumanDemonstrationTrace(
        trace_id="hdt_test",
        session_id=session.session_id,
        status=HumanDemonstrationTraceStatus.ACTIVE,
        action_count=1,
        started_at=now,
    )
    action = HumanActionEvent(
        action_id="act_test",
        trace_id=trace.trace_id,
        session_id=session.session_id,
        sequence_index=0,
        kind=HumanActionKind.HOTKEY,
        occurred_at=now,
        occurred_at_monotonic_ms=1_100,
        media_time_ms=100,
        hotkey_semantic=HotkeySemantic.SUBMIT,
    )
    action_link = ActionEvidenceLink(
        link_id="ael_after",
        action_id=action.action_id,
        role=HumanActionEvidenceRole.AFTER_KEYFRAME,
        keyframe_id=keyframe.keyframe_id,
        event_id=event.event_id,
        created_at=now,
    )
    observation = ActionResultObservation(
        observation_id="aob_test",
        action_id=action.action_id,
        status=HumanActionOutcomeStatus.OBSERVED,
        observed_at=now,
        result_keyframe_id=keyframe.keyframe_id,
    )
    producer_event = ProducerEventEnvelope(
        producer_event_id="pev_test",
        session_id=session.session_id,
        event_kind=ProducerInputEventKind.HOTKEY,
        producer_kind="macos_capture",
        occurred_at=now,
        occurred_at_monotonic_ms=1_100,
        keyboard=KeyboardInputPayload(
            keyboard_event_kind=KeyboardEventKind.HOTKEY,
            input_class=KeyboardInputClass.SHORTCUT,
            capture_policy=KeyCapturePolicy.KEY_CHORD_ALLOWED,
            key_chord=KeyChord(
                physical_key_code=36,
                normalized_key_label="enter",
                semantic=HotkeySemantic.SUBMIT,
            ),
            hotkey_semantic=HotkeySemantic.SUBMIT,
        ),
    )
    producer_decision = ProducerDecision(
        decision_id="ped_test",
        producer_event_id=producer_event.producer_event_id,
        session_id=session.session_id,
        status=ProducerDecisionStatus.ACCEPTED,
        reason=ProducerDecisionReason.COMMAND_SUBMITTED,
        action_kind=HumanActionKind.HOTKEY,
        trigger_kind=KeyframeTriggerKind.COMMAND_SUBMITTED,
        action_id=action.action_id,
        created_at=now,
    )
    manifest = RecordingTimelineManifest(
        manifest_id="tlm_test",
        session_id=session.session_id,
        primary_event_id=event.event_id,
        video=VideoArtifactRef(
            artifact_id="art_video",
            state=VideoArtifactState.AVAILABLE,
            content_type=RecordingVideoContentType.MP4,
            duration_ms=1_000,
            byte_size=512,
        ),
        clock_origin_wall_time=now,
        clock_origin_monotonic_ms=1_000,
        duration_ms=1_000,
        entries=(
            TimelineKeyframeEntry(
                keyframe_id=keyframe.keyframe_id,
                role=keyframe.role,
                trigger_kind=keyframe.trigger_kind,
                sequence_index=keyframe.sequence_index,
                captured_at_wall_time=keyframe.captured_at,
                captured_at_monotonic_ms=keyframe.captured_at_monotonic_ms,
                media_time_ms=0,
                video_artifact_id="art_video",
                alignment_confidence=TimelineAlignmentConfidence.EXACT,
                alignment_status=TimelineAlignmentStatus.ALIGNED,
            ),
        ),
        created_at=now,
        updated_at=now,
    )
    repositories.active_capture.save_session(session)
    repositories.active_capture.save_keyframe(keyframe)
    repositories.active_capture.save_evidence_links(
        (
            KeyframeEvidenceLink(
                link_id="kel_text",
                keyframe_id=keyframe.keyframe_id,
                event_id=event.event_id,
                evidence_id="ev_text",
                artifact_id="art_text",
                role=KeyframeEvidenceRole.SELECTION_TEXT,
                created_at=now,
            ),
        )
    )
    repositories.active_capture.append_human_action_graph(
        action=action,
        links=(action_link,),
        observation=observation,
        trace=trace,
    )
    repositories.active_capture.append_producer_event_graph(event=producer_event, decision=producer_decision)
    repositories.active_capture.save_timeline_manifest(manifest)
    service = RecordingInspectService(
        repository=repositories.active_capture,
        clock=Clock(),
        event_lookup=_FakeEventLookup(event),
        event_inspector=_FakeEventInspector(now),
        safe_index=SafeIndexProjectionService(ids=IdFactory()),
    )

    inspect = service.build_for_event(
        event_id=event.event_id,
        actor=ActorRef(actor_id="actor_test"),
        purpose="unit test",
        requested_sections=(
            EventInspectSection.ACTIVE_CAPTURE_SUMMARY,
            EventInspectSection.RECORDING_TIMELINE,
            EventInspectSection.VIDEO_REF,
            EventInspectSection.SELECTION_TEXT,
        ),
    )

    assert inspect is not None
    assert inspect.timeline is not None
    assert [step.step_id for step in inspect.timeline.steps] == ["kf:kf_test", "act:act_test"]
    assert inspect.timeline.steps[1].safe_caption == "按下 Enter"
    assert inspect.video_ref is not None
    assert inspect.video_ref.artifact_id == "art_video"
    assert inspect.video_ref.duration_ms == 1_000
    assert inspect.user_note == "记录支付设置复现步骤"
    assert inspect.safe_text_blocks[0].text == "safe selected text"
    assert inspect.skill_readiness.state == "ready"
    action_summary = inspect.timeline.steps[1].action_summary
    assert action_summary is not None
    assert action_summary.key_chord is not None
    assert action_summary.key_chord.normalized_key_label == "enter"
    assert action_summary.producer_decision_reason == ProducerDecisionReason.COMMAND_SUBMITTED

    batch = service.index_projection_for_inspect(inspect, actor=ActorRef(actor_id="actor_test"))

    assert batch is not None
    assert batch.replace_event is False
    indexed_text = "\n".join(projection.text for projection in batch.projections)
    assert "按下 Enter" in indexed_text
    assert "safe selected text" in indexed_text
    assert "记录支付设置复现步骤" in indexed_text


def test_recording_inspect_omits_keyframes_without_visible_event_lookup() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    _seed_event_and_run(repositories, now)
    _seed_event_and_run_ids(
        repositories,
        now,
        event_id="evt_hidden",
        trigger_id="trg_hidden",
        capture_run_id="run_hidden",
    )
    event = _event(now)
    session = ActiveCaptureSession(
        session_id="acs_test",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.COMPLETED,
        primary_event_id=event.event_id,
        created_at=now,
        updated_at=now,
    )
    visible = _keyframe("kf_visible", sequence_index=0, captured_at=now)
    hidden = _keyframe("kf_hidden", sequence_index=1, captured_at=now).model_copy(
        update={"event_id": "evt_hidden", "capture_run_id": "run_hidden"}
    )
    trace = HumanDemonstrationTrace(
        trace_id="hdt_hidden",
        session_id=session.session_id,
        status=HumanDemonstrationTraceStatus.ACTIVE,
        action_count=1,
        started_at=now,
    )
    hidden_action = HumanActionEvent(
        action_id="act_hidden",
        trace_id=trace.trace_id,
        session_id=session.session_id,
        sequence_index=0,
        kind=HumanActionKind.HOTKEY,
        occurred_at=now,
        hotkey_semantic=HotkeySemantic.OPEN_COMMAND,
    )
    hidden_link = ActionEvidenceLink(
        link_id="ael_hidden",
        action_id=hidden_action.action_id,
        role=HumanActionEvidenceRole.AFTER_KEYFRAME,
        keyframe_id=hidden.keyframe_id,
        event_id="evt_hidden",
        created_at=now,
    )
    hidden_observation = ActionResultObservation(
        observation_id="aob_hidden",
        action_id=hidden_action.action_id,
        status=HumanActionOutcomeStatus.OBSERVED,
        observed_at=now,
        result_keyframe_id=hidden.keyframe_id,
    )
    hidden_producer_event = ProducerEventEnvelope(
        producer_event_id="pev_hidden",
        session_id=session.session_id,
        event_kind=ProducerInputEventKind.HOTKEY,
        producer_kind="macos_capture",
        occurred_at=now,
        keyboard=KeyboardInputPayload(
            keyboard_event_kind=KeyboardEventKind.HOTKEY,
            input_class=KeyboardInputClass.SHORTCUT,
            capture_policy=KeyCapturePolicy.KEY_CHORD_ALLOWED,
            key_chord=KeyChord(
                physical_key_code=40,
                normalized_key_label="k",
                modifiers=(ModifierKey.COMMAND,),
                semantic=HotkeySemantic.OPEN_COMMAND,
            ),
            hotkey_semantic=HotkeySemantic.OPEN_COMMAND,
        ),
    )
    hidden_decision = ProducerDecision(
        decision_id="ped_hidden",
        producer_event_id=hidden_producer_event.producer_event_id,
        session_id=session.session_id,
        status=ProducerDecisionStatus.ACCEPTED,
        reason=ProducerDecisionReason.COMMAND_SUBMITTED,
        action_kind=HumanActionKind.HOTKEY,
        trigger_kind=KeyframeTriggerKind.COMMAND_SUBMITTED,
        action_id=hidden_action.action_id,
        keyframe_id=hidden.keyframe_id,
        created_at=now,
    )
    pending_action = HumanActionEvent(
        action_id="act_pending",
        trace_id=trace.trace_id,
        session_id=session.session_id,
        sequence_index=0,
        kind=HumanActionKind.HOTKEY,
        occurred_at=now,
        hotkey_semantic=HotkeySemantic.SUBMIT,
    )
    repositories.active_capture.save_session(session)
    repositories.active_capture.save_keyframe(visible)
    repositories.active_capture.save_keyframe(hidden)
    repositories.active_capture.append_human_action_graph(
        action=hidden_action,
        links=(hidden_link,),
        observation=hidden_observation,
        trace=trace,
    )
    repositories.active_capture.append_producer_event_graph(event=hidden_producer_event, decision=hidden_decision)
    repositories.active_capture.append_human_action_graph(
        action=pending_action,
        links=(),
        observation=None,
        trace=trace,
    )
    service = RecordingInspectService(
        repository=repositories.active_capture,
        clock=Clock(),
        event_lookup=_FakeEventLookup(event),
        event_inspector=_FakeEventInspector(now),
        safe_index=SafeIndexProjectionService(ids=IdFactory()),
    )

    inspect = service.build_for_event(
        event_id=event.event_id,
        actor=ActorRef(actor_id="actor_test"),
        purpose="unit test",
        requested_sections=(
            EventInspectSection.ACTIVE_CAPTURE_SUMMARY,
            EventInspectSection.RECORDING_TIMELINE,
            EventInspectSection.SELECTION_TEXT,
        ),
    )

    assert inspect is not None
    assert inspect.timeline is not None
    assert [step.keyframe_id for step in inspect.timeline.steps if step.keyframe_id is not None] == ["kf_visible"]
    action_steps = [step for step in inspect.timeline.steps if step.action_id is not None]
    assert [step.action_id for step in action_steps] == ["act_pending"]
    assert action_steps[0].needs_review is True
    assert {block.event_id for block in inspect.safe_text_blocks} == {event.event_id}


def test_recording_inspect_omits_session_when_primary_event_hidden() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    event = _event(now)
    _seed_event_and_run(repositories, now)
    _seed_event_and_run_ids(
        repositories,
        now,
        event_id="evt_hidden_primary",
        trigger_id="trg_hidden_primary",
        capture_run_id="run_hidden_primary",
    )
    session = ActiveCaptureSession(
        session_id="acs_primary_hidden",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.COMPLETED,
        primary_event_id="evt_hidden_primary",
        created_at=now,
        updated_at=now,
    )
    repositories.active_capture.save_session(session)
    repositories.active_capture.save_keyframe(
        _keyframe("kf_visible", sequence_index=0, captured_at=now).model_copy(update={"session_id": session.session_id})
    )
    service = RecordingInspectService(
        repository=repositories.active_capture,
        clock=Clock(),
        event_lookup=_FakeEventLookup(event),
        event_inspector=_FakeEventInspector(now),
        safe_index=SafeIndexProjectionService(ids=IdFactory()),
    )

    inspect = service.build_for_event(
        event_id=event.event_id,
        actor=ActorRef(actor_id="actor_test"),
        purpose="unit test",
        requested_sections=(EventInspectSection.ACTIVE_CAPTURE_SUMMARY,),
    )

    assert inspect is None


def test_skill_distillation_projection_uses_session_batch_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    _seed_event_and_run(repositories, now)
    session = ActiveCaptureSession(
        session_id="acs_skill_batch",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.COMPLETED,
        primary_event_id="evt_test",
        created_at=now,
        updated_at=now,
    )
    keyframe = _keyframe("kf_skill", sequence_index=0, captured_at=now).model_copy(
        update={"session_id": session.session_id}
    )
    trace = HumanDemonstrationTrace(
        trace_id="hdt_skill_batch",
        session_id=session.session_id,
        status=HumanDemonstrationTraceStatus.ACTIVE,
        action_count=1,
        started_at=now,
    )
    action = HumanActionEvent(
        action_id="act_skill_batch",
        trace_id=trace.trace_id,
        session_id=session.session_id,
        sequence_index=0,
        kind=HumanActionKind.HOTKEY,
        occurred_at=now,
        hotkey_semantic=HotkeySemantic.SUBMIT,
    )
    repositories.active_capture.save_session(session)
    repositories.active_capture.save_keyframe(keyframe)
    repositories.active_capture.append_human_action_graph(
        action=action,
        trace=trace,
        links=(
            ActionEvidenceLink(
                link_id="ael_skill_batch",
                action_id=action.action_id,
                role=HumanActionEvidenceRole.AFTER_KEYFRAME,
                keyframe_id=keyframe.keyframe_id,
                created_at=now,
            ),
        ),
        observation=ActionResultObservation(
            observation_id="aob_skill_batch",
            action_id=action.action_id,
            status=HumanActionOutcomeStatus.OBSERVED,
            observed_at=now,
            result_keyframe_id=keyframe.keyframe_id,
        ),
    )

    def _unexpected_per_action_lookup(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("skill projection must use session-level batch edge readers")

    monkeypatch.setattr(repositories.active_capture, "list_action_evidence_links", _unexpected_per_action_lookup)
    monkeypatch.setattr(repositories.active_capture, "get_action_observation", _unexpected_per_action_lookup)

    projection = SkillDistillationInputProjector(repository=repositories.active_capture, clock=Clock()).build(session)

    assert len(projection.steps) == 1
    assert projection.steps[0].evidence_keyframe_ids == (keyframe.keyframe_id,)


def test_human_action_contract_requires_semantic_hotkey_not_raw_text() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)

    with pytest.raises(ValueError, match="hotkey action requires"):
        HumanActionEvent(
            action_id="act_hotkey",
            trace_id="hdt_test",
            session_id="acs_test",
            sequence_index=0,
            kind=HumanActionKind.HOTKEY,
            occurred_at=now,
        )

    action = HumanActionEvent(
        action_id="act_hotkey",
        trace_id="hdt_test",
        session_id="acs_test",
        sequence_index=0,
        kind=HumanActionKind.HOTKEY,
        occurred_at=now,
        hotkey_semantic=HotkeySemantic.SUBMIT,
    )

    assert action.hotkey_semantic == HotkeySemantic.SUBMIT


def test_typing_pause_contract_rejects_free_text_target_fields() -> None:
    with pytest.raises(ValueError, match="typing_pause action cannot carry free-text target fields"):
        RecordHumanActionCommand(
            kind=HumanActionKind.TYPING_PAUSE,
            target=ActionTargetRef(accessible_name="raw typed query"),
        )

    command = RecordHumanActionCommand(
        kind=HumanActionKind.TYPING_PAUSE,
        target=ActionTargetRef(
            keyframe_id="kf_structured",
            coordinates=_action_coordinates(),
            confidence=0.9,
        ),
    )

    assert command.target is not None
    assert command.target.keyframe_id == "kf_structured"


def test_producer_keyboard_contract_requires_explicit_full_content_policy_for_raw_keys() -> None:
    chord = KeyChord(
        physical_key_code=40,
        normalized_key_label="k",
        modifiers=(ModifierKey.COMMAND,),
        semantic=HotkeySemantic.OPEN_COMMAND,
    )
    shortcut = RecordProducerInputEventCommand(
        event_kind=ProducerInputEventKind.HOTKEY,
        producer_kind="macos_capture",
        keyboard=KeyboardInputPayload(
            keyboard_event_kind=KeyboardEventKind.HOTKEY,
            input_class=KeyboardInputClass.SHORTCUT,
            capture_policy=KeyCapturePolicy.KEY_CHORD_ALLOWED,
            key_chord=chord,
            hotkey_semantic=HotkeySemantic.OPEN_COMMAND,
        ),
    )

    assert shortcut.keyboard is not None
    assert shortcut.keyboard.key_chord == chord

    unknown_chord = KeyChord(
        physical_key_code=11,
        normalized_key_label="b",
        modifiers=(ModifierKey.OPTION,),
        semantic=HotkeySemantic.UNKNOWN,
    )
    unknown_shortcut = RecordProducerInputEventCommand(
        event_kind=ProducerInputEventKind.HOTKEY,
        producer_kind="macos_capture",
        keyboard=KeyboardInputPayload(
            keyboard_event_kind=KeyboardEventKind.HOTKEY,
            input_class=KeyboardInputClass.SHORTCUT,
            capture_policy=KeyCapturePolicy.KEY_CHORD_ALLOWED,
            key_chord=unknown_chord,
            hotkey_semantic=HotkeySemantic.UNKNOWN,
        ),
    )

    assert unknown_shortcut.keyboard is not None
    assert unknown_shortcut.keyboard.key_chord == unknown_chord

    with pytest.raises(ValueError, match="ordinary text input cannot store exact key chords"):
        RecordProducerInputEventCommand(
            event_kind=ProducerInputEventKind.HOTKEY,
            producer_kind="macos_capture",
            keyboard=KeyboardInputPayload(
                keyboard_event_kind=KeyboardEventKind.HOTKEY,
                input_class=KeyboardInputClass.TEXT_INPUT,
                capture_policy=KeyCapturePolicy.AGGREGATE_ONLY,
                key_chord=chord,
            ),
        )

    with pytest.raises(ValueError, match="forbidden sensitive metadata"):
        RecordProducerInputEventCommand(
            event_kind=ProducerInputEventKind.TYPING_PAUSE,
            producer_kind="macos_capture",
            keyboard=KeyboardInputPayload(
                keyboard_event_kind=KeyboardEventKind.TYPING_PAUSE,
                input_class=KeyboardInputClass.TEXT_INPUT,
                capture_policy=KeyCapturePolicy.AGGREGATE_ONLY,
                typing_summary=TypingSessionSummary(event_count=3, character_count=3),
            ),
            metadata={"typed_text": "secret"},
        )

    with pytest.raises(ValueError, match="require full_content capture policy"):
        RecordProducerInputEventCommand(
            event_kind=ProducerInputEventKind.KEY_DOWN,
            producer_kind="macos_capture",
            keyboard=KeyboardInputPayload(
                keyboard_event_kind=KeyboardEventKind.KEY_DOWN,
                input_class=KeyboardInputClass.SHORTCUT,
                capture_policy=KeyCapturePolicy.KEY_CHORD_ALLOWED,
                key_chord=chord,
                hotkey_semantic=HotkeySemantic.OPEN_COMMAND,
            ),
        )

    raw_key = RecordProducerInputEventCommand(
        event_kind=ProducerInputEventKind.KEY_DOWN,
        producer_kind="macos_capture",
        keyboard=KeyboardInputPayload(
            keyboard_event_kind=KeyboardEventKind.KEY_DOWN,
            input_class=KeyboardInputClass.TEXT_INPUT,
            capture_policy=KeyCapturePolicy.FULL_CONTENT,
            key_chord=KeyChord(
                physical_key_code=4,
                normalized_key_label="h",
                modifiers=(ModifierKey.SHIFT,),
                characters="H",
            ),
        ),
    )
    assert raw_key.keyboard is not None
    assert raw_key.keyboard.key_chord is not None
    assert raw_key.keyboard.key_chord.characters == "H"

    with pytest.raises(ValueError, match="forbidden sensitive metadata"):
        RecordProducerInputEventCommand(
            event_kind=ProducerInputEventKind.TYPING_PAUSE,
            producer_kind="macos_capture",
            keyboard=KeyboardInputPayload(
                keyboard_event_kind=KeyboardEventKind.TYPING_PAUSE,
                input_class=KeyboardInputClass.TEXT_INPUT,
                capture_policy=KeyCapturePolicy.AGGREGATE_ONLY,
                typing_summary=TypingSessionSummary(event_count=3, character_count=3),
            ),
            metadata={"typedTextPreview": "secret"},
        )


def test_producer_decision_policy_maps_click_and_hotkey_to_actions_and_triggers() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    session = ActiveCaptureSession(
        session_id="acs_producer_policy",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=now,
        updated_at=now,
    )
    click = ProducerEventEnvelope(
        producer_event_id="pev_click",
        session_id=session.session_id,
        event_kind=ProducerInputEventKind.POINTER_CLICK,
        producer_kind="macos_capture",
        occurred_at=now,
        occurred_at_monotonic_ms=1_000,
        pointer=PointerInputPayload(
            button=PointerButton.RIGHT,
            click_count=2,
            coordinates=_action_coordinates(),
        ),
    )
    hotkey = ProducerEventEnvelope(
        producer_event_id="pev_hotkey",
        session_id=session.session_id,
        event_kind=ProducerInputEventKind.HOTKEY,
        producer_kind="macos_capture",
        occurred_at=now,
        occurred_at_monotonic_ms=1_500,
        keyboard=KeyboardInputPayload(
            keyboard_event_kind=KeyboardEventKind.HOTKEY,
            input_class=KeyboardInputClass.SHORTCUT,
            capture_policy=KeyCapturePolicy.KEY_CHORD_ALLOWED,
            key_chord=KeyChord(
                physical_key_code=36,
                normalized_key_label="enter",
                semantic=HotkeySemantic.SUBMIT,
            ),
            hotkey_semantic=HotkeySemantic.SUBMIT,
        ),
    )

    policy = ProducerEventDecisionPolicy()
    click_plan = policy.plan(session=session, event=click)
    hotkey_plan = policy.plan(session=session, event=hotkey)

    assert click_plan.action is not None
    assert click_plan.action.kind == HumanActionKind.CLICK
    assert click_plan.action.metadata == {
        "producer_event_id": "pev_click",
        "button": "right",
        "click_count": 2,
    }
    assert click_plan.trigger is not None
    assert click_plan.trigger.trigger_kind == KeyframeTriggerKind.CLICK_SETTLE
    assert hotkey_plan.action is not None
    assert hotkey_plan.action.hotkey_semantic == HotkeySemantic.SUBMIT
    assert hotkey_plan.trigger is not None
    assert hotkey_plan.trigger.trigger_kind == KeyframeTriggerKind.COMMAND_SUBMITTED


def test_producer_ingest_preserves_native_event_wall_time_for_actions() -> None:
    started = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    delayed_ingest_time = datetime(2026, 5, 30, 12, 1, tzinfo=UTC)
    occurred_at = datetime(2026, 5, 30, 12, 0, 5, tzinfo=UTC)
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    session = ActiveCaptureSession(
        session_id="acs_producer_wall_time",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        started_at=started,
        created_at=started,
        updated_at=started,
    )
    repositories.active_capture.save_session(session)
    service = _producer_ingest_service(
        repository=repositories.active_capture,
        clock=_FixedClock(delayed_ingest_time),
        ids=IdFactory(),
    )

    service.ingest(
        session=session,
        command=RecordProducerInputEventCommand(
            event_kind=ProducerInputEventKind.POINTER_CLICK,
            producer_kind="macos_capture",
            occurred_at_wall_time=occurred_at,
            occurred_at_monotonic_ms=6_000,
            pointer=PointerInputPayload(button=PointerButton.LEFT, coordinates=_action_coordinates()),
        ),
    )

    producer_event = repositories.active_capture.list_producer_events_for_session(session.session_id)[0]
    action = repositories.active_capture.list_human_actions_for_session(session.session_id)[0]
    assert producer_event.occurred_at == occurred_at
    assert producer_event.occurred_at_wall_time == occurred_at
    assert action.occurred_at == occurred_at


def test_producer_ingest_derives_event_wall_time_from_segment_anchor_for_legacy_events() -> None:
    started = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    delayed_ingest_time = datetime(2026, 5, 30, 12, 1, tzinfo=UTC)
    expected_occurred_at = datetime(2026, 5, 30, 12, 0, 5, tzinfo=UTC)
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    session = ActiveCaptureSession(
        session_id="acs_producer_segment_time",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        started_at=started,
        created_at=started,
        updated_at=started,
    )
    repositories.active_capture.save_session(session)
    repositories.active_capture.save_recording_segment(
        RecordingVideoSegmentRef(
            segment_id="rseg_test",
            session_id=session.session_id,
            sequence_index=0,
            state=RecordingSegmentState.RECORDING,
            started_at=started,
            started_at_monotonic_ms=1_000,
        )
    )
    service = _producer_ingest_service(
        repository=repositories.active_capture,
        clock=_FixedClock(delayed_ingest_time),
        ids=IdFactory(),
    )

    service.ingest(
        session=session,
        command=RecordProducerInputEventCommand(
            event_kind=ProducerInputEventKind.POINTER_CLICK,
            producer_kind="macos_capture",
            occurred_at_monotonic_ms=6_000,
            pointer=PointerInputPayload(button=PointerButton.LEFT, coordinates=_action_coordinates()),
        ),
    )

    producer_event = repositories.active_capture.list_producer_events_for_session(session.session_id)[0]
    action = repositories.active_capture.list_human_actions_for_session(session.session_id)[0]
    assert producer_event.occurred_at == expected_occurred_at
    assert producer_event.occurred_at_wall_time is None
    assert action.occurred_at == expected_occurred_at


def test_producer_decision_policy_maps_pointer_drag_to_drag_action() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    session = ActiveCaptureSession(
        session_id="acs_producer_drag_policy",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=now,
        updated_at=now,
    )
    drag = ProducerEventEnvelope(
        producer_event_id="pev_drag",
        session_id=session.session_id,
        event_kind=ProducerInputEventKind.POINTER_DRAG,
        producer_kind="macos_capture",
        occurred_at=now,
        occurred_at_monotonic_ms=2_000,
        pointer=PointerInputPayload(
            button=PointerButton.LEFT,
            coordinates=_action_coordinates(),
        ),
        metadata={
            "button": "left",
            "drag_start_x": 120.0,
            "drag_start_y": 240.0,
            "drag_path": "120,240;150,260;180,300",
            "drag_duration_ms": 700,
        },
    )

    plan = ProducerEventDecisionPolicy().plan(session=session, event=drag)

    assert plan.reason == ProducerDecisionReason.DRAG_SETTLED
    assert plan.action is not None
    assert plan.action.kind == HumanActionKind.DRAG
    assert plan.action.metadata["drag_path"] == "120,240;150,260;180,300"
    assert plan.trigger is not None
    assert plan.trigger.trigger_kind == KeyframeTriggerKind.ACTION_RESULT_SETTLE


def test_producer_decision_policy_keeps_plain_typing_trace_only() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    session = ActiveCaptureSession(
        session_id="acs_typing_trace_only",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=now,
        updated_at=now,
    )
    event = ProducerEventEnvelope(
        producer_event_id="pev_typing_pause",
        session_id=session.session_id,
        event_kind=ProducerInputEventKind.TYPING_PAUSE,
        producer_kind="macos_capture",
        occurred_at=now,
        occurred_at_monotonic_ms=2_000,
        keyboard=KeyboardInputPayload(
            keyboard_event_kind=KeyboardEventKind.TYPING_PAUSE,
            input_class=KeyboardInputClass.TEXT_INPUT,
            capture_policy=KeyCapturePolicy.AGGREGATE_ONLY,
            typing_summary=TypingSessionSummary(event_count=6, character_count=6, submitted_by_enter=False),
        ),
    )

    plan = ProducerEventDecisionPolicy().plan(session=session, event=event)

    assert plan.status == ProducerDecisionStatus.ACTION_ONLY
    assert plan.reason == ProducerDecisionReason.TYPING_SETTLED
    assert plan.action is not None
    assert plan.action.kind == HumanActionKind.TYPING_PAUSE
    assert plan.trigger is None


def test_producer_decision_policy_captures_meaningful_plain_typing_milestone() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    session = ActiveCaptureSession(
        session_id="acs_typing_milestone",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=now,
        updated_at=now,
    )
    event = ProducerEventEnvelope(
        producer_event_id="pev_typing_milestone",
        session_id=session.session_id,
        event_kind=ProducerInputEventKind.TYPING_PAUSE,
        producer_kind="macos_capture",
        occurred_at=now,
        occurred_at_monotonic_ms=2_000,
        keyboard=KeyboardInputPayload(
            keyboard_event_kind=KeyboardEventKind.TYPING_PAUSE,
            input_class=KeyboardInputClass.TEXT_INPUT,
            capture_policy=KeyCapturePolicy.AGGREGATE_ONLY,
            typing_summary=TypingSessionSummary(event_count=14, character_count=13, submitted_by_enter=False),
        ),
    )

    plan = ProducerEventDecisionPolicy().plan(session=session, event=event)

    assert plan.status == ProducerDecisionStatus.ACCEPTED
    assert plan.reason == ProducerDecisionReason.TYPING_SETTLED
    assert plan.action is not None
    assert plan.action.kind == HumanActionKind.TYPING_PAUSE
    assert plan.trigger is not None
    assert plan.trigger.trigger_kind == KeyframeTriggerKind.TYPING_SETTLE
    assert plan.trigger.metadata["typing_char_count"] == 13


def test_producer_decision_policy_promotes_enter_submitted_typing_to_command_boundary() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    session = ActiveCaptureSession(
        session_id="acs_typing_submit",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=now,
        updated_at=now,
    )
    event = ProducerEventEnvelope(
        producer_event_id="pev_typing_submit",
        session_id=session.session_id,
        event_kind=ProducerInputEventKind.TYPING_PAUSE,
        producer_kind="macos_capture",
        occurred_at=now,
        occurred_at_monotonic_ms=2_000,
        keyboard=KeyboardInputPayload(
            keyboard_event_kind=KeyboardEventKind.TYPING_PAUSE,
            input_class=KeyboardInputClass.TEXT_INPUT,
            capture_policy=KeyCapturePolicy.AGGREGATE_ONLY,
            typing_summary=TypingSessionSummary(event_count=8, character_count=6, submitted_by_enter=True),
        ),
    )

    plan = ProducerEventDecisionPolicy().plan(session=session, event=event)

    assert plan.status == ProducerDecisionStatus.ACCEPTED
    assert plan.reason == ProducerDecisionReason.COMMAND_SUBMITTED
    assert plan.trigger is not None
    assert plan.trigger.trigger_kind == KeyframeTriggerKind.COMMAND_SUBMITTED


def test_producer_decision_policy_requires_observed_scope_for_scoped_keyboard_events() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    session = ActiveCaptureSession(
        session_id="acs_scoped_keyboard",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        scope=RecordingScope(
            kind=RecordingScopeKind.WINDOW,
            window_id="window_target",
            bounds=BoundingBox(x=0, y=0, width=800, height=600, coordinate_space=CoordinateSpace.MACOS_GLOBAL),
        ),
        created_at=now,
        updated_at=now,
    )
    event = ProducerEventEnvelope(
        producer_event_id="pev_hotkey_out_of_scope",
        session_id=session.session_id,
        event_kind=ProducerInputEventKind.HOTKEY,
        producer_kind="macos_capture",
        occurred_at=now,
        occurred_at_monotonic_ms=1_000,
        keyboard=KeyboardInputPayload(
            keyboard_event_kind=KeyboardEventKind.HOTKEY,
            input_class=KeyboardInputClass.SHORTCUT,
            capture_policy=KeyCapturePolicy.KEY_CHORD_ALLOWED,
            key_chord=KeyChord(
                physical_key_code=40,
                normalized_key_label="k",
                modifiers=(ModifierKey.COMMAND,),
                semantic=HotkeySemantic.OPEN_COMMAND,
            ),
            hotkey_semantic=HotkeySemantic.OPEN_COMMAND,
        ),
    )

    plan = ProducerEventDecisionPolicy().plan(session=session, event=event)

    assert plan.status == ProducerDecisionStatus.DROPPED
    assert plan.reason == ProducerDecisionReason.SCOPE_LOST


def test_producer_decision_policy_rejects_strict_events_without_observed_identity() -> None:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    session = ActiveCaptureSession(
        session_id="acs_scoped_keyboard_bounds_only",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        scope=RecordingScope(
            kind=RecordingScopeKind.REGION,
            display_id="main",
            selection_region=BoundingBox(
                x=0,
                y=0,
                width=800,
                height=600,
                coordinate_space=CoordinateSpace.MACOS_GLOBAL,
            ),
        ),
        created_at=now,
        updated_at=now,
    )
    event = ProducerEventEnvelope(
        producer_event_id="pev_hotkey_no_identity",
        session_id=session.session_id,
        event_kind=ProducerInputEventKind.HOTKEY,
        producer_kind="macos_capture",
        occurred_at=now,
        occurred_at_monotonic_ms=1_000,
        scope=RecordingScope(
            kind=RecordingScopeKind.REGION,
            display_id="main",
            selection_region=BoundingBox(
                x=0,
                y=0,
                width=800,
                height=600,
                coordinate_space=CoordinateSpace.MACOS_GLOBAL,
            ),
        ),
        keyboard=KeyboardInputPayload(
            keyboard_event_kind=KeyboardEventKind.HOTKEY,
            input_class=KeyboardInputClass.SHORTCUT,
            capture_policy=KeyCapturePolicy.KEY_CHORD_ALLOWED,
            key_chord=KeyChord(
                physical_key_code=40,
                normalized_key_label="k",
                modifiers=(ModifierKey.COMMAND,),
                semantic=HotkeySemantic.OPEN_COMMAND,
            ),
            hotkey_semantic=HotkeySemantic.OPEN_COMMAND,
        ),
    )

    plan = ProducerEventDecisionPolicy().plan(session=session, event=event)

    assert plan.status == ProducerDecisionStatus.DROPPED
    assert plan.reason == ProducerDecisionReason.SCOPE_LOST


def test_trigger_scheduler_counts_only_active_candidates_for_budget() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    session = ActiveCaptureSession(
        session_id="acs_trigger_budget",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
    )
    repositories.active_capture.save_session(session)
    scheduler = KeyframeTriggerScheduler(
        repository=repositories.active_capture,
        ids=IdFactory(),
        clock=Clock(),
        config=ActiveCapturePolicyConfig(max_pending_trigger_candidates=1),
    )

    first = scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
            occurred_at_monotonic_ms=1_000,
        ),
    )
    repositories.active_capture.save_trigger_candidate(
        first.model_copy(update={"status": KeyframeTriggerCandidateStatus.CAPTURED})
    )
    second = scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.SCROLL_STOP,
            occurred_at_monotonic_ms=2_000,
        ),
    )
    repositories.active_capture.save_trigger_candidate(
        second.model_copy(
            update={
                "status": KeyframeTriggerCandidateStatus.DEBOUNCED,
                "drop_reason": KeyframeDropReason.TOO_SOON,
            }
        )
    )
    third = scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.HOTKEY_SETTLE,
            occurred_at_monotonic_ms=4_000,
        ),
    )
    captured_first = repositories.active_capture.get_trigger_candidate(first.candidate_id)

    assert first.status == KeyframeTriggerCandidateStatus.ACCEPTED
    assert captured_first is not None
    assert captured_first.status == KeyframeTriggerCandidateStatus.CAPTURED
    assert second.status == KeyframeTriggerCandidateStatus.ACCEPTED
    assert third.status == KeyframeTriggerCandidateStatus.ACCEPTED


def test_trigger_scheduler_does_not_capture_terminal_dropped_candidate() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    session = ActiveCaptureSession(
        session_id="acs_trigger_terminal",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
    )
    repositories.active_capture.save_session(session)
    scheduler = KeyframeTriggerScheduler(
        repository=repositories.active_capture,
        ids=IdFactory(),
        clock=Clock(),
        config=ActiveCapturePolicyConfig(),
    )
    candidate = scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
            occurred_at_monotonic_ms=1_000,
        ),
    )

    scheduler.mark_dropped(
        candidate_id=candidate.candidate_id,
        reason=KeyframeDropReason.SCOPE_LOST,
        diagnostic="test terminal drop",
    )
    scheduler.mark_captured(candidate_id=candidate.candidate_id, keyframe_id="kf_late", event_id="evt_late")
    stored = repositories.active_capture.get_trigger_candidate(candidate.candidate_id)

    assert stored is not None
    assert stored.status == KeyframeTriggerCandidateStatus.DROPPED
    assert stored.keyframe_id is None
    assert stored.event_id is None


def test_trigger_scheduler_debounces_low_delta_and_required_bypass() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    session = ActiveCaptureSession(
        session_id="acs_trigger_policy",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
    )
    repositories.active_capture.save_session(session)
    scheduler = KeyframeTriggerScheduler(
        repository=repositories.active_capture,
        ids=IdFactory(),
        clock=Clock(),
        config=ActiveCapturePolicyConfig(min_keyframe_gap_ms=500, visual_diff_threshold=0.2),
    )

    first = scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
            occurred_at_monotonic_ms=1_000,
        ),
    )
    debounced = scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
            occurred_at_monotonic_ms=1_100,
        ),
    )
    low_delta = scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.VISUAL_CHANGE,
            occurred_at_monotonic_ms=2_000,
            diff=KeyframeDiffReport(visual_delta=0.05),
        ),
    )
    required = scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.USER_MARK,
            occurred_at_monotonic_ms=1_101,
        ),
    )

    assert first.status == KeyframeTriggerCandidateStatus.ACCEPTED
    assert debounced.status == KeyframeTriggerCandidateStatus.DEBOUNCED
    assert debounced.drop_reason == KeyframeDropReason.TOO_SOON
    assert low_delta.status == KeyframeTriggerCandidateStatus.DROPPED
    assert low_delta.drop_reason == KeyframeDropReason.LOW_DELTA
    assert required.status == KeyframeTriggerCandidateStatus.ACCEPTED
    assert required.priority == KeyframePriorityBand.REQUIRED


def test_trigger_scheduler_applies_quality_information_gain_policy() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    session = ActiveCaptureSession(
        session_id="acs_trigger_quality",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
    )
    repositories.active_capture.save_session(session)
    scheduler = KeyframeTriggerScheduler(
        repository=repositories.active_capture,
        ids=IdFactory(),
        clock=Clock(),
        config=ActiveCapturePolicyConfig(quality_min_information_gain=0.2),
    )

    low_information = scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.ACTION_RESULT_SETTLE,
            occurred_at_monotonic_ms=2_000,
            diff=KeyframeDiffReport(visual_delta=0.01, text_delta=0.01),
            quality=KeyframeQualityReport(confidence=0.1),
        ),
    )

    assert low_information.status == KeyframeTriggerCandidateStatus.DROPPED
    assert low_information.drop_reason == KeyframeDropReason.LOW_INFORMATION_GAIN


def test_trigger_scheduler_caps_result_frames_per_action() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    session = ActiveCaptureSession(
        session_id="acs_trigger_action_budget",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
    )
    repositories.active_capture.save_session(session)
    trace = HumanDemonstrationTrace(
        trace_id="hdt_budget",
        session_id=session.session_id,
        status=HumanDemonstrationTraceStatus.ACTIVE,
        action_count=1,
        started_at=session.created_at,
    )
    repositories.active_capture.append_human_action_graph(
        action=HumanActionEvent(
            action_id="act_budget",
            trace_id=trace.trace_id,
            session_id=session.session_id,
            sequence_index=0,
            kind=HumanActionKind.CLICK,
            occurred_at=session.created_at,
            coordinates=_action_coordinates(),
        ),
        links=(),
        observation=None,
        trace=trace,
    )
    scheduler = KeyframeTriggerScheduler(
        repository=repositories.active_capture,
        ids=IdFactory(),
        clock=Clock(),
        config=ActiveCapturePolicyConfig(max_result_frames_per_action=1),
    )

    first = scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
            occurred_at_monotonic_ms=2_000,
            action_id="act_budget",
            action_evidence_role=HumanActionEvidenceRole.AFTER_KEYFRAME,
            metadata={"timing_plan_signal_id": "pev_budget"},
        ),
    )
    second = scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.TARGET_RESOLUTION_PROBE,
            occurred_at_monotonic_ms=2_000,
            action_id="act_budget",
            action_evidence_role=HumanActionEvidenceRole.TARGET_EVIDENCE,
            metadata={"timing_plan_signal_id": "pev_budget"},
        ),
    )

    assert first.status == KeyframeTriggerCandidateStatus.ACCEPTED
    assert second.status == KeyframeTriggerCandidateStatus.DROPPED
    assert second.drop_reason == KeyframeDropReason.BUDGET_EXCEEDED


def test_keyframe_recorder_submits_target_probe_after_low_confidence_resolution() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    session = ActiveCaptureSession(
        session_id="acs_test",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
    )
    _seed_event_and_run(repositories, session.created_at)
    repositories.active_capture.save_session(session)
    trace = HumanDemonstrationTrace(
        trace_id="hdt_probe",
        session_id=session.session_id,
        status=HumanDemonstrationTraceStatus.ACTIVE,
        action_count=1,
        started_at=session.created_at,
    )
    repositories.active_capture.append_human_action_graph(
        action=HumanActionEvent(
            action_id="act_probe",
            trace_id=trace.trace_id,
            session_id=session.session_id,
            sequence_index=0,
            kind=HumanActionKind.CLICK,
            occurred_at=session.created_at,
            coordinates=_action_coordinates(),
        ),
        links=(),
        observation=None,
        trace=trace,
    )
    config = ActiveCapturePolicyConfig()
    scheduler = KeyframeTriggerScheduler(
        repository=repositories.active_capture,
        ids=IdFactory(),
        clock=Clock(),
        config=config,
    )
    recorder = KeyframeRecorder(
        repository=repositories.active_capture,
        ids=IdFactory(),
        clock=Clock(),
        config=config,
        keyframe_policy=KeyframeCapturePolicy(config=config, ids=IdFactory(), clock=Clock()),
        trigger_scheduler=scheduler,
        scope_matcher=RecordingScopeMatcher(),
        access_checker=lambda _session, _attempt: True,
    )

    recorder.target_probe_backfill.submit_if_needed(
        session=session,
        action_id="act_probe",
        keyframe=_keyframe("kf_probe_base", sequence_index=0, captured_at_monotonic_ms=2_000),
        needs_review=True,
    )

    candidates = repositories.active_capture.list_trigger_candidates_for_session(session.session_id)
    assert len(candidates) == 1
    assert candidates[0].trigger_kind == KeyframeTriggerKind.TARGET_RESOLUTION_PROBE
    assert candidates[0].action_id == "act_probe"
    assert candidates[0].action_evidence_role == HumanActionEvidenceRole.TARGET_EVIDENCE
    assert candidates[0].metadata["settle_live_polling_state"] == "pending"
    assert candidates[0].metadata["settle_timeout_capture_enabled"] is False


def test_trigger_scheduler_rejects_cross_session_action_binding() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    session_a = ActiveCaptureSession(
        session_id="acs_a",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=now,
        updated_at=now,
    )
    session_b = session_a.model_copy(update={"session_id": "acs_b"})
    repositories.active_capture.save_session(session_a)
    repositories.active_capture.save_session(session_b)
    trace = HumanDemonstrationTrace(
        trace_id="hdt_a",
        session_id=session_a.session_id,
        status=HumanDemonstrationTraceStatus.ACTIVE,
        action_count=1,
        started_at=now,
    )
    repositories.active_capture.append_human_action_graph(
        action=HumanActionEvent(
            action_id="act_a",
            trace_id=trace.trace_id,
            session_id=session_a.session_id,
            sequence_index=0,
            kind=HumanActionKind.CLICK,
            occurred_at=now,
            coordinates=_action_coordinates(),
        ),
        links=(),
        observation=None,
        trace=trace,
    )
    scheduler = KeyframeTriggerScheduler(
        repository=repositories.active_capture,
        ids=IdFactory(),
        clock=Clock(),
        config=ActiveCapturePolicyConfig(),
    )

    with pytest.raises(ValueError, match="action_id does not belong"):
        scheduler.submit(
            session=session_b,
            command=SubmitKeyframeTriggerCommand(
                trigger_kind=KeyframeTriggerKind.TARGET_RESOLUTION_PROBE,
                action_id="act_a",
                action_evidence_role=HumanActionEvidenceRole.TARGET_EVIDENCE,
            ),
        )


def test_trigger_scheduler_required_boundary_bypasses_pending_budget() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    session = ActiveCaptureSession(
        session_id="acs_trigger_required_budget",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
    )
    repositories.active_capture.save_session(session)
    scheduler = KeyframeTriggerScheduler(
        repository=repositories.active_capture,
        ids=IdFactory(),
        clock=Clock(),
        config=ActiveCapturePolicyConfig(max_pending_trigger_candidates=1),
    )

    normal = scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.CLICK_SETTLE,
            occurred_at_monotonic_ms=1_000,
        ),
    )
    over_budget = scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.SCROLL_STOP,
            occurred_at_monotonic_ms=2_000,
        ),
    )
    required_final = scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.RECORDING_STOP,
            occurred_at_monotonic_ms=3_000,
        ),
    )

    assert normal.status == KeyframeTriggerCandidateStatus.ACCEPTED
    assert over_budget.status == KeyframeTriggerCandidateStatus.DROPPED
    assert over_budget.drop_reason == KeyframeDropReason.BUDGET_EXCEEDED
    assert required_final.status == KeyframeTriggerCandidateStatus.ACCEPTED
    assert required_final.priority == KeyframePriorityBand.REQUIRED
    assert required_final.keep_reason == KeyframeKeepReason.REQUIRED_BOUNDARY


def test_trigger_scheduler_prepare_candidate_uses_batch_local_existing_candidates() -> None:
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    session = ActiveCaptureSession(
        session_id="acs_trigger_batch_policy",
        mode=ActiveCaptureMode.RECORDING_SESSION,
        status=ActiveCaptureStatus.RECORDING,
        created_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
        updated_at=datetime(2026, 5, 30, 12, 0, tzinfo=UTC),
    )
    scheduler = KeyframeTriggerScheduler(
        repository=repositories.active_capture,
        ids=IdFactory(),
        clock=Clock(),
        config=ActiveCapturePolicyConfig(min_keyframe_gap_ms=500),
    )

    first = scheduler.prepare_candidate(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.HOTKEY_SETTLE,
            occurred_at_monotonic_ms=1_000,
        ),
        existing=(),
    )
    second = scheduler.prepare_candidate(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=KeyframeTriggerKind.HOTKEY_SETTLE,
            occurred_at_monotonic_ms=1_100,
        ),
        existing=(first,),
    )

    assert first.status == KeyframeTriggerCandidateStatus.ACCEPTED
    assert second.status == KeyframeTriggerCandidateStatus.DEBOUNCED
    assert second.drop_reason == KeyframeDropReason.TOO_SOON


class _FakeEventLookup(EventLookupPort):
    def __init__(self, event: ContextEvent) -> None:
        self.events = {event.event_id: event}

    def get_event(
        self,
        event_id: str,
        *,
        actor: ActorRef | None = None,
        workspace_id: str | None = None,
    ) -> ContextEvent | None:
        return self.events.get(event_id)

    def get_events(
        self,
        event_ids: tuple[str, ...],
        *,
        actor: ActorRef | None = None,
        workspace_id: str | None = None,
    ) -> tuple[ContextEvent, ...]:
        return tuple(event for event_id in event_ids if (event := self.events.get(event_id)) is not None)


class _FakeEventInspector(EventEvidenceInspectPort):
    def __init__(self, captured_at: datetime) -> None:
        self.captured_at = captured_at

    def inspect_event(
        self,
        *,
        event: ContextEvent,
        actor: ActorRef,
        purpose: str,
        requested_sections: tuple[EventInspectSection, ...],
    ) -> EventInspectView:
        return EventInspectView(
            event_id=event.event_id,
            captured_at=self.captured_at,
            source=SearchResultSource(
                app_name=event.source_binding.source_ref.app_name,
                title=event.source_binding.source_ref.title,
                origin=event.source_binding.source_ref.origin,
                sanitized_url=event.source_binding.source_ref.url,
            ),
            readable_evidence=(
                ReadableEvidenceView(
                    artifact_id="art_text",
                    artifact_type=ArtifactType.A11Y_SELECTION_TEXT,
                    role=ArtifactRole.SELECTION_TEXT,
                    evidence_id="ev_text",
                    disclosure_class=DisclosureClass.SELECTION_BOUND_TEXT,
                    text="safe selected text",
                    confidence=0.95,
                ),
            ),
            disclosure_decision=DisclosureDecision(
                decision_id="dsc_test",
                status=DisclosureDecisionStatus.ALLOWED,
                view=DisclosureView.EVENT_INSPECT,
                profile_key="unit.test",
                resource_type="event",
                resource_id=event.event_id,
            ),
        )


def _event(now: datetime) -> ContextEvent:
    return ContextEvent(
        event_id="evt_test",
        event_type="screen.region.captured",
        trigger=TriggerEnvelope(
            trigger_id="trg_test",
            trigger_type=TriggerType.MANUAL_OS_REGION_HOTKEY,
            capture_strategy=CaptureStrategy.OS_REGION,
            actor=ActorRef(actor_id="actor_test"),
            occurred_at=now,
        ),
        source_binding=SourceBinding(
            binding_id="src_test",
            source_ref=SourceRef(
                source_type=SourceType.WEB,
                title="ACME Dashboard",
                app_name="Chrome",
                url="https://example.test/acme",
                origin="https://example.test",
            ),
            confidence=1.0,
            resolved_at=now,
        ),
        status=EventStatus.AGENT_READY,
        intent_text=None,
        created_at=now,
        updated_at=now,
    )


def _keyframe(
    keyframe_id: str,
    *,
    sequence_index: int,
    captured_at: datetime | None = None,
    captured_at_monotonic_ms: int | None = None,
    media_time_ms: int | None = None,
) -> ContextKeyframe:
    now = captured_at or datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    return ContextKeyframe(
        keyframe_id=keyframe_id,
        session_id="acs_test",
        event_id="evt_test",
        capture_run_id="run_test",
        role=KeyframeRole.ANCHOR,
        trigger_kind=KeyframeTriggerKind.MANUAL_SCREENSHOT,
        keep_reason=KeyframeKeepReason.USER_ANCHOR,
        captured_at=now,
        sequence_index=sequence_index,
        captured_at_monotonic_ms=captured_at_monotonic_ms,
        media_time_ms=media_time_ms,
    )


def _action_coordinates() -> ActionCoordinates:
    return ActionCoordinates(
        screen_abs=ActionPoint(x=120.0, y=240.0, coordinate_space=CoordinateSpace.MACOS_GLOBAL, display_id="main"),
        screenshot_rel=ActionPoint(x=20.0, y=40.0, coordinate_space=CoordinateSpace.ARTIFACT_PX),
        scope_rel=ActionPoint(x=10.0, y=30.0, coordinate_space=CoordinateSpace.WINDOW_PX),
    )


def _candidate(
    *,
    existing_keyframe_count: int,
    role: KeyframeRole = KeyframeRole.ANCHOR,
    trigger_kind: KeyframeTriggerKind = KeyframeTriggerKind.MANUAL_SCREENSHOT,
) -> KeyframeCandidate:
    return KeyframeCandidate(
        session_id="acs_test",
        event_id="evt_test",
        role=role,
        trigger_kind=trigger_kind,
        existing_keyframe_count=existing_keyframe_count,
        candidate_id="candidate_test",
    )


def _scope_attempt(
    *,
    selected_region: BoundingBox,
    window_hint: WindowHint | None,
    display_id: str = "display_main",
    scale_factor: float = 2.0,
) -> CaptureAttemptRequest:
    now = datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    return CaptureAttemptRequest(
        trigger=TriggerEnvelope(
            trigger_id="trg_scope",
            trigger_type=TriggerType.MANUAL_OS_REGION_HOTKEY,
            capture_strategy=CaptureStrategy.OS_REGION,
            actor=ActorRef(actor_id="test-cli", display_name="Test CLI"),
            occurred_at=now,
            selection=selected_region,
        ),
        selection_geometry=SelectionGeometry(
            selected_region=selected_region,
            display=DisplayGeometry(
                display_id=display_id,
                frame=BoundingBox(x=0, y=0, width=1440, height=900, coordinate_space=CoordinateSpace.MACOS_GLOBAL),
                scale_factor=scale_factor,
            ),
        ),
        window_hints=(window_hint,) if window_hint is not None else (),
        workspace=WorkspaceSelection(),
        actor=ActorRef(actor_id="test-cli", display_name="Test CLI"),
        staged_artifact=StagedArtifactRef(
            local_path="/tmp/workrecorder-test.png",
            artifact_type=ArtifactType.SCREENSHOT,
            content_type="image/png",
            filename="workrecorder-test.png",
        ),
    )


def _empty_capture_envelope(event: ContextEvent) -> EventCaptureEnvelope:
    return EventCaptureEnvelope(
        capture_run_id="run_test",
        event_id=event.event_id,
        event_type=EventType.SCREEN_REGION_CAPTURED,
        trigger=event.trigger,
        selection_geometry=SelectionGeometry(
            selected_region=BoundingBox(x=0, y=0, width=800, height=600),
            display=DisplayGeometry(
                display_id="display_main",
                frame=BoundingBox(x=0, y=0, width=1440, height=900),
                scale_factor=2.0,
            ),
        ),
        route_plan=ProviderRoutePlan(trigger_id=event.trigger.trigger_id),
        index_manifest=IndexManifest(event_id=event.event_id),
        policy_snapshot=PolicySnapshot(create_event_decision_id="pol_test"),
        created_at=event.created_at,
        updated_at=event.updated_at,
    )


def _write_mp4(path: Path, *, duration_ms: int) -> None:
    def box(kind: bytes, payload: bytes) -> bytes:
        return (len(payload) + 8).to_bytes(4, byteorder="big") + kind + payload

    ftyp = box(b"ftyp", b"mp42\x00\x00\x00\x00mp42isom")
    mvhd_payload = (
        b"\x00\x00\x00\x00"
        + (0).to_bytes(4, byteorder="big")
        + (0).to_bytes(4, byteorder="big")
        + (1000).to_bytes(4, byteorder="big")
        + duration_ms.to_bytes(4, byteorder="big")
    )
    path.write_bytes(ftyp + box(b"moov", box(b"mvhd", mvhd_payload)) + box(b"mdat", b"test-video"))


def _seed_event_and_run(repositories: RepositoryContainer, now: datetime) -> None:
    _seed_event_and_run_ids(
        repositories,
        now,
        event_id="evt_test",
        trigger_id="trg_test",
        capture_run_id="run_test",
    )


def _seed_event_and_run_ids(
    repositories: RepositoryContainer,
    now: datetime,
    *,
    event_id: str,
    trigger_id: str,
    capture_run_id: str,
) -> None:
    with repositories.database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO context_events(event_id, status, payload, created_at, updated_at)
            VALUES (?, 'agent_ready', '{}', ?, ?)
            """,
            (event_id, now.isoformat(), now.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO capture_attempts(
              trigger_id, actor_id, workspace_id, status, occurred_at, selection_payload, payload, created_at
            )
            VALUES (?, 'actor_test', 'auto', 'accepted', ?, '{}', '{}', ?)
            """,
            (trigger_id, now.isoformat(), now.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO capture_runs(
              capture_run_id, trigger_id, event_id, status, envelope_payload, created_at, updated_at
            )
            VALUES (?, ?, ?, 'agent_ready', '{}', ?, ?)
            """,
            (capture_run_id, trigger_id, event_id, now.isoformat(), now.isoformat()),
        )


def _seed_artifact_and_evidence(
    repositories: RepositoryContainer,
    now: datetime,
    *,
    artifact_id: str,
    evidence_id: str,
    artifact_type: str = "screenshot",
    evidence_kind: str = "screenshot",
    role: str = "screenshot",
) -> None:
    with repositories.database.transaction() as connection:
        connection.execute(
            """
            INSERT INTO artifacts(artifact_id, event_id, artifact_type, payload, created_at)
            VALUES (?, 'evt_test', ?, '{}', ?)
            """,
            (artifact_id, artifact_type, now.isoformat()),
        )
        connection.execute(
            """
            INSERT INTO evidence_records(
              evidence_id, event_id, capture_run_id, phase, evidence_kind, artifact_id,
              artifact_type, role, provider_key, source_uri, observed_at, captured_at,
              ingested_at, sensitivity, trust_state, ingest_state, redaction_state,
              indexable, payload
            )
            VALUES (?, 'evt_test', 'run_test', 'capture', ?, ?, ?, ?, 'system.capture',
                    'workrecorder://test', ?, ?, ?, 'low', 'trusted', 'available',
                    'unredacted', 1, '{}')
            """,
            (
                evidence_id,
                evidence_kind,
                artifact_id,
                artifact_type,
                role,
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
