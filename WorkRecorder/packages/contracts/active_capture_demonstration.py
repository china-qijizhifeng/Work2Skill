"""Typed low-sensitive human demonstration trace contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from .active_capture import RecordingScope
from .active_capture_metadata import validate_safe_metadata
from .base import ContractModel
from .common import BoundingBox, JsonScalar
from .enums import (
    CoordinateSpace,
    HotkeySemantic,
    HumanActionEvidenceRole,
    HumanActionKind,
    HumanActionOutcomeStatus,
    HumanActionTargetKind,
    HumanDemonstrationTraceStatus,
    RedactionState,
)


def _validate_action_metadata(metadata: dict[str, JsonScalar]) -> None:
    validate_safe_metadata(metadata, context="human action metadata")


def _target_has_free_text(target: "ActionTargetRef | None") -> bool:
    if target is None:
        return False
    return any(
        (
            target.selector,
            target.element_id,
            target.role,
            target.accessible_name,
            target.metadata,
        )
    )


class ActionPoint(ContractModel):
    """A point in an explicit coordinate space."""

    x: float
    y: float
    coordinate_space: CoordinateSpace
    display_id: str | None = None
    scale_factor: float | None = Field(default=None, gt=0.0)


class ActionCoordinates(ContractModel):
    """Exact coordinates preserved for reproducible but reviewable traces."""

    screen_abs: ActionPoint | None = None
    screenshot_rel: ActionPoint | None = None
    scope_rel: ActionPoint | None = None
    target_bounds: BoundingBox | None = None

    @model_validator(mode="after")
    def _require_at_least_one_coordinate(self) -> "ActionCoordinates":
        if not any((self.screen_abs, self.screenshot_rel, self.scope_rel, self.target_bounds)):
            raise ValueError("action coordinates require at least one point or target bounds")
        return self


class ActionTargetRef(ContractModel):
    """Typed target reference for one human action."""

    target_kind: HumanActionTargetKind = HumanActionTargetKind.UNKNOWN
    keyframe_id: str | None = None
    evidence_id: str | None = None
    artifact_id: str | None = None
    provider_key: str | None = None
    selector: str | None = Field(default=None, max_length=1_000)
    element_id: str | None = Field(default=None, max_length=500)
    role: str | None = Field(default=None, max_length=120)
    accessible_name: str | None = Field(default=None, max_length=500)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    coordinates: ActionCoordinates | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata_keys(self) -> "ActionTargetRef":
        _validate_action_metadata(self.metadata)
        return self


class HumanActionSemanticHint(ContractModel):
    """Reviewable semantic hint; never raw ordinary keyboard content."""

    label: str | None = Field(default=None, max_length=500)
    intent: str | None = Field(default=None, max_length=1_000)
    result_hint: str | None = Field(default=None, max_length=1_000)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    generated_by: str | None = Field(default=None, max_length=200)


class ActionEvidenceLink(ContractModel):
    """Traceable evidence edge for a human action."""

    link_id: str
    action_id: str
    role: HumanActionEvidenceRole
    keyframe_id: str | None = None
    event_id: str | None = None
    evidence_id: str | None = None
    artifact_id: str | None = None
    created_at: datetime
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata_keys(self) -> "ActionEvidenceLink":
        _validate_action_metadata(self.metadata)
        return self


class ActionEvidenceRefInput(ContractModel):
    """Input reference to evidence; repository assigns the link id."""

    role: HumanActionEvidenceRole
    keyframe_id: str | None = None
    event_id: str | None = None
    evidence_id: str | None = None
    artifact_id: str | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata_keys(self) -> "ActionEvidenceRefInput":
        _validate_action_metadata(self.metadata)
        return self


class ActionResultObservation(ContractModel):
    """Observed state after an action, linked to evidence when possible."""

    observation_id: str
    action_id: str
    status: HumanActionOutcomeStatus = HumanActionOutcomeStatus.UNKNOWN
    observed_at: datetime
    observed_at_monotonic_ms: int | None = Field(default=None, ge=0)
    result_keyframe_id: str | None = None
    summary: str | None = Field(default=None, max_length=1_000)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata_keys(self) -> "ActionResultObservation":
        _validate_action_metadata(self.metadata)
        return self


class ActionResultObservationInput(ContractModel):
    """Input observation; service assigns observation/action ids."""

    status: HumanActionOutcomeStatus = HumanActionOutcomeStatus.UNKNOWN
    observed_at_monotonic_ms: int | None = Field(default=None, ge=0)
    result_keyframe_id: str | None = None
    summary: str | None = Field(default=None, max_length=1_000)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata_keys(self) -> "ActionResultObservationInput":
        _validate_action_metadata(self.metadata)
        return self


class HumanActionEvent(ContractModel):
    """One low-sensitive action event recorded during a user-triggered session."""

    action_id: str
    trace_id: str
    session_id: str
    sequence_index: int = Field(ge=0)
    kind: HumanActionKind
    occurred_at: datetime
    occurred_at_monotonic_ms: int | None = Field(default=None, ge=0)
    media_time_ms: int | None = Field(default=None, ge=0)
    scope: RecordingScope | None = None
    coordinates: ActionCoordinates | None = None
    target: ActionTargetRef | None = None
    semantic_hint: HumanActionSemanticHint | None = None
    hotkey_semantic: HotkeySemantic | None = None
    scroll_delta_x: float | None = None
    scroll_delta_y: float | None = None
    result_observation: ActionResultObservation | None = None
    redaction_state: RedactionState = RedactionState.NONE
    policy_version: str = Field(default="active_capture_policy_v1", min_length=1)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_action_shape(self) -> "HumanActionEvent":
        if self.kind == HumanActionKind.HOTKEY and self.hotkey_semantic is None:
            raise ValueError("hotkey action requires hotkey_semantic")
        if self.kind in {HumanActionKind.CLICK, HumanActionKind.DRAG} and self.coordinates is None and self.target is None:
            raise ValueError(f"{self.kind.value} action requires coordinates or target")
        if self.kind == HumanActionKind.SCROLL and self.scroll_delta_x is None and self.scroll_delta_y is None:
            raise ValueError("scroll action requires scroll delta")
        if self.kind == HumanActionKind.TYPING_PAUSE and self.semantic_hint is not None:
            raise ValueError("typing_pause action cannot carry free-text semantic_hint")
        if (
            self.kind == HumanActionKind.TYPING_PAUSE
            and self.result_observation is not None
            and self.result_observation.summary is not None
        ):
            raise ValueError("typing_pause action cannot carry free-text result summary")
        if self.kind == HumanActionKind.TYPING_PAUSE and _target_has_free_text(self.target):
            raise ValueError("typing_pause action cannot carry free-text target fields")
        _validate_action_metadata(self.metadata)
        return self


class HumanActionPublicSummary(ContractModel):
    """Public action write response without exact coordinates or metadata."""

    action_id: str
    trace_id: str
    session_id: str
    sequence_index: int = Field(ge=0)
    kind: HumanActionKind
    occurred_at: datetime
    occurred_at_monotonic_ms: int | None = Field(default=None, ge=0)
    media_time_ms: int | None = Field(default=None, ge=0)
    hotkey_semantic: HotkeySemantic | None = None
    result_status: HumanActionOutcomeStatus | None = None


class HumanDemonstrationTrace(ContractModel):
    """Session-level trace that can later seed workflow/skill distillation."""

    trace_id: str
    session_id: str
    status: HumanDemonstrationTraceStatus
    action_count: int = Field(default=0, ge=0)
    started_at: datetime
    ended_at: datetime | None = None
    policy_version: str = Field(default="active_capture_policy_v1", min_length=1)
    warnings: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class RecordHumanActionCommand(ContractModel):
    """Command accepted by trusted producers to append one action event."""

    kind: HumanActionKind
    occurred_at_monotonic_ms: int | None = Field(default=None, ge=0)
    media_time_ms: int | None = Field(default=None, ge=0)
    scope: RecordingScope | None = None
    coordinates: ActionCoordinates | None = None
    target: ActionTargetRef | None = None
    semantic_hint: HumanActionSemanticHint | None = None
    hotkey_semantic: HotkeySemantic | None = None
    scroll_delta_x: float | None = None
    scroll_delta_y: float | None = None
    result: ActionResultObservationInput | None = None
    evidence_refs: tuple[ActionEvidenceRefInput, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata_keys(self) -> "RecordHumanActionCommand":
        _validate_action_metadata(self.metadata)
        if self.kind == HumanActionKind.TYPING_PAUSE and self.semantic_hint is not None:
            raise ValueError("typing_pause action cannot carry free-text semantic_hint")
        if self.kind == HumanActionKind.TYPING_PAUSE and self.result is not None and self.result.summary is not None:
            raise ValueError("typing_pause action cannot carry free-text result summary")
        if self.kind == HumanActionKind.TYPING_PAUSE and _target_has_free_text(self.target):
            raise ValueError("typing_pause action cannot carry free-text target fields")
        return self
