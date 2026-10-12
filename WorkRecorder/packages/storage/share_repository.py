"""Persistence for context share grants, snapshots, revisions, and targets."""

from __future__ import annotations

from datetime import datetime

from packages.contracts import (
    ContextShare,
    ContextShareStatus,
    ExternalShareTarget,
    ShareAuditEvent,
    SharePublishStatus,
    ShareRevision,
    ShareSnapshot,
    ShareSyncJob,
    UserFilter,
)

from .database import SQLiteDatabase


class ContextShareRepository:
    """SQLite-backed share ledger repository."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def save_share(self, share: ContextShare) -> ContextShare:
        """Insert or update one share row.

        Args:
            share: Typed share contract to persist as JSON plus indexed columns.

        Returns:
            The same share contract after the write succeeds.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO context_shares(
                  share_id, event_id, user_id, status, scope, target, token_hash,
                  snapshot_id, current_revision_id, payload, created_at, updated_at,
                  expires_at, revoked_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(share_id) DO UPDATE SET
                  event_id = excluded.event_id,
                  user_id = excluded.user_id,
                  status = excluded.status,
                  scope = excluded.scope,
                  target = excluded.target,
                  token_hash = excluded.token_hash,
                  snapshot_id = excluded.snapshot_id,
                  current_revision_id = excluded.current_revision_id,
                  payload = excluded.payload,
                  updated_at = excluded.updated_at,
                  expires_at = excluded.expires_at,
                  revoked_at = excluded.revoked_at
                """,
                (
                    share.share_id,
                    share.event_id,
                    share.user.user_id,
                    share.status.value,
                    share.scope.value,
                    share.target.value,
                    share.token_hash,
                    None,
                    share.current_revision_id,
                    share.model_dump_json(),
                    share.created_at.isoformat(),
                    share.updated_at.isoformat(),
                    share.expires_at.isoformat() if share.expires_at else None,
                    share.revoked_at.isoformat() if share.revoked_at else None,
                ),
            )
        return share

    def get_share(self, share_id: str) -> ContextShare | None:
        """Load one share by id.

        Args:
            share_id: Stable share identifier.

        Returns:
            Share contract, or None when absent.
        """

        with self.database.transaction() as connection:
            row = connection.execute("SELECT payload FROM context_shares WHERE share_id = ?", (share_id,)).fetchone()
        return ContextShare.model_validate_json(str(row["payload"])) if row else None

    def get_share_by_token_hash(self, token_hash: str) -> ContextShare | None:
        """Load one share by hashed token.

        Args:
            token_hash: SHA-256 token digest stored in the ledger.

        Returns:
            Matching share contract, or None when absent.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM context_shares WHERE token_hash = ?",
                (token_hash,),
            ).fetchone()
        return ContextShare.model_validate_json(str(row["payload"])) if row else None

    def list_shares(self, *, user: UserFilter | None = None, limit: int = 50) -> tuple[ContextShare, ...]:
        """List recent shares with optional typed user filters.

        Args:
            user: Optional owner/user filter.
            limit: Maximum number of rows to return.

        Returns:
            Shares ordered by creation time descending.
        """

        clauses: list[str] = []
        params_list: list[object] = []
        if user:
            if user.query:
                clauses.append("(lower(user_id) LIKE ? OR lower(json_extract(payload, '$.user.display_name')) LIKE ?)")
                params_list.extend((f"%{user.query.lower()}%", f"%{user.query.lower()}%"))
            if user.user_id:
                clauses.append("user_id = ?")
                params_list.append(user.user_id)
            if user.display_name:
                clauses.append("lower(json_extract(payload, '$.user.display_name')) LIKE ?")
                params_list.append(f"%{user.display_name.lower()}%")
            if user.identity_provider:
                clauses.append("json_extract(payload, '$.user.identity_provider') = ?")
                params_list.append(user.identity_provider.value)
            if user.tenant_key:
                clauses.append("json_extract(payload, '$.user.tenant_key') = ?")
                params_list.append(user.tenant_key)
            if user.feishu_open_id:
                clauses.append("json_extract(payload, '$.user.feishu_open_id') = ?")
                params_list.append(user.feishu_open_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params = (*params_list, limit)
        with self.database.transaction() as connection:
            rows = connection.execute(
                f"SELECT payload FROM context_shares {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return tuple(ContextShare.model_validate_json(str(row["payload"])) for row in rows)

    def get_share_by_provider_url(self, provider_url: str) -> ContextShare | None:
        """Resolve a share from a sanitized external provider URL.

        Args:
            provider_url: Query/hash-free URL stored for an external target.

        Returns:
            Matching share contract, or None when unknown.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT s.payload FROM context_shares s
                JOIN external_share_targets t ON t.share_id = s.share_id
                WHERE t.provider_url = ?
                ORDER BY t.updated_at DESC
                LIMIT 1
                """,
                (provider_url,),
            ).fetchone()
        return ContextShare.model_validate_json(str(row["payload"])) if row else None

    def get_share_by_package_hash(self, package_hash: str) -> ContextShare | None:
        """Resolve an imported share by its immutable package hash.

        Args:
            package_hash: SHA-256 hash of the downloaded share HTML package.

        Returns:
            Matching share contract, or None when this package is new.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT payload FROM context_shares
                WHERE json_extract(payload, '$.metadata.package_hash') = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (package_hash,),
            ).fetchone()
        return ContextShare.model_validate_json(str(row["payload"])) if row else None

    def save_snapshot(self, snapshot: ShareSnapshot) -> ShareSnapshot:
        """Persist one immutable safe-context snapshot.

        Args:
            snapshot: Frozen disclosure payload and screenshot reference.

        Returns:
            The same snapshot contract after persistence.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO context_share_snapshots(
                  snapshot_id, share_id, event_id, revision, payload_hash, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.share_id,
                    snapshot.event_id,
                    snapshot.revision,
                    snapshot.payload_hash,
                    snapshot.model_dump_json(),
                    snapshot.created_at.isoformat(),
                ),
            )
        return snapshot

    def get_snapshot(self, snapshot_id: str) -> ShareSnapshot | None:
        """Load one snapshot by id.

        Args:
            snapshot_id: Stable snapshot identifier.

        Returns:
            Snapshot contract, or None when absent.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM context_share_snapshots WHERE snapshot_id = ?",
                (snapshot_id,),
            ).fetchone()
        return ShareSnapshot.model_validate_json(str(row["payload"])) if row else None

    def latest_snapshot(self, share_id: str) -> ShareSnapshot | None:
        """Load the newest snapshot for a share.

        Args:
            share_id: Share whose latest snapshot should be returned.

        Returns:
            Latest snapshot contract, or None when the share has none.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT payload FROM context_share_snapshots
                WHERE share_id = ?
                ORDER BY revision DESC
                LIMIT 1
                """,
                (share_id,),
            ).fetchone()
        return ShareSnapshot.model_validate_json(str(row["payload"])) if row else None

    def save_revision(self, revision: ShareRevision) -> ShareRevision:
        """Insert or update one share revision.

        Args:
            revision: Immutable package revision metadata.

        Returns:
            The same revision contract after persistence.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO context_share_revisions(
                  revision_id, share_id, event_id, revision, snapshot_id, status,
                  payload, created_at, published_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(revision_id) DO UPDATE SET
                  status = excluded.status,
                  payload = excluded.payload,
                  published_at = excluded.published_at
                """,
                (
                    revision.revision_id,
                    revision.share_id,
                    revision.event_id,
                    revision.revision,
                    revision.snapshot_id,
                    revision.status.value,
                    revision.model_dump_json(),
                    revision.created_at.isoformat(),
                    revision.published_at.isoformat() if revision.published_at else None,
                ),
            )
        return revision

    def get_revision(self, revision_id: str) -> ShareRevision | None:
        """Load one share revision by id.

        Args:
            revision_id: Stable revision identifier.

        Returns:
            Revision contract, or None when absent.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM context_share_revisions WHERE revision_id = ?",
                (revision_id,),
            ).fetchone()
        return ShareRevision.model_validate_json(str(row["payload"])) if row else None

    def latest_revision(self, share_id: str) -> ShareRevision | None:
        """Load the newest revision for a share.

        Args:
            share_id: Share whose latest package revision is needed.

        Returns:
            Latest revision contract, or None when absent.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT payload FROM context_share_revisions
                WHERE share_id = ?
                ORDER BY revision DESC
                LIMIT 1
                """,
                (share_id,),
            ).fetchone()
        return ShareRevision.model_validate_json(str(row["payload"])) if row else None

    def save_target(self, target: ExternalShareTarget) -> ExternalShareTarget:
        """Persist external publish target metadata.

        Args:
            target: Provider target state including URL or failure details.

        Returns:
            The same target contract after persistence.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO external_share_targets(
                  target_id, share_id, revision_id, target, status, provider_file_token,
                  provider_url, visibility, retry_count, last_error_code, last_error_message,
                  payload, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    target.target_id,
                    target.share_id,
                    target.revision_id,
                    target.target.value,
                    target.status.value,
                    target.provider_file_token,
                    target.provider_url,
                    target.visibility.value,
                    target.retry_count,
                    target.last_error_code,
                    target.last_error_message,
                    target.model_dump_json(),
                    target.created_at.isoformat(),
                    target.updated_at.isoformat(),
                ),
            )
        return target

    def latest_target(self, share_id: str) -> ExternalShareTarget | None:
        """Load the newest external target for a share.

        Args:
            share_id: Share whose provider target should be returned.

        Returns:
            Latest target contract, or None when no publish was attempted.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                """
                SELECT payload FROM external_share_targets
                WHERE share_id = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (share_id,),
            ).fetchone()
        return ExternalShareTarget.model_validate_json(str(row["payload"])) if row else None

    def save_job(self, job: ShareSyncJob) -> ShareSyncJob:
        """Persist one share sync job row.

        Args:
            job: Upload/retry job state.

        Returns:
            The same job contract after persistence.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO share_sync_jobs(
                  job_id, share_id, revision_id, target, status, retry_count,
                  last_error_code, last_error_message, payload, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.share_id,
                    job.revision_id,
                    job.target.value,
                    job.status.value,
                    job.retry_count,
                    job.last_error_code,
                    job.last_error_message,
                    job.model_dump_json(),
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                ),
            )
        return job

    def list_jobs(self, share_id: str) -> tuple[ShareSyncJob, ...]:
        """List sync jobs for a share.

        Args:
            share_id: Share whose upload jobs should be listed.

        Returns:
            Jobs ordered newest first.
        """

        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM share_sync_jobs
                WHERE share_id = ?
                ORDER BY created_at DESC
                """,
                (share_id,),
            ).fetchall()
        return tuple(ShareSyncJob.model_validate_json(str(row["payload"])) for row in rows)

    def record_audit(self, event: ShareAuditEvent) -> ShareAuditEvent:
        """Append one share audit event.

        Args:
            event: Sanitized audit event without raw shared content.

        Returns:
            The same audit event after persistence.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO share_audit_events(
                  share_audit_id, share_id, event_id, action, success, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.share_audit_id,
                    event.share_id,
                    event.event_id,
                    event.action.value,
                    int(event.success),
                    event.model_dump_json(),
                    event.created_at.isoformat(),
                ),
            )
        return event

    def mark_share_status(
        self,
        *,
        share: ContextShare,
        status: ContextShareStatus,
        updated_at: datetime,
        current_revision_id: str | None = None,
        revoked_at: datetime | None = None,
    ) -> ContextShare:
        """Update lifecycle status fields on an existing share.

        Args:
            share: Existing share contract to update.
            status: New lifecycle status.
            updated_at: Timestamp for the status transition.
            current_revision_id: Optional latest revision id.
            revoked_at: Optional revoke timestamp.

        Returns:
            Updated and persisted share contract.
        """

        updated = share.model_copy(
            update={
                "status": status,
                "updated_at": updated_at,
                "current_revision_id": current_revision_id or share.current_revision_id,
                "revoked_at": revoked_at if revoked_at is not None else share.revoked_at,
            }
        )
        return self.save_share(updated)
