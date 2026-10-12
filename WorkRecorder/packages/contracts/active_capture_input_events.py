"""Typed producer-event contracts for active-capture input streams."""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import Field, model_validator

from .active_capture import RecordingScope
from .active_capture_click_targets import ClickTargetPublicView
from .active_capture_demonstration import ActionCoordinates, ActionTargetRef, HumanActionPublicSummary
from .active_capture_metadata import validate_safe_metadata
from .active_capture_projection import ProjectionTruncationSummary
from .active_capture_triggers import KeyframeTriggerSubmission
from .base import ContractModel
from .common import JsonScalar
from .enums import (
    HotkeySemantic,
    HumanActionKind,
    HumanActionTargetKind,
    KeyboardEventKind,
    KeyboardInputClass,
    KeyCapturePolicy,
    KeyframeTriggerKind,
    ModifierKey,
    PointerButton,
    ProducerDecisionReason,
    ProducerDecisionStatus,
    ProducerInputEventKind,
    RedactionState,
    ScrollPhase,
)


def _validate_producer_metadata(metadata: dict[str, JsonScalar]) -> None:
    validate_safe_metadata(
        metadata,
        context="producer event metadata",
        extra_exact_keys=frozenset({"field"}),
        extra_fragments=("field",),
    )


class KeyChord(ContractModel):
    """Exact physical chord and optional produced text for one keyboard event."""

    physical_key_code: int = Field(ge=0)
    normalized_key_label: str = Field(min_length=1, max_length=80)
    modifiers: tuple[ModifierKey, ...] = Field(default_factory=tuple)
    keyboard_layout_id: str | None = Field(default=None, max_length=120)
    is_repeat: bool = False
    semantic: HotkeySemantic = HotkeySemantic.UNKNOWN
    characters: str | None = Field(default=None, max_length=64)


class PointerInputPayload(ContractModel):
    """Pointer click payload emitted by a trusted local producer."""

    button: PointerButton = PointerButton.LEFT
    click_count: int = Field(default=1, ge=1, le=5)
    coordinates: ActionCoordinates
    target: ActionTargetRef | None = None


class ScrollInputPayload(ContractModel):
    """Coalesced scroll payload emitted at gesture stop or phase transitions."""

    delta_x: float = 0.0
    delta_y: float = 0.0
    phase: ScrollPhase = ScrollPhase.UNKNOWN
    duration_ms: int | None = Field(default=None, ge=0)
    velocity_bucket: int | None = Field(default=None, ge=0, le=10)
    coordinates: ActionCoordinates | None = None
    target: ActionTargetRef | None = None

    @model_validator(mode="after")
    def _require_scroll_delta(self) -> "ScrollInputPayload":
        if self.delta_x == 0.0 and self.delta_y == 0.0:
            raise ValueError("scroll payload requires a non-zero delta")
        return self


class TypingSessionSummary(ContractModel):
    """Privacy-preserving summary of ordinary text entry."""

    event_count: int = Field(default=0, ge=0)
    text_event_count: int = Field(default=0, ge=0)
    character_count: int = Field(default=0, ge=0)
    deletion_key_count: int = Field(default=0, ge=0)
    non_text_key_count: int = Field(default=0, ge=0)
    composition_used: bool = False
    submitted_by_enter: bool = False
    duration_ms: int | None = Field(default=None, ge=0)
    target: ActionTargetRef | None = None


class KeyboardInputPayload(ContractModel):
    """Keyboard payload after producer-side classification."""

    keyboard_event_kind: KeyboardEventKind
    input_class: KeyboardInputClass = KeyboardInputClass.UNKNOWN
    capture_policy: KeyCapturePolicy = KeyCapturePolicy.AGGREGATE_ONLY
    key_chord: KeyChord | None = None
    typing_summary: TypingSessionSummary | None = None
    target: ActionTargetRef | None = None
    hotkey_semantic: HotkeySemantic | None = None

    @model_validator(mode="after")
    def _validate_keyboard_privacy_shape(self) -> "KeyboardInputPayload":
        if self.keyboard_event_kind in {KeyboardEventKind.KEY_DOWN, KeyboardEventKind.KEY_UP}:
            if self.capture_policy != KeyCapturePolicy.FULL_CONTENT:
                raise ValueError("low-level key_down/key_up events require full_content capture policy")
            if self.key_chord is None:
                raise ValueError("low-level key_down/key_up events require key_chord")
        if self.input_class in {KeyboardInputClass.TEXT_INPUT, KeyboardInputClass.COMPOSITION}:
            if self.capture_policy == KeyCapturePolicy.FULL_CONTENT:
                if self.key_chord is None:
                    raise ValueError("full-content text input requires key_chord")
            elif self.key_chord is not None:
                raise ValueError("ordinary text input cannot store exact key chords")
            if self.capture_policy not in {KeyCapturePolicy.AGGREGATE_ONLY, KeyCapturePolicy.FULL_CONTENT}:
                raise ValueError("ordinary text input must use aggregate-only capture policy")
        if self.capture_policy == KeyCapturePolicy.KEY_CHORD_ALLOWED and self.key_chord is None:
            raise ValueError("key_chord_allowed keyboard payload requires key_chord")
        if self.keyboard_event_kind == KeyboardEventKind.HOTKEY and self.hotkey_semantic is None:
            raise ValueError("hotkey keyboard payload requires hotkey_semantic")
        return self


