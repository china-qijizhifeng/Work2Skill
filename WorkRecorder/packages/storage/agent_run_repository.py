"""Repositories for agent-run usage trace ledgers."""

from __future__ import annotations

import sqlite3
from typing import TypeVar

from packages.contracts import (
    AgentRun,
    AgentRunReplay,
    AgentUsageEventV2,
    AnswerRecord,
    CitationRecord,
    ContextQuery,
    DeliveredContextItem,
    DeliveredContextSnapshot,
    RetrievalCall,
    RiskAdvisoryRecord,
)
from packages.contracts.base import ContractModel

from .database import SQLiteDatabase

TContract = TypeVar("TContract", bound=ContractModel)


class AgentRunLedgerRepository:
    """Persist and replay agent-facing retrieval traces."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save_run(self, run: AgentRun) -> AgentRun:
        """Insert or update one agent run.

        Args:
            run: Agent run contract to persist.

        Returns:
            The same run contract after the database write succeeds.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO agent_runs(
                  agent_run_id, actor_id, agent, purpose, origin, status,
                  workspace_id, user_question_hash, payload, started_at, last_seen_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_run_id) DO UPDATE SET
                  actor_id = excluded.actor_id,
                  agent = excluded.agent,
                  purpose = excluded.purpose,
                  origin = excluded.origin,
                  status = excluded.status,
                  workspace_id = excluded.workspace_id,
                  user_question_hash = excluded.user_question_hash,
                  payload = excluded.payload,
                  last_seen_at = excluded.last_seen_at,
                  completed_at = excluded.completed_at
                """,
                (
                    run.agent_run_id,
                    run.actor.actor_id,
                    run.agent,
                    run.purpose,
                    run.origin.value,
                    run.status.value,
                    run.workspace_id,
                    run.user_question_hash,
                    run.model_dump_json(),
                    run.started_at.isoformat(),
                    run.last_seen_at.isoformat(),
                    run.completed_at.isoformat() if run.completed_at else None,
                ),
            )
        return run

    def get_run(self, agent_run_id: str) -> AgentRun | None:
        """Return one run by id.

        Args:
            agent_run_id: Primary key of the run.

        Returns:
            Agent run when present, otherwise ``None``.
        """

        row = self._payload_row("agent_runs", "agent_run_id", agent_run_id)
        return AgentRun.model_validate_json(str(row["payload"])) if row is not None else None

    def save_context_query(self, query: ContextQuery) -> ContextQuery:
        """Persist one query/intention row.

        Args:
            query: Context query contract to persist.

        Returns:
            The same query contract after the database write succeeds.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO context_queries(
                  context_query_id, agent_run_id, query_hash, purpose, workspace_id, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(context_query_id) DO UPDATE SET
                  agent_run_id = excluded.agent_run_id,
                  query_hash = excluded.query_hash,
                  purpose = excluded.purpose,
                  workspace_id = excluded.workspace_id,
                  payload = excluded.payload,
                  created_at = excluded.created_at
                """,
                (
                    query.context_query_id,
                    query.agent_run_id,
                    query.query_hash,
                    query.purpose,
                    query.workspace_id,
                    query.model_dump_json(),
                    query.created_at.isoformat(),
                ),
            )
        return query

    def get_context_query(self, context_query_id: str) -> ContextQuery | None:
        """Return one query row by id.

        Args:
            context_query_id: Primary key of the query row.

        Returns:
            Context query when present, otherwise ``None``.
        """

        row = self._payload_row("context_queries", "context_query_id", context_query_id)
        return ContextQuery.model_validate_json(str(row["payload"])) if row is not None else None

    def save_citation(self, citation: CitationRecord) -> CitationRecord:
        """Persist one citation record.

        Args:
            citation: Citation contract to persist.

        Returns:
            The same citation contract after the database write succeeds.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO citation_records(
                  citation_id, agent_run_id, event_id, evidence_id, artifact_id, chunk_id,
                  state, source_snapshot_id, source_retrieval_call_id, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(citation_id) DO UPDATE SET
                  agent_run_id = excluded.agent_run_id,
                  event_id = excluded.event_id,
                  evidence_id = excluded.evidence_id,
                  artifact_id = excluded.artifact_id,
                  chunk_id = excluded.chunk_id,
                  state = excluded.state,
                  source_snapshot_id = excluded.source_snapshot_id,
                  source_retrieval_call_id = excluded.source_retrieval_call_id,
                  payload = excluded.payload
                """,
                (
                    citation.citation_id,
                    citation.agent_run_id,
                    citation.event_id,
                    citation.evidence_id,
                    citation.artifact_id,
                    citation.chunk_id,
                    citation.state.value,
                    citation.source_snapshot_id,
                    citation.source_retrieval_call_id,
                    citation.model_dump_json(),
                    citation.created_at.isoformat(),
                ),
            )
        return citation

    def get_citation(self, citation_id: str) -> CitationRecord | None:
        """Return one citation.

        Args:
            citation_id: Primary key of the citation.

        Returns:
            Citation record when present, otherwise ``None``.
        """

        row = self._payload_row("citation_records", "citation_id", citation_id)
        return CitationRecord.model_validate_json(str(row["payload"])) if row is not None else None

    def save_answer(self, answer: AnswerRecord) -> AnswerRecord:
        """Persist one final answer pointer.

        Args:
            answer: Answer pointer and hash contract to persist.

        Returns:
            The same answer contract after the database write succeeds.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO answer_records(answer_id, agent_run_id, output_ref, answer_hash, payload, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(answer_id) DO UPDATE SET
                  agent_run_id = excluded.agent_run_id,
                  output_ref = excluded.output_ref,
                  answer_hash = excluded.answer_hash,
                  payload = excluded.payload
                """,
                (
                    answer.answer_id,
                    answer.agent_run_id,
                    answer.output_ref,
                    answer.answer_hash,
                    answer.model_dump_json(),
                    answer.created_at.isoformat(),
                ),
            )
        return answer

    def save_risk_advisory(self, advisory: RiskAdvisoryRecord) -> RiskAdvisoryRecord:
        """Persist one high-risk advisory.

        Args:
            advisory: Risk advisory contract to persist.

        Returns:
            The same advisory contract after the database write succeeds.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO risk_advisory_records(
                  risk_advisory_id, agent_run_id, category, severity, action_state, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(risk_advisory_id) DO UPDATE SET
                  agent_run_id = excluded.agent_run_id,
                  category = excluded.category,
                  severity = excluded.severity,
                  action_state = excluded.action_state,
                  payload = excluded.payload
                """,
                (
                    advisory.risk_advisory_id,
                    advisory.agent_run_id,
                    advisory.category.value,
                    advisory.severity.value,
                    advisory.action_state.value,
                    advisory.model_dump_json(),
                    advisory.created_at.isoformat(),
                ),
            )
        return advisory

    def save_usage(self, usage: AgentUsageEventV2) -> AgentUsageEventV2:
        """Persist one v2 usage cover.

        Args:
            usage: Usage cover contract to persist.

        Returns:
            The same usage contract after the database write succeeds.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO agent_usage_events_v2(
                  usage_id, agent_run_id, agent, purpose, output_ref, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(usage_id) DO UPDATE SET
                  agent_run_id = excluded.agent_run_id,
                  agent = excluded.agent,
                  purpose = excluded.purpose,
                  output_ref = excluded.output_ref,
                  payload = excluded.payload
                """,
                (
                    usage.usage_id,
                    usage.agent_run_id,
                    usage.agent,
                    usage.purpose,
                    usage.output_ref,
                    usage.model_dump_json(),
                    usage.created_at.isoformat(),
                ),
            )
        return usage

    def link_audit(
        self,
        *,
        agent_run_id: str,
        audit_id: str,
        request_id: str,
        resource_type: str,
        resource_id: str | None,
        created_at: str,
    ) -> None:
        """Link an audit event to an agent run.

        Args:
            agent_run_id: Run id that owns the audit link.
            audit_id: Audit event id from the disclosure or raw gate.
            request_id: API request id that produced the audit event.
            resource_type: Logical resource type such as event or artifact.
            resource_id: Optional resource id associated with the audit event.
            created_at: ISO timestamp for the link.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO agent_run_audit_links(
                  agent_run_id, audit_id, request_id, resource_type, resource_id, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(agent_run_id, audit_id) DO UPDATE SET
                  request_id = excluded.request_id,
                  resource_type = excluded.resource_type,
                  resource_id = excluded.resource_id,
                  created_at = excluded.created_at
                """,
                (agent_run_id, audit_id, request_id, resource_type, resource_id, created_at),
            )

    def replay(self, agent_run_id: str) -> AgentRunReplay | None:
        """Return all replay rows for one run.

        Args:
            agent_run_id: Run id to replay.

        Returns:
            Aggregated replay contract, or ``None`` when the run is missing.
        """

        run = self.get_run(agent_run_id)
        if run is None:
            return None
        return AgentRunReplay(
            agent_run=run,
            context_queries=self._list("context_queries", "agent_run_id", agent_run_id, ContextQuery),
            retrieval_calls=self._list("retrieval_calls", "agent_run_id", agent_run_id, RetrievalCall),
            snapshots=self._list("delivered_context_snapshots", "agent_run_id", agent_run_id, DeliveredContextSnapshot),
            snapshot_items=self._snapshot_items(agent_run_id),
            citations=self._list("citation_records", "agent_run_id", agent_run_id, CitationRecord),
            answers=self._list("answer_records", "agent_run_id", agent_run_id, AnswerRecord),
            risk_advisories=self._list("risk_advisory_records", "agent_run_id", agent_run_id, RiskAdvisoryRecord),
            usage_events=self._list("agent_usage_events_v2", "agent_run_id", agent_run_id, AgentUsageEventV2),
        )

    def latest_active_run(self, *, actor_id: str) -> AgentRun | None:
        """Return the newest active run for an actor.

        Args:
            actor_id: Actor id whose active run should be reused.

        Returns:
            Newest active run for the actor, otherwise ``None``.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT payload FROM agent_runs
                WHERE actor_id = ? AND status = 'active'
                ORDER BY last_seen_at DESC
                LIMIT 1
                """,
                (actor_id,),
            ).fetchone()
        return AgentRun.model_validate_json(str(row["payload"])) if row is not None else None

    def _payload_row(self, table: str, key: str, value: str) -> sqlite3.Row | None:
        """Fetch a single payload row from a keyed ledger table.

        Args:
            table: Ledger table name.
            key: Column name used for lookup.
            value: Lookup value.

        Returns:
            SQLite row with a ``payload`` column, or ``None``.
        """

        with self.database.transaction() as connection:
            row: sqlite3.Row | None = connection.execute(
                f"SELECT payload FROM {table} WHERE {key} = ?", (value,)
            ).fetchone()
            return row

    def _list(self, table: str, key: str, value: str, model: type[TContract]) -> tuple[TContract, ...]:
        """List typed contracts from one ledger table.

        Args:
            table: Ledger table name.
            key: Column name used for lookup.
            value: Lookup value.
            model: Contract model used to parse each JSON payload.

        Returns:
            Ordered contract rows.
        """

        with self.database.transaction() as connection:
            rows = connection.execute(
                f"SELECT payload FROM {table} WHERE {key} = ? ORDER BY created_at ASC",
                (value,),
            ).fetchall()
        return tuple(model.model_validate_json(str(row["payload"])) for row in rows)

    def _snapshot_items(self, agent_run_id: str) -> tuple[DeliveredContextItem, ...]:
        """List delivered snapshot items for one run.

        Args:
            agent_run_id: Run id whose delivered items should be returned.

        Returns:
            Ordered delivered context item contracts.
        """

        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT item.payload
                FROM delivered_context_items item
                JOIN delivered_context_snapshots snapshot ON snapshot.snapshot_id = item.snapshot_id
                WHERE snapshot.agent_run_id = ?
                ORDER BY snapshot.created_at ASC, item.item_id ASC
                """,
                (agent_run_id,),
            ).fetchall()
        return tuple(DeliveredContextItem.model_validate_json(str(row["payload"])) for row in rows)
