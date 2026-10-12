"""Provider and routing enum contracts."""

from __future__ import annotations

from enum import StrEnum


class SurfaceKind(StrEnum):
    """Detected local surface categories used for provider routing."""

    WEB_BROWSER = "web_browser"
    DESKTOP_WINDOW = "desktop_window"
    UNKNOWN = "unknown"


class ProviderCapability(StrEnum):
    """Capabilities a provider can advertise to the capture router."""

    RESOLVE_SOURCE = "resolve_source"
    COLLECT_SYSTEM_APPSHOT = "collect_system_appshot"
    READ_A11Y = "read_a11y"
    COLLECT_PAGE_METADATA = "collect_page_metadata"
    COLLECT_VISIBLE_TEXT = "collect_visible_text"
    COLLECT_SELECTED_TEXT = "collect_selected_text"
    COLLECT_PAGE_TEXT = "collect_page_text"
    COLLECT_READABILITY_TEXT = "collect_readability_text"
    COLLECT_SANITIZED_DOM = "collect_sanitized_dom"
    COLLECT_FULL_DOM = "collect_full_dom"
    MAP_SELECTION = "map_selection"
    BUILD_CANONICAL_TEXT = "build_canonical_text"
    RUN_VISUAL_OCR = "run_visual_ocr"


class ProviderKind(StrEnum):
    """Provider runtime families that can register command sessions."""

    SOURCE = "source"
    SYSTEM_EVIDENCE = "system_evidence"
    ENRICHMENT = "enrichment"


class ProviderMode(StrEnum):
    """Provider execution modes advertised by provider manifests."""

    CAPTURE = "capture"
    ENRICH = "enrich"
    SYSTEM = "system"


class ProviderRouteRole(StrEnum):
    """Role assigned to a routed provider inside one capture run."""

    PRIMARY_SOURCE = "primary_source"
    SECONDARY_SOURCE = "secondary_source"
    SYSTEM_EVIDENCE = "system_evidence"


class ProviderCommandType(StrEnum):
    """Command names sent from the daemon to provider sessions."""

    COLLECT_EVIDENCE = "collect_evidence"
    HEARTBEAT = "heartbeat"


class ProviderCommandStatus(StrEnum):
    """Provider command lifecycle result."""

    SUCCEEDED = "succeeded"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class ProviderCaptureOutcomeStatus(StrEnum):
    """Capture-run outcome for one routed provider or system evidence source."""

    SELECTED = "selected"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    STALE = "stale"
    UNSUPPORTED = "unsupported"
    TIMEOUT = "timeout"


class ProviderInstallKind(StrEnum):
    """How a provider is made available to WorkRecorder."""

    BUILT_IN = "built_in"
    MANUAL_UNPACKED_BROWSER_EXTENSION = "manual_unpacked_browser_extension"
    FUTURE_EXTERNAL_CONNECTOR = "future_external_connector"


class ProviderRuntimeState(StrEnum):
    """Workbench-facing provider lifecycle state."""

    READY = "ready"
    NEEDS_SETUP = "needs_setup"
    ONLINE = "online"
    STALE = "stale"
    OFFLINE = "offline"
    ERROR = "error"


class ProviderPermissionKind(StrEnum):
    """Permission families a provider may require."""

    SCREEN_RECORDING = "screen_recording"
    ACCESSIBILITY = "accessibility"
    BROWSER_EXTENSION = "browser_extension"
    LOCAL_DAEMON = "local_daemon"


class ProviderPermissionState(StrEnum):
    """Safe permission state exposed to setup and diagnostics UIs."""

    GRANTED = "granted"
    NEEDS_USER_ACTION = "needs_user_action"
    NOT_REQUIRED = "not_required"
    UNKNOWN = "unknown"


class ProviderDiagnosticStatus(StrEnum):
    """Result of a provider lifecycle diagnostic check."""

    PASSED = "passed"
    WARNING = "warning"
    FAILED = "failed"


class ProviderDecisionStatus(StrEnum):
    """Routing decision status for one provider."""

    SELECTED = "selected"
    SKIPPED = "skipped"
    UNSUPPORTED = "unsupported"
    STALE = "stale"
