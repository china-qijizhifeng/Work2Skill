"""Ports used by active-capture inspect projections."""

from __future__ import annotations

from typing import Protocol

from packages.contracts import ActorRef, ContextEvent, EventInspectSection, EventInspectView


class EventLookupPort(Protocol):
    """Narrow port for looking up event metadata needed by inspect."""

    def get_event(
        self,
        event_id: str,
        *,
        actor: ActorRef | None = None,
        workspace_id: str | None = None,
    ) -> ContextEvent | None: ...

    def get_events(
        self,
        event_ids: tuple[str, ...],
        *,
        actor: ActorRef | None = None,
        workspace_id: str | None = None,
    ) -> tuple[ContextEvent, ...]: ...


class EventEvidenceInspectPort(Protocol):
    """Narrow port over the existing event disclosure inspect service."""

    def inspect_event(
        self,
        *,
        event: ContextEvent,
        actor: ActorRef,
        purpose: str,
        requested_sections: tuple[EventInspectSection, ...],
    ) -> EventInspectView: ...
