"""Audit writer service for daemon action traces."""

from __future__ import annotations

from packages.contracts import AuditLogEvent, AuditLogEventCreate
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from packages.storage.security_repository import AuditLogRepository


class AuditWriter:
    """Create and persist audit events through a repository boundary."""

    def __init__(self, *, repository: AuditLogRepository, ids: IdFactory, clock: Clock) -> None:
        """Create an audit writer.

        Args:
            repository: Audit repository used for persistence.
            ids: Identifier generator.
            clock: Clock used for event timestamps.
        """

        self.repository = repository
        self.ids = ids
        self.clock = clock

    def record(self, event_create: AuditLogEventCreate) -> AuditLogEvent:
        """Persist one audit event.

        Args:
            event_create: Typed event creation payload.

        Returns:
            Persisted audit event.
        """

        event = AuditLogEvent(
            audit_id=self.ids.new("aud"),
            request_id=event_create.request_id,
            actor=event_create.actor,
            action=event_create.action,
            resource_type=event_create.resource_type,
            resource_id=event_create.resource_id,
            policy_decision_id=event_create.policy_decision_id,
            success=event_create.success,
            details=event_create.details,
            created_at=self.clock.now(),
        )
        return self.repository.save(event)
