"""SQLite row mappers and writers for active-capture repository storage."""

from __future__ import annotations

import sqlite3

from packages.contracts import (
    ActionEvidenceLink,
    ActionResultObservation,
    ActiveCaptureSession,
    Artifact,
    ContextKeyframe,
    HumanActionEvent,
    HumanDemonstrationTrace,
    KeyframeCaptureDecision,
    KeyframeContextBundle,
    KeyframeEvidenceLink,
    KeyframeRole,
    KeyframeTriggerCandidate,
    KeyframeTriggerKind,
    ProducerDecision,
    ProducerEventEnvelope,
    RecordingControlEvent,
    RecordingPauseInterval,
    RecordingTimelineManifest,
    RecordingVideoSegmentRef,
)


def _insert_session(connection: sqlite3.Connection, session: ActiveCaptureSession) -> None:
    connection.execute(
        """
        INSERT INTO active_capture_sessions(
          session_id, mode, status, primary_event_id, payload, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
          mode = excluded.mode,
          status = excluded.status,
          primary_event_id = excluded.primary_event_id,
          payload = excluded.payload,
          updated_at = excluded.updated_at
        """,
        (
            session.session_id,
            session.mode.value,
            session.status.value,
            session.primary_event_id,
            session.model_dump_json(),
            session.created_at.isoformat(),
            session.updated_at.isoformat(),
        ),
    )


def _find_keyframe_in_transaction(
    connection: sqlite3.Connection,
    *,
    session_id: str,
    event_id: str,
    role: KeyframeRole,
    trigger_kind: KeyframeTriggerKind,
) -> ContextKeyframe | None:
    row = connection.execute(
        """
        SELECT payload FROM context_keyframes
        WHERE session_id = ? AND event_id = ? AND role = ? AND trigger_kind = ?
        ORDER BY sequence_index ASC
        LIMIT 1
        """,
        (session_id, event_id, role.value, trigger_kind.value),
    ).fetchone()
    if row is None:
        return None
    return ContextKeyframe.model_validate_json(str(row["payload"]))


