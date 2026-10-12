"""SQLite statements for context share ledger tables and indexes."""

from __future__ import annotations

SHARE_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS context_shares (
      share_id TEXT PRIMARY KEY,
      event_id TEXT NOT NULL,
      user_id TEXT NOT NULL,
      status TEXT NOT NULL,
      scope TEXT NOT NULL,
      target TEXT NOT NULL,
      token_hash TEXT NOT NULL UNIQUE,
      snapshot_id TEXT,
      current_revision_id TEXT,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      expires_at TEXT,
      revoked_at TEXT,
      FOREIGN KEY(event_id) REFERENCES context_events(event_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_share_snapshots (
      snapshot_id TEXT PRIMARY KEY,
      share_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      revision INTEGER NOT NULL,
      payload_hash TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(share_id) REFERENCES context_shares(share_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS context_share_revisions (
      revision_id TEXT PRIMARY KEY,
      share_id TEXT NOT NULL,
      event_id TEXT NOT NULL,
      revision INTEGER NOT NULL,
      snapshot_id TEXT NOT NULL,
      status TEXT NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      published_at TEXT,
      FOREIGN KEY(share_id) REFERENCES context_shares(share_id) ON DELETE CASCADE,
      FOREIGN KEY(snapshot_id) REFERENCES context_share_snapshots(snapshot_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS external_share_targets (
      target_id TEXT PRIMARY KEY,
      share_id TEXT NOT NULL,
      revision_id TEXT NOT NULL,
      target TEXT NOT NULL,
      status TEXT NOT NULL,
      provider_file_token TEXT,
      provider_url TEXT,
      visibility TEXT NOT NULL,
      retry_count INTEGER NOT NULL,
      last_error_code TEXT,
      last_error_message TEXT,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(share_id) REFERENCES context_shares(share_id) ON DELETE CASCADE,
      FOREIGN KEY(revision_id) REFERENCES context_share_revisions(revision_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS share_sync_jobs (
      job_id TEXT PRIMARY KEY,
      share_id TEXT NOT NULL,
      revision_id TEXT NOT NULL,
      target TEXT NOT NULL,
      status TEXT NOT NULL,
      retry_count INTEGER NOT NULL,
      last_error_code TEXT,
      last_error_message TEXT,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      FOREIGN KEY(share_id) REFERENCES context_shares(share_id) ON DELETE CASCADE,
      FOREIGN KEY(revision_id) REFERENCES context_share_revisions(revision_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS share_imports (
      import_id TEXT PRIMARY KEY,
      share_id TEXT,
      original_event_id TEXT,
      imported_event_id TEXT,
      imported_by_user_id TEXT,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS share_audit_events (
      share_audit_id TEXT PRIMARY KEY,
      share_id TEXT NOT NULL,
      event_id TEXT,
      action TEXT NOT NULL,
      success INTEGER NOT NULL,
      payload TEXT NOT NULL,
      created_at TEXT NOT NULL,
      FOREIGN KEY(share_id) REFERENCES context_shares(share_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_context_shares_event ON context_shares(event_id)",
    "CREATE INDEX IF NOT EXISTS idx_context_shares_user ON context_shares(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_context_share_targets_share ON external_share_targets(share_id)",
    "CREATE INDEX IF NOT EXISTS idx_share_sync_jobs_share ON share_sync_jobs(share_id)",
)
