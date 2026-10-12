"""Provider session and command contracts for event-driven capture."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from .base import ContractModel
from .capture import CaptureAttemptRequest
from .common import BrowserTabRef, DetectedSurface, FloatRect, JsonScalar, SourceBinding
from .enums import (
    DomCaptureMode,
    EvidenceKind,
    ProviderCapability,
    ProviderCommandStatus,
    ProviderCommandType,
    ProviderDiagnosticStatus,
    ProviderInstallKind,
    ProviderKind,
    ProviderPermissionKind,
    ProviderPermissionState,
    ProviderRuntimeState,
    SourceType,
)
from .protocol import ProviderEvidenceBundle
from .web import BrowserViewport, BrowserWindowRef


class ProviderSessionRegistration(ContractModel):
    """Online provider session registered with the daemon command bus.

    The registration contains identity, route hints, and capabilities only. It
    must not carry DOM, page text, a11y text, screenshots, or other evidence.
    """

    schema_version: int = Field(default=1, ge=1)
    provider_key: str = Field(min_length=1)
    provider_session_id: str = Field(min_length=1, max_length=180)
    provider_kind: ProviderKind
    display_name: str | None = None
    app_name: str | None = None
    process_id: int | None = None
    window_id: str | None = None
    window: BrowserWindowRef | None = None
    tab: BrowserTabRef | None = None
    viewport: BrowserViewport | None = None
    capabilities: tuple[ProviderCapability, ...] = Field(default_factory=tuple)
    registered_at: datetime
    ttl_ms: int = Field(default=15000, ge=1000, le=120000)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class ProviderInstallSpec(ContractModel):
    """Workbench-facing provider installation instructions."""

    install_kind: ProviderInstallKind
    bundled_resource: str | None = None
    open_url: str | None = None
    copy_path_hint: str | None = None
    supports_auto_install: bool = False
    runtime_targets: tuple["ProviderInstallTarget", ...] = Field(default_factory=tuple)
    instructions: tuple[str, ...] = Field(default_factory=tuple)


class ProviderInstallTarget(ContractModel):
    """Concrete runtime target for a provider setup action."""

    target_key: str = Field(min_length=1)
    display_name: str
    open_url: str
    instructions: tuple[str, ...] = Field(default_factory=tuple)


class ProviderPermissionSpec(ContractModel):
    """Permission needed by a provider before it can collect evidence."""

    permission_key: ProviderPermissionKind
    display_name: str
    state: ProviderPermissionState = ProviderPermissionState.UNKNOWN
    reason: str
    action_label: str | None = None
    action_url: str | None = None


class ProviderRuntimeHealth(ContractModel):
    """Runtime health summary independent from a single WebSocket session."""

    state: ProviderRuntimeState
    connected_session_count: int = Field(default=0, ge=0)
    last_seen_at: datetime | None = None
    message: str | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class ProviderDiagnosticCheck(ContractModel):
    """Diagnostic check advertised by a provider lifecycle definition."""

    check_key: str = Field(min_length=1)
    display_name: str
    description: str


class ProviderDiagnosticResult(ContractModel):
    """Result of one provider lifecycle diagnostic check."""

    check_key: str = Field(min_length=1)
    status: ProviderDiagnosticStatus
    message: str
    details: dict[str, JsonScalar] = Field(default_factory=dict)


class ProviderDefinition(ContractModel):
    """Provider lifecycle definition used by WorkRecorder.app and future installers."""

    provider_key: str = Field(min_length=1)
    display_name: str
    summary: str
    provider_kind: ProviderKind
    source_types: tuple[SourceType, ...] = Field(default_factory=tuple)
    install: ProviderInstallSpec
    permissions: tuple[ProviderPermissionSpec, ...] = Field(default_factory=tuple)
    diagnostics: tuple[ProviderDiagnosticCheck, ...] = Field(default_factory=tuple)
    manifest_key: str | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class ProviderStatusReport(ContractModel):
    """Aggregated install, permission, session, and diagnostic status."""

    provider_key: str
    display_name: str
    installed: bool = False
    configured: bool = False
    permissions: tuple[ProviderPermissionSpec, ...] = Field(default_factory=tuple)
    runtime: ProviderRuntimeHealth
    diagnostics: tuple[ProviderDiagnosticResult, ...] = Field(default_factory=tuple)
    sessions: tuple[ProviderSessionRef, ...] = Field(default_factory=tuple)


class ProviderSessionRef(ContractModel):
    """Safe provider session metadata returned to diagnostics and routing."""

    provider_key: str
    provider_session_id: str
    provider_kind: ProviderKind
    display_name: str | None = None
    app_name: str | None = None
    process_id: int | None = None
    window_id: str | None = None
    tab: BrowserTabRef | None = None
    capabilities: tuple[ProviderCapability, ...] = Field(default_factory=tuple)
    registered_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    connected: bool = True


class ProviderHeartbeat(ContractModel):
    """Provider liveness and route-hint refresh without evidence payloads."""

    provider_key: str
    provider_session_id: str
    observed_at: datetime
    tab: BrowserTabRef | None = None
    viewport: BrowserViewport | None = None
    window: BrowserWindowRef | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class CollectEvidenceCommand(ContractModel):
    """Capture-time command sent from daemon to one provider session."""

    command_id: str
    provider_key: str
    attempt: CaptureAttemptRequest
    surface: DetectedSurface | None = None
    evidence_kinds: tuple[EvidenceKind, ...] = Field(default_factory=tuple)
    required_capabilities: tuple[ProviderCapability, ...] = Field(default_factory=tuple)
    dom_capture_mode: DomCaptureMode = DomCaptureMode.SANITIZED_SELECTION
    selection_in_surface: FloatRect | None = None
    deadline_ms: int = Field(default=3000, ge=100, le=30000)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class ProviderCommandEnvelope(ContractModel):
    """WebSocket message sent by the daemon to a provider."""

    schema_version: int = Field(default=1, ge=1)
    message_type: ProviderCommandType
    command: CollectEvidenceCommand
    sent_at: datetime


class CollectEvidenceResult(ContractModel):
    """Typed result returned by a provider after a collect command."""

    schema_version: int = Field(default=1, ge=1)
    message_type: str = Field(default="collect_evidence_result")
    command_id: str
    provider_key: str
    provider_session_id: str | None = None
    status: ProviderCommandStatus
    evidence_kind: EvidenceKind
    source_binding: SourceBinding | None = None
    evidence_bundle: ProviderEvidenceBundle | None = None
    diagnostics: dict[str, JsonScalar] = Field(default_factory=dict)
    error_message: str | None = None
    completed_at: datetime


class CaptureEvidenceBundle(ContractModel):
    """Merged provider evidence produced for a single accepted capture."""

    source_binding: SourceBinding
    event_type: str
    evidence: tuple[ProviderEvidenceBundle, ...] = Field(default_factory=tuple)
    command_results: tuple[CollectEvidenceResult, ...] = Field(default_factory=tuple)
