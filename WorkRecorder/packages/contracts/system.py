"""System evidence contracts collected independently of app providers."""

from __future__ import annotations

from pydantic import Field, model_validator

from .base import ContractModel
from .common import BoundingBox, JsonScalar
from .enums import (
    A11yPermissionState,
    EvidenceKind,
    ProviderCaptureOutcomeStatus,
    ProviderPermissionState,
    ProviderRouteRole,
    SelectionTextSourceMethod,
    VisualOCRStatus,
)

FORBIDDEN_APPSHOT_KEY_MARKERS = ("raw", "vault", "storage_uri", "local_path", "storage_path")
FORBIDDEN_APPSHOT_VALUE_MARKERS = (
    "local-artifact://",
    "file://",
    "vault://",
    "/users/",
    "/private/",
    "/tmp/",
    "/var/folders/",
)


class A11yTextBlock(ContractModel):
    """Text extracted from one accessibility element overlapping a capture."""

    text: str = Field(min_length=1)
    block_id: str | None = None
    element_id: str | None = None
    role: str | None = None
    node_path: str | None = None
    role_path: tuple[str, ...] = Field(default_factory=tuple)
    text_source: str | None = None
    frame: BoundingBox | None = None
    selection_overlap_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    element_overlap_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    order_index: int | None = Field(default=None, ge=0)
    is_leaf_text: bool = True
    edge_recovered: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class SelectionTextBlock(ContractModel):
    """One text block admitted into the daemon-owned selection projection."""

    text: str = Field(min_length=1)
    source_block_id: str | None = None
    role: str | None = None
    frame: BoundingBox | None = None
    selection_overlap_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    element_overlap_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    edge_recovered: bool = False


class SelectionTextProjection(ContractModel):
    """Daemon-derived text projection for the user's OS selection bbox."""

    text: str = ""
    source_method: SelectionTextSourceMethod = SelectionTextSourceMethod.A11Y_BLOCKS
    selection: BoundingBox
    blocks: tuple[SelectionTextBlock, ...] = Field(default_factory=tuple)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    truncated: bool = False
    truncation_reason: str | None = None
    overbroad_parent_only: bool = False
    block_count: int = Field(default=0, ge=0)
    source_block_count: int = Field(default=0, ge=0)
    redaction_version: str = "local_dlp_v1"


class A11yNode(ContractModel):
    """Normalized accessibility node with geometry and useful text fields."""

    element_id: str | None = None
    role: str = Field(min_length=1)
    name: str | None = None
    value: str | None = None
    description: str | None = None
    frame: BoundingBox | None = None
    overlap_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    children: tuple["A11yNode", ...] = Field(default_factory=tuple)


class A11yCoverageReport(ContractModel):
    """Diagnostics for how well a11y extraction covered the selected bbox."""

    selection: BoundingBox
    permission_state: A11yPermissionState
    node_count: int = Field(ge=0)
    text_block_count: int = Field(ge=0)
    covered_area_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    error_message: str | None = None


class A11ySnapshot(ContractModel):
    """Accessibility evidence captured at the same instant as a screenshot."""

    extraction_revision: str = "macos_a11y_v1"
    permission_state: A11yPermissionState
    app_name: str | None = None
    process_id: int | None = None
    window_id: str | None = None
    selection: BoundingBox
    root_nodes: tuple[A11yNode, ...] = Field(default_factory=tuple)
    text_blocks: tuple[A11yTextBlock, ...] = Field(default_factory=tuple)
    full_text: str = ""
    coverage: A11yCoverageReport
    max_depth: int | None = Field(default=None, ge=0)
    max_nodes: int | None = Field(default=None, ge=0)
    truncated: bool = False


class SystemEvidenceBundle(ContractModel):
    """System evidence collected for a capture before source-specific evidence."""

    a11y: A11ySnapshot | None = None


class AppshotWindowIdentity(ContractModel):
    """User-facing app/window identity captured with a system appshot."""

    app_name: str
    title: str | None = None
    bundle_id: str | None = None
    bundle_url: str | None = None
    process_id: int | None = None
    window_id: str | None = None
    frame: BoundingBox | None = None
    display_id: str | None = None
    window_layer: int | None = None
    window_order: int | None = Field(default=None, ge=0)
    visible_area_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    is_frontmost: bool | None = None
    app_icon_ref: str | None = None


class AppshotSurfaceSnapshot(ContractModel):
    """One detected surface represented inside a system appshot."""

    surface_id: str
    kind: str = Field(min_length=1)
    role: ProviderRouteRole
    identity: AppshotWindowIdentity
    overlap_ratio: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)


class AppshotComponentRef(ContractModel):
    """Reference to one evidence-producing component inside an appshot."""

    provider_key: str = Field(min_length=1)
    evidence_kind: EvidenceKind
    status: ProviderCaptureOutcomeStatus
    role: ProviderRouteRole = ProviderRouteRole.SYSTEM_EVIDENCE
    route_id: str | None = None
    command_id: str | None = None
    provider_session_id: str | None = None
    evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    artifact_ids: tuple[str, ...] = Field(default_factory=tuple)
    reason_code: str | None = None


class AppshotPermissionReport(ContractModel):
    """Permission state captured when building the system appshot."""

    screen_recording: ProviderPermissionState = ProviderPermissionState.UNKNOWN
    accessibility: ProviderPermissionState = ProviderPermissionState.UNKNOWN
    target_app_allowed: bool | None = None
    blocked_reason: str | None = None


class AppshotQualityReport(ContractModel):
    """Quality and coverage diagnostics for a system appshot."""

    screenshot_present: bool = False
    a11y_supported: bool = False
    a11y_permission_state: A11yPermissionState | None = None
    surface_count: int = Field(default=0, ge=0)
    text_block_count: int = Field(default=0, ge=0)
    primary_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    coverage_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    diagnostics: tuple[str, ...] = Field(default_factory=tuple)


class SystemAppshotSnapshot(ContractModel):
    """Read-only system appshot made from screenshot, surfaces, AX, and OCR state."""

    schema_version: int = Field(default=1, ge=1)
    capture_revision: str = Field(min_length=1)
    selected_region: BoundingBox
    primary_surface_id: str | None = None
    primary_app_name: str | None = None
    primary_bundle_id: str | None = None
    primary_process_id: int | None = None
    primary_window_id: str | None = None
    surfaces: tuple[AppshotSurfaceSnapshot, ...] = Field(default_factory=tuple)
    screenshot_evidence_id: str | None = None
    a11y_evidence_ids: tuple[str, ...] = Field(default_factory=tuple)
    ocr_job_status: VisualOCRStatus | None = None
    quality: AppshotQualityReport
    permissions: AppshotPermissionReport
    components: tuple[AppshotComponentRef, ...] = Field(default_factory=tuple)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_raw_metadata(self) -> "SystemAppshotSnapshot":
        """Prevent appshot payloads from becoming covert raw-material carriers."""

        _reject_raw_locator_payload(self.model_dump(mode="json"))
        return self


def _reject_raw_locator_payload(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered_key = str(key).lower()
            if any(marker in lowered_key for marker in FORBIDDEN_APPSHOT_KEY_MARKERS):
                raise ValueError("system appshot payload must not contain raw or vault locator fields")
            _reject_raw_locator_payload(child)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _reject_raw_locator_payload(child)
        return
    if isinstance(value, str):
        lowered_value = value.lower()
        if any(marker in lowered_value for marker in FORBIDDEN_APPSHOT_VALUE_MARKERS):
            raise ValueError("system appshot payload must not contain raw or vault locator values")