def _next_sequence_index(connection: sqlite3.Connection, session_id: str) -> int:
    row = connection.execute(
        "SELECT COALESCE(MAX(sequence_index), -1) + 1 AS next_sequence FROM context_keyframes WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    return int(row["next_sequence"])


def _next_action_sequence_index(connection: sqlite3.Connection, trace_id: str) -> int:
    row = connection.execute(
        """
        SELECT COALESCE(MAX(sequence_index), -1) + 1 AS next_sequence
        FROM human_action_events
        WHERE trace_id = ?
        """,
        (trace_id,),
    ).fetchone()
    return int(row["next_sequence"])


def _insert_artifact(connection: sqlite3.Connection, artifact: Artifact) -> None:
    connection.execute(
        """
        INSERT OR REPLACE INTO artifacts(artifact_id, event_id, artifact_type, payload, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            artifact.artifact_id,
            artifact.event_id,
            artifact.artifact_type.value,
            artifact.model_dump_json(),
            artifact.created_at.isoformat(),
        ),
    )


def _recording_segment_from_row(row: sqlite3.Row) -> RecordingVideoSegmentRef:
    segment = RecordingVideoSegmentRef.model_validate_json(str(row["payload"]))
    if row["video_artifact_id"] is None and segment.video is not None and segment.video.artifact_id is not None:
        return segment.model_copy(update={"video": None, "staged_video": None})
    if segment.staged_video is not None:
        return segment.model_copy(update={"staged_video": None})
    return segment


def _insert_keyframe(connection: sqlite3.Connection, keyframe: ContextKeyframe) -> None:
    connection.execute(
        """
        INSERT INTO context_keyframes(
          keyframe_id, session_id, event_id, capture_run_id, role, trigger_kind,
          captured_at, sequence_index, screenshot_artifact_id, screenshot_evidence_id,
          system_appshot_evidence_id, payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(keyframe_id) DO UPDATE SET
          role = excluded.role,
          trigger_kind = excluded.trigger_kind,
          captured_at = excluded.captured_at,
          sequence_index = excluded.sequence_index,
          screenshot_artifact_id = excluded.screenshot_artifact_id,
          screenshot_evidence_id = excluded.screenshot_evidence_id,
          system_appshot_evidence_id = excluded.system_appshot_evidence_id,
          payload = excluded.payload
        """,
        (
            keyframe.keyframe_id,
            keyframe.session_id,
            keyframe.event_id,
            keyframe.capture_run_id,
            keyframe.role.value,
            keyframe.trigger_kind.value,
            keyframe.captured_at.isoformat(),
            keyframe.sequence_index,
            keyframe.screenshot_artifact_id,
            keyframe.screenshot_evidence_id,
            keyframe.system_appshot_evidence_id,
            keyframe.model_dump_json(),
        ),
    )


def _insert_evidence_link(connection: sqlite3.Connection, link: KeyframeEvidenceLink) -> None:
    connection.execute(
        """
        INSERT INTO keyframe_evidence_links(
          link_id, keyframe_id, event_id, evidence_id, artifact_id, role,
          provider_key, payload, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(link_id) DO UPDATE SET
          artifact_id = excluded.artifact_id,
          role = excluded.role,
          provider_key = excluded.provider_key,
          payload = excluded.payload
        """,
        (
            link.link_id,
            link.keyframe_id,
            link.event_id,
            link.evidence_id,
            link.artifact_id,
            link.role.value,
            link.provider_key,
            link.model_dump_json(),
            link.created_at.isoformat(),
        ),
    )


def _insert_capture_decision(connection: sqlite3.Connection, decision: KeyframeCaptureDecision) -> None:
    connection.execute(
        """
        INSERT INTO keyframe_capture_decisions(
          decision_id, session_id, event_id, candidate_id, role, trigger_kind,
          kept, kept_keyframe_id, drop_reason, payload, decided_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(decision_id) DO UPDATE SET
          event_id = excluded.event_id,
          kept = excluded.kept,
          kept_keyframe_id = excluded.kept_keyframe_id,
          drop_reason = excluded.drop_reason,
          payload = excluded.payload,
          decided_at = excluded.decided_at
        """,
        (
            decision.decision_id,
            decision.session_id,
            decision.event_id,
            decision.candidate_id,
            decision.role.value,
            decision.trigger_kind.value,
            int(decision.kept),
            decision.kept_keyframe_id,
            decision.drop_reason.value if decision.drop_reason is not None else None,
            decision.model_dump_json(),
            decision.decided_at.isoformat(),
        ),
    )


def _insert_bundle(connection: sqlite3.Connection, bundle: KeyframeContextBundle) -> None:
    connection.execute(
        """
        INSERT INTO keyframe_context_bundles(
          bundle_id, session_id, primary_event_id, status, anchor_keyframe_id,
          keyframe_count, payload, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
          primary_event_id = excluded.primary_event_id,
          status = excluded.status,
          anchor_keyframe_id = excluded.anchor_keyframe_id,
          keyframe_count = excluded.keyframe_count,
          payload = excluded.payload,
          updated_at = excluded.updated_at
        """,
        (
            bundle.bundle_id,
            bundle.session_id,
            bundle.primary_event_id,
            bundle.status.value,
            bundle.anchor_keyframe_id,
            bundle.keyframe_count,
            bundle.model_dump_json(),
            bundle.created_at.isoformat(),
            bundle.updated_at.isoformat(),
        ),
    )


def _insert_timeline_manifest(
    connection: sqlite3.Connection,
    manifest: RecordingTimelineManifest,
) -> None:
    connection.execute(
        """
        INSERT INTO recording_timeline_manifests(
          manifest_id, session_id, primary_event_id, video_artifact_id, payload, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
          primary_event_id = excluded.primary_event_id,
          video_artifact_id = excluded.video_artifact_id,
          payload = excluded.payload,
          updated_at = excluded.updated_at
        """,
        (
            manifest.manifest_id,
            manifest.session_id,
            manifest.primary_event_id,
            manifest.video.artifact_id,
            manifest.model_dump_json(),
            manifest.created_at.isoformat(),
            manifest.updated_at.isoformat(),
        ),
    )


def _insert_control_event(connection: sqlite3.Connection, event: RecordingControlEvent) -> None:
    connection.execute(
        """
        INSERT INTO active_capture_control_events(
          control_id, session_id, kind, source, occurred_at, segment_id, payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(control_id) DO UPDATE SET
          kind = excluded.kind,
          source = excluded.source,
          occurred_at = excluded.occurred_at,
          segment_id = excluded.segment_id,
          payload = excluded.payload
        """,
        (
            event.control_id,
            event.session_id,
            event.kind.value,
            event.source.value,
            event.occurred_at.isoformat(),
            event.segment_id,
            event.model_dump_json(),
        ),
    )


def _insert_recording_segment(connection: sqlite3.Connection, segment: RecordingVideoSegmentRef) -> None:
    connection.execute(
        """
        INSERT INTO recording_video_segments(
          segment_id, session_id, sequence_index, state, video_artifact_id,
          started_at, ended_at, payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(segment_id) DO UPDATE SET
          sequence_index = excluded.sequence_index,
          state = excluded.state,
          video_artifact_id = excluded.video_artifact_id,
          ended_at = excluded.ended_at,
          payload = excluded.payload
        """,
        (
            segment.segment_id,
            segment.session_id,
            segment.sequence_index,
            segment.state.value,
            segment.video.artifact_id if segment.video is not None else None,
            segment.started_at.isoformat(),
            segment.ended_at.isoformat() if segment.ended_at is not None else None,
            segment.model_dump_json(),
        ),
    )


def _insert_pause_interval(connection: sqlite3.Connection, interval: RecordingPauseInterval) -> None:
    connection.execute(
        """
        INSERT INTO recording_pause_intervals(
          pause_id, session_id, started_at, ended_at, reason, payload
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(pause_id) DO UPDATE SET
          ended_at = excluded.ended_at,
          reason = excluded.reason,
          payload = excluded.payload
        """,
        (
            interval.pause_id,
            interval.session_id,
            interval.started_at.isoformat(),
            interval.ended_at.isoformat() if interval.ended_at is not None else None,
            interval.reason.value,
            interval.model_dump_json(),
        ),
    )


def _insert_trigger_candidate(connection: sqlite3.Connection, candidate: KeyframeTriggerCandidate) -> None:
    connection.execute(
        """
        INSERT INTO active_capture_trigger_candidates(
          candidate_id, session_id, trigger_kind, role, priority, status,
          occurred_at, event_id, keyframe_id, payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(candidate_id) DO UPDATE SET
          role = excluded.role,
          priority = excluded.priority,
          status = excluded.status,
          event_id = excluded.event_id,
          keyframe_id = excluded.keyframe_id,
          payload = excluded.payload
        """,
        (
            candidate.candidate_id,
            candidate.session_id,
            candidate.trigger_kind.value,
            candidate.role.value,
            candidate.priority.value,
            candidate.status.value,
            candidate.occurred_at.isoformat(),
            candidate.event_id,
            candidate.keyframe_id,
            candidate.model_dump_json(),
        ),
    )


def _insert_demonstration_trace(connection: sqlite3.Connection, trace: HumanDemonstrationTrace) -> None:
    connection.execute(
        """
        INSERT INTO human_demonstration_traces(
          trace_id, session_id, status, action_count, payload, started_at, ended_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
          status = excluded.status,
          action_count = excluded.action_count,
          payload = excluded.payload,
          ended_at = excluded.ended_at
        """,
        (
            trace.trace_id,
            trace.session_id,
            trace.status.value,
            trace.action_count,
            trace.model_dump_json(),
            trace.started_at.isoformat(),
            trace.ended_at.isoformat() if trace.ended_at is not None else None,
        ),
    )


def _insert_human_action(connection: sqlite3.Connection, action: HumanActionEvent) -> None:
    connection.execute(
        """
        INSERT INTO human_action_events(
          action_id, trace_id, session_id, sequence_index, kind, occurred_at, payload
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(action_id) DO UPDATE SET
          sequence_index = excluded.sequence_index,
          kind = excluded.kind,
          occurred_at = excluded.occurred_at,
          payload = excluded.payload
        """,
        (
            action.action_id,
            action.trace_id,
            action.session_id,
            action.sequence_index,
            action.kind.value,
            action.occurred_at.isoformat(),
            action.model_dump_json(),
        ),
    )


def _insert_action_evidence_link(connection: sqlite3.Connection, link: ActionEvidenceLink) -> None:
    connection.execute(
        """
        INSERT INTO action_evidence_links(
          link_id, action_id, role, keyframe_id, event_id, evidence_id, artifact_id, payload, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(link_id) DO UPDATE SET
          role = excluded.role,
          keyframe_id = excluded.keyframe_id,
          event_id = excluded.event_id,
          evidence_id = excluded.evidence_id,
          artifact_id = excluded.artifact_id,
          payload = excluded.payload
        """,
        (
            link.link_id,
            link.action_id,
            link.role.value,
            link.keyframe_id,
            link.event_id,
            link.evidence_id,
            link.artifact_id,
            link.model_dump_json(),
            link.created_at.isoformat(),
        ),
    )


def _insert_action_result_observation(
    connection: sqlite3.Connection,
    observation: ActionResultObservation,
) -> None:
    connection.execute(
        """
        INSERT INTO action_result_observations(
          observation_id, action_id, status, result_keyframe_id, observed_at, payload
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(action_id) DO UPDATE SET
          observation_id = excluded.observation_id,
          status = excluded.status,
          result_keyframe_id = excluded.result_keyframe_id,
          observed_at = excluded.observed_at,
          payload = excluded.payload
        """,
        (
            observation.observation_id,
            observation.action_id,
            observation.status.value,
            observation.result_keyframe_id,
            observation.observed_at.isoformat(),
            observation.model_dump_json(),
        ),
    )


def _insert_producer_event(connection: sqlite3.Connection, event: ProducerEventEnvelope) -> None:
    connection.execute(
        """
        INSERT INTO active_capture_producer_events(
          producer_event_id, session_id, event_kind, producer_kind, occurred_at, payload
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(producer_event_id) DO UPDATE SET
          event_kind = excluded.event_kind,
          producer_kind = excluded.producer_kind,
          occurred_at = excluded.occurred_at,
          payload = excluded.payload
        """,
        (
            event.producer_event_id,
            event.session_id,
            event.event_kind.value,
            event.producer_kind,
            event.occurred_at.isoformat(),
            event.model_dump_json(),
        ),
    )


def _insert_producer_decision(connection: sqlite3.Connection, decision: ProducerDecision) -> None:
    connection.execute(
        """
        INSERT INTO active_capture_producer_decisions(
          decision_id, producer_event_id, session_id, status, reason,
          action_id, candidate_id, keyframe_id, payload, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(decision_id) DO UPDATE SET
          status = excluded.status,
          reason = excluded.reason,
          action_id = excluded.action_id,
          candidate_id = excluded.candidate_id,
          keyframe_id = excluded.keyframe_id,
          payload = excluded.payload
        """,
        (
            decision.decision_id,
            decision.producer_event_id,
            decision.session_id,
            decision.status.value,
            decision.reason.value,
            decision.action_id,
            decision.candidate_id,
            decision.keyframe_id,
            decision.model_dump_json(),
            decision.created_at.isoformat(),
        ),
    )
