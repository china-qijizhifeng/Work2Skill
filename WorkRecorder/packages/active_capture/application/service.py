"""Application services for the active capture backend."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime

from packages.active_capture.application.demonstration_trace import HumanDemonstrationService
from packages.active_capture.application.input_events.ingest import ProducerEventIngestService
from packages.active_capture.application.input_events.skill_projection import SkillDistillationInputProjector
from packages.active_capture.application.keyframe_recorder import KeyframeRecorder
from packages.active_capture.application.keyframe_triggers import KeyframeTriggerScheduler
from packages.active_capture.application.keyframe_views import inspect_summaries_for_event
from packages.active_capture.application.recording_controls import RecordingControlService
from packages.active_capture.application.recording_projection import RecordingPublicProjector
from packages.active_capture.application.service_helpers import is_terminal_status
from packages.active_capture.application.session_completion import SessionCompletionService
from packages.active_capture.application.session_views import (
    build_session_view,
    filter_session_view_for_visible_events,
)
from packages.active_capture.application.storyboard import RecordingStoryboardService
from packages.active_capture.application.trigger_failure import report_keyframe_capture_failure
from packages.active_capture.application.view_projector import ActiveCaptureViewProjector
from packages.active_capture.application.vm_a11y_probe import VMAccessibilityProbePort
from packages.active_capture.application.vm_coordinate_mapping import VMDisplayGeometry
from packages.active_capture.click_targets.adapters.candidate_providers import (
    A11yTargetCandidateProvider,
    CoordinateFallbackProvider,
    EvidencePayloadReader,
    VisualOcrTargetCandidateProvider,
    WebSelectionMapTargetCandidateProvider,
)
from packages.active_capture.click_targets.application import ClickTargetResolutionService
from packages.active_capture.click_targets.domain.label_policy import ClickTargetLabelPolicy
from packages.active_capture.domain.keyframe_policy import KeyframeCandidate, KeyframeCapturePolicy
from packages.active_capture.domain.scope_matcher import RecordingScopeMatcher
from packages.active_capture.domain.session_completion_policy import TerminalSessionQualityPolicy
from packages.active_capture.domain.session_state import ActiveCaptureSessionStateMachine
from packages.active_capture.domain.timeline_alignment import RecordingTimelineManifestBuilder
from packages.active_capture.keyframes.application.orchestrator import KeyframeTimingOrchestrator
from packages.active_capture.keyframes.polling.application import AdaptiveSettlePollingService
from packages.active_capture.ports.video_artifact import PreparedVideoArtifact, VideoArtifactPort
from packages.active_capture.repositories.protocol import ActiveCaptureRepository
from packages.artifacts.vault import ArtifactVaultError, ArtifactVaultTransientError
from packages.contracts import (
    ActiveCaptureBinding,
    ActiveCaptureControlTriggerSubmission,
    ActiveCaptureMode,
    ActiveCapturePolicyConfig,
    ActiveCaptureProjectionConfig,
    ActiveCapturePublicView,
    ActiveCaptureSession,
    ActiveCaptureSessionSource,
    ActiveCaptureSessionView,
    ActiveCaptureStatus,
    ActiveCaptureWarning,
    ActiveCaptureWarningCode,
    ApplyRecordingControlCommand,
    Artifact,
    AttachRecordingSegmentCommand,
    CaptureAttemptRequest,
    ClickTargetResolverConfig,
    CompleteActiveCaptureSessionCommand,
    ContextEvent,
    ContextKeyframe,
    CreateActiveCaptureSessionCommand,
    EventCaptureEnvelope,
    EvidenceKind,
    EvidenceRecord,
    HumanActionEvent,
    HumanActionPublicSummary,
    KeyframeBundleStatus,
    KeyframeCaptureInstruction,
    KeyframeContextBundle,
    KeyframeEvidenceLink,
    KeyframeInspectSummary,
    KeyframeKeepReason,
    KeyframeQualityReport,
    KeyframeRole,
    KeyframeTimingConfig,
    KeyframeTriggerCandidate,
    KeyframeTriggerCandidateStatus,
    KeyframeTriggerKind,
    KeyframeTriggerPublicSummary,
    KeyframeTriggerSubmission,
    PendingKeyframeCaptureInstructionsResponse,
    PollKeyframeCaptureInstructionsCommand,
    ProducerEventIngestBatchResult,
    RecordHumanActionCommand,
    RecordingControlEvent,
    RecordingControlKind,
    RecordingControlPublicSummary,
    RecordingPauseInterval,
    RecordingPausePublicSummary,
    RecordingSegmentManifest,
    RecordingSegmentManifestPublicView,
    RecordingSegmentState,
    RecordingStoryboardProjection,
    RecordingTimelineManifest,
    RecordingVideoSegmentPublicSummary,
    RecordingVideoSegmentRef,
    RecordProducerInputBatchCommand,
    ReportKeyframeCaptureFailureCommand,
    SearchMatchReason,
    SearchResultCard,
    SearchResultSource,
    SkillDistillationInputView,
    StagedVideoArtifactRef,
    SubmitKeyframeTriggerCommand,
    VideoArtifactFailureReason,
    VideoArtifactPublicSummary,
    VideoArtifactRef,
    VideoArtifactState,
    WorkspaceSelection,
)
from packages.contracts.common import JsonScalar
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

logger = logging.getLogger(__name__)


def _submit_recording_control_keyframe_boundary(
    *,
    trigger_scheduler: KeyframeTriggerScheduler,
    session: ActiveCaptureSession,
    command: ApplyRecordingControlCommand,
) -> KeyframeTriggerCandidate | None:
    """Submit the typed keyframe boundary implied by one recording control."""

    mapping: dict[RecordingControlKind, tuple[KeyframeTriggerKind, KeyframeRole]] = {
        RecordingControlKind.USER_MARK: (KeyframeTriggerKind.USER_MARK, KeyframeRole.USER_MARK),
        RecordingControlKind.PAUSE: (KeyframeTriggerKind.PAUSE_BOUNDARY, KeyframeRole.PAUSE_BOUNDARY),
        RecordingControlKind.RESUME: (KeyframeTriggerKind.RESUME_BOUNDARY, KeyframeRole.RESUME_BOUNDARY),
    }
    boundary = mapping.get(command.kind)
    if boundary is None:
        return None
    trigger_kind, role = boundary
    return trigger_scheduler.submit(
        session=session,
        command=SubmitKeyframeTriggerCommand(
            trigger_kind=trigger_kind,
            role=role,
            occurred_at_monotonic_ms=command.occurred_at_monotonic_ms,
            metadata=command.metadata,
        ),
    )


def _build_producer_event_ingest_service(
    *,
    repository: ActiveCaptureRepository,
    demonstrations: HumanDemonstrationService,
    triggers: KeyframeTriggerScheduler,
    projector: RecordingPublicProjector,
    ids: IdFactory,
    clock: Clock,
    config: ActiveCapturePolicyConfig,
    vm_a11y_probe: VMAccessibilityProbePort | None = None,
    vm_display: VMDisplayGeometry | None = None,
) -> ProducerEventIngestService:
    timing_config = KeyframeTimingConfig.from_active_capture_policy(config)
    return ProducerEventIngestService(
        repository=repository,
        demonstrations=demonstrations,
        triggers=triggers,
        projector=projector,
        ids=ids,
        clock=clock,
        config=config,
        timing_orchestrator=KeyframeTimingOrchestrator(
            repository=repository,
            ids=ids,
            clock=clock,
            config=timing_config,
        ),
        vm_a11y_probe=vm_a11y_probe,
        vm_display=vm_display,
    )


def _build_adaptive_settle_polling_service(
    *,
    repository: ActiveCaptureRepository,
    ids: IdFactory,
    clock: Clock,
    config: ActiveCapturePolicyConfig,
    projector: RecordingPublicProjector,
) -> AdaptiveSettlePollingService:
    return AdaptiveSettlePollingService(
        repository=repository,
        ids=ids,
        clock=clock,
        config=KeyframeTimingConfig.from_active_capture_policy(config),
        projector=projector,
    )


class ActiveCaptureService:
    """Orchestrate sessions, keyframes, video artifact refs, and timelines."""

    def __init__(
        self,
        *,
        repository: ActiveCaptureRepository,
        ids: IdFactory,
        clock: Clock,
        config: ActiveCapturePolicyConfig | None = None,
        projection_config: ActiveCaptureProjectionConfig | None = None,
        video_artifacts: VideoArtifactPort | None = None,
        artifact_vault: object | None = None,
        vm_a11y_probe: VMAccessibilityProbePort | None = None,
        vm_display: VMDisplayGeometry | None = None,
    ) -> None:
        self.repository = repository
        self.ids = ids
        self.clock = clock
        self.config = config or ActiveCapturePolicyConfig()
        self.projection_config = projection_config or ActiveCaptureProjectionConfig()
        self.keyframe_policy = KeyframeCapturePolicy(config=self.config, ids=ids, clock=clock)
        self.state_machine = ActiveCaptureSessionStateMachine()
        self.scope_matcher = RecordingScopeMatcher()
        self.completion_policy = TerminalSessionQualityPolicy(config=self.config)
        self.timeline_builder = RecordingTimelineManifestBuilder(ids=ids, clock=clock)
        self.view_projector = ActiveCaptureViewProjector(repository=repository)
        self.recording_projector = RecordingPublicProjector()
        self.vm_a11y_probe = vm_a11y_probe
        self.vm_display = vm_display
        self.recording_controls = RecordingControlService(
            repository=repository,
            ids=ids,
            clock=clock,
            config=self.config,
            state_machine=self.state_machine,
        )
        self.trigger_scheduler = KeyframeTriggerScheduler(
            repository=repository,
            ids=ids,
            clock=clock,
            config=self.config,
        )
        self.click_target_resolver = self._click_target_resolver(artifact_vault=artifact_vault)
        self.keyframe_recorder = KeyframeRecorder(
            repository=repository,
            ids=ids,
            clock=clock,
            config=self.config,
            keyframe_policy=self.keyframe_policy,
            trigger_scheduler=self.trigger_scheduler,
            scope_matcher=self.scope_matcher,
            access_checker=self._capture_attempt_can_access_session,
            click_target_resolver=self.click_target_resolver,
        )
        self.demonstrations = HumanDemonstrationService(
            repository=repository,
            ids=ids,
            clock=clock,
            config=self.config,
        )
        self.producer_events = _build_producer_event_ingest_service(
            repository=repository,
            demonstrations=self.demonstrations,
            triggers=self.trigger_scheduler,
            projector=self.recording_projector,
            ids=ids,
            clock=clock,
            config=self.config,
            vm_a11y_probe=self.vm_a11y_probe,
            vm_display=self.vm_display,
        )
        self.adaptive_settle_polling = _build_adaptive_settle_polling_service(
            repository=repository,
            ids=ids,
            clock=clock,
            config=self.config,
            projector=self.recording_projector,
        )
        self.storyboards = RecordingStoryboardService(
            repository=repository,
            clock=clock,
            projection_config=self.projection_config,
        )
        self.skill_distillation_inputs = SkillDistillationInputProjector(
            repository=repository,
            clock=clock,
            projection_config=self.projection_config,
        )
        self.video_artifacts = video_artifacts
        self.session_completion = SessionCompletionService(
            repository=repository,
            clock=clock,
            ids=ids,
            state_machine=self.state_machine,
            recording_controls=self.recording_controls,
            timeline_builder=self.timeline_builder,
            completion_policy=self.completion_policy,
            keyframe_recorder=self.keyframe_recorder,
            demonstrations=self.demonstrations,
            video_artifacts=video_artifacts,
            timeline_alignment_tolerance_ms=self.config.timeline_alignment_tolerance_ms,
        )

    def _click_target_resolver(self, *, artifact_vault: object | None) -> ClickTargetResolutionService:
        target_config = ClickTargetResolverConfig(
            enabled=self.config.click_target_resolver_enabled,
            high_confidence_threshold=self.config.click_target_high_confidence_threshold,
            review_confidence_threshold=self.config.click_target_review_confidence_threshold,
            max_candidates=self.config.click_target_max_candidates,
            max_safe_label_chars=self.config.click_target_max_safe_label_chars,
            policy_version=self.config.policy_version,
        )
        payload_reader = EvidencePayloadReader(vault=artifact_vault)  # type: ignore[arg-type]
        label_policy = ClickTargetLabelPolicy(max_chars=target_config.max_safe_label_chars)
        confidence_bands = {
            "high": target_config.high_confidence_threshold,
            "review": target_config.review_confidence_threshold,
        }
        providers = (
            A11yTargetCandidateProvider(
                label_policy=label_policy,
                payload_reader=payload_reader,
                confidence_bands=confidence_bands,
            ),
            WebSelectionMapTargetCandidateProvider(
                label_policy=label_policy,
                payload_reader=payload_reader,
                confidence_bands=confidence_bands,
            ),
            VisualOcrTargetCandidateProvider(
                label_policy=label_policy,
                payload_reader=payload_reader,
                confidence_bands=confidence_bands,
            ),
            CoordinateFallbackProvider(
                label_policy=label_policy,
                payload_reader=payload_reader,
                confidence_bands=confidence_bands,
            ),
        )
        return ClickTargetResolutionService(
            repository=self.repository,
            providers=providers,
            ids=self.ids,
            clock=self.clock,
            config=target_config,
        )

    def create_session(
        self,
        *,
        command: CreateActiveCaptureSessionCommand,
        actor_id: str | None,
        actor_display_name: str | None,
    ) -> ActiveCaptureSessionView:
        """Create a backend session without exposing any UI surface."""

        from packages.contracts import ActorRef

        if not self.config.enabled:
            raise ValueError("active capture is disabled")
        now = self.clock.now()
        session = ActiveCaptureSession(
            session_id=self.ids.new("acs"),
            mode=command.mode,
            status=ActiveCaptureStatus.CREATED,
            actor=ActorRef(actor_id=actor_id, display_name=actor_display_name) if actor_id is not None else None,
            workspace_id=command.workspace_id,
            scope=command.scope,
            created_at=now,
            updated_at=now,
            policy_version=self.config.policy_version,
            metadata=command.metadata | {"source": ActiveCaptureSessionSource.HEADLESS_BACKEND.value},
        )
        if command.mode == ActiveCaptureMode.RECORDING_SESSION and command.start_recording:
            session = self.state_machine.transition(session, ActiveCaptureStatus.RECORDING).model_copy(
                update={"started_at": now, "updated_at": now}
            )
        saved = self.repository.save_session(session)
        if saved.mode == ActiveCaptureMode.RECORDING_SESSION and saved.status == ActiveCaptureStatus.RECORDING:
            self.recording_controls.initialize_recording_session(saved)
        logger.info(
            "active capture session created",
            extra={"session_id": saved.session_id, "mode": saved.mode.value, "status": saved.status.value},
        )
        return self.view_session(saved.session_id)

    def apply_recording_control(
        self,
        *,
        session_id: str,
        command: ApplyRecordingControlCommand,
    ) -> ActiveCaptureSessionView:
        """Apply pause/resume/mark/stop controls without touching UI code."""

        session = self._require_session(session_id)
        updated = self.recording_controls.apply_control(session=session, command=command)
        candidate = _submit_recording_control_keyframe_boundary(
            trigger_scheduler=self.trigger_scheduler,
            session=updated,
            command=command,
        )
        view = self.view_session(session_id)
        if candidate is None:
            return view
        trigger = ActiveCaptureControlTriggerSubmission.model_validate(
            self.recording_projector.to_trigger_submission(candidate).model_dump(mode="python")
        )
        return view.model_copy(update={"control_trigger": trigger})

    def attach_recording_segment(
        self,
        *,
        session_id: str,
        command: AttachRecordingSegmentCommand,
    ) -> RecordingVideoSegmentRef:
        """Attach a trusted native recording segment update."""

        session = self._require_session(session_id)
        segment = self.recording_controls.attach_segment(session=session, command=command)
        prepared_video = self._prepare_segment_video_if_present(session=session, segment=segment, command=command)
        if prepared_video is None:
            return self.repository.save_recording_segment_graph(
                segment=segment.model_copy(update={"staged_video": None})
            )
        next_state = segment.state
        if prepared_video.ref.state == VideoArtifactState.AVAILABLE:
            next_state = RecordingSegmentState.AVAILABLE
        if prepared_video.ref.state == VideoArtifactState.FAILED:
            next_state = RecordingSegmentState.FAILED
        try:
            saved = self.repository.save_recording_segment_graph(
                segment=segment.model_copy(
                    update={"video": prepared_video.ref, "state": next_state, "staged_video": None}
                ),
                artifacts=(prepared_video.artifact,) if prepared_video.artifact is not None else (),
            )
        except Exception:
            logger.exception(
                "active capture segment graph write failed; discarding prepared recording video",
                extra={"session_id": session_id, "segment_id": segment.segment_id},
            )
            self._discard_prepared_video(prepared_video)
            raise
        if (
            command.staged_video is not None
            and prepared_video.artifact is not None
            and self.video_artifacts is not None
        ):
            self._discard_committed_staged_video(command.staged_video)
        return saved

    def submit_keyframe_trigger(
        self,
        *,
        session_id: str,
        command: SubmitKeyframeTriggerCommand,
    ) -> KeyframeTriggerSubmission:
        """Submit an event-driven keyframe trigger candidate."""

        session = self._require_session(session_id)
        candidate = self.trigger_scheduler.submit(session=session, command=command)
        return KeyframeTriggerSubmission(
            candidate=self.recording_projector.to_public_trigger_candidate(candidate),
            capture_instruction=self.recording_projector.capture_instruction_for_candidate(candidate),
        )

    def record_human_action(
        self,
        *,
        session_id: str,
        command: RecordHumanActionCommand,
    ) -> HumanActionPublicSummary:
        """Append a low-sensitive action event to the session demonstration trace."""

        session = self._require_session(session_id)
        action = self.demonstrations.record_action(session=session, command=command)
        return self.recording_projector.to_public_human_action(action)

    def record_producer_events(
        self,
        *,
        session_id: str,
        command: RecordProducerInputBatchCommand,
    ) -> ProducerEventIngestBatchResult:
        """Ingest trusted native input events and derive actions/triggers."""

        return self.producer_events.ingest_batch(session=self._require_session(session_id), command=command)

    def poll_pending_capture_instructions(
        self,
        *,
        session_id: str,
        command: PollKeyframeCaptureInstructionsCommand,
    ) -> PendingKeyframeCaptureInstructionsResponse:
        """Poll adaptive-settle candidates and return finalized capture instructions."""

        return self.adaptive_settle_polling.poll_session(session=self._require_session(session_id), command=command)

    def report_keyframe_capture_failure(
        self,
        *,
        session_id: str,
        command: ReportKeyframeCaptureFailureCommand,
    ) -> KeyframeTriggerPublicSummary:
        """Close a capture instruction that native code could not commit."""

        return report_keyframe_capture_failure(
            repository=self.repository,
            trigger_scheduler=self.trigger_scheduler,
            projector=self.recording_projector,
            session=self._require_session(session_id),
            command=command,
        )

    def storyboard_for_session(self, session_id: str) -> RecordingStoryboardProjection:
        """Build a safe recording storyboard projection."""

        return self.storyboards.build(self._require_session(session_id))

    def recording_session_cards(
        self,
        *,
        limit: int | None = None,
        include: Callable[[ActiveCaptureSession], bool] | None = None,
    ) -> tuple[SearchResultCard, ...]:
        """Return lightweight safe cards for recording-library listing."""

        sessions = self.repository.list_sessions(
            mode=ActiveCaptureMode.RECORDING_SESSION.value,
            limit=None if include is not None else limit,
            require_primary_event=True,
        )
        cards: list[SearchResultCard] = []
        for session in sessions:
            if session.primary_event_id is None:
                continue
            if include is not None and not include(session):
                continue
            cards.append(self._recording_session_card(session))
            if limit is not None and len(cards) >= limit:
                break
        return tuple(cards)

    def _recording_session_card(self, session: ActiveCaptureSession) -> SearchResultCard:
        scope = session.scope
        title = _recording_card_title(session)
        app_name = scope.app_name if scope is not None and scope.app_name else "本机录制"
        hidden_artifacts = ["active_capture_raw_materials", "active_capture_recording"]
        if self._session_has_available_video(session.session_id):
            hidden_artifacts.append("recording_video")
        return SearchResultCard(
            event_id=session.primary_event_id or session.session_id,
            event_type="region_recording",
            captured_at=session.started_at or session.created_at,
            source=SearchResultSource(app_name=app_name, title=title),
            user_note=session.user_note,
            match_reason=SearchMatchReason.ACTIVE_CAPTURE_SUMMARY,
            hidden_artifacts=tuple(hidden_artifacts),
            source_kind="region_recording",
        )

    def _session_has_available_video(self, session_id: str) -> bool:
        timeline = self.repository.get_timeline_manifest(session_id)
        if timeline is not None and timeline.video.state == VideoArtifactState.AVAILABLE:
            return True
        return any(
            segment.video is not None and segment.video.state == VideoArtifactState.AVAILABLE
            for segment in self.repository.list_recording_segments_for_session(session_id)
        )

    def segment_manifest_for_session(self, session_id: str) -> RecordingSegmentManifest:
        """Build the current pause/resume segment manifest."""

        self._require_session(session_id)
        return self.recording_controls.build_segment_manifest(session_id)

    def skill_distillation_input_for_session(self, session_id: str) -> SkillDistillationInputView:
        """Build a safe read-only P7.11 input projection."""

        return self.skill_distillation_inputs.build(self._require_session(session_id))

    def vm_a11y_probe_snapshot_for_session(self, session_id: str) -> dict[str, object]:
        """Return the latest VM accessibility probe sample for a readable session."""

        self._require_session(session_id)
        if self.vm_a11y_probe is None:
            return {"enabled": False, "running": False, "latest": None, "last_error": "vm_a11y_probe_unconfigured"}
        return self.vm_a11y_probe.latest_snapshot()

    def complete_session(
        self,
        *,
        session_id: str,
        command: CompleteActiveCaptureSessionCommand,
    ) -> ActiveCaptureSessionView:
        """Finalize a session, optionally promoting a staged video and timeline."""

        session = self._require_session(session_id)
        self.session_completion.complete_session(session=session, command=command)
        completed = self._require_session(session_id)
        archiver = getattr(self.vm_a11y_probe, "archive_session", None)
        if callable(archiver):
            try:
                archiver(
                    session_id=session_id,
                    started_at_epoch=completed.started_at.timestamp() if completed.started_at is not None else None,
                    ended_at_epoch=completed.ended_at.timestamp() if completed.ended_at is not None else None,
                )
            except Exception:  # noqa: BLE001 - probe archival must not fail recording completion
                logger.exception("failed to archive VM accessibility streams", extra={"session_id": session_id})
        return self.view_session(session_id)

    def cancel_session(self, *, session_id: str, reason: str | None = None) -> ActiveCaptureSessionView:
        """Cancel a live session and keep already committed ledger rows."""

        session = self._require_session(session_id)
        now = self.clock.now()
        cancelled = self.state_machine.transition(session, ActiveCaptureStatus.CANCELLED).model_copy(
            update={"ended_at": now, "updated_at": now, "metadata": session.metadata | {"cancel_reason": reason}}
        )
        self.repository.save_session(cancelled)
        return self.view_session(session_id)

    def view_session(self, session_id: str) -> ActiveCaptureSessionView:
        """Return the current backend view for a session."""

        return build_session_view(repository=self.repository, session=self._require_session(session_id))

    def to_public_view(self, view: ActiveCaptureSessionView) -> ActiveCapturePublicView:
        """Project an internal session graph into the safe API response shape."""

        return self.view_projector.to_public_view(view)

    def filter_view_for_visible_events(
        self,
        *,
        view: ActiveCaptureSessionView,
        visible_event_ids: set[str],
    ) -> ActiveCaptureSessionView:
        """Return a session view with keyframes/timeline entries limited to visible events."""

        return filter_session_view_for_visible_events(view=view, visible_event_ids=visible_event_ids)

    def can_access_session(
        self,
        *,
        session: ActiveCaptureSession,
        actor_id: str,
        workspace_id: str | None = None,
    ) -> bool:
        """Return whether a caller identity may operate on a session."""

        if session.actor is not None and session.actor.actor_id != actor_id:
            return False
        if workspace_id is not None and session.workspace_id not in {None, WorkspaceSelection.AUTO_WORKSPACE_ID}:
            return session.workspace_id == workspace_id
        if workspace_id is None and session.workspace_id not in {None, WorkspaceSelection.AUTO_WORKSPACE_ID}:
            return False
        return True

    def _capture_attempt_can_access_session(
        self,
        session: ActiveCaptureSession,
        attempt: CaptureAttemptRequest,
    ) -> bool:
        return self.can_access_session(
            session=session,
            actor_id=attempt.actor.actor_id,
            workspace_id=attempt.workspace.workspace_id,
        )

    def after_capture_committed(
        self,
        *,
        attempt: CaptureAttemptRequest,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        envelope: EventCaptureEnvelope,
    ) -> None:
        """Capture hook that records anchor/start/final keyframes after commit."""

        self.keyframe_recorder.after_capture_committed(
            attempt=attempt,
            event=event,
            artifacts=artifacts,
            envelope=envelope,
        )

    def record_keyframe(
        self,
        *,
        session: ActiveCaptureSession,
        binding: ActiveCaptureBinding,
        attempt: CaptureAttemptRequest,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        envelope: EventCaptureEnvelope,
    ) -> ContextKeyframe | None:
        """Persist a keyframe and its typed evidence links idempotently."""

        return self.keyframe_recorder.record_keyframe(
            session=session,
            binding=binding,
            attempt=attempt,
            event=event,
            artifacts=artifacts,
            envelope=envelope,
        )

    def keyframes_for_event(self, event_id: str) -> tuple[ContextKeyframe, ...]:
        """Return keyframes linked to an existing context event."""

        return self.keyframe_recorder.keyframes_for_event(event_id)

    def inspect_summaries_for_event(self, event_id: str) -> tuple[KeyframeInspectSummary, ...]:
        """Return safe keyframe summaries for explicit event inspection."""

        return inspect_summaries_for_event(repository=self.repository, event_id=event_id)

    def _prepare_segment_video_if_present(
        self,
        *,
        session: ActiveCaptureSession,
        segment: RecordingVideoSegmentRef,
        command: AttachRecordingSegmentCommand,
    ) -> PreparedVideoArtifact | None:
        if command.staged_video is None:
            return None
        if self.video_artifacts is None:
            return PreparedVideoArtifact(
                ref=VideoArtifactRef(
                    state=VideoArtifactState.FAILED,
                    failure_reason=VideoArtifactFailureReason.ADAPTER_MISSING,
                )
            )
        try:
            return self.video_artifacts.prepare_staged_segment_video(
                session=session,
                segment=segment,
                staged=command.staged_video,
            )
        except ArtifactVaultTransientError:
            logger.warning(
                "active capture segment video promotion failed transiently",
                extra={"session_id": session.session_id, "segment_id": segment.segment_id},
            )
            raise
        except ArtifactVaultError as exc:
            logger.warning(
                "active capture segment video unavailable",
                extra={"session_id": session.session_id, "segment_id": segment.segment_id, "warning": str(exc)},
            )
            return PreparedVideoArtifact(
                ref=VideoArtifactRef(
                    state=VideoArtifactState.FAILED,
                    failure_reason=VideoArtifactFailureReason.VALIDATION_FAILED,
                    failure_message=str(exc),
                )
            )

    def _discard_committed_staged_video(self, staged: StagedVideoArtifactRef) -> None:
        if self.video_artifacts is None:
            return
        try:
            self.video_artifacts.discard_staged_video(staged)
        except ArtifactVaultError:
            logger.warning("active capture staged video cleanup failed", exc_info=True)

    def _discard_prepared_video(self, prepared: PreparedVideoArtifact) -> None:
        if self.video_artifacts is None:
            return
        self.video_artifacts.discard_prepared_video(prepared)

    def _require_session(self, session_id: str) -> ActiveCaptureSession:
        session = self.repository.get_session(session_id)
        if session is None:
            raise ValueError(f"active capture session not found: {session_id}")
        return session


def _recording_card_title(session: ActiveCaptureSession) -> str:
    scope = session.scope
    if scope is not None:
        if scope.title is not None and scope.title.strip():
            return scope.title.strip()
        if scope.app_name is not None and scope.app_name.strip():
            return f"{scope.app_name.strip()} 录制"
    return "录制复盘"
