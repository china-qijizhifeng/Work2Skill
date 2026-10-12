"""SQLite schema migrations for the WorkRecorder P0 skeleton."""

from __future__ import annotations

from .database import SQLiteDatabase
from .share_migrations import SHARE_SCHEMA_STATEMENTS


class MigrationRunner:
    """Apply idempotent P0 SQLite schema migrations."""

    def __init__(self, database: SQLiteDatabase) -> None:
        """Create a migration runner.

        Args:
            database: Database wrapper to migrate.
        """

        self.database = database

    def apply(self) -> None:
        """Create all P0 tables when they do not already exist."""

        with self.database.transaction() as connection:
            for statement in self._statements():
                connection.execute(statement)

    def _statements(self) -> tuple[str, ...]:
        return _SCHEMA_STATEMENTS


_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS context_events (
      event_id TEXT PRIMARY KEY,
      status TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS artifacts (
      artifact_id TEXT PRIMARY KEY,
      event_id TEXT NOT NULL,
      artifact_type TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(event_id) REFERENCES context_events(event_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS policy_decisions (
      decision_id TEXT PRIMARY KEY,
      effect TEXT NOT NULL,
      payload TEXT NOT NULL,
      evaluated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log_events (
      audit_id TEXT PRIMARY KEY,
      request_id TEXT NOT NULL,
      action TEXT NOT NULL,
      resource_type TEXT NOT NULL,
      resource_id TEXT,
      success INTEGER NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_bundles (
      bundle_id TEXT PRIMARY KEY,
      query TEXT NOT NULL,
      purpose TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_usage_events (
      usage_id TEXT PRIMARY KEY,
      bundle_id TEXT NOT NULL,
      agent TEXT NOT NULL,
      purpose TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(bundle_id) REFERENCES context_bundles(bundle_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_runs (
      agent_run_id TEXT PRIMARY KEY,
      actor_id TEXT NOT NULL,
      agent TEXT NOT NULL,
      purpose TEXT NOT NULL,
      origin TEXT NOT NULL,
      status TEXT NOT NULL,
      workspace_id TEXT,
      user_question_hash TEXT,
      payload TEXT NOT NULL,
      started_at TEXT NOT NULL,
      last_seen_at TEXT NOT NULL,
      completed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_queries (
      context_query_id TEXT PRIMARY KEY,
      agent_run_id TEXT NOT NULL,
      query_hash TEXT NOT NULL,
      purpose TEXT NOT NULL,
      workspace_id TEXT,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(agent_run_id) REFERENCES agent_runs(agent_run_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS retrieval_calls (
      retrieval_call_id TEXT PRIMARY KEY,
      agent_run_id TEXT NOT NULL,
      context_query_id TEXT,
      request_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      resource_type TEXT NOT NULL,
      resource_id TEXT,
      purpose TEXT NOT NULL,
      request_hash TEXT NOT NULL,
      response_hash TEXT,
      status TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      completed_at TEXT,
      FOREIGN KEY(agent_run_id) REFERENCES agent_runs(agent_run_id) ON DELETE CASCADE,
      FOREIGN KEY(context_query_id) REFERENCES context_queries(context_query_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS delivered_context_snapshots (
      snapshot_id TEXT PRIMARY KEY,
      agent_run_id TEXT NOT NULL,
      retrieval_call_id TEXT NOT NULL UNIQUE,
      context_query_id TEXT,
      kind TEXT NOT NULL,
      payload_hash TEXT NOT NULL,
      byte_size INTEGER NOT NULL,
      item_count INTEGER NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(agent_run_id) REFERENCES agent_runs(agent_run_id) ON DELETE CASCADE,
      FOREIGN KEY(retrieval_call_id) REFERENCES retrieval_calls(retrieval_call_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS delivered_context_items (
      item_id TEXT PRIMARY KEY,
      snapshot_id TEXT NOT NULL,
      event_id TEXT,
      evidence_id TEXT,
      artifact_id TEXT,
      citation_id TEXT,
      field_path TEXT NOT NULL,
      disclosure_class TEXT,
      text_hash TEXT,
      payload TEXT NOT NULL,
      FOREIGN KEY(snapshot_id) REFERENCES delivered_context_snapshots(snapshot_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS citation_records (
      citation_id TEXT PRIMARY KEY,
      agent_run_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      evidence_id TEXT,
      artifact_id TEXT,
      chunk_id TEXT,
      state TEXT NOT NULL,
      source_snapshot_id TEXT,
      source_retrieval_call_id TEXT,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(agent_run_id) REFERENCES agent_runs(agent_run_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS answer_records (
      answer_id TEXT PRIMARY KEY,
      agent_run_id TEXT NOT NULL,
      output_ref TEXT NOT NULL,
      answer_hash TEXT,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(agent_run_id) REFERENCES agent_runs(agent_run_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS risk_advisory_records (
      risk_advisory_id TEXT PRIMARY KEY,
      agent_run_id TEXT NOT NULL,
      category TEXT NOT NULL,
      severity TEXT NOT NULL,
      action_state TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(agent_run_id) REFERENCES agent_runs(agent_run_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_usage_events_v2 (
      usage_id TEXT PRIMARY KEY,
      agent_run_id TEXT NOT NULL,
      agent TEXT NOT NULL,
      purpose TEXT NOT NULL,
      output_ref TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(agent_run_id) REFERENCES agent_runs(agent_run_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_run_audit_links (
      agent_run_id TEXT NOT NULL,
      audit_id TEXT NOT NULL,
      request_id TEXT NOT NULL,
      resource_type TEXT NOT NULL,
      resource_id TEXT,
      created_at TEXT NOT NULL,
      PRIMARY KEY(agent_run_id, audit_id),
      FOREIGN KEY(agent_run_id) REFERENCES agent_runs(agent_run_id) ON DELETE CASCADE,
      FOREIGN KEY(audit_id) REFERENCES audit_log_events(audit_id) ON DELETE CASCADE
    )
    """,
    *SHARE_SCHEMA_STATEMENTS,
    """
    CREATE TABLE IF NOT EXISTS capture_jobs (
      job_id TEXT PRIMARY KEY,
      event_id TEXT NOT NULL,
      job_type TEXT NOT NULL,
      status TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(event_id) REFERENCES context_events(event_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS capture_attempts (
      trigger_id TEXT PRIMARY KEY,
      actor_id TEXT NOT NULL,
      workspace_id TEXT NOT NULL,
      status TEXT NOT NULL,
      occurred_at TEXT NOT NULL,
      selection_payload TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS capture_runs (
      capture_run_id TEXT PRIMARY KEY,
      trigger_id TEXT NOT NULL,
      event_id TEXT,
      status TEXT NOT NULL,
      primary_source_binding_id TEXT,
      envelope_payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(trigger_id) REFERENCES capture_attempts(trigger_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS detected_surfaces (
      surface_id TEXT NOT NULL,
      capture_run_id TEXT NOT NULL,
      app_name TEXT NOT NULL,
      surface_kind TEXT NOT NULL,
      process_id INTEGER,
      window_id TEXT,
      overlap_ratio REAL NOT NULL,
      confidence REAL NOT NULL,
      payload TEXT NOT NULL,
      PRIMARY KEY(surface_id, capture_run_id),
      FOREIGN KEY(capture_run_id) REFERENCES capture_runs(capture_run_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_routes (
      route_id TEXT PRIMARY KEY,
      capture_run_id TEXT NOT NULL,
      provider_key TEXT NOT NULL,
      provider_kind TEXT NOT NULL,
      route_role TEXT NOT NULL,
      surface_id TEXT,
      selected INTEGER NOT NULL,
      confidence REAL NOT NULL,
      payload TEXT NOT NULL,
      FOREIGN KEY(capture_run_id) REFERENCES capture_runs(capture_run_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_command_runs (
      command_id TEXT PRIMARY KEY,
      capture_run_id TEXT NOT NULL,
      provider_key TEXT NOT NULL,
      provider_session_id TEXT,
      route_id TEXT,
      evidence_kind TEXT NOT NULL,
      status TEXT NOT NULL,
      sent_at TEXT,
      completed_at TEXT,
      payload TEXT NOT NULL,
      FOREIGN KEY(capture_run_id) REFERENCES capture_runs(capture_run_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_capture_outcomes (
      outcome_id TEXT PRIMARY KEY,
      capture_run_id TEXT NOT NULL,
      route_id TEXT,
      provider_key TEXT NOT NULL,
      provider_kind TEXT NOT NULL,
      route_role TEXT NOT NULL,
      surface_id TEXT,
      status TEXT NOT NULL,
      command_id TEXT,
      provider_session_id TEXT,
      payload TEXT NOT NULL,
      FOREIGN KEY(capture_run_id) REFERENCES capture_runs(capture_run_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evidence_bundle_records (
      bundle_id TEXT PRIMARY KEY,
      capture_run_id TEXT NOT NULL,
      provider_key TEXT NOT NULL,
      provider_kind TEXT NOT NULL,
      evidence_kind TEXT NOT NULL,
      status TEXT NOT NULL,
      route_role TEXT NOT NULL,
      route_id TEXT,
      command_id TEXT,
      source_binding_id TEXT,
      payload TEXT NOT NULL,
      FOREIGN KEY(capture_run_id) REFERENCES capture_runs(capture_run_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS capture_run_source_bindings (
      source_binding_id TEXT NOT NULL,
      capture_run_id TEXT NOT NULL,
      source_type TEXT NOT NULL,
      title TEXT NOT NULL,
      provider_key TEXT,
      payload TEXT NOT NULL,
      PRIMARY KEY(source_binding_id, capture_run_id),
      FOREIGN KEY(capture_run_id) REFERENCES capture_runs(capture_run_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS evidence_records (
      evidence_id TEXT PRIMARY KEY,
      event_id TEXT NOT NULL,
      capture_run_id TEXT NOT NULL,
      phase TEXT NOT NULL,
      evidence_kind TEXT NOT NULL,
      artifact_id TEXT,
      artifact_type TEXT NOT NULL,
      role TEXT NOT NULL,
      provider_key TEXT NOT NULL,
      provider_session_id TEXT,
      command_id TEXT,
      source_uri TEXT NOT NULL,
      observed_at TEXT NOT NULL,
      captured_at TEXT NOT NULL,
      ingested_at TEXT NOT NULL,
      sensitivity TEXT NOT NULL,
      trust_state TEXT NOT NULL,
      ingest_state TEXT NOT NULL,
      redaction_state TEXT NOT NULL,
      indexable INTEGER NOT NULL,
      payload TEXT NOT NULL,
      FOREIGN KEY(event_id) REFERENCES context_events(event_id) ON DELETE CASCADE,
      FOREIGN KEY(capture_run_id) REFERENCES capture_runs(capture_run_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS artifact_provenance (
      artifact_id TEXT PRIMARY KEY,
      evidence_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      capture_run_id TEXT NOT NULL,
      provider_key TEXT NOT NULL,
      provider_session_id TEXT,
      command_id TEXT,
      source_uri TEXT NOT NULL,
      sha256 TEXT,
      storage_uri TEXT NOT NULL,
      extractor_name TEXT,
      extractor_version TEXT,
      payload TEXT NOT NULL,
      FOREIGN KEY(artifact_id) REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
      FOREIGN KEY(evidence_id) REFERENCES evidence_records(evidence_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS enrichment_runs (
      enrichment_id TEXT PRIMARY KEY,
      event_id TEXT NOT NULL,
      capture_run_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      status TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(event_id) REFERENCES context_events(event_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS canonical_documents (
      document_id TEXT PRIMARY KEY,
      event_id TEXT NOT NULL,
      capture_run_id TEXT NOT NULL,
      evidence_id TEXT NOT NULL,
      text TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(event_id) REFERENCES context_events(event_id) ON DELETE CASCADE,
      FOREIGN KEY(evidence_id) REFERENCES evidence_records(evidence_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS document_chunks (
      chunk_id TEXT PRIMARY KEY,
      document_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      evidence_id TEXT NOT NULL,
      ordinal INTEGER NOT NULL,
      text TEXT NOT NULL,
      payload TEXT NOT NULL,
      FOREIGN KEY(document_id) REFERENCES canonical_documents(document_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS index_records (
      index_id TEXT PRIMARY KEY,
      event_id TEXT NOT NULL,
      capture_run_id TEXT NOT NULL,
      evidence_id TEXT NOT NULL,
      index_kind TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(event_id) REFERENCES context_events(event_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS keyword_index_documents (
      chunk_id TEXT PRIMARY KEY,
      document_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      evidence_id TEXT,
      artifact_id TEXT,
      provider_key TEXT,
      source_uri TEXT,
      captured_at TEXT NOT NULL,
      observed_at TEXT,
      extractor_name TEXT,
      extractor_version TEXT,
      policy_version TEXT NOT NULL,
      disclosure_class TEXT NOT NULL,
      evidence_kind TEXT,
      artifact_type TEXT,
      sensitivity TEXT NOT NULL,
      redaction_state TEXT NOT NULL,
      event_status TEXT NOT NULL,
      field_kind TEXT NOT NULL,
      text_hash TEXT NOT NULL,
      title TEXT,
      app_name TEXT,
      origin TEXT,
      sanitized_url TEXT,
      source_type TEXT,
      workspace_id TEXT,
      search_text TEXT NOT NULL,
      payload TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS keyword_index_ngrams (
      gram TEXT NOT NULL,
      chunk_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      PRIMARY KEY(gram, chunk_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS local_settings (
      settings_key TEXT PRIMARY KEY,
      payload TEXT NOT NULL,
      updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS event_changes (
      change_id INTEGER PRIMARY KEY AUTOINCREMENT,
      event_id TEXT NOT NULL,
      change_type TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(event_id) REFERENCES context_events(event_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS active_capture_sessions (
      session_id TEXT PRIMARY KEY,
      mode TEXT NOT NULL,
      status TEXT NOT NULL,
      primary_event_id TEXT,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(primary_event_id) REFERENCES context_events(event_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS capture_post_commit_outbox (
      task_id TEXT PRIMARY KEY,
      kind TEXT NOT NULL,
      handler_id TEXT NOT NULL,
      status TEXT NOT NULL,
      event_id TEXT NOT NULL,
      trigger_id TEXT NOT NULL,
      attempt_count INTEGER NOT NULL,
      max_attempts INTEGER NOT NULL,
      next_attempt_at TEXT NOT NULL,
      locked_at TEXT,
      lease_id TEXT,
      last_error TEXT,
      task_json TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE(kind, handler_id, event_id),
      FOREIGN KEY(event_id) REFERENCES context_events(event_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_keyframes (
      keyframe_id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      capture_run_id TEXT NOT NULL,
      role TEXT NOT NULL,
      trigger_kind TEXT NOT NULL,
      captured_at TEXT NOT NULL,
      sequence_index INTEGER NOT NULL,
      screenshot_artifact_id TEXT,
      screenshot_evidence_id TEXT,
      system_appshot_evidence_id TEXT,
      payload TEXT NOT NULL,
      FOREIGN KEY(session_id) REFERENCES active_capture_sessions(session_id) ON DELETE CASCADE,
      FOREIGN KEY(event_id) REFERENCES context_events(event_id) ON DELETE CASCADE,
      FOREIGN KEY(capture_run_id) REFERENCES capture_runs(capture_run_id) ON DELETE CASCADE,
      FOREIGN KEY(screenshot_artifact_id) REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
      FOREIGN KEY(screenshot_evidence_id) REFERENCES evidence_records(evidence_id) ON DELETE CASCADE,
      FOREIGN KEY(system_appshot_evidence_id) REFERENCES evidence_records(evidence_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS keyframe_evidence_links (
      link_id TEXT PRIMARY KEY,
      keyframe_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      evidence_id TEXT NOT NULL,
      artifact_id TEXT,
      role TEXT NOT NULL,
      provider_key TEXT,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(keyframe_id) REFERENCES context_keyframes(keyframe_id) ON DELETE CASCADE,
      FOREIGN KEY(event_id) REFERENCES context_events(event_id) ON DELETE CASCADE,
      FOREIGN KEY(evidence_id) REFERENCES evidence_records(evidence_id) ON DELETE CASCADE,
      FOREIGN KEY(artifact_id) REFERENCES artifacts(artifact_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS keyframe_capture_decisions (
      decision_id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      event_id TEXT,
      candidate_id TEXT NOT NULL,
      role TEXT NOT NULL,
      trigger_kind TEXT NOT NULL,
      kept INTEGER NOT NULL,
      kept_keyframe_id TEXT,
      drop_reason TEXT,
      payload TEXT NOT NULL,
      decided_at TEXT NOT NULL,
      FOREIGN KEY(session_id) REFERENCES active_capture_sessions(session_id) ON DELETE CASCADE,
      FOREIGN KEY(event_id) REFERENCES context_events(event_id) ON DELETE SET NULL,
      FOREIGN KEY(kept_keyframe_id) REFERENCES context_keyframes(keyframe_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS keyframe_context_bundles (
      bundle_id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL UNIQUE,
      primary_event_id TEXT,
      status TEXT NOT NULL,
      anchor_keyframe_id TEXT,
      keyframe_count INTEGER NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(session_id) REFERENCES active_capture_sessions(session_id) ON DELETE CASCADE,
      FOREIGN KEY(primary_event_id) REFERENCES context_events(event_id) ON DELETE SET NULL,
      FOREIGN KEY(anchor_keyframe_id) REFERENCES context_keyframes(keyframe_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recording_timeline_manifests (
      manifest_id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL UNIQUE,
      primary_event_id TEXT,
      video_artifact_id TEXT,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(session_id) REFERENCES active_capture_sessions(session_id) ON DELETE CASCADE,
      FOREIGN KEY(primary_event_id) REFERENCES context_events(event_id) ON DELETE SET NULL,
      FOREIGN KEY(video_artifact_id) REFERENCES artifacts(artifact_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS active_capture_control_events (
      control_id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      source TEXT NOT NULL,
      occurred_at TEXT NOT NULL,
      segment_id TEXT,
      payload TEXT NOT NULL,
      FOREIGN KEY(session_id) REFERENCES active_capture_sessions(session_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recording_video_segments (
      segment_id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      sequence_index INTEGER NOT NULL,
      state TEXT NOT NULL,
      video_artifact_id TEXT,
      started_at TEXT NOT NULL,
      ended_at TEXT,
      payload TEXT NOT NULL,
      FOREIGN KEY(session_id) REFERENCES active_capture_sessions(session_id) ON DELETE CASCADE,
      FOREIGN KEY(video_artifact_id) REFERENCES artifacts(artifact_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS recording_pause_intervals (
      pause_id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      started_at TEXT NOT NULL,
      ended_at TEXT,
      reason TEXT NOT NULL,
      payload TEXT NOT NULL,
      FOREIGN KEY(session_id) REFERENCES active_capture_sessions(session_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS active_capture_trigger_candidates (
      candidate_id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      trigger_kind TEXT NOT NULL,
      role TEXT NOT NULL,
      priority TEXT NOT NULL,
      status TEXT NOT NULL,
      occurred_at TEXT NOT NULL,
      event_id TEXT,
      keyframe_id TEXT,
      payload TEXT NOT NULL,
      FOREIGN KEY(session_id) REFERENCES active_capture_sessions(session_id) ON DELETE CASCADE,
      FOREIGN KEY(event_id) REFERENCES context_events(event_id) ON DELETE SET NULL,
      FOREIGN KEY(keyframe_id) REFERENCES context_keyframes(keyframe_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS human_demonstration_traces (
      trace_id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL UNIQUE,
      status TEXT NOT NULL,
      action_count INTEGER NOT NULL,
      payload TEXT NOT NULL,
      started_at TEXT NOT NULL,
      ended_at TEXT,
      FOREIGN KEY(session_id) REFERENCES active_capture_sessions(session_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS human_action_events (
      action_id TEXT PRIMARY KEY,
      trace_id TEXT NOT NULL,
      session_id TEXT NOT NULL,
      sequence_index INTEGER NOT NULL,
      kind TEXT NOT NULL,
      occurred_at TEXT NOT NULL,
      payload TEXT NOT NULL,
      FOREIGN KEY(trace_id) REFERENCES human_demonstration_traces(trace_id) ON DELETE CASCADE,
      FOREIGN KEY(session_id) REFERENCES active_capture_sessions(session_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS action_evidence_links (
      link_id TEXT PRIMARY KEY,
      action_id TEXT NOT NULL,
      role TEXT NOT NULL,
      keyframe_id TEXT,
      event_id TEXT,
      evidence_id TEXT,
      artifact_id TEXT,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(action_id) REFERENCES human_action_events(action_id) ON DELETE CASCADE,
      FOREIGN KEY(keyframe_id) REFERENCES context_keyframes(keyframe_id) ON DELETE SET NULL,
      FOREIGN KEY(event_id) REFERENCES context_events(event_id) ON DELETE SET NULL,
      FOREIGN KEY(evidence_id) REFERENCES evidence_records(evidence_id) ON DELETE SET NULL,
      FOREIGN KEY(artifact_id) REFERENCES artifacts(artifact_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS action_result_observations (
      observation_id TEXT PRIMARY KEY,
      action_id TEXT NOT NULL UNIQUE,
      status TEXT NOT NULL,
      result_keyframe_id TEXT,
      observed_at TEXT NOT NULL,
      payload TEXT NOT NULL,
      FOREIGN KEY(action_id) REFERENCES human_action_events(action_id) ON DELETE CASCADE,
      FOREIGN KEY(result_keyframe_id) REFERENCES context_keyframes(keyframe_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS action_target_resolutions (
      resolution_id TEXT PRIMARY KEY,
      action_id TEXT NOT NULL,
      session_id TEXT NOT NULL,
      status TEXT NOT NULL,
      semantic_kind TEXT NOT NULL,
      confidence REAL NOT NULL,
      input_fingerprint TEXT NOT NULL,
      resolver_version TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(action_id) REFERENCES human_action_events(action_id) ON DELETE CASCADE,
      FOREIGN KEY(session_id) REFERENCES active_capture_sessions(session_id) ON DELETE CASCADE,
      UNIQUE(action_id, resolver_version, input_fingerprint)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS action_target_candidates (
      candidate_id TEXT PRIMARY KEY,
      resolution_id TEXT NOT NULL,
      action_id TEXT NOT NULL,
      session_id TEXT NOT NULL,
      source_kind TEXT NOT NULL,
      semantic_kind TEXT NOT NULL,
      confidence REAL NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(resolution_id) REFERENCES action_target_resolutions(resolution_id) ON DELETE CASCADE,
      FOREIGN KEY(action_id) REFERENCES human_action_events(action_id) ON DELETE CASCADE,
      FOREIGN KEY(session_id) REFERENCES active_capture_sessions(session_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS active_capture_producer_events (
      producer_event_id TEXT PRIMARY KEY,
      session_id TEXT NOT NULL,
      event_kind TEXT NOT NULL,
      producer_kind TEXT NOT NULL,
      occurred_at TEXT NOT NULL,
      payload TEXT NOT NULL,
      FOREIGN KEY(session_id) REFERENCES active_capture_sessions(session_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS active_capture_producer_decisions (
      decision_id TEXT PRIMARY KEY,
      producer_event_id TEXT NOT NULL,
      session_id TEXT NOT NULL,
      status TEXT NOT NULL,
      reason TEXT NOT NULL,
      action_id TEXT,
      candidate_id TEXT,
      keyframe_id TEXT,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(producer_event_id) REFERENCES active_capture_producer_events(producer_event_id) ON DELETE CASCADE,
      FOREIGN KEY(session_id) REFERENCES active_capture_sessions(session_id) ON DELETE CASCADE,
      FOREIGN KEY(action_id) REFERENCES human_action_events(action_id) ON DELETE SET NULL,
      FOREIGN KEY(candidate_id) REFERENCES active_capture_trigger_candidates(candidate_id) ON DELETE SET NULL,
      FOREIGN KEY(keyframe_id) REFERENCES context_keyframes(keyframe_id) ON DELETE SET NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS active_capture_settle_audits (
      audit_id TEXT PRIMARY KEY,
      plan_id TEXT NOT NULL,
      candidate_id TEXT NOT NULL,
      session_id TEXT NOT NULL,
      status TEXT NOT NULL,
      stop_reason TEXT NOT NULL,
      sample_count INTEGER NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(candidate_id) REFERENCES active_capture_trigger_candidates(candidate_id) ON DELETE CASCADE,
      FOREIGN KEY(session_id) REFERENCES active_capture_sessions(session_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS index_policy_decisions (
      decision_id TEXT PRIMARY KEY,
      event_id TEXT NOT NULL,
      session_id TEXT,
      source_id TEXT,
      field_kind TEXT NOT NULL,
      status TEXT NOT NULL,
      suppression_reason TEXT NOT NULL,
      sensitive_surface_type TEXT NOT NULL,
      source_text_hash TEXT NOT NULL,
      output_text_hash TEXT,
      policy_version TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(event_id) REFERENCES context_events(event_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_active_capture_artifact_delete
    BEFORE DELETE ON artifacts
    BEGIN
      DELETE FROM keyframe_evidence_links WHERE artifact_id = OLD.artifact_id;
      DELETE FROM context_keyframes WHERE screenshot_artifact_id = OLD.artifact_id;
      DELETE FROM recording_timeline_manifests WHERE video_artifact_id = OLD.artifact_id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_active_capture_evidence_delete
    BEFORE DELETE ON evidence_records
    BEGIN
      DELETE FROM keyframe_evidence_links WHERE evidence_id = OLD.evidence_id;
      DELETE FROM context_keyframes
      WHERE screenshot_evidence_id = OLD.evidence_id
         OR system_appshot_evidence_id = OLD.evidence_id;
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS trg_active_capture_keyframe_delete
    BEFORE DELETE ON context_keyframes
    BEGIN
      DELETE FROM keyframe_evidence_links WHERE keyframe_id = OLD.keyframe_id;
      DELETE FROM keyframe_context_bundles WHERE anchor_keyframe_id = OLD.keyframe_id;
    END
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_context_events_trigger_id
    ON context_events(json_extract(payload, '$.trigger.trigger_id'))
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_capture_jobs_event_type
    ON capture_jobs(event_id, job_type)
    """,
    "CREATE INDEX IF NOT EXISTS idx_capture_runs_trigger_id ON capture_runs(trigger_id)",
    "CREATE INDEX IF NOT EXISTS idx_agent_runs_status_time ON agent_runs(status, last_seen_at)",
    "CREATE INDEX IF NOT EXISTS idx_context_queries_run ON context_queries(agent_run_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_retrieval_calls_run ON retrieval_calls(agent_run_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_snapshots_run ON delivered_context_snapshots(agent_run_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_citations_run ON citation_records(agent_run_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_usage_v2_run ON agent_usage_events_v2(agent_run_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_provider_routes_capture_run ON provider_routes(capture_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_provider_commands_capture_run ON provider_command_runs(capture_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_provider_outcomes_capture_run ON provider_capture_outcomes(capture_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_evidence_bundles_capture_run ON evidence_bundle_records(capture_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_source_bindings_capture_run ON capture_run_source_bindings(capture_run_id)",
    "CREATE INDEX IF NOT EXISTS idx_evidence_event_kind ON evidence_records(event_id, evidence_kind)",
    "CREATE INDEX IF NOT EXISTS idx_evidence_provider_time ON evidence_records(provider_key, captured_at)",
    "CREATE INDEX IF NOT EXISTS idx_artifact_provenance_event ON artifact_provenance(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_document_chunks_event ON document_chunks(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_keyword_index_event ON keyword_index_documents(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_keyword_index_time ON keyword_index_documents(captured_at)",
    "CREATE INDEX IF NOT EXISTS idx_keyword_index_origin ON keyword_index_documents(origin)",
    "CREATE INDEX IF NOT EXISTS idx_keyword_index_ngrams_event ON keyword_index_ngrams(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_event_changes_event_id ON event_changes(event_id, change_id)",
    "CREATE INDEX IF NOT EXISTS idx_active_capture_sessions_primary_event ON active_capture_sessions(primary_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_capture_post_commit_due ON capture_post_commit_outbox(status, next_attempt_at)",
    "CREATE INDEX IF NOT EXISTS idx_capture_post_commit_running_stale ON capture_post_commit_outbox(status, locked_at)",
    "CREATE INDEX IF NOT EXISTS idx_capture_post_commit_event ON capture_post_commit_outbox(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_context_keyframes_session ON context_keyframes(session_id, sequence_index)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_context_keyframes_session_sequence ON context_keyframes(session_id, sequence_index)",
    "CREATE INDEX IF NOT EXISTS idx_context_keyframes_event ON context_keyframes(event_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_context_keyframes_unique_role ON context_keyframes(session_id, event_id, role, trigger_kind)",
    "CREATE INDEX IF NOT EXISTS idx_keyframe_links_keyframe ON keyframe_evidence_links(keyframe_id)",
    "CREATE INDEX IF NOT EXISTS idx_keyframe_links_evidence ON keyframe_evidence_links(evidence_id)",
    "CREATE INDEX IF NOT EXISTS idx_keyframe_decisions_session ON keyframe_capture_decisions(session_id, decided_at)",
    "CREATE INDEX IF NOT EXISTS idx_timeline_manifests_session ON recording_timeline_manifests(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_active_capture_controls_session ON active_capture_control_events(session_id, occurred_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_recording_segments_session_sequence ON recording_video_segments(session_id, sequence_index)",
    "CREATE INDEX IF NOT EXISTS idx_recording_segments_session ON recording_video_segments(session_id, started_at)",
    "CREATE INDEX IF NOT EXISTS idx_recording_pause_session ON recording_pause_intervals(session_id, started_at)",
    "CREATE INDEX IF NOT EXISTS idx_trigger_candidates_session ON active_capture_trigger_candidates(session_id, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_trigger_candidates_status ON active_capture_trigger_candidates(status, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_demo_traces_session ON human_demonstration_traces(session_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_human_actions_trace_sequence ON human_action_events(trace_id, sequence_index)",
    "CREATE INDEX IF NOT EXISTS idx_human_actions_session ON human_action_events(session_id, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_action_links_action ON action_evidence_links(action_id)",
    "CREATE INDEX IF NOT EXISTS idx_action_target_resolutions_action ON action_target_resolutions(action_id)",
    "CREATE INDEX IF NOT EXISTS idx_action_target_resolutions_session ON action_target_resolutions(session_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_action_target_candidates_resolution ON action_target_candidates(resolution_id)",
    "CREATE INDEX IF NOT EXISTS idx_producer_events_session ON active_capture_producer_events(session_id, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_producer_events_kind ON active_capture_producer_events(event_kind, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_producer_decisions_session ON active_capture_producer_decisions(session_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_producer_decisions_event ON active_capture_producer_decisions(producer_event_id)",
    "CREATE INDEX IF NOT EXISTS idx_producer_decisions_candidate ON active_capture_producer_decisions(session_id, candidate_id)",
    "CREATE INDEX IF NOT EXISTS idx_settle_audits_candidate ON active_capture_settle_audits(candidate_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_settle_audits_session ON active_capture_settle_audits(session_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_index_policy_decisions_event ON index_policy_decisions(event_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_index_policy_decisions_session ON index_policy_decisions(session_id, created_at)",
)
