"""Contracts for OS-level capture shells and durable capture persistence."""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field

from .active_capture import ActiveCaptureBinding, NativeCaptureTimingReceipt
from .artifacts import Artifact, ArtifactManifest
from .base import ContractModel
from .common import ActorRef, BoundingBox, DetectedSurface, FloatRect, JsonScalar, SourceBinding, WindowHint
from .enums import (
    ArtifactType,
    CaptureAttemptStatus,
    ProviderDecisionStatus,
    ProviderKind,
    ProviderRouteRole,
    UnsupportedReason,
)
from .events import ContextEvent, TriggerEnvelope


class DisplayGeometry(ContractModel):
    """Display geometry reported by a native capture shell.

    Attributes:
        display_id: OS display identifier or a stable shell-provided label.
        frame: Display frame in the coordinate space used by the shell.
        scale_factor: Display backing scale factor.
    """

    display_id: str = Field(min_length=1)
    frame: BoundingBox
    scale_factor: float = Field(gt=0.0)


class SelectionGeometry(ContractModel):
    """User-selected region and display context for a capture.

    Attributes:
        selected_region: Region selected by the user.
        display: Display that owns the selected region.
        pixel_region: Optional region passed to the native screenshot tool.
    """

    selected_region: BoundingBox
    display: DisplayGeometry
    pixel_region: BoundingBox | None = None


class StagedArtifactRef(ContractModel):
    """Reference to a local file staged by the native capture shell.

    Attributes:
        local_path: Absolute local path inside the WorkRecorder staging directory.
        artifact_type: Artifact category expected after vault promotion.
        content_type: MIME type of the staged file.
        filename: Optional original file name for diagnostics.
        metadata: Small scalar metadata, never raw file content.
    """

    local_path: str = Field(min_length=1)
    artifact_type: ArtifactType = ArtifactType.SCREENSHOT
    content_type: str = Field(default="image/png", min_length=1)
    filename: str | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class WorkspaceSelection(ContractModel):
    """Workspace selection supplied by the Light Sheet.

    Attributes:
        workspace_id: Stable workspace id, or ``auto`` for deferred inference.
        label: User-facing workspace label.
        auto: Whether the daemon should keep the event in auto-routing mode.
    """

    AUTO_WORKSPACE_ID: ClassVar[str] = "auto"

    workspace_id: str = Field(default=AUTO_WORKSPACE_ID, min_length=1)
    label: str = Field(default="Auto", min_length=1)
    auto: bool = True

    @classmethod
    def auto_selection(cls) -> "WorkspaceSelection":
        """Return the explicit deferred-routing workspace contract."""

        return cls(workspace_id=cls.AUTO_WORKSPACE_ID, label="Auto", auto=True)

    @property
    def is_auto(self) -> bool:
        """Whether this workspace is still deferred to daemon inference."""

        return self.auto or self.workspace_id == self.AUTO_WORKSPACE_ID


class CaptureSaveRequest(ContractModel):
    """Atomic save request for a native OS capture.

    Attributes:
        trigger: Normalized trigger envelope created before persistence.
        selection_geometry: Screen/display geometry for the capture.
        source_binding: Best-effort source binding from the capture shell.
        workspace: Workspace selected or inferred by the user interface.
        actor: Actor used for audit and event ownership.
        staged_artifact: Screenshot file staged by the native shell.
        event_type: Context event taxonomy value.
        intent_text: Optional user note collected in the Light Sheet.
        metadata: Small scalar capture metadata.
    """

    trigger: TriggerEnvelope
    selection_geometry: SelectionGeometry
    source_binding: SourceBinding
    workspace: WorkspaceSelection = Field(default_factory=WorkspaceSelection)
    actor: ActorRef
    staged_artifact: StagedArtifactRef
    event_type: str = Field(default="screen.region.captured", min_length=1)
    intent_text: str | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class CaptureAttemptRequest(ContractModel):
    """Versioned capture attempt submitted by a system capture shell.

    The attempt contains system evidence and hints only. Final source binding,
    event type, provider selection, and app-specific evidence collection happen
    inside the daemon.
    """

    schema_version: int = Field(default=1, ge=1)
    trigger: TriggerEnvelope
    selection_geometry: SelectionGeometry
    window_hints: tuple[WindowHint, ...] = Field(default_factory=tuple)
    workspace: WorkspaceSelection = Field(default_factory=WorkspaceSelection)
    actor: ActorRef
    staged_artifact: StagedArtifactRef
    intent_text: str | None = None
    active_capture: ActiveCaptureBinding | None = None
    native_timing_receipt: NativeCaptureTimingReceipt | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class ProviderDecision(ContractModel):
    """Routing decision for a provider candidate."""

    provider_key: str
    status: ProviderDecisionStatus
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str | None = None
    surface_id: str | None = None


