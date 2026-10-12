"""Public projections for active-capture recording backend objects."""

from __future__ import annotations

from packages.contracts import (
    ActiveCaptureBinding,
    HumanActionEvent,
    HumanActionPublicSummary,
    KeyframeCaptureInstruction,
    KeyframeTriggerCandidate,
    KeyframeTriggerCandidateStatus,
    KeyframeTriggerPublicSummary,
    KeyframeTriggerSubmission,
    RecordingControlEvent,
    RecordingControlPublicSummary,
    RecordingPauseInterval,
    RecordingPausePublicSummary,
    RecordingSegmentManifest,
    RecordingSegmentManifestPublicView,
    RecordingVideoSegmentPublicSummary,
    RecordingVideoSegmentRef,
    VideoArtifactPublicSummary,
    VideoArtifactRef,
)
from packages.contracts.common import JsonScalar


class RecordingPublicProjector:
    """Convert internal recording graphs into safe public response models."""

    def to_public_recording_segment(
        self,
        segment: RecordingVideoSegmentRef,
    ) -> RecordingVideoSegmentPublicSummary:
        """Project one segment without staged paths or producer metadata.

        Args:
            segment: Internal recording segment reference.

        Returns:
            Public segment summary safe for daemon API responses.
        """

        return RecordingVideoSegmentPublicSummary(
            segment_id=segment.segment_id,
            session_id=segment.session_id,
            sequence_index=segment.sequence_index,
            state=segment.state,
            started_at=segment.started_at,
            ended_at=segment.ended_at,
            started_at_monotonic_ms=segment.started_at_monotonic_ms,
            media_start_monotonic_ms=segment.media_start_monotonic_ms,
            ended_at_monotonic_ms=segment.ended_at_monotonic_ms,
            duration_ms=segment.duration_ms,
            close_reason=segment.close_reason,
            video=self.public_video(segment.video),
        )

    def to_public_control_event(self, control: RecordingControlEvent) -> RecordingControlPublicSummary:
        """Project a recording control without note or metadata.

        Args:
            control: Internal recording control event.

        Returns:
            Public control summary.
        """

        return RecordingControlPublicSummary(
            control_id=control.control_id,
            session_id=control.session_id,
            kind=control.kind,
            source=control.source,
            occurred_at=control.occurred_at,
            occurred_at_monotonic_ms=control.occurred_at_monotonic_ms,
            segment_id=control.segment_id,
        )

    def to_public_pause_interval(self, pause: RecordingPauseInterval) -> RecordingPausePublicSummary:
        """Project a pause interval without producer metadata.

        Args:
            pause: Internal pause interval.

        Returns:
            Public pause interval summary.
        """

        return RecordingPausePublicSummary(
            pause_id=pause.pause_id,
            session_id=pause.session_id,
            started_at=pause.started_at,
            started_at_monotonic_ms=pause.started_at_monotonic_ms,
            ended_at=pause.ended_at,
            ended_at_monotonic_ms=pause.ended_at_monotonic_ms,
            reason=pause.reason,
        )

    def to_public_trigger_candidate(self, candidate: KeyframeTriggerCandidate) -> KeyframeTriggerPublicSummary:
        """Project a trigger candidate without scope, diff, quality, or metadata.

        Args:
            candidate: Internal keyframe trigger candidate.

        Returns:
            Public trigger summary.
        """

        return KeyframeTriggerPublicSummary(
            candidate_id=candidate.candidate_id,
            status=candidate.status,
            trigger_kind=candidate.trigger_kind,
            role=candidate.role,
            priority=candidate.priority,
            debounce_until_monotonic_ms=candidate.debounce_until_monotonic_ms,
            keyframe_id=candidate.keyframe_id,
            event_id=candidate.event_id,
            drop_reason=candidate.drop_reason,
            diagnostics=candidate.diagnostics,
        )

    def to_public_human_action(self, action: HumanActionEvent) -> HumanActionPublicSummary:
        """Project an action without coordinates, target metadata, or scope.

        Args:
            action: Internal human demonstration action event.

        Returns:
            Public action summary safe for future UI and API clients.
        """

        return HumanActionPublicSummary(
            action_id=action.action_id,
            trace_id=action.trace_id,
            session_id=action.session_id,
            sequence_index=action.sequence_index,
            kind=action.kind,
            occurred_at=action.occurred_at,
            occurred_at_monotonic_ms=action.occurred_at_monotonic_ms,
            media_time_ms=action.media_time_ms,
            hotkey_semantic=action.hotkey_semantic,
            result_status=action.result_observation.status if action.result_observation is not None else None,
        )

    def capture_instruction_for_candidate(
        self,
        candidate: KeyframeTriggerCandidate,
        *,
        allow_claimed: bool = False,
    ) -> KeyframeCaptureInstruction | None:
        """Build a typed capture instruction for accepted trigger candidates.

        Args:
            candidate: Internal trigger candidate from the scheduler.

        Returns:
            Capture instruction for trusted producers, or None when not accepted.
        """

        if candidate.status != KeyframeTriggerCandidateStatus.ACCEPTED:
            return None
        settle_state = candidate.metadata.get("settle_live_polling_state")
        if settle_state in {"pending", "observing"}:
            return None
        if settle_state == "capturing" and not allow_claimed:
            return None
        binding_metadata = self._capture_binding_metadata(candidate)
        return KeyframeCaptureInstruction(
            candidate_id=candidate.candidate_id,
            session_id=candidate.session_id,
            role=candidate.role,
            trigger_kind=candidate.trigger_kind,
            execute_after_monotonic_ms=candidate.debounce_until_monotonic_ms,
            binding=ActiveCaptureBinding(
                session_id=candidate.session_id,
                role=candidate.role,
                trigger_kind=candidate.trigger_kind,
                keep_reason=candidate.keep_reason,
                candidate_id=candidate.candidate_id,
                metadata=binding_metadata,
            ),
        )

    def _capture_binding_metadata(self, candidate: KeyframeTriggerCandidate) -> dict[str, JsonScalar]:
        """Return safe settle metadata that can travel with the final paired keyframe."""

        allowed_keys = {
            "settle_live_polling_state",
            "settle_decision_status",
            "settle_stop_reason",
            "settle_sample_count",
            "settle_stable_sample_count",
            "settle_needs_review",
            "settle_capture_claim_id",
            "settle_capture_claim_expires_monotonic_ms",
        }
        return {key: value for key, value in candidate.metadata.items() if key in allowed_keys}

    def to_trigger_submission(self, candidate: KeyframeTriggerCandidate) -> KeyframeTriggerSubmission:
        """Project a candidate plus optional capture instruction."""

        return KeyframeTriggerSubmission(
            candidate=self.to_public_trigger_candidate(candidate),
            capture_instruction=self.capture_instruction_for_candidate(candidate),
        )

    def to_public_segment_manifest(
        self,
        manifest: RecordingSegmentManifest,
    ) -> RecordingSegmentManifestPublicView:
        """Project an internal segment manifest without raw video material.

        Args:
            manifest: Internal recording segment manifest.

        Returns:
            Public segment manifest for daemon API responses.
        """

        return RecordingSegmentManifestPublicView(
            manifest_id=manifest.manifest_id,
            session_id=manifest.session_id,
            segments=tuple(self.to_public_recording_segment(segment) for segment in manifest.segments),
            pause_intervals=tuple(self.to_public_pause_interval(pause) for pause in manifest.pause_intervals),
            control_events=tuple(self.to_public_control_event(control) for control in manifest.control_events),
            total_recorded_duration_ms=manifest.total_recorded_duration_ms,
            total_paused_duration_ms=manifest.total_paused_duration_ms,
            created_at=manifest.created_at,
            updated_at=manifest.updated_at,
        )

    def public_video(self, video: VideoArtifactRef | None) -> VideoArtifactPublicSummary | None:
        """Project a video artifact ref without integrity hashes or metadata.

        Args:
            video: Internal video artifact reference.

        Returns:
            Public video summary, or None when no video exists.
        """

        if video is None:
            return None
        return VideoArtifactPublicSummary(
            artifact_id=video.artifact_id,
            state=video.state,
            content_type=video.content_type,
            byte_size=video.byte_size,
            duration_ms=video.duration_ms,
            failure_reason=video.failure_reason,
            failure_message=video.failure_message,
            created_at=video.created_at,
        )