class ProducerEventEnvelope(ContractModel):
    """Backend-owned trusted producer event persisted before projection."""

    producer_event_id: str
    session_id: str
    event_kind: ProducerInputEventKind
    producer_kind: str = Field(min_length=1, max_length=120)
    producer_version: str | None = Field(default=None, max_length=120)
    occurred_at: datetime
    occurred_at_wall_time: datetime | None = None
    occurred_at_monotonic_ms: int | None = Field(default=None, ge=0)
    scope: RecordingScope | None = None
    pointer: PointerInputPayload | None = None
    scroll: ScrollInputPayload | None = None
    keyboard: KeyboardInputPayload | None = None
    redaction_state: RedactionState = RedactionState.NONE
    policy_version: str = Field(default="active_capture_policy_v1", min_length=1)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_payload_for_kind(self) -> "ProducerEventEnvelope":
        _validate_producer_metadata(self.metadata)
        if self.event_kind in {ProducerInputEventKind.POINTER_CLICK, ProducerInputEventKind.POINTER_DRAG} and self.pointer is None:
            raise ValueError(f"{self.event_kind.value} event requires pointer payload")
        if self.event_kind == ProducerInputEventKind.SCROLL and self.scroll is None:
            raise ValueError("scroll event requires scroll payload")
        if (
            self.event_kind
            in {
                ProducerInputEventKind.KEY_DOWN,
                ProducerInputEventKind.KEY_UP,
                ProducerInputEventKind.HOTKEY,
                ProducerInputEventKind.TYPING_PAUSE,
            }
            and self.keyboard is None
        ):
            raise ValueError("keyboard event requires keyboard payload")
        return self


class ProducerDecision(ContractModel):
    """Typed decision linking one producer event to actions and triggers."""

    decision_id: str
    producer_event_id: str
    session_id: str
    status: ProducerDecisionStatus
    reason: ProducerDecisionReason
    native_status: ProducerDecisionStatus | None = None
    native_reason: ProducerDecisionReason | None = None
    action_kind: HumanActionKind | None = None
    trigger_kind: KeyframeTriggerKind | None = None
    action_id: str | None = None
    candidate_id: str | None = None
    keyframe_id: str | None = None
    debounce_until_monotonic_ms: int | None = Field(default=None, ge=0)
    key_capture_policy: KeyCapturePolicy | None = None
    redaction_state: RedactionState = RedactionState.NONE
    needs_review: bool = False
    created_at: datetime
    diagnostics: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata(self) -> "ProducerDecision":
        _validate_producer_metadata(self.metadata)
        return self


class RecordProducerInputEventCommand(ContractModel):
    """Trusted native command to append one input producer event."""

    event_kind: ProducerInputEventKind
    producer_kind: str = Field(min_length=1, max_length=120)
    producer_version: str | None = Field(default=None, max_length=120)
    occurred_at_wall_time: datetime | None = None
    occurred_at_monotonic_ms: int | None = Field(default=None, ge=0)
    scope: RecordingScope | None = None
    pointer: PointerInputPayload | None = None
    scroll: ScrollInputPayload | None = None
    keyboard: KeyboardInputPayload | None = None
    native_status: ProducerDecisionStatus | None = None
    native_reason: ProducerDecisionReason | None = None
    redaction_state: RedactionState = RedactionState.NONE
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_command_shape(self) -> "RecordProducerInputEventCommand":
        _validate_producer_metadata(self.metadata)
        envelope = ProducerEventEnvelope(
            producer_event_id="producer_event_validation_probe",
            session_id="session_validation_probe",
            event_kind=self.event_kind,
            producer_kind=self.producer_kind,
            producer_version=self.producer_version,
            occurred_at=self.occurred_at_wall_time or datetime.fromtimestamp(0, tz=UTC),
            occurred_at_wall_time=self.occurred_at_wall_time,
            occurred_at_monotonic_ms=self.occurred_at_monotonic_ms,
            scope=self.scope,
            pointer=self.pointer,
            scroll=self.scroll,
            keyboard=self.keyboard,
            redaction_state=self.redaction_state,
            metadata=self.metadata,
        )
        if envelope.producer_event_id != "producer_event_validation_probe":
            raise ValueError("invalid producer event command")
        return self


