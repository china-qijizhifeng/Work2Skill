"""Daemon adapters for active-capture inspect services."""

from __future__ import annotations

from packages.active_capture.application.inspect import EventEvidenceInspectPort, EventLookupPort
from packages.contracts import ActorRef, ContextEvent, EventInspectSection, EventInspectView, EventStatus
from packages.disclosure import DisclosurePolicyService
from packages.storage.event_repository import ContextEventRepository

_LOCAL_ACTIVE_CAPTURE_READER_ACTORS = frozenset({"workrecorder-workbench"})


class RepositoryEventLookupAdapter(EventLookupPort):
    """Adapt the daemon event repository to the active-capture inspect port."""

    def __init__(self, events: ContextEventRepository) -> None:
        self.events = events

    def get_event(
        self,
        event_id: str,
        *,
        actor: ActorRef | None = None,
        workspace_id: str | None = None,
    ) -> ContextEvent | None:
        events = self.get_events((event_id,), actor=actor, workspace_id=workspace_id)
        return events[0] if events else None

    def get_events(
        self,
        event_ids: tuple[str, ...],
        *,
        actor: ActorRef | None = None,
        workspace_id: str | None = None,
    ) -> tuple[ContextEvent, ...]:
        events = self.events.list_by_ids(tuple(dict.fromkeys(event_ids)))
        return tuple(event for event in events if self._event_allowed(event, actor=actor, workspace_id=workspace_id))

    def _event_allowed(
        self,
        event: ContextEvent,
        *,
        actor: ActorRef | None,
        workspace_id: str | None,
    ) -> bool:
        if event.status in {EventStatus.DELETED, EventStatus.RESTRICTED}:
            return False
        if actor is not None and event.trigger.actor.actor_id != actor.actor_id:
            if actor.actor_id in _LOCAL_ACTIVE_CAPTURE_READER_ACTORS:
                return self._workspace_allowed(event, workspace_id=workspace_id)
            if event.user is None or event.user.user_id != actor.actor_id:
                return False
        return self._workspace_allowed(event, workspace_id=workspace_id)

    def _workspace_allowed(self, event: ContextEvent, *, workspace_id: str | None) -> bool:
        if workspace_id is not None and event.user is not None and event.user.tenant_key != workspace_id:
            return False
        return True


class DisclosureEventEvidenceInspectAdapter(EventEvidenceInspectPort):
    """Adapt the existing disclosure inspect service without route coupling."""

    def __init__(self, disclosure: DisclosurePolicyService) -> None:
        self.disclosure = disclosure

    def inspect_event(
        self,
        *,
        event: ContextEvent,
        actor: ActorRef,
        purpose: str,
        requested_sections: tuple[EventInspectSection, ...],
    ) -> EventInspectView:
        return self.disclosure.inspect_event(
            event=event,
            actor=actor,
            purpose=purpose,
            requested_sections=requested_sections,
        )
