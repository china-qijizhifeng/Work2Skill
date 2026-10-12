"""Typed contracts for event-driven active-capture keyframe scheduling."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field, model_validator

from .active_capture import ActiveCaptureBinding, KeyframeDiffReport, KeyframeQualityReport, RecordingScope
from .active_capture_keyframe_timing import SettleProbeSnapshot
from .active_capture_metadata import validate_safe_metadata
from .base import ContractModel
from .common import JsonScalar
from .enums import (
    HumanActionEvidenceRole,
    KeyframeDropReason,
    KeyframeKeepReason,
    KeyframePriorityBand,
    KeyframeRole,
    KeyframeTriggerCandidateStatus,
    KeyframeTriggerKind,
)


class TriggerDebouncePolicy(ContractModel):
    """Configurable debounce and budget policy for trigger candidates."""

    min_keyframe_gap_ms: int = Field(default=500, ge=0)
    click_settle_delay_ms: int = Field(default=300, ge=0)
    scroll_stop_delay_ms: int = Field(default=400, ge=0)
    typing_pause_delay_ms: int = Field(default=500, ge=0)
    idle_anchor_interval_ms: int = Field(default=30_000, ge=1_000)
    visual_diff_threshold: float = Field(default=0.06, ge=0.0, le=1.0)
    text_diff_threshold: float = Field(default=0.12, ge=0.0, le=1.0)
    max_pending_candidates: int = Field(default=128, ge=1, le=10_000)


class KeyframeTriggerCandidate(ContractModel):
    """A typed event that may become a kept or dropped keyframe."""

    candidate_id: str
    session_id: str
    trigger_kind: KeyframeTriggerKind
    role: KeyframeRole
    priority: KeyframePriorityBand
    status: KeyframeTriggerCandidateStatus = KeyframeTriggerCandidateStatus.RECEIVED
    occurred_at: datetime
    occurred_at_monotonic_ms: int | None = Field(default=None, ge=0)
    event_id: str | None = None
    keyframe_id: str | None = None
    action_id: str | None = None
    action_evidence_role: HumanActionEvidenceRole | None = None
    keep_reason: KeyframeKeepReason | None = None
    drop_reason: KeyframeDropReason | None = None
    scope: RecordingScope | None = None
    diff: KeyframeDiffReport | None = None
    quality: KeyframeQualityReport | None = None
    debounce_until_monotonic_ms: int | None = Field(default=None, ge=0)
    policy_version: str = Field(default="active_capture_policy_v1", min_length=1)
    diagnostics: tuple[str, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata_keys(self) -> "KeyframeTriggerCandidate":
        validate_safe_metadata(self.metadata, context="keyframe trigger candidate metadata")
        if self.action_evidence_role is not None and self.action_id is None:
            raise ValueError("keyframe trigger candidate action_evidence_role requires action_id")
        return self


class KeyframeCaptureInstruction(ContractModel):
    """Typed instruction for a trusted producer to capture an accepted trigger."""

    candidate_id: str
    session_id: str
    role: KeyframeRole
    trigger_kind: KeyframeTriggerKind
    binding: ActiveCaptureBinding
    execute_after_monotonic_ms: int | None = Field(default=None, ge=0)


class KeyframeTriggerPublicSummary(ContractModel):
    """Public trigger response without scope, diff, quality, or producer metadata."""

    candidate_id: str
    status: KeyframeTriggerCandidateStatus
    trigger_kind: KeyframeTriggerKind
    role: KeyframeRole
    priority: KeyframePriorityBand
    debounce_until_monotonic_ms: int | None = Field(default=None, ge=0)
    keyframe_id: str | None = None
    event_id: str | None = None
    drop_reason: KeyframeDropReason | None = None
    diagnostics: tuple[str, ...] = Field(default_factory=tuple)


class KeyframeTriggerSubmission(ContractModel):
    """Response for trigger submissions plus an optional capture instruction."""

    candidate: KeyframeTriggerPublicSummary
    capture_instruction: KeyframeCaptureInstruction | None = None


class PollKeyframeCaptureInstructionsCommand(ContractModel):
    """Trusted native producer request to poll finalized settle instructions."""

    now_monotonic_ms: int = Field(ge=0)
    limit: int = Field(default=16, ge=1, le=128)
    probe_snapshot: SettleProbeSnapshot | None = None
    allow_degraded_sample: bool = True


class PendingKeyframeCaptureInstructionsResponse(ContractModel):
    """Instructions ready after adaptive-settle polling finalized candidates."""

    instructions: tuple[KeyframeCaptureInstruction, ...] = Field(default_factory=tuple)
    observed_candidate_count: int = Field(default=0, ge=0)
    ready_candidate_count: int = Field(default=0, ge=0)
    probe_required_candidate_count: int = Field(default=0, ge=0)


class ReportKeyframeCaptureFailureCommand(ContractModel):
    """Trusted native report that a capture instruction could not be committed."""

    candidate_id: str = Field(min_length=1)
    reason: KeyframeDropReason = KeyframeDropReason.INVALID_EVIDENCE
    diagnostic: str | None = Field(default=None, max_length=160)

    @model_validator(mode="after")
    def _reject_sensitive_diagnostic(self) -> "ReportKeyframeCaptureFailureCommand":
        diagnostic = (self.diagnostic or "").lower()
        forbidden = ("/users/", "local_path", "storage_uri", "bearer", "token", "password", "secret")
        if any(item in diagnostic for item in forbidden):
            raise ValueError("capture failure diagnostic must not contain sensitive material")
        return self


class SubmitKeyframeTriggerCommand(ContractModel):
    """Command accepted by trusted producers to submit a trigger candidate."""

    trigger_kind: KeyframeTriggerKind
    role: KeyframeRole | None = None
    priority: KeyframePriorityBand | None = None
    keep_reason: KeyframeKeepReason | None = None
    occurred_at_monotonic_ms: int | None = Field(default=None, ge=0)
    debounce_until_monotonic_ms: int | None = Field(default=None, ge=0)
    event_id: str | None = None
    action_id: str | None = None
    action_evidence_role: HumanActionEvidenceRole | None = None
    scope: RecordingScope | None = None
    diff: KeyframeDiffReport | None = None
    quality: KeyframeQualityReport | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_sensitive_metadata_keys(self) -> "SubmitKeyframeTriggerCommand":
        validate_safe_metadata(self.metadata, context="keyframe trigger command metadata")
        if self.action_evidence_role is not None and self.action_id is None:
            raise ValueError("keyframe trigger command action_evidence_role requires action_id")
        return self
