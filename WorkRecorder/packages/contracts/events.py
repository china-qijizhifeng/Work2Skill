"""Context event and trigger contracts for WorkRecorder."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import ContractModel
from .common import ActorRef, BoundingBox, JsonScalar, SourceBinding, UserRef
from .enums import CaptureStrategy, EventStatus, TriggerType


class TriggerEnvelope(ContractModel):
    """Normalized trigger emitted by capture shells and future adapters.

    Attributes:
        trigger_id: Stable trigger id created before event persistence.
        trigger_type: Typed trigger category.
        capture_strategy: Capture strategy selected for the attempt.
        actor: User or system actor that initiated the attempt.
        occurred_at: Time the user action occurred.
        selection: Optional region selected by the user.
        intent_text: Optional one-line user intent.
        surface_id: Optional desktop, browser tab, or source surface id.
        device_id: Optional endpoint device id for future policy and audit.
        metadata: Small scalar trigger metadata that adapters can extend safely.
    """

    trigger_id: str
    trigger_type: TriggerType
    capture_strategy: CaptureStrategy
    actor: ActorRef
    occurred_at: datetime
    selection: BoundingBox | None = None
    intent_text: str | None = None
    surface_id: str | None = None
    device_id: str | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class ContextEventCreate(ContractModel):
    """Create request accepted by the P0 daemon.

    Attributes:
        trigger: Normalized trigger envelope.
        source_binding: Source that the daemon resolved before persistence.
        event_type: Product event type string kept explicit for taxonomy growth.
        intent_text: User intent to carry into search and bundle creation.
    """

    trigger: TriggerEnvelope
    source_binding: SourceBinding
    event_type: str = Field(default="webpage.selection.captured", min_length=1)
    intent_text: str | None = None


class ContextEvent(ContractModel):
    """Persisted context event fact.

    Attributes:
        event_id: Stable event id.
        event_type: Event taxonomy value.
        trigger: Original normalized trigger.
        source_binding: Source binding used for the event.
        status: Current event lifecycle status.
        intent_text: User intent or note.
        created_at: Persistence time.
        updated_at: Last lifecycle update time.
    """

    event_id: str
    event_type: str
    trigger: TriggerEnvelope
    source_binding: SourceBinding
    status: EventStatus
    intent_text: str | None
    created_at: datetime
    updated_at: datetime
    user: UserRef | None = None
