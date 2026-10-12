"""Repositories for policy decisions and audit events."""

from __future__ import annotations

from packages.contracts import AuditLogEvent, PolicyDecision

from .database import SQLiteDatabase


class PolicyDecisionRepository:
    """Persist policy decisions for replayable authorization traces."""

    def __init__(self, database: SQLiteDatabase) -> None:
        """Create a policy decision repository.

        Args:
            database: Database wrapper used for all operations.
        """

        self.database = database

    def save(self, decision: PolicyDecision) -> PolicyDecision:
        """Persist one policy decision.

        Args:
            decision: Policy decision to persist.

        Returns:
            Persisted decision.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO policy_decisions(decision_id, effect, payload, evaluated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.effect.value,
                    decision.model_dump_json(),
                    decision.evaluated_at.isoformat(),
                ),
            )
        return decision

    def get(self, decision_id: str) -> PolicyDecision | None:
        """Return one policy decision by id.

        Args:
            decision_id: Policy decision identifier.

        Returns:
            Decision when found, otherwise ``None``.
        """

        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT payload FROM policy_decisions WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        if row is None:
            return None
        return PolicyDecision.model_validate_json(str(row["payload"]))


class AuditLogRepository:
    """Persist append-only audit events."""

    def __init__(self, database: SQLiteDatabase) -> None:
        """Create an audit log repository.

        Args:
            database: Database wrapper used for all operations.
        """

        self.database = database

    def save(self, event: AuditLogEvent) -> AuditLogEvent:
        """Persist one audit log event.

        Args:
            event: Audit event to persist.

        Returns:
            Persisted audit event.
        """

        with self.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO audit_log_events(
                  audit_id, request_id, action, resource_type, resource_id, success, payload, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.audit_id,
                    event.request_id,
                    event.action.value,
                    event.resource_type,
                    event.resource_id,
                    1 if event.success else 0,
                    event.model_dump_json(),
                    event.created_at.isoformat(),
                ),
            )
        return event

    def list(self, *, limit: int = 100) -> tuple[AuditLogEvent, ...]:
        """List recent audit events.

        Args:
            limit: Maximum number of rows to return.

        Returns:
            Audit events sorted newest first.
        """

        with self.database.transaction() as connection:
            rows = connection.execute(
                "SELECT payload FROM audit_log_events ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(AuditLogEvent.model_validate_json(str(row["payload"])) for row in rows)

    def list_for_resource(self, *, resource_id: str, limit: int = 100) -> tuple[AuditLogEvent, ...]:
        """List audit events for one resource id.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        with self.database.transaction() as connection:
            rows = connection.execute(
                """
                SELECT payload FROM audit_log_events
                WHERE resource_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (resource_id, limit),
            ).fetchall()
        return tuple(AuditLogEvent.model_validate_json(str(row["payload"])) for row in rows)

    def list_for_resources(self, *, resource_ids: tuple[str, ...], limit: int = 250) -> tuple[AuditLogEvent, ...]:
        """List audit events for any resource id in a small event trail.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        if not resource_ids:
            return ()
        placeholders = ",".join("?" for _ in resource_ids)
        with self.database.transaction() as connection:
            rows = connection.execute(
                f"""
                SELECT payload FROM audit_log_events
                WHERE resource_id IN ({placeholders})
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (*resource_ids, limit),
            ).fetchall()
        return tuple(AuditLogEvent.model_validate_json(str(row["payload"])) for row in rows)
