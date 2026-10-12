"""Atomic persistence for agent-run delivery traces."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable

from packages.contracts import CitationRecord, DeliveredContextItem, DeliveredContextSnapshot, RetrievalCall

from .database import SQLiteDatabase


class AgentRunTraceRepository:
    """Persist retrieval calls, delivered snapshots, and citation source links."""

    def __init__(self, database: SQLiteDatabase) -> None:
        """Create a trace repository.

        Args:
            database: Shared SQLite database wrapper.
        """

        self.database = database

    def save_delivery_trace(
        self,
        *,
        call: RetrievalCall,
        snapshot: DeliveredContextSnapshot,
        items: Iterable[DeliveredContextItem],
        audit_link: dict[str, str | None] | None = None,
    ) -> None:
        """Atomically persist one retrieval call, snapshot, items, and links.

        Args:
            call: Retrieval call ledger row.
            snapshot: Safe replay snapshot for the call.
            items: Delivered item index rows extracted from the snapshot.
            audit_link: Optional audit id linkage written in the same transaction.
        """

        item_rows = tuple(items)
        citation_ids = tuple(item.citation_id for item in item_rows if item.citation_id)
        with self.database.transaction() as connection:
            self._upsert_retrieval_call(connection, call)
            self._upsert_snapshot(connection, snapshot)
            for item in item_rows:
                self._upsert_snapshot_item(connection, item)
            for citation_id in citation_ids:
                self._attach_citation_source(
                    connection,
                    citation_id=citation_id,
                    snapshot_id=snapshot.snapshot_id,
                    retrieval_call_id=call.retrieval_call_id,
                )
            if audit_link and audit_link.get("audit_id"):
                self._upsert_audit_link(connection, audit_link)

    def has_delivered_artifact(self, *, agent_run_id: str, artifact_id: str) -> bool:
        """Return whether an artifact ref was delivered in a run snapshot.

        Args:
            agent_run_id: Agent run being checked.
            artifact_id: Artifact that a raw endpoint wants to disclose.

        Returns:
            True when a prior same-run snapshot delivered this artifact id.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM delivered_context_items item
                JOIN delivered_context_snapshots snapshot ON snapshot.snapshot_id = item.snapshot_id
                WHERE snapshot.agent_run_id = ? AND item.artifact_id = ?
                LIMIT 1
                """,
                (agent_run_id, artifact_id),
            ).fetchone()
        return row is not None

    def has_successful_screenshot_ref_delivery(self, *, agent_run_id: str, artifact_id: str, event_id: str) -> bool:
        """Return whether a successful event-inspect call delivered a screenshot ref.

        Raw screenshot access is allowed only after the same agent run has
        received a screenshot/artifact reference through an agent-facing
        event-inspect path. Workbench prefetch/inspection is intentionally
        excluded so UI thumbnails cannot silently prime raw access. Denied raw
        attempts deliberately do not satisfy this prerequisite.

        Args:
            agent_run_id: Agent run being checked.
            artifact_id: Screenshot artifact id.
            event_id: Event id that the raw request is bound to.

        Returns:
            True only for a previous successful event-inspect delivery.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM delivered_context_items item
                JOIN delivered_context_snapshots snapshot ON snapshot.snapshot_id = item.snapshot_id
                JOIN retrieval_calls call ON call.retrieval_call_id = snapshot.retrieval_call_id
                WHERE snapshot.agent_run_id = ?
                  AND item.artifact_id = ?
                  AND item.disclosure_class = 'raw_visual'
                  AND call.status = 'succeeded'
                  AND call.kind = 'event_inspect'
                  AND call.purpose NOT LIKE 'workbench_%'
                  AND EXISTS (
                    SELECT 1
                    FROM delivered_context_items event_item
                    WHERE event_item.snapshot_id = snapshot.snapshot_id
                      AND event_item.event_id = ?
                  )
                LIMIT 1
                """,
                (agent_run_id, artifact_id, event_id),
            ).fetchone()
        return row is not None

    def _upsert_audit_link(self, connection: sqlite3.Connection, audit_link: dict[str, str | None]) -> None:
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
            (
                audit_link["agent_run_id"],
                audit_link["audit_id"],
                audit_link["request_id"],
                audit_link["resource_type"],
                audit_link["resource_id"],
                audit_link["created_at"],
            ),
        )

    def _upsert_retrieval_call(self, connection: sqlite3.Connection, call: RetrievalCall) -> None:
        connection.execute(
            """
            INSERT INTO retrieval_calls(
              retrieval_call_id, agent_run_id, context_query_id, request_id, kind,
              resource_type, resource_id, purpose, request_hash, response_hash,
              status, payload, created_at, completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(retrieval_call_id) DO UPDATE SET
              agent_run_id = excluded.agent_run_id,
              context_query_id = excluded.context_query_id,
              request_id = excluded.request_id,
              kind = excluded.kind,
              resource_type = excluded.resource_type,
              resource_id = excluded.resource_id,
              purpose = excluded.purpose,
              request_hash = excluded.request_hash,
              response_hash = excluded.response_hash,
              status = excluded.status,
              payload = excluded.payload,
              completed_at = excluded.completed_at
            """,
            (
                call.retrieval_call_id,
                call.agent_run_id,
                call.context_query_id,
                call.request_id,
                call.kind.value,
                call.resource_type,
                call.resource_id,
                call.purpose,
                call.request_hash,
                call.response_hash,
                call.status,
                call.model_dump_json(),
                call.created_at.isoformat(),
                call.completed_at.isoformat() if call.completed_at else None,
            ),
        )

    def _upsert_snapshot(self, connection: sqlite3.Connection, snapshot: DeliveredContextSnapshot) -> None:
        connection.execute(
            """
            INSERT INTO delivered_context_snapshots(
              snapshot_id, agent_run_id, retrieval_call_id, context_query_id, kind,
              payload_hash, byte_size, item_count, payload, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(snapshot_id) DO UPDATE SET
              agent_run_id = excluded.agent_run_id,
              retrieval_call_id = excluded.retrieval_call_id,
              context_query_id = excluded.context_query_id,
              kind = excluded.kind,
              payload_hash = excluded.payload_hash,
              byte_size = excluded.byte_size,
              item_count = excluded.item_count,
              payload = excluded.payload,
              created_at = excluded.created_at
            """,
            (
                snapshot.snapshot_id,
                snapshot.agent_run_id,
                snapshot.retrieval_call_id,
                snapshot.context_query_id,
                snapshot.kind.value,
                snapshot.payload_hash,
                snapshot.byte_size,
                snapshot.item_count,
                snapshot.model_dump_json(),
                snapshot.created_at.isoformat(),
            ),
        )

    def _upsert_snapshot_item(self, connection: sqlite3.Connection, item: DeliveredContextItem) -> None:
        connection.execute(
            """
            INSERT INTO delivered_context_items(
              item_id, snapshot_id, event_id, evidence_id, artifact_id, citation_id,
              field_path, disclosure_class, text_hash, payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(item_id) DO UPDATE SET
              snapshot_id = excluded.snapshot_id,
              event_id = excluded.event_id,
              evidence_id = excluded.evidence_id,
              artifact_id = excluded.artifact_id,
              citation_id = excluded.citation_id,
              field_path = excluded.field_path,
              disclosure_class = excluded.disclosure_class,
              text_hash = excluded.text_hash,
              payload = excluded.payload
            """,
            (
                item.item_id,
                item.snapshot_id,
                item.event_id,
                item.evidence_id,
                item.artifact_id,
                item.citation_id,
                item.field_path,
                item.disclosure_class,
                item.text_hash,
                item.model_dump_json(),
            ),
        )

    def _attach_citation_source(
        self,
        connection: sqlite3.Connection,
        *,
        citation_id: str,
        snapshot_id: str,
        retrieval_call_id: str,
    ) -> None:
        row = connection.execute(
            "SELECT payload FROM citation_records WHERE citation_id = ?", (citation_id,)
        ).fetchone()
        if row is None:
            return
        citation = CitationRecord.model_validate_json(str(row["payload"]))
        updated = citation.model_copy(
            update={"source_snapshot_id": snapshot_id, "source_retrieval_call_id": retrieval_call_id}
        )
        connection.execute(
            """
            UPDATE citation_records
            SET source_snapshot_id = ?, source_retrieval_call_id = ?, payload = ?
            WHERE citation_id = ?
            """,
            (snapshot_id, retrieval_call_id, updated.model_dump_json(), citation_id),
        )
