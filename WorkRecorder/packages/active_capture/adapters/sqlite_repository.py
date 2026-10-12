"""SQLite adapter for the active capture repository."""

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
    RecordingControlEvent,
    RecordingPauseInterval,
    RecordingTimelineManifest,
    RecordingVideoSegmentRef,
)
from packages.storage.database import SQLiteDatabase

from .sqlite_click_target_repository import SQLiteClickTargetRepositoryMixin
from .sqlite_producer_repository import SQLiteProducerEventRepositoryMixin
from .sqlite_projection_repository import SQLiteProjectionReadRepositoryMixin
from .sqlite_repository_helpers import (
    _find_keyframe_in_transaction,
    _insert_action_evidence_link,
    _insert_action_result_observation,
    _insert_artifact,
    _insert_bundle,
    _insert_capture_decision,
    _insert_control_event,
    _insert_demonstration_trace,
    _insert_evidence_link,
    _insert_human_action,
    _insert_keyframe,
    _insert_pause_interval,
    _insert_recording_segment,
    _insert_session,
    _insert_timeline_manifest,
    _insert_trigger_candidate,
    _next_action_sequence_index,
    _next_sequence_index,
    _recording_segment_from_row,
)
from .sqlite_timing_repository import SQLiteTimingRepositoryMixin

SEQUENCE_APPEND_RETRY_LIMIT = 3


