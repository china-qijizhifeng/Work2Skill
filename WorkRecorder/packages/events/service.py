"""Service layer for context event mutation flows."""

from __future__ import annotations

from packages.contracts import ContextEvent, ContextEventCreate, EventStatus, UserRef
from packages.shared.ids import IdFactory
from packages.shared.time import Clock
from packages.storage.event_repository import ContextEventRepository


class ContextEventIngestService:
    """Create and mutate context event records without route-level assembly."""

    def __init__(self, *, events: ContextEventRepository, ids: IdFactory, clock: Clock) -> None:
        """Create an event ingest service.

        Args:
            events: Repository used to persist event records.
            ids: Identifier generator.
            clock: Shared clock.
        """

        self.events = events
        self.ids = ids
        self.clock = clock

    def build(self, request: ContextEventCreate) -> ContextEvent:
        """Build a captured event payload without writing it.

        Args:
            request: Typed context event create contract.

        Returns:
            Context event ready for durable evidence write.
        """

        now = self.clock.now()
        return ContextEvent(
            event_id=self.ids.new("evt"),
            event_type=request.event_type,
            trigger=request.trigger,
            source_binding=request.source_binding,
            status=EventStatus.CAPTURED,
            intent_text=request.intent_text or request.trigger.intent_text,
            created_at=now,
            updated_at=now,
            user=UserRef.from_actor(request.trigger.actor),
        )

    def save(self, event: ContextEvent) -> ContextEvent:
        """Persist a prebuilt context event.

        Args:
            event: Context event built by ``build`` or a future provider.

        Returns:
            Persisted context event.
        """

        return self.events.save(event)

    def create(self, request: ContextEventCreate) -> ContextEvent:
        """Create and persist a captured event from a typed request.

        Args:
            request: Typed context event create contract.

        Returns:
            Persisted context event.
        """

        return self.save(self.build(request))

    def mark_deleted(self, event: ContextEvent) -> ContextEvent:
        """Write a deleted tombstone for an existing event.

        Args:
            event: Existing event loaded by the caller.

        Returns:
            Deleted event payload.
        """

        deleted = event.model_copy(update={"status": EventStatus.DELETED, "updated_at": self.clock.now()})
        return self.events.mark_deleted(event.event_id, deleted_payload=deleted)
