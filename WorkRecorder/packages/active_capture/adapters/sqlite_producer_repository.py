"""SQLite producer-event persistence mixin for active capture."""

from __future__ import annotations

from typing import Protocol

from packages.contracts import (
    ActionEvidenceLink,
    ActionResultObservation,
    HumanActionEvent,
    HumanDemonstrationTrace,
    KeyframeTriggerCandidate,
    KeyframeTriggerCandidateStatus,
    ProducerDecision,
    ProducerEventEnvelope,
)
from packages.storage.database import SQLiteDatabase

from .sqlite_repository_helpers import (
    _insert_action_evidence_link,
    _insert_action_result_observation,
    _insert_demonstration_trace,
    _insert_human_action,
    _insert_producer_decision,
    _insert_producer_event,
    _insert_trigger_candidate,
)


class _HasDatabase(Protocol):
    database: SQLiteDatabase


class SQLiteProducerEventRepositoryMixin:
    """Producer-event graph persistence methods for the SQLite adapter."""

    database: SQLiteDatabase

    def append_producer_event_graph(
        self: _HasDatabase,
        *,
        event: ProducerEventEnvelope,
        decision: ProducerDecision,
    ) -> ProducerEventEnvelope:
        with self.database.transaction(immediate=True) as connection:
            _insert_producer_event(connection, event)
            _insert_producer_decision(connection, decision)
        return event

    def append_producer_event_batch_graph(
        self: _HasDatabase,
        *,
        trace: HumanDemonstrationTrace | None,
        actions: tuple[HumanActionEvent, ...],
        action_links: tuple[ActionEvidenceLink, ...],
        action_observations: tuple[ActionResultObservation, ...],
        trigger_candidates: tuple[KeyframeTriggerCandidate, ...],
        producer_events: tuple[ProducerEventEnvelope, ...],
        producer_decisions: tuple[ProducerDecision, ...],
        max_producer_events_per_session: int,
        max_action_events_per_session: int,
        max_pending_trigger_candidates: int,
    ) -> tuple[ProducerEventEnvelope, ...]:
        with self.database.transaction(immediate=True) as connection:
            if producer_events:
                session_id = producer_events[0].session_id
                producer_count = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM active_capture_producer_events
                    WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
                if int(producer_count["count"]) + len(producer_events) > max_producer_events_per_session:
                    raise ValueError("active capture producer event budget exceeded")
                action_count = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM human_action_events
                    WHERE session_id = ?
                    """,
                    (session_id,),
                ).fetchone()
                if int(action_count["count"]) + len(actions) > max_action_events_per_session:
                    raise ValueError("active capture action trace budget exceeded")
                active_status_values = (
                    KeyframeTriggerCandidateStatus.RECEIVED.value,
                    KeyframeTriggerCandidateStatus.ACCEPTED.value,
                )
                active_candidate_count = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM active_capture_trigger_candidates
                    WHERE session_id = ? AND status IN (?, ?)
                    """,
                    (session_id, *active_status_values),
                ).fetchone()
                active_statuses = {
                    KeyframeTriggerCandidateStatus.RECEIVED,
                    KeyframeTriggerCandidateStatus.ACCEPTED,
                }
                planned_active_candidates = sum(
                    1 for candidate in trigger_candidates if candidate.status in active_statuses
                )
                if int(active_candidate_count["count"]) + planned_active_candidates > max_pending_trigger_candidates:
                    raise ValueError("active capture trigger candidate budget exceeded")
            if trace is not None:
                _insert_demonstration_trace(connection, trace)
            for action in actions:
                _insert_human_action(connection, action)
            for link in action_links:
                _insert_action_evidence_link(connection, link)
            for observation in action_observations:
                _insert_action_result_observation(connection, observation)
            for candidate in trigger_candidates:
                _insert_trigger_candidate(connection, candidate)
            for event in producer_events:
                _insert_producer_event(connection, event)
            for decision in producer_decisions:
                _insert_producer_decision(connection, decision)
        return producer_events

    def save_producer_decision(self: _HasDatabase, decision: ProducerDecision) -> ProducerDecision:
        with self.database.transaction() as connection:
            _insert_producer_decision(connection, decision)
        return decision

    def count_producer_events_for_session(self: _HasDatabase, session_id: str) -> int:
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM active_capture_producer_events WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        return int(row["count"])

    def list_producer_events_for_session(
        self: _HasDatabase, session_id: str, *, limit: int | None = None
    ) -> tuple[ProducerEventEnvelope, ...]:
        query = """
                SELECT payload FROM active_capture_producer_events
                WHERE session_id = ?
                ORDER BY occurred_at ASC, producer_event_id ASC
                """
        params: tuple[object, ...] = (session_id,)
        if limit is not None:
            query = f"{query} LIMIT ?"
            params = (*params, limit)
        with self.database.transaction() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(ProducerEventEnvelope.model_validate_json(str(row["payload"])) for row in rows)

    def list_producer_decisions_for_session(
        self: _HasDatabase, session_id: str, *, limit: int | None = None
    ) -> tuple[ProducerDecision, ...]:
        query = """
                SELECT payload FROM active_capture_producer_decisions
                WHERE session_id = ?
                ORDER BY created_at ASC, decision_id ASC
                """
        params: tuple[object, ...] = (session_id,)
        if limit is not None:
            query = f"{query} LIMIT ?"
            params = (*params, limit)
        with self.database.transaction() as connection:
            rows = connection.execute(query, params).fetchall()
        return tuple(ProducerDecision.model_validate_json(str(row["payload"])) for row in rows)

    def get_producer_decision_by_candidate_id(
        self: _HasDatabase, *, session_id: str, candidate_id: str
    ) -> ProducerDecision | None:
        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT payload FROM active_capture_producer_decisions
                WHERE session_id = ? AND candidate_id = ?
                ORDER BY created_at DESC, decision_id DESC
                LIMIT 1
                """,
                (session_id, candidate_id),
            ).fetchone()
        if row is None:
            return None
        return ProducerDecision.model_validate_json(str(row["payload"]))