class RecordProducerInputBatchCommand(ContractModel):
    """Trusted native command to append one or more input events."""

    events: tuple[RecordProducerInputEventCommand, ...] = Field(min_length=1, max_length=100)


class ProducerEventPublicSummary(ContractModel):
    """Safe producer-event response without raw coordinates or typing details."""

    producer_event_id: str
    session_id: str
    event_kind: ProducerInputEventKind
    occurred_at: datetime
    occurred_at_monotonic_ms: int | None = Field(default=None, ge=0)
    redaction_state: RedactionState
    needs_review: bool = False


class ProducerDecisionPublicSummary(ContractModel):
    """Safe producer decision response without native diagnostics metadata."""

    decision_id: str
    producer_event_id: str
    session_id: str
    status: ProducerDecisionStatus
    reason: ProducerDecisionReason
    action_kind: HumanActionKind | None = None
    trigger_kind: KeyframeTriggerKind | None = None
    action_id: str | None = None
    candidate_id: str | None = None
    keyframe_id: str | None = None
    debounce_until_monotonic_ms: int | None = Field(default=None, ge=0)
    key_capture_policy: KeyCapturePolicy | None = None
    redaction_state: RedactionState = RedactionState.NONE
    needs_review: bool = False
    diagnostics: tuple[str, ...] = Field(default_factory=tuple)


class ProducerEventIngestResult(ContractModel):
    """Result of one producer event ingest."""

    event: ProducerEventPublicSummary
    decision: ProducerDecisionPublicSummary
    action: HumanActionPublicSummary | None = None
    trigger: KeyframeTriggerSubmission | None = None
    triggers: tuple[KeyframeTriggerSubmission, ...] = Field(default_factory=tuple)


class ProducerEventIngestBatchResult(ContractModel):
    """Batch result for trusted producer ingestion."""

    results: tuple[ProducerEventIngestResult, ...]


class SkillDistillationTargetView(ContractModel):
    """Safe target projection that strips selectors, a11y names, and metadata."""

    target_kind: HumanActionTargetKind = HumanActionTargetKind.UNKNOWN
    resolved_target: ClickTargetPublicView | None = None
    keyframe_id: str | None = None
    evidence_id: str | None = None
    artifact_id: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    has_coordinates: bool = False


class TypingSessionAggregateView(ContractModel):
    """Safe ordinary typing aggregate without raw text or target details."""

    event_count: int = Field(default=0, ge=0)
    text_event_count: int = Field(default=0, ge=0)
    character_count: int = Field(default=0, ge=0)
    deletion_key_count: int = Field(default=0, ge=0)
    non_text_key_count: int = Field(default=0, ge=0)
    composition_used: bool = False
    submitted_by_enter: bool = False
    duration_ms: int | None = Field(default=None, ge=0)


class SkillDistillationStepView(ContractModel):
    """Safe future P7.11 input step derived from persisted action traces."""

    step_id: str
    sequence_index: int = Field(ge=0)
    action_kind: HumanActionKind
    occurred_at: datetime
    media_time_ms: int | None = Field(default=None, ge=0)
    hotkey_semantic: HotkeySemantic | None = None
    key_chord: KeyChord | None = None
    trigger_kind: KeyframeTriggerKind | None = None
    target: SkillDistillationTargetView | None = None
    typing_summary: TypingSessionAggregateView | None = None
    evidence_keyframe_ids: tuple[str, ...] = Field(default_factory=tuple)
    needs_review: bool = False
    sensitivity_flags: tuple[ProducerDecisionReason, ...] = Field(default_factory=tuple)


class SkillDistillationInputView(ContractModel):
    """Read-only safe projection for future skill distillation."""

    session_id: str
    steps: tuple[SkillDistillationStepView, ...]
    projection: ProjectionTruncationSummary = Field(default_factory=ProjectionTruncationSummary)
    generated_at: datetime
    warnings: tuple[str, ...] = Field(default_factory=tuple)
