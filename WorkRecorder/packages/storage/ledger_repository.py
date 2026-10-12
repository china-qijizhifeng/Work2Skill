"""Repositories for auditable capture runs and evidence provenance."""

from __future__ import annotations

import sqlite3

from packages.contracts import (
    Artifact,
    CaptureAttemptRequest,
    CaptureJob,
    CapturePostCommitOutboxTask,
    ContextEvent,
    EnrichmentRecord,
    EventCaptureEnvelope,
    EvidenceRecord,
    IndexManifest,
)

from .capture_post_commit_outbox_repository import CapturePostCommitOutboxRepository
from .database import SQLiteDatabase
from .ledger_repository_internals import _CaptureLedgerRepositoryInternals


class CaptureLedgerRepository(_CaptureLedgerRepositoryInternals):
    """Persist and query the capture run ledger."""

    def __init__(self, database: SQLiteDatabase) -> None:
        """Create a capture ledger repository.

        Args:
            database: Shared SQLite database wrapper.
        """

        self.database = database

    def save_capture_envelope(
        self,
        *,
        attempt: CaptureAttemptRequest,
        envelope: EventCaptureEnvelope,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        index_text_by_evidence_id: dict[str, str] | None = None,
    ) -> EventCaptureEnvelope:
        """Persist an accepted capture envelope and queryable provenance rows.

        Args:
            attempt: Capture attempt that started the run.
            envelope: Complete auditable capture envelope.
            event: Persisted context event.
            artifacts: Persisted artifacts produced by evidence records.

        Returns:
            The saved envelope.
        """

        with self.database.transaction() as connection:
            self._insert_capture_ledger_rows(
                connection,
                attempt=attempt,
                envelope=envelope,
                event=event,
                artifacts=artifacts,
                index_text_by_evidence_id=index_text_by_evidence_id or {},
            )
        return envelope

    def save_full_capture(
        self,
        *,
        attempt: CaptureAttemptRequest,
        envelope: EventCaptureEnvelope,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        jobs: tuple[CaptureJob, ...],
        index_text_by_evidence_id: dict[str, str],
        post_commit_tasks: tuple[CapturePostCommitOutboxTask, ...] = (),
    ) -> EventCaptureEnvelope:
        """Persist event rows and ledger rows inside one SQLite transaction.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        with self.database.transaction() as connection:
            self._insert_event_artifacts_jobs(connection, event=event, artifacts=artifacts, jobs=jobs)
            self._insert_capture_ledger_rows(
                connection,
                attempt=attempt,
                envelope=envelope,
                event=event,
                artifacts=artifacts,
                index_text_by_evidence_id=index_text_by_evidence_id,
            )
            self._insert_capture_post_commit_tasks(connection, tasks=post_commit_tasks)
        return envelope

    def append_enrichment(
        self,
        *,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        evidence_records: tuple[EvidenceRecord, ...],
        enrichment_records: tuple[EnrichmentRecord, ...],
        index_manifest: IndexManifest,
        index_text_by_evidence_id: dict[str, str],
    ) -> EventCaptureEnvelope:
        """Append derived evidence to an existing capture envelope and query rows.

        Args:
            event: Updated context event after derived evidence is available.
            artifacts: New artifacts produced by the enrichment pass.
            evidence_records: New evidence records to append.
            enrichment_records: Enrichment ledger rows for provenance.
            index_manifest: Updated index manifest including derived evidence.
            index_text_by_evidence_id: Searchable text keyed by evidence id.

        Returns:
            Updated capture envelope after evidence and index rows are persisted.

        Raises:
            RuntimeError: If the target event has no capture envelope.
        """

        envelope = self.get_envelope_by_event_id(event.event_id)
        if envelope is None:
            raise RuntimeError("cannot append enrichment without capture envelope")
        updated = self._envelope_with_enrichment(
            envelope=envelope,
            event=event,
            artifacts=artifacts,
            evidence_records=evidence_records,
            enrichment_records=enrichment_records,
            index_manifest=index_manifest,
        )
        with self.database.transaction() as connection:
            self._insert_event_artifacts_jobs(connection, event=event, artifacts=artifacts, jobs=())
            self._insert_derived_evidence_rows(connection, event=event, artifacts=artifacts, records=evidence_records)
            self._insert_enrichment_rows(connection, event=event, records=enrichment_records)
            self._update_capture_run_envelope(connection, event=event, envelope=updated)
            self._insert_derived_index_rows(
                connection,
                event=event,
                envelope=updated,
                index_manifest=index_manifest,
                index_text_by_evidence_id=index_text_by_evidence_id,
            )
        return updated

    def _envelope_with_enrichment(
        self,
        *,
        envelope: EventCaptureEnvelope,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        evidence_records: tuple[EvidenceRecord, ...],
        enrichment_records: tuple[EnrichmentRecord, ...],
        index_manifest: IndexManifest,
    ) -> EventCaptureEnvelope:
        return envelope.model_copy(
            update={
                "evidence_records": (*envelope.evidence_records, *evidence_records),
                "artifact_ids": (*envelope.artifact_ids, *(artifact.artifact_id for artifact in artifacts)),
                "enrichment_records": (*envelope.enrichment_records, *enrichment_records),
                "index_manifest": index_manifest,
                "context_event": event,
                "updated_at": event.updated_at,
            }
        )

    def _insert_derived_evidence_rows(
        self,
        connection: sqlite3.Connection,
        *,
        event: ContextEvent,
        artifacts: tuple[Artifact, ...],
        records: tuple[EvidenceRecord, ...],
    ) -> None:
        artifact_by_id = {artifact.artifact_id: artifact for artifact in artifacts}
        for evidence in records:
            self._insert_evidence(connection, evidence)
            artifact = artifact_by_id.get(evidence.artifact_id or "")
            if artifact is None:
                continue
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
                    evidence.capture_run_id,
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

    def _insert_enrichment_rows(
        self,
        connection: sqlite3.Connection,
        *,
        event: ContextEvent,
        records: tuple[EnrichmentRecord, ...],
    ) -> None:
        for enrichment in records:
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
                    enrichment.capture_run_id,
                    enrichment.kind.value,
                    enrichment.status,
                    enrichment.model_dump_json(),
                    enrichment.created_at.isoformat(),
                ),
            )

    def _update_capture_run_envelope(
        self,
        connection: sqlite3.Connection,
        *,
        event: ContextEvent,
        envelope: EventCaptureEnvelope,
    ) -> None:
        connection.execute(
            "UPDATE capture_runs SET envelope_payload = ?, updated_at = ? WHERE event_id = ?",
            (envelope.model_dump_json(), event.updated_at.isoformat(), event.event_id),
        )

    def _insert_derived_index_rows(
        self,
        connection: sqlite3.Connection,
        *,
        event: ContextEvent,
        envelope: EventCaptureEnvelope,
        index_manifest: IndexManifest,
        index_text_by_evidence_id: dict[str, str],
    ) -> None:
        evidence_by_id = {record.evidence_id: record for record in envelope.evidence_records}
        for index, evidence_id in enumerate(index_manifest.indexed_evidence_ids):
            text = index_text_by_evidence_id.get(evidence_id)
            matching_evidence = evidence_by_id.get(evidence_id)
            if not text or matching_evidence is None:
                continue
            document_id = (
                index_manifest.canonical_document_ids[index]
                if index < len(index_manifest.canonical_document_ids)
                else f"doc_{evidence_id}"
            )
            chunk_id = (
                index_manifest.document_chunk_ids[index]
                if index < len(index_manifest.document_chunk_ids)
                else f"chk_{evidence_id}_0"
            )
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
                    matching_evidence.capture_run_id,
                    evidence_id,
                    text,
                    matching_evidence.model_dump_json(),
                    event.updated_at.isoformat(),
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
                    matching_evidence.model_dump_json(),
                ),
            )

    def _insert_capture_post_commit_tasks(
        self,
        connection: sqlite3.Connection,
        *,
        tasks: tuple[CapturePostCommitOutboxTask, ...],
    ) -> None:
        if not tasks:
            return
        CapturePostCommitOutboxRepository(self.database).save_many_in_transaction(connection, tasks=tasks)
