"""Internal SQLite row writers and diagnostics readers for the capture ledger."""

from __future__ import annotations

import json
import sqlite3

from packages.contracts import (
    Artifact,
    CaptureAttemptRequest,
    CaptureJob,
    ContextEvent,
    EventCaptureEnvelope,
    EvidenceRecord,
)
from packages.indexing.contracts import IndexReceipt
from packages.storage.database import SQLiteDatabase


class _CaptureLedgerRepositoryInternals:
    """Private mixin that owns detailed ledger SQL row mapping and lookup helpers."""

    database: SQLiteDatabase

    def _insert_event_artifacts_jobs(
        self,
        connection: sqlite3.Connection,
        *,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        jobs: tuple[CaptureJob, ...],
    ) -> None:
        connection.execute(
            """
            INSERT INTO context_events(event_id, status, payload, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
              status = excluded.status,
              payload = excluded.payload,
              updated_at = excluded.updated_at
            """,
            (
                event.event_id,
                event.status.value,
                event.model_dump_json(),
                event.created_at.isoformat(),
                event.updated_at.isoformat(),
            ),
        )
        for artifact in artifacts:
            connection.execute(
                """
                INSERT INTO artifacts(artifact_id, event_id, artifact_type, payload, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                  event_id = excluded.event_id,
                  artifact_type = excluded.artifact_type,
                  payload = excluded.payload
                """,
                (
                    artifact.artifact_id,
                    artifact.event_id,
                    artifact.artifact_type.value,
                    artifact.model_dump_json(),
                    artifact.created_at.isoformat(),
                ),
            )
        for job in jobs:
            connection.execute(
                """
                INSERT INTO capture_jobs(job_id, event_id, job_type, status, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id, job_type) DO UPDATE SET
                  job_id = excluded.job_id,
                  status = excluded.status,
                  payload = excluded.payload,
                  updated_at = excluded.updated_at
                """,
                (
                    job.job_id,
                    job.event_id,
                    job.job_type.value,
                    job.status.value,
                    job.model_dump_json(),
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                ),
            )

    def _insert_capture_ledger_rows(
        self,
        connection: sqlite3.Connection,
        *,
        attempt: CaptureAttemptRequest,
        envelope: EventCaptureEnvelope,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        index_text_by_evidence_id: dict[str, str],
    ) -> None:
        artifact_by_id = {artifact.artifact_id: artifact for artifact in artifacts}
        evidence_by_id = {evidence.evidence_id: evidence for evidence in envelope.evidence_records}
        connection.execute(
            """
            INSERT OR REPLACE INTO capture_attempts(
              trigger_id, actor_id, workspace_id, status, occurred_at,
              selection_payload, payload, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                attempt.trigger.trigger_id,
                attempt.actor.actor_id,
                attempt.workspace.workspace_id,
                "accepted",
                attempt.trigger.occurred_at.isoformat(),
                attempt.selection_geometry.model_dump_json(),
                attempt.model_dump_json(),
                envelope.created_at.isoformat(),
            ),
        )
        connection.execute(
            """
            INSERT OR REPLACE INTO capture_runs(
              capture_run_id, trigger_id, event_id, status,
              primary_source_binding_id, envelope_payload, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                envelope.capture_run_id,
                attempt.trigger.trigger_id,
                event.event_id,
                event.status.value,
                event.source_binding.binding_id,
                envelope.model_dump_json(),
                envelope.created_at.isoformat(),
                envelope.updated_at.isoformat(),
            ),
        )
        for surface in envelope.detected_surfaces:
            connection.execute(
                """
                INSERT OR REPLACE INTO detected_surfaces(
                  surface_id, capture_run_id, app_name, surface_kind,
                  process_id, window_id, overlap_ratio, confidence, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    surface.surface_id,
                    envelope.capture_run_id,
                    surface.app_name,
                    surface.kind,
                    surface.process_id,
                    surface.window_id,
                    surface.overlap_ratio,
                    surface.confidence,
                    surface.model_dump_json(),
                ),
            )
        for route in envelope.provider_routes:
            connection.execute(
                """
                INSERT OR REPLACE INTO provider_routes(
                  route_id, capture_run_id, provider_key, provider_kind,
                  route_role, surface_id, selected, confidence, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    route.route_id,
                    envelope.capture_run_id,
                    route.provider_key,
                    route.provider_kind.value,
                    route.role.value,
                    route.surface_id,
                    int(route.selected),
                    route.confidence,
                    route.model_dump_json(),
                ),
            )
        for source_binding in envelope.source_bindings:
            connection.execute(
                """
                INSERT OR REPLACE INTO capture_run_source_bindings(
                  source_binding_id, capture_run_id, source_type, title, provider_key, payload
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    source_binding.binding_id,
                    envelope.capture_run_id,
                    source_binding.source_ref.source_type.value,
                    source_binding.source_ref.title,
                    source_binding.provider_key,
                    source_binding.model_dump_json(),
                ),
            )
        for command in envelope.provider_command_runs:
            connection.execute(
                """
                INSERT OR REPLACE INTO provider_command_runs(
                  command_id, capture_run_id, provider_key, provider_session_id,
                  route_id, evidence_kind, status, sent_at, completed_at, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command.command_id,
                    envelope.capture_run_id,
                    command.provider_key,
                    command.provider_session_id,
                    command.route_id,
                    command.evidence_kind.value,
                    command.status.value,
                    command.sent_at.isoformat() if command.sent_at else None,
                    command.completed_at.isoformat() if command.completed_at else None,
                    command.model_dump_json(),
                ),
            )
        for index, outcome in enumerate(envelope.provider_outcomes):
            connection.execute(
                """
                INSERT OR REPLACE INTO provider_capture_outcomes(
                  outcome_id, capture_run_id, route_id, provider_key, provider_kind,
                  route_role, surface_id, status, command_id, provider_session_id, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"{envelope.capture_run_id}:outcome:{index + 1}",
                    envelope.capture_run_id,
                    outcome.route_id,
                    outcome.provider_key,
                    outcome.provider_kind.value,
                    outcome.role.value,
                    outcome.surface_id,
                    outcome.status.value,
                    outcome.command_id,
                    outcome.provider_session_id,
                    outcome.model_dump_json(),
                ),
            )
        for bundle in envelope.evidence_bundles:
            connection.execute(
                """
                INSERT OR REPLACE INTO evidence_bundle_records(
                  bundle_id, capture_run_id, provider_key, provider_kind, evidence_kind,
                  status, route_role, route_id, command_id, source_binding_id, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bundle.bundle_id,
                    envelope.capture_run_id,
                    bundle.provider_key,
                    bundle.provider_kind.value,
                    bundle.evidence_kind.value,
                    bundle.status.value,
                    bundle.role.value,
                    bundle.route_id,
                    bundle.command_id,
                    bundle.source_binding_id,
                    bundle.model_dump_json(),
                ),
            )
        for evidence in envelope.evidence_records:
            self._insert_evidence(connection, evidence)
            if evidence.artifact_id is not None and evidence.artifact_id in artifact_by_id:
                artifact = artifact_by_id[evidence.artifact_id]
                connection.execute(
                    """
                    INSERT OR REPLACE INTO artifact_provenance(
                      artifact_id, evidence_id, event_id, capture_run_id,
                      provider_key, provider_session_id, command_id, source_uri,
                      sha256, storage_uri, extractor_name, extractor_version, payload
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact.artifact_id,
                        evidence.evidence_id,
                        event.event_id,
                        envelope.capture_run_id,
                        evidence.provenance.provider_key,
                        evidence.provenance.provider_session_id,
                        evidence.provenance.command_id,
                        evidence.locator.source_uri,
                        artifact.sha256,
                        artifact.storage_uri,
                        evidence.provenance.extractor.name,
                        evidence.provenance.extractor.version,
                        evidence.model_dump_json(),
                    ),
                )
        for enrichment in envelope.enrichment_records:
            connection.execute(
                """
                INSERT OR REPLACE INTO enrichment_runs(
                  enrichment_id, event_id, capture_run_id, kind, status, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    enrichment.enrichment_id,
                    event.event_id,
                    envelope.capture_run_id,
                    enrichment.kind.value,
                    enrichment.status,
                    enrichment.model_dump_json(),
                    enrichment.created_at.isoformat(),
                ),
            )
        for index, evidence_id in enumerate(envelope.index_manifest.indexed_evidence_ids):
            chunk_id = (
                envelope.index_manifest.document_chunk_ids[index]
                if index < len(envelope.index_manifest.document_chunk_ids)
                else f"chk_{evidence_id}_0"
            )
            indexed_evidence = evidence_by_id.get(evidence_id)
            document_id = (
                envelope.index_manifest.canonical_document_ids[index]
                if index < len(envelope.index_manifest.canonical_document_ids)
                else f"doc_{evidence_id}"
            )
            text = index_text_by_evidence_id.get(evidence_id, "")
            if indexed_evidence is None or not text:
                continue
            connection.execute(
                """
                INSERT OR REPLACE INTO canonical_documents(
                  document_id, event_id, capture_run_id, evidence_id, text, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    event.event_id,
                    envelope.capture_run_id,
                    evidence_id,
                    text,
                    indexed_evidence.model_dump_json(),
                    envelope.created_at.isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO document_chunks(
                  chunk_id, document_id, event_id, evidence_id, ordinal, text, payload
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id,
                    document_id,
                    event.event_id,
                    evidence_id,
                    0,
                    text,
                    indexed_evidence.model_dump_json(),
                ),
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO index_records(
                  index_id, event_id, capture_run_id, evidence_id, index_kind, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"idx_{chunk_id}",
                    event.event_id,
                    envelope.capture_run_id,
                    evidence_id,
                    "fts",
                    envelope.index_manifest.model_dump_json(),
                    envelope.created_at.isoformat(),
                ),
            )

    def save_unsupported_attempt(
        self,
        *,
        attempt: CaptureAttemptRequest,
        capture_run_id: str,
        status: str,
        envelope_payload: str,
        created_at: str,
    ) -> None:
        """Persist diagnostics for attempts that do not create events.

        Args:
            See the typed signature for the accepted parameters and validation boundary."""

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO capture_attempts(
                  trigger_id, actor_id, workspace_id, status, occurred_at,
                  selection_payload, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt.trigger.trigger_id,
                    attempt.actor.actor_id,
                    attempt.workspace.workspace_id,
                    status,
                    attempt.trigger.occurred_at.isoformat(),
                    attempt.selection_geometry.model_dump_json(),
                    attempt.model_dump_json(),
                    created_at,
                ),
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO capture_runs(
                  capture_run_id, trigger_id, event_id, status,
                  primary_source_binding_id, envelope_payload, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    capture_run_id,
                    attempt.trigger.trigger_id,
                    None,
                    status,
                    None,
                    envelope_payload,
                    created_at,
                    created_at,
                ),
            )

    def get_envelope_by_event_id(self, event_id: str) -> EventCaptureEnvelope | None:
        """Return a capture envelope by event id.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT envelope_payload FROM capture_runs WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        return EventCaptureEnvelope.model_validate_json(str(row["envelope_payload"]))

    def get_envelope_by_trigger_id(self, trigger_id: str) -> EventCaptureEnvelope | None:
        """Return a capture envelope by trigger id when it produced an event.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT envelope_payload FROM capture_runs WHERE trigger_id = ? ORDER BY created_at DESC LIMIT 1",
                (trigger_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            return EventCaptureEnvelope.model_validate_json(str(row["envelope_payload"]))
        except ValueError:
            return None

    def get_capture_diagnostics_by_trigger_id(self, trigger_id: str) -> dict[str, object] | None:
        """Return raw run diagnostics for accepted or unsupported attempts.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT capture_run_id, trigger_id, event_id, status, envelope_payload, created_at, updated_at
                FROM capture_runs
                WHERE trigger_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (trigger_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            payload: object = json.loads(str(row["envelope_payload"]))
        except json.JSONDecodeError:
            payload = {"raw": str(row["envelope_payload"])}
        return {
            "capture_run_id": str(row["capture_run_id"]),
            "trigger_id": str(row["trigger_id"]),
            "event_id": row["event_id"],
            "status": str(row["status"]),
            "payload": payload,
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }

    def add_audit_ref(self, *, event_id: str, audit_id: str) -> None:
        """Append a route-level audit id into the stored event envelope.

        Args:
            See the typed signature for the accepted parameters and validation boundary."""

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT envelope_payload FROM capture_runs WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                return
            envelope = EventCaptureEnvelope.model_validate_json(str(row["envelope_payload"]))
            refs = tuple(dict.fromkeys((*envelope.audit_refs, audit_id)))
            updated = envelope.model_copy(update={"audit_refs": refs})
            connection.execute(
                "UPDATE capture_runs SET envelope_payload = ?, updated_at = ? WHERE event_id = ?",
                (updated.model_dump_json(), updated.updated_at.isoformat(), event_id),
            )

    def save_index_receipt(self, *, event_id: str, capture_run_id: str, receipt: IndexReceipt) -> None:
        """Persist an auditable index backend receipt.

        Args:
            See the typed signature for the accepted parameters and validation boundary."""

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO index_records(
                  index_id, event_id, capture_run_id, evidence_id, index_kind, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    f"idx_receipt_{receipt.backend}_{event_id}",
                    event_id,
                    capture_run_id,
                    "__index_receipt__",
                    receipt.backend,
                    receipt.model_dump_json(),
                ),
            )

    def list_evidence_for_event(self, event_id: str) -> tuple[EvidenceRecord, ...]:
        """List evidence records for one event in ingest order.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT payload FROM evidence_records WHERE event_id = ? ORDER BY ingested_at ASC",
                (event_id,),
            ).fetchall()
        return tuple(EvidenceRecord.model_validate_json(str(row["payload"])) for row in rows)

    def get_evidence(self, evidence_id: str) -> EvidenceRecord | None:
        """Return one evidence record by id.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM evidence_records WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
        if row is None:
            return None
        return EvidenceRecord.model_validate_json(str(row["payload"]))

    def search_canonical_event_ids(self, *, query: str, limit: int) -> tuple[str, ...]:
        """Return event ids whose canonical chunks contain a query.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT event_id
                FROM document_chunks
                WHERE lower(text) LIKE ?
                ORDER BY event_id
                LIMIT ?
                """,
                (f"%{query.lower()}%", limit),
            ).fetchall()
        return tuple(str(row["event_id"]) for row in rows)

    def _insert_evidence(self, connection: sqlite3.Connection, evidence: EvidenceRecord) -> None:
        connection.execute(
            """
            INSERT OR REPLACE INTO evidence_records(
              evidence_id, event_id, capture_run_id, phase, evidence_kind,
              artifact_id, artifact_type, role, provider_key, provider_session_id,
              command_id, source_uri, observed_at, captured_at, ingested_at,
              sensitivity, trust_state, ingest_state, redaction_state, indexable, payload
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence.evidence_id,
                evidence.event_id,
                evidence.capture_run_id,
                evidence.phase.value,
                evidence.kind.value,
                evidence.artifact_id,
                evidence.artifact_type.value,
                evidence.role.value,
                evidence.provenance.provider_key,
                evidence.provenance.provider_session_id,
                evidence.provenance.command_id,
                evidence.locator.source_uri,
                evidence.observed_at.isoformat(),
                evidence.captured_at.isoformat(),
                evidence.ingested_at.isoformat(),
                evidence.sensitivity.value,
                evidence.trust_state.value,
                evidence.ingest_state.value,
                evidence.redaction_state.value,
                int(evidence.indexable),
                evidence.model_dump_json(),
            ),
        )