class SQLiteActiveCaptureRepository(
    SQLiteProjectionReadRepositoryMixin,
    SQLiteProducerEventRepositoryMixin,
    SQLiteClickTargetRepositoryMixin,
    SQLiteTimingRepositoryMixin,
):
    """Persist active capture sessions, keyframes, decisions, and timelines."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save_session(self, session: ActiveCaptureSession) -> ActiveCaptureSession:
        with self.database.transaction() as connection:
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
        return session

    def get_session(self, session_id: str) -> ActiveCaptureSession | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM active_capture_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return ActiveCaptureSession.model_validate_json(str(row["payload"]))

    def list_sessions(
        self,
        *,
        mode: str | None = None,
        limit: int | None = None,
        require_primary_event: bool = False,
    ) -> tuple[ActiveCaptureSession, ...]:
        where: list[str] = []
        params: list[object] = []
        if mode is not None:
            where.append("mode = ?")
            params.append(mode)
        if require_primary_event:
            where.append("primary_event_id IS NOT NULL")
        sql = "SELECT payload FROM active_capture_sessions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY COALESCE(json_extract(payload, '$.started_at'), created_at) DESC, created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self.database.transaction() as connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        return tuple(ActiveCaptureSession.model_validate_json(str(row["payload"])) for row in rows)

    def save_keyframe(self, keyframe: ContextKeyframe) -> ContextKeyframe:
        with self.database.transaction() as connection:
            _insert_keyframe(connection, keyframe)
        return keyframe

    def save_keyframe_graph(
        self,
        *,
        keyframe: ContextKeyframe,
        links: tuple[KeyframeEvidenceLink, ...],
        decision: KeyframeCaptureDecision,
        session: ActiveCaptureSession | None = None,
        bundle: KeyframeContextBundle | None = None,
    ) -> ContextKeyframe:
        with self.database.transaction() as connection:
            if session is not None:
                _insert_session(connection, session)
            _insert_keyframe(connection, keyframe)
            for link in links:
                _insert_evidence_link(connection, link)
            _insert_capture_decision(connection, decision)
            if bundle is not None:
                _insert_bundle(connection, bundle)
        return keyframe

    def append_keyframe_graph(
        self,
        *,
        keyframe: ContextKeyframe,
        links: tuple[KeyframeEvidenceLink, ...],
        decision: KeyframeCaptureDecision,
        session: ActiveCaptureSession,
    ) -> ContextKeyframe:
        """Append a keyframe graph and allocate sequence_index in one transaction."""

        last_conflict: sqlite3.IntegrityError | None = None
        for _attempt in range(SEQUENCE_APPEND_RETRY_LIMIT):
            try:
                with self.database.transaction() as connection:
                    existing = _find_keyframe_in_transaction(
                        connection,
                        session_id=keyframe.session_id,
                        event_id=keyframe.event_id,
                        role=keyframe.role,
                        trigger_kind=keyframe.trigger_kind,
                    )
                    if existing is not None:
                        return existing
                    next_sequence = _next_sequence_index(connection, keyframe.session_id)
                    appended = keyframe.model_copy(update={"sequence_index": next_sequence})
                    appended_links = tuple(
                        link.model_copy(update={"keyframe_id": appended.keyframe_id}) for link in links
                    )
                    appended_decision = decision.model_copy(update={"kept_keyframe_id": appended.keyframe_id})
                    _insert_session(connection, session)
                    _insert_keyframe(connection, appended)
                    for link in appended_links:
                        _insert_evidence_link(connection, link)
                    _insert_capture_decision(connection, appended_decision)
                return appended
            except sqlite3.IntegrityError as exc:
                message = str(exc)
                if (
                    "idx_context_keyframes_session_sequence" not in message
                    and "context_keyframes.session_id" not in message
                ):
                    raise
                last_conflict = exc
        raise sqlite3.IntegrityError("failed to append keyframe after sequence retry") from last_conflict

    def get_keyframe(self, keyframe_id: str) -> ContextKeyframe | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM context_keyframes WHERE keyframe_id = ?",
                (keyframe_id,),
            ).fetchone()
        if row is None:
            return None
        return ContextKeyframe.model_validate_json(str(row["payload"]))

    def find_keyframe(
        self,
        *,
        session_id: str,
        event_id: str,
        role: KeyframeRole,
        trigger_kind: KeyframeTriggerKind,
    ) -> ContextKeyframe | None:
        with self.database.transaction() as connection:
            return _find_keyframe_in_transaction(
                connection,
                session_id=session_id,
                event_id=event_id,
                role=role,
                trigger_kind=trigger_kind,
            )

    def list_keyframes_for_session(self, session_id: str, *, limit: int | None = None) -> tuple[ContextKeyframe, ...]:
        query = (
            "SELECT payload FROM context_keyframes WHERE session_id = ? ORDER BY sequence_index ASC, captured_at ASC"
        )
        params: tuple[object, ...] = (session_id,)
        if limit is not None:
            query = f"{query} LIMIT ?"
            params = (*params, limit)
        with self.database.transaction() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(ContextKeyframe.model_validate_json(str(row["payload"])) for row in rows)

    def list_keyframes_for_event(self, event_id: str) -> tuple[ContextKeyframe, ...]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT payload FROM context_keyframes WHERE event_id = ? ORDER BY sequence_index ASC, captured_at ASC",
                (event_id,),
            ).fetchall()
        return tuple(ContextKeyframe.model_validate_json(str(row["payload"])) for row in rows)

    def save_evidence_links(self, links: tuple[KeyframeEvidenceLink, ...]) -> tuple[KeyframeEvidenceLink, ...]:
        with self.database.transaction() as connection:
            for link in links:
                _insert_evidence_link(connection, link)
        return links

    def list_evidence_links_for_keyframe(self, keyframe_id: str) -> tuple[KeyframeEvidenceLink, ...]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT payload FROM keyframe_evidence_links WHERE keyframe_id = ? ORDER BY created_at ASC",
                (keyframe_id,),
            ).fetchall()
        return tuple(KeyframeEvidenceLink.model_validate_json(str(row["payload"])) for row in rows)

    def list_evidence_links_for_session(self, session_id: str) -> tuple[KeyframeEvidenceLink, ...]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT l.payload
                FROM keyframe_evidence_links l
                JOIN context_keyframes k ON k.keyframe_id = l.keyframe_id
                WHERE k.session_id = ?
                ORDER BY k.sequence_index ASC, l.created_at ASC
                """,
                (session_id,),
            ).fetchall()
        return tuple(KeyframeEvidenceLink.model_validate_json(str(row["payload"])) for row in rows)

    def save_capture_decision(self, decision: KeyframeCaptureDecision) -> KeyframeCaptureDecision:
        with self.database.transaction() as connection:
            _insert_capture_decision(connection, decision)
        return decision

    def save_bundle(self, bundle: KeyframeContextBundle) -> KeyframeContextBundle:
        with self.database.transaction() as connection:
            _insert_bundle(connection, bundle)
        return bundle

    def get_bundle_for_session(self, session_id: str) -> KeyframeContextBundle | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM keyframe_context_bundles WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return KeyframeContextBundle.model_validate_json(str(row["payload"]))

    def get_bundle_for_event(self, event_id: str) -> KeyframeContextBundle | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM keyframe_context_bundles WHERE primary_event_id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        return KeyframeContextBundle.model_validate_json(str(row["payload"]))

    def save_timeline_manifest(self, manifest: RecordingTimelineManifest) -> RecordingTimelineManifest:
        with self.database.transaction() as connection:
            _insert_timeline_manifest(connection, manifest)
        return manifest

    def complete_session_graph(
        self,
        *,
        session: ActiveCaptureSession,
        timeline: RecordingTimelineManifest,
        bundle: KeyframeContextBundle,
        artifacts: tuple[Artifact, ...] = (),
    ) -> ActiveCaptureSession:
        with self.database.transaction() as connection:
            for artifact in artifacts:
                _insert_artifact(connection, artifact)
            _insert_session(connection, session)
            _insert_timeline_manifest(connection, timeline)
            _insert_bundle(connection, bundle)
        return session

    def get_timeline_manifest(self, session_id: str) -> RecordingTimelineManifest | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM recording_timeline_manifests WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return RecordingTimelineManifest.model_validate_json(str(row["payload"]))

    def save_control_event(self, event: RecordingControlEvent) -> RecordingControlEvent:
        with self.database.transaction() as connection:
            _insert_control_event(connection, event)
        return event

    def list_control_events_for_session(
        self, session_id: str, *, limit: int | None = None
    ) -> tuple[RecordingControlEvent, ...]:
        query = """
                SELECT payload FROM active_capture_control_events
                WHERE session_id = ?
                ORDER BY occurred_at ASC, control_id ASC
                """
        params: tuple[object, ...] = (session_id,)
        if limit is not None:
            query = f"{query} LIMIT ?"
            params = (*params, limit)
        with self.database.transaction() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(RecordingControlEvent.model_validate_json(str(row["payload"])) for row in rows)

    def save_recording_segment(self, segment: RecordingVideoSegmentRef) -> RecordingVideoSegmentRef:
        with self.database.transaction() as connection:
            _insert_recording_segment(connection, segment)
        return segment

    def save_recording_segment_graph(
        self,
        *,
        segment: RecordingVideoSegmentRef,
        artifacts: tuple[Artifact, ...] = (),
    ) -> RecordingVideoSegmentRef:
        with self.database.transaction() as connection:
            for artifact in artifacts:
                _insert_artifact(connection, artifact)
            _insert_recording_segment(connection, segment)
        return segment

    def get_recording_segment(self, segment_id: str) -> RecordingVideoSegmentRef | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT video_artifact_id, payload FROM recording_video_segments WHERE segment_id = ?",
                (segment_id,),
            ).fetchone()
        if row is None:
            return None
        return _recording_segment_from_row(row)

    def list_recording_segments_for_session(self, session_id: str) -> tuple[RecordingVideoSegmentRef, ...]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT video_artifact_id, payload FROM recording_video_segments
                WHERE session_id = ?
                ORDER BY sequence_index ASC, started_at ASC
                """,
                (session_id,),
            ).fetchall()
        return tuple(_recording_segment_from_row(row) for row in rows)

    def save_pause_interval(self, interval: RecordingPauseInterval) -> RecordingPauseInterval:
        with self.database.transaction() as connection:
            _insert_pause_interval(connection, interval)
        return interval

    def list_pause_intervals_for_session(self, session_id: str) -> tuple[RecordingPauseInterval, ...]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM recording_pause_intervals
                WHERE session_id = ?
                ORDER BY started_at ASC, pause_id ASC
                """,
                (session_id,),
            ).fetchall()
        return tuple(RecordingPauseInterval.model_validate_json(str(row["payload"])) for row in rows)

    def save_trigger_candidate(self, candidate: KeyframeTriggerCandidate) -> KeyframeTriggerCandidate:
        with self.database.transaction() as connection:
            _insert_trigger_candidate(connection, candidate)
        return candidate

    def get_trigger_candidate(self, candidate_id: str) -> KeyframeTriggerCandidate | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM active_capture_trigger_candidates WHERE candidate_id = ?",
                (candidate_id,),
            ).fetchone()
        if row is None:
            return None
        return KeyframeTriggerCandidate.model_validate_json(str(row["payload"]))

    def list_trigger_candidates_for_session(self, session_id: str) -> tuple[KeyframeTriggerCandidate, ...]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM active_capture_trigger_candidates
                WHERE session_id = ?
                ORDER BY occurred_at ASC, candidate_id ASC
                """,
                (session_id,),
            ).fetchall()
        return tuple(KeyframeTriggerCandidate.model_validate_json(str(row["payload"])) for row in rows)

    def save_demonstration_trace(self, trace: HumanDemonstrationTrace) -> HumanDemonstrationTrace:
        with self.database.transaction() as connection:
            _insert_demonstration_trace(connection, trace)
        return trace

    def get_demonstration_trace_for_session(self, session_id: str) -> HumanDemonstrationTrace | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM human_demonstration_traces WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return HumanDemonstrationTrace.model_validate_json(str(row["payload"]))

    def append_human_action_graph(
        self,
        *,
        action: HumanActionEvent,
        links: tuple[ActionEvidenceLink, ...],
        observation: ActionResultObservation | None,
        trace: HumanDemonstrationTrace,
    ) -> HumanActionEvent:
        with self.database.transaction() as connection:
            next_sequence = _next_action_sequence_index(connection, action.trace_id)
            appended = action.model_copy(update={"sequence_index": next_sequence})
            appended_links = tuple(link.model_copy(update={"action_id": appended.action_id}) for link in links)
            appended_observation = (
                observation.model_copy(update={"action_id": appended.action_id}) if observation is not None else None
            )
            _insert_demonstration_trace(connection, trace)
            _insert_human_action(connection, appended)
            for link in appended_links:
                _insert_action_evidence_link(connection, link)
            if appended_observation is not None:
                _insert_action_result_observation(connection, appended_observation)
        return appended

    def list_human_actions_for_session(
        self, session_id: str, *, limit: int | None = None
    ) -> tuple[HumanActionEvent, ...]:
        query = """
                SELECT payload FROM human_action_events
                WHERE session_id = ?
                ORDER BY sequence_index ASC, occurred_at ASC
                """
        params: tuple[object, ...] = (session_id,)
        if limit is not None:
            query = f"{query} LIMIT ?"
            params = (*params, limit)
        with self.database.transaction() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(HumanActionEvent.model_validate_json(str(row["payload"])) for row in rows)

    def list_action_evidence_links(self, action_id: str) -> tuple[ActionEvidenceLink, ...]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM action_evidence_links
                WHERE action_id = ?
                ORDER BY created_at ASC, link_id ASC
                """,
                (action_id,),
            ).fetchall()
        return tuple(ActionEvidenceLink.model_validate_json(str(row["payload"])) for row in rows)

    def list_action_evidence_links_for_session(self, session_id: str) -> tuple[ActionEvidenceLink, ...]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT l.payload
                FROM action_evidence_links l
                JOIN human_action_events a ON a.action_id = l.action_id
                WHERE a.session_id = ?
                ORDER BY a.sequence_index ASC, l.created_at ASC, l.link_id ASC
                """,
                (session_id,),
            ).fetchall()
        return tuple(ActionEvidenceLink.model_validate_json(str(row["payload"])) for row in rows)

    def save_action_evidence_link(self, link: ActionEvidenceLink) -> ActionEvidenceLink:
        with self.database.transaction() as connection:
            _insert_action_evidence_link(connection, link)
        return link

    def get_action_observation(self, action_id: str) -> ActionResultObservation | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM action_result_observations WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        if row is None:
            return None
        return ActionResultObservation.model_validate_json(str(row["payload"]))

    def list_action_observations_for_session(self, session_id: str) -> tuple[ActionResultObservation, ...]:
        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT o.payload
                FROM action_result_observations o
                JOIN human_action_events a ON a.action_id = o.action_id
                WHERE a.session_id = ?
                ORDER BY a.sequence_index ASC, o.observed_at ASC
                """,
                (session_id,),
            ).fetchall()
        return tuple(ActionResultObservation.model_validate_json(str(row["payload"])) for row in rows)

    def save_action_observation(self, observation: ActionResultObservation) -> ActionResultObservation:
        with self.database.transaction() as connection:
            _insert_action_result_observation(connection, observation)
        return observation
