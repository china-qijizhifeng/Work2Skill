from __future__ import annotations

from packages.contracts import ContextEvent, EventStatus
from packages.storage.container import RepositoryContainer
from packages.storage.database import SQLiteDatabase


def test_repository_round_trips_event(event_create):
    repositories = RepositoryContainer(SQLiteDatabase(":memory:"))
    now = event_create.trigger.occurred_at
    event = ContextEvent(
        event_id="evt_test",
        event_type=event_create.event_type,
        trigger=event_create.trigger,
        source_binding=event_create.source_binding,
        status=EventStatus.CAPTURED,
        intent_text=event_create.intent_text,
        created_at=now,
        updated_at=now,
    )
    repositories.events.save(event)
    loaded = repositories.events.get("evt_test")
    assert loaded is not None
    assert loaded.event_id == "evt_test"