class ProviderRouteCandidate(ContractModel):
    """Provider route candidate produced by surface detection + routing."""

    route_id: str = Field(min_length=1)
    provider_key: str = Field(min_length=1)
    provider_kind: ProviderKind
    role: ProviderRouteRole
    surface_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    selected: bool = False
    reason: str | None = None
    target: dict[str, JsonScalar] = Field(default_factory=dict)


class ProviderRoutePlan(ContractModel):
    """Provider routing diagnostics persisted or returned for a capture."""

    trigger_id: str
    routes: tuple[ProviderRouteCandidate, ...] = Field(default_factory=tuple)
    primary_surface_id: str | None = None
    primary_route_id: str | None = None
    selected_route_ids: tuple[str, ...] = Field(default_factory=tuple)
    selected_provider_key: str | None = None
    selected_surface_id: str | None = None
    decisions: tuple[ProviderDecision, ...] = Field(default_factory=tuple)


class CoordinateTransform(ContractModel):
    """Mapping between two coordinate spaces for one capture."""

    source: BoundingBox | FloatRect
    target: BoundingBox | FloatRect
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    transform_version: str = "v1"


class SourceSpan(ContractModel):
    """Text span inside a source-native document."""

    selector: str | None = None
    start: int = Field(default=0, ge=0)
    end: int = Field(default=0, ge=0)
    text: str = ""


class SelectionMap(ContractModel):
    """Provider-produced map from selected screen region to source-native spans."""

    binding_id: str
    screen_region: BoundingBox
    viewport_region: FloatRect | None = None
    artifact_region: BoundingBox | None = None
    transforms: tuple[CoordinateTransform, ...] = Field(default_factory=tuple)
    spans: tuple[SourceSpan, ...] = Field(default_factory=tuple)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class CanonicalDocument(ContractModel):
    """Indexable text projection generated after capture-time policy checks."""

    event_id: str
    text: str
    source_artifact_ids: tuple[str, ...] = Field(default_factory=tuple)
    source_spans: tuple[SourceSpan, ...] = Field(default_factory=tuple)
    untrusted_source: bool = True


class CaptureProviderBundle(ContractModel):
    """Resolved provider result ready for persistence."""

    source_binding: SourceBinding
    event_type: str = "webpage.selection.captured"
    artifacts: tuple[ArtifactManifest, ...] = Field(default_factory=tuple)
    selected_surface: DetectedSurface | None = None


class CaptureSaveResponse(ContractModel):
    """Result returned after the daemon persists a native capture.

    Attributes:
        event: Persisted context event.
        artifact: Persisted screenshot artifact metadata.
        workspace: Workspace state used for the event.
        pending_enrichment: Whether asynchronous enrichment should run later.
        staged_file_retained: Whether the original staged file remains in place.
    """

    event: ContextEvent
    artifact: Artifact
    workspace: WorkspaceSelection
    pending_enrichment: bool
    staged_file_retained: bool = False


class CaptureAttemptResponse(ContractModel):
    """Result returned to capture shells after daemon provider orchestration."""

    status: CaptureAttemptStatus
    event: ContextEvent | None = None
    artifacts: tuple[Artifact, ...] = Field(default_factory=tuple)
    workspace: WorkspaceSelection | None = None
    pending_enrichment: bool = False
    route_plan: ProviderRoutePlan | None = None
    unsupported_reason: UnsupportedReason | None = None
    message: str | None = None
