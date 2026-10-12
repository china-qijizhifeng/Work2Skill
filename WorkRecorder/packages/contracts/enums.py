"""Enumerations used by WorkRecorder contracts instead of raw strings."""

from __future__ import annotations

from enum import StrEnum

from .active_capture_enums import ActiveCaptureMetricName as ActiveCaptureMetricName
from .active_capture_enums import ActiveCaptureMode as ActiveCaptureMode
from .active_capture_enums import ActiveCaptureSessionSource as ActiveCaptureSessionSource
from .active_capture_enums import ActiveCaptureStatus as ActiveCaptureStatus
from .active_capture_enums import ActiveCaptureWarningCode as ActiveCaptureWarningCode
from .active_capture_enums import ClickTargetConfidenceBand as ClickTargetConfidenceBand
from .active_capture_enums import ClickTargetResolutionStatus as ClickTargetResolutionStatus
from .active_capture_enums import ClickTargetSemanticKind as ClickTargetSemanticKind
from .active_capture_enums import ClickTargetSourceKind as ClickTargetSourceKind
from .active_capture_enums import ClickTargetSuppressionReason as ClickTargetSuppressionReason
from .active_capture_enums import HotkeySemantic as HotkeySemantic
from .active_capture_enums import HumanActionEvidenceRole as HumanActionEvidenceRole
from .active_capture_enums import HumanActionKind as HumanActionKind
from .active_capture_enums import HumanActionOutcomeStatus as HumanActionOutcomeStatus
from .active_capture_enums import HumanActionTargetKind as HumanActionTargetKind
from .active_capture_enums import HumanDemonstrationTraceStatus as HumanDemonstrationTraceStatus
from .active_capture_enums import KeyboardEventKind as KeyboardEventKind
from .active_capture_enums import KeyboardInputClass as KeyboardInputClass
from .active_capture_enums import KeyCapturePolicy as KeyCapturePolicy
from .active_capture_enums import KeyframeBundleStatus as KeyframeBundleStatus
from .active_capture_enums import KeyframeDropReason as KeyframeDropReason
from .active_capture_enums import KeyframeEvidenceRole as KeyframeEvidenceRole
from .active_capture_enums import KeyframeKeepReason as KeyframeKeepReason
from .active_capture_enums import KeyframePriorityBand as KeyframePriorityBand
from .active_capture_enums import KeyframeRole as KeyframeRole
from .active_capture_enums import KeyframeTriggerCandidateStatus as KeyframeTriggerCandidateStatus
from .active_capture_enums import KeyframeTriggerKind as KeyframeTriggerKind
from .active_capture_enums import ModifierKey as ModifierKey
from .active_capture_enums import NativeCaptureTimingAuthority as NativeCaptureTimingAuthority
from .active_capture_enums import NativeTimingClock as NativeTimingClock
from .active_capture_enums import PointerButton as PointerButton
from .active_capture_enums import ProducerDecisionReason as ProducerDecisionReason
from .active_capture_enums import ProducerDecisionStatus as ProducerDecisionStatus
from .active_capture_enums import ProducerInputEventKind as ProducerInputEventKind
from .active_capture_enums import ProviderReadinessState as ProviderReadinessState
from .active_capture_enums import RecordingAvailableField as RecordingAvailableField
from .active_capture_enums import RecordingControlKind as RecordingControlKind
from .active_capture_enums import RecordingControlSource as RecordingControlSource
from .active_capture_enums import RecordingExportFallbackMode as RecordingExportFallbackMode
from .active_capture_enums import RecordingHiddenMaterial as RecordingHiddenMaterial
from .active_capture_enums import RecordingScopeKind as RecordingScopeKind
from .active_capture_enums import RecordingSegmentCloseReason as RecordingSegmentCloseReason
from .active_capture_enums import RecordingSegmentState as RecordingSegmentState
from .active_capture_enums import RecordingStoryboardItemKind as RecordingStoryboardItemKind
from .active_capture_enums import RecordingTimelineStepFoldReason as RecordingTimelineStepFoldReason
from .active_capture_enums import RecordingTimelineStepVisibilityClass as RecordingTimelineStepVisibilityClass
from .active_capture_enums import RecordingVideoContentType as RecordingVideoContentType
from .active_capture_enums import RecordingVideoMetadataKey as RecordingVideoMetadataKey
from .active_capture_enums import ScrollPhase as ScrollPhase
from .active_capture_enums import SensitiveActionMetadataKey as SensitiveActionMetadataKey
from .active_capture_enums import SettleDecisionStatus as SettleDecisionStatus
from .active_capture_enums import SettleSampleStatus as SettleSampleStatus
from .active_capture_enums import SettleSignalKind as SettleSignalKind
from .active_capture_enums import SettleStopReason as SettleStopReason
from .active_capture_enums import TextDiffMethod as TextDiffMethod
from .active_capture_enums import TimelineAlignmentConfidence as TimelineAlignmentConfidence
from .active_capture_enums import TimelineAlignmentStatus as TimelineAlignmentStatus
from .active_capture_enums import VideoArtifactFailureReason as VideoArtifactFailureReason
from .active_capture_enums import VideoArtifactState as VideoArtifactState
from .active_capture_enums import VisualProbeMode as VisualProbeMode
from .error_enums import ErrorCode as ErrorCode
from .provider_enums import ProviderCapability as ProviderCapability
from .provider_enums import ProviderCaptureOutcomeStatus as ProviderCaptureOutcomeStatus
from .provider_enums import ProviderCommandStatus as ProviderCommandStatus
from .provider_enums import ProviderCommandType as ProviderCommandType
from .provider_enums import ProviderDecisionStatus as ProviderDecisionStatus
from .provider_enums import ProviderDiagnosticStatus as ProviderDiagnosticStatus
from .provider_enums import ProviderInstallKind as ProviderInstallKind
from .provider_enums import ProviderKind as ProviderKind
from .provider_enums import ProviderMode as ProviderMode
from .provider_enums import ProviderPermissionKind as ProviderPermissionKind
from .provider_enums import ProviderPermissionState as ProviderPermissionState
from .provider_enums import ProviderRouteRole as ProviderRouteRole
from .provider_enums import ProviderRuntimeState as ProviderRuntimeState
from .provider_enums import SurfaceKind as SurfaceKind
from .share_enums import ContextShareStatus as ContextShareStatus
from .share_enums import IdentityProvider as IdentityProvider
from .share_enums import ShareAuditAction as ShareAuditAction
from .share_enums import ShareImportSourceKind as ShareImportSourceKind
from .share_enums import ShareImportStatus as ShareImportStatus
from .share_enums import SharePublishStatus as SharePublishStatus
from .share_enums import ShareScope as ShareScope
from .share_enums import ShareTargetKind as ShareTargetKind
from .share_enums import ShareVisibility as ShareVisibility
from .visual_ocr_enums import EventChangeType as EventChangeType
from .visual_ocr_enums import VisualOCRAPIStyle as VisualOCRAPIStyle
from .visual_ocr_enums import VisualOCRElementRole as VisualOCRElementRole
from .visual_ocr_enums import VisualOCRProviderKind as VisualOCRProviderKind
from .visual_ocr_enums import VisualOCRStatus as VisualOCRStatus


class TriggerType(StrEnum):
    """How a capture attempt or future observation was started."""

    MANUAL_OS_REGION_HOTKEY = "manual_os_region_hotkey"
    MANUAL_OS_FRONTMOST_WINDOW_HOTKEY = "manual_os_frontmost_window_hotkey"
    MANUAL_FULLSCREEN_HOTKEY = "manual_fullscreen_hotkey"
    MANUAL_BROWSER_BUTTON = "manual_browser_button"
    MANUAL_BROWSER_VIEWPORT = "manual_browser_viewport"
    MANUAL_SHARE_IMPORT = "manual_share_import"
    SOURCE_WEBHOOK = "source_webhook"
    EPHEMERAL_BUFFER_COMMIT = "ephemeral_buffer_commit"


class CaptureStrategy(StrEnum):
    """Capture approach selected by the trigger layer."""

    OS_REGION = "os_region"
    OS_WINDOW = "os_window"
    OS_FULLSCREEN = "os_fullscreen"
    BROWSER_VIEWPORT = "browser_viewport"
    BROWSER_FULL_PAGE = "browser_full_page"
    SOURCE_NATIVE = "source_native"


class ShortcutCommandKind(StrEnum):
    """User-configurable local capture command shortcuts."""

    CURRENT_APPSHOT = "current_appshot"
    REGION_SCREENSHOT = "region_screenshot"
    REGION_RECORDING = "region_recording"


class ShortcutRegistrationState(StrEnum):
    """Native shortcut registration status reported by the macOS shell."""

    REGISTERED = "registered"
    DISABLED = "disabled"
    CONFLICT = "conflict"
    FAILED = "failed"


class ShortcutModifier(StrEnum):
    """Supported native shortcut modifiers."""

    CONTROL = "control"
    OPTION = "option"
    SHIFT = "shift"
    COMMAND = "command"


class SourceType(StrEnum):
    """Kind of source that an event or artifact is bound to."""

    WEB = "web"
    DESKTOP_WINDOW = "desktop_window"
    DOCUMENT = "document"
    IMPORTED_CONTEXT = "imported_context"
    SOURCE_RECORD = "source_record"
    MOCK = "mock"
    UNKNOWN = "unknown"


class EventType(StrEnum):
    """Product event taxonomy values persisted in the event ledger."""

    WEBPAGE_SELECTION_CAPTURED = "webpage.selection.captured"
    SCREEN_REGION_CAPTURED = "screen.region.captured"
    SCREEN_WINDOW_CAPTURED = "screen.window.captured"
    CHAT_THREAD_CAPTURED = "chat.thread.captured"
    DOCUMENT_SECTION_CAPTURED = "document.section.captured"
    TERMINAL_ERROR_CAPTURED = "terminal.error.captured"
    DASHBOARD_METRIC_OBSERVED = "dashboard.metric.observed"
    IMPORTED_CONTEXT = "context.imported"


class CaptureAttemptStatus(StrEnum):
    """Lifecycle result for a capture attempt before/after event creation."""

    ACCEPTED = "accepted"
    UNSUPPORTED = "unsupported"
    NEEDS_CONFIRMATION = "needs_confirmation"
    FAILED = "failed"


class CapturePostCommitTaskKind(StrEnum):
    """Durable post-commit work scheduled after a capture event is saved."""

    ACTIVE_CAPTURE_KEYFRAME = "active_capture_keyframe"


class CapturePostCommitTaskStatus(StrEnum):
    """Lifecycle for one durable capture post-commit outbox task."""

    PENDING = "pending"
    RUNNING = "running"
    RETRYABLE = "retryable"
    COMPLETED = "completed"
    FAILED = "failed"


class UnsupportedReason(StrEnum):
    """Stable reasons for capture attempts that do not create events."""

    NON_WEB_SOURCE = "non_web_source"
    NO_PROVIDER = "no_provider"
    STALE_PROVIDER_CONTEXT = "stale_provider_context"
    PROVIDER_COMMAND_FAILED = "provider_command_failed"
    AMBIGUOUS_SURFACE = "ambiguous_surface"
    LOW_CONFIDENCE = "low_confidence"
    VALIDATION_FAILED = "validation_failed"


class EvidenceKind(StrEnum):
    """Evidence bundle families returned by command-driven providers."""

    WEB = "web"
    A11Y = "a11y"
    SYSTEM = "system"
    SYSTEM_APPSHOT = "system_appshot"
    SCREENSHOT = "screenshot"
    PAGE_METADATA = "page_metadata"
    SELECTION_MAP = "selection_map"
    FULL_DOM = "full_dom"
    PAGE_TEXT = "page_text"
    VISIBLE_TEXT = "visible_text"
    SELECTED_TEXT = "selected_text"
    SELECTION_TEXT = "selection_text"
    VISUAL_OCR_TEXT = "visual_ocr_text"
    CLEAN_PAGE_TEXT = "clean_page_text"
    CANONICAL_TEXT = "canonical_text"
    KEYFRAME_CONTEXT_TEXT = "keyframe_context_text"
    PROVIDER_DIAGNOSTICS = "provider_diagnostics"


class EvidencePhase(StrEnum):
    """Whether evidence is directly captured or derived later."""

    CAPTURED = "captured"
    ENRICHED = "enriched"
    INDEXED = "indexed"


class EvidenceSensitivity(StrEnum):
    """Sensitivity class used before access scopes are granted."""

    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    HIGH_SENSITIVITY = "high_sensitivity"


class EvidenceTrustState(StrEnum):
    """Policy/DLP trust state for evidence and derived projections."""

    UNTRUSTED = "untrusted"
    PROVIDER_REDACTED = "provider_redacted"
    DLP_PASSED = "dlp_passed"
    QUARANTINED = "quarantined"
    BLOCKED = "blocked"


class DomCaptureMode(StrEnum):
    """How much DOM a Web command asks a browser provider to collect."""

    FULL = "full"
    SANITIZED_SELECTION = "sanitized_selection"


class A11yPermissionState(StrEnum):
    """macOS Accessibility permission state reported by the native provider."""

    GRANTED = "granted"
    DENIED = "denied"
    UNKNOWN = "unknown"


class SelectionTextSourceMethod(StrEnum):
    """Extractor families that may produce OS selection text projections."""

    A11Y_BLOCKS = "a11y_blocks"
    A11Y_RANGE = "a11y_range"
    OCR = "ocr"
    WEB_DOM_PROJECTION = "web_dom_projection"


class JobType(StrEnum):
    """Durable enrichment/index job types."""

    DLP_CLASSIFICATION = "dlp_classification"
    CANONICAL_TEXT_V0 = "canonical_text_v0"
    FTS_REFRESH = "fts_refresh"
    EVIDENCE_LAYER_EXTRACTION = "evidence_layer_extraction"
    VISUAL_OCR_V0 = "visual_ocr_v0"


class JobStatus(StrEnum):
    """Durable job lifecycle status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class BrowserKind(StrEnum):
    """Supported browser families for Web provider v1."""

    CHROME = "chrome"
    EDGE = "edge"
    ARC = "arc"
    SAFARI = "safari"
    FIREFOX = "firefox"
    UNKNOWN = "unknown"


class RetrievalMode(StrEnum):
    """Retrieval mode requested by CLI, API, or bundle builders."""

    KEYWORD = "keyword"
    HYBRID = "hybrid"


class SearchSort(StrEnum):
    """Sort order requested by agent-facing search/list surfaces."""

    CAPTURED_AT = "captured_at"
    SCORE = "score"


class SearchFieldKind(StrEnum):
    """Searchable field families exposed by index and replay contracts."""

    SAFE_METADATA = "safe_metadata"
    USER_NOTE = "user_note"
    SELECTION_TEXT = "selection_text"
    VISUAL_OCR_TEXT = "visual_ocr_text"
    CANONICAL_TEXT = "canonical_text"
    CLEAN_PAGE_TEXT = "clean_page_text"
    KEYFRAME_CONTEXT_TEXT = "keyframe_context_text"
    ACTIVE_CAPTURE_SUMMARY = "active_capture_summary"
    RECORDING_TIMELINE = "recording_timeline"
    HUMAN_DEMO_SUMMARY = "human_demo_summary"


class SearchMatchReason(StrEnum):
    """Stable reason for why a search result was selected."""

    METADATA = "metadata"
    RECENT = "recent"
    USER_NOTE = "user_note"
    SELECTION_TEXT = "selection_text"
    VISUAL_OCR_TEXT = "visual_ocr_text"
    CANONICAL_TEXT = "canonical_text"
    CLEAN_PAGE_TEXT = "clean_page_text"
    INTENT = "intent"
    TITLE = "title"
    ACTIVE_CAPTURE_SUMMARY = "active_capture_summary"
    RECORDING_TIMELINE = "recording_timeline"
    HUMAN_DEMO_SUMMARY = "human_demo_summary"


class EventInspectSection(StrEnum):
    """Explicit sections that can be requested from event inspection."""

    SYSTEM_APPSHOT = "system_appshot"
    SELECTION_TEXT = "selection_text"
    VISUAL_OCR_TEXT = "visual_ocr_text"
    CANONICAL = "canonical"
    CLEAN_PAGE_TEXT = "clean_page_text"
    SCREENSHOT_REF = "screenshot_ref"
    EVIDENCE_REFS = "evidence_refs"
    ARTIFACT_METADATA = "artifact_metadata"
    KEYFRAMES = "keyframes"
    ACTIVE_CAPTURE_SUMMARY = "active_capture_summary"
    RECORDING_TIMELINE = "recording_timeline"
    VIDEO_REF = "video_ref"
    HUMAN_DEMO_SUMMARY = "human_demo_summary"


class ActiveCaptureCitationKind(StrEnum):
    """Typed citation targets inside an active-capture inspect view."""

    SESSION = "session"
    KEYFRAME = "keyframe"
    TEXT_RANGE = "text_range"
    BBOX = "bbox"
    ACTION_STEP = "action_step"
    VIDEO_TIME = "video_time"


class SkillReadinessState(StrEnum):
    """Whether a recorded action graph is ready for later skill distillation."""

    READY = "ready"
    NEEDS_REVIEW = "needs_review"
    BLOCKED = "blocked"


class IndexPolicyDecisionStatus(StrEnum):
    """Policy-before-index outcome for one text source."""

    ALLOWED = "allowed"
    REDACTED = "redacted"
    SUPPRESSED = "suppressed"


class IndexPolicyAuditWriteState(StrEnum):
    """Durable write state for a policy-before-index audit row."""

    PENDING = "pending"
    INDEXED = "indexed"
    FAILED = "failed"


class IndexSuppressionReason(StrEnum):
    """Typed reason why a candidate text source was not indexed."""

    NONE = "none"
    EMPTY_TEXT = "empty_text"
    BLOCKED_REDACTION_STATE = "blocked_redaction_state"
    SENSITIVE_SURFACE = "sensitive_surface"
    RAW_MATERIAL = "raw_material"
    UNSUPPORTED_FIELD = "unsupported_field"


class SensitiveSurfaceType(StrEnum):
    """Coarse sensitive surface classes used before index writes."""

    NONE = "none"
    PASSWORD_FIELD = "password_field"
    SECRET_MANAGER = "secret_manager"
    PRIVATE_BROWSER = "private_browser"
    SYSTEM_SECURITY = "system_security"
    USER_CONFIGURED = "user_configured"
    UNKNOWN_SENSITIVE = "unknown_sensitive"


class AgentVisibleField(StrEnum):
    """Safe agent-facing fields allowed after policy projection."""

    SAFE_METADATA = "safe_metadata"
    USER_NOTE = "user_note"
    SELECTION_TEXT = "selection_text"
    VISUAL_OCR_TEXT = "visual_ocr_text"
    CANONICAL_TEXT = "canonical_text"
    CLEAN_PAGE_TEXT = "clean_page_text"
    ACTIVE_CAPTURE_SUMMARY = "active_capture_summary"
    RECORDING_TIMELINE = "recording_timeline"
    HUMAN_DEMO_SUMMARY = "human_demo_summary"
    KEYFRAME_REF = "keyframe_ref"
    VIDEO_REF = "video_ref"


class AgentRunStatus(StrEnum):
    """Lifecycle state for one agent answer/retrieval run."""

    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class AgentRunOrigin(StrEnum):
    """How an agent run was created."""

    CLI_EXPLICIT = "cli_explicit"
    CLI_IMPLICIT = "cli_implicit"
    DAEMON_IMPLICIT = "daemon_implicit"
    API_EXPLICIT = "api_explicit"


class RetrievalCallKind(StrEnum):
    """Agent-facing read operations that can deliver context."""

    SEARCH = "search"
    EVENT_INSPECT = "event_inspect"
    BUNDLE_CREATE = "bundle_create"
    BUNDLE_READ = "bundle_read"
    BUNDLE_EXPORT = "bundle_export"
    ARTIFACT_PREVIEW = "artifact_preview"
    ARTIFACT_RAW = "artifact_raw"
    CITATION_RESOLVE = "citation_resolve"
    SHARE_RESOLVE = "share_resolve"
    SHARE_IMPORT = "share_import"
    USAGE_RECORD = "usage_record"


class SnapshotKind(StrEnum):
    """Safe replay snapshot families stored for an agent run."""

    SEARCH_RESULT = "search_result"
    EVENT_INSPECT = "event_inspect"
    CONTEXT_BUNDLE = "context_bundle"
    ARTIFACT_REF = "artifact_ref"
    ARTIFACT_TEXT = "artifact_text"
    CITATION = "citation"
    SHARE = "share"
    USAGE = "usage"


class CitationUseState(StrEnum):
    """How a citation is being used by an agent workflow."""

    DELIVERED = "delivered"
    INCLUDED_IN_BUNDLE = "included_in_bundle"
    USED_IN_ANSWER = "used_in_answer"
    REJECTED = "rejected"


class RiskAdvisoryCategory(StrEnum):
    """High-risk agent suggestion categories recorded separately from usage."""

    EXTERNAL_COMMUNICATION = "external_communication"
    DATA_CHANGE = "data_change"
    FINANCIAL = "financial"
    SECURITY = "security"
    LEGAL = "legal"
    UNKNOWN = "unknown"


class RiskSeverity(StrEnum):
    """Severity level for high-risk advisories."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class RiskActionState(StrEnum):
    """Whether a high-risk item was only suggested or actually executed."""

    SUGGESTED_ONLY = "suggested_only"
    USER_APPROVED = "user_approved"
    EXECUTED = "executed"
    BLOCKED = "blocked"


class DisclosureView(StrEnum):
    """Consumer-facing views built from stored evidence at read time."""

    SUMMARY_CARD = "summary_card"
    EVENT_INSPECT = "event_inspect"
    SHARE_SUMMARY = "share_summary"
    SHARE_IMPORT = "share_import"
    BUNDLE_ITEM = "bundle_item"
    ARTIFACT_PREVIEW = "artifact_preview"
    RAW_ARTIFACT = "raw_artifact"
    DEBUG_MANIFEST = "debug_manifest"


class DisclosureClass(StrEnum):
    """Stable disclosure classes used by SDK profiles and route policies."""

    SAFE_METADATA = "safe_metadata"
    SELECTION_BOUND_TEXT = "selection_bound_text"
    VISUAL_OCR_TEXT = "visual_ocr_text"
    REDACTED_CANONICAL = "redacted_canonical"
    CLEAN_PAGE_TEXT = "clean_page_text"
    RAW_VISUAL = "raw_visual"
    RAW_SOURCE = "raw_source"
    RAW_UI_TREE = "raw_ui_tree"
    DEBUG_PROVENANCE = "debug_provenance"


class DisclosureDecisionStatus(StrEnum):
    """Read-time disclosure decision status."""

    ALLOWED = "allowed"
    DENIED = "denied"
    REDACTED = "redacted"
    TRUNCATED = "truncated"


class DisclosureField(StrEnum):
    """Stable field names recorded in disclosure decisions."""

    EVENT_ID = "event_id"
    CAPTURED_AT = "captured_at"
    SOURCE = "source"
    SELECTION_BBOX = "selection_bbox"
    SYSTEM_APPSHOT = "system_appshot"
    SELECTION_TEXT = "selection_text"
    VISUAL_OCR_TEXT = "visual_ocr_text"
    CANONICAL_TEXT = "canonical_text"
    CANONICAL_TEXT_TRUNCATED = "canonical_text_truncated"
    CLEAN_PAGE_TEXT = "clean_page_text"
    CLEAN_PAGE_TEXT_TRUNCATED = "clean_page_text_truncated"
    RAW_ARTIFACT_REFS = "raw_artifact_refs"
    RAW_ARTIFACTS = "raw_artifacts"
    READABLE_EVIDENCE = "readable_evidence"
    KEYFRAMES = "keyframes"
    ACTIVE_CAPTURE = "active_capture"
    HIDDEN_ARTIFACTS = "hidden_artifacts"
    TEXT = "text"
    CONTENT_BASE64 = "content_base64"
    CONTENT_TYPE = "content_type"
    SHA256 = "sha256"
    DISCLOSURE_DECISION = "disclosure_decision"


class IndexExposure(StrEnum):
    """How a derived evidence record can be used by retrieval surfaces."""

    NONE = "none"
    INDEX_ONLY = "index_only"
    SUMMARY_PREVIEW = "summary_preview"
    BUNDLE_ALLOWED = "bundle_allowed"
    INSPECT_ALLOWED = "inspect_allowed"


class ArtifactType(StrEnum):
    """Evidence artifact categories supported by the P0 contract."""

    SYSTEM_APPSHOT = "system_appshot"
    SCREENSHOT = "screenshot"
    OS_REGION_SCREENSHOT = "os_region_screenshot"
    OS_REGION_CROP = "os_region_crop"
    THUMBNAIL = "thumbnail"
    BROWSER_DOM_SNAPSHOT = "browser_dom_snapshot"
    BROWSER_FULL_DOM = "browser_full_dom"
    PAGE_METADATA = "page_metadata"
    SELECTION_MAP = "selection_map"
    CANONICAL_TEXT = "canonical_text"
    CLEAN_PAGE_TEXT = "clean_page_text"
    MOCK_SOURCE = "mock_source"
    BROWSER_READABILITY_MARKDOWN = "browser_readability_markdown"
    BROWSER_VISIBLE_TEXT = "browser_visible_text"
    BROWSER_SELECTED_TEXT = "browser_selected_text"
    DOM_SELECTION_TEXT = "dom_selection_text"
    A11Y_SELECTION_TEXT = "a11y_selection_text"
    VISUAL_OCR_TEXT = "visual_ocr_text"
    VISUAL_OCR_RESULT = "visual_ocr_result"
    A11Y_TREE = "a11y_tree"
    A11Y_TEXT = "a11y_text"
    A11Y_COVERAGE = "a11y_coverage"
    KEYFRAME_CONTEXT_TEXT = "keyframe_context_text"
    RECORDING_VIDEO = "recording_video"


class ArtifactRole(StrEnum):
    """Semantic role of an artifact inside an event."""

    SYSTEM_APPSHOT = "system_appshot"
    VISUAL_EVIDENCE = "visual_evidence"
    SOURCE_TEXT = "source_text"
    SELECTION_TEXT = "selection_text"
    VISUAL_OCR_TEXT = "visual_ocr_text"
    SELECTION_MAP = "selection_map"
    CANONICAL_TEXT = "canonical_text"
    CLEAN_PAGE_TEXT = "clean_page_text"
    PAGE_METADATA = "page_metadata"
    THUMBNAIL = "thumbnail"
    UI_STRUCTURE = "ui_structure"
    FULL_DOM = "full_dom"
    PROVIDER_DIAGNOSTICS = "provider_diagnostics"
    DERIVED_SUMMARY = "derived_summary"
    KEYFRAME_IMAGE = "keyframe_image"
    KEYFRAME_CONTEXT_TEXT = "keyframe_context_text"
    RECORDING_VIDEO = "recording_video"


class ArtifactIngestState(StrEnum):
    """Artifact ingest state before indexing or agent access."""

    STAGED = "staged"
    QUARANTINED = "quarantined"
    DLP_PASSED = "dlp_passed"
    INDEXED = "indexed"
    BLOCKED = "blocked"


class EventStatus(StrEnum):
    """Lifecycle status for a context event."""

    CAPTURED = "captured"
    PENDING_ENRICHMENT = "pending_enrichment"
    INDEXED = "indexed"
    AGENT_READY = "agent_ready"
    RESTRICTED = "restricted"
    DELETED = "deleted"


class AccessScope(StrEnum):
    """Fine-grained access scope checked by policy before actions."""

    READ_METADATA = "read_metadata"
    READ_TEXT = "read_text"
    READ_THUMBNAIL = "read_thumbnail"
    READ_IMAGE = "read_image"
    READ_RAW_ARTIFACT = "read_raw_artifact"
    CREATE_EVENT = "create_event"
    REGISTER_PROVIDER_CONTEXT = "register_provider_context"
    MANAGE_LOCAL_SETTINGS = "manage_local_settings"
    RUN_ENRICHMENT = "run_enrichment"
    READ_JOB_STATUS = "read_job_status"
    CREATE_BUNDLE = "create_bundle"
    RECORD_USAGE = "record_usage"
    DELETE_EVENT = "delete_event"
    CHECK_POLICY = "check_policy"
    CREATE_SHARE = "create_share"
    READ_SHARE = "read_share"
    REVOKE_SHARE = "revoke_share"
    IMPORT_SHARE = "import_share"


class PolicyEffect(StrEnum):
    """Authorization outcome produced by the policy evaluator."""

    ALLOW = "allow"
    DENY = "deny"
    REDACT = "redact"
    QUARANTINE = "quarantine"


class CoordinateSpace(StrEnum):
    """Coordinate system used by bbox references."""

    MACOS_GLOBAL = "macos_global"
    SCREEN_PX = "screen_px"
    WINDOW_PX = "window_px"
    VIEWPORT_CSS_PX = "viewport_css_px"
    PAGE_CSS_PX = "page_css_px"
    CSS_PX = "css_px"
    ARTIFACT_PX = "artifact_px"


class RedactionState(StrEnum):
    """Whether content was redacted before indexing or returning."""

    NONE = "none"
    REDACTED = "redacted"
    BLOCKED = "blocked"
    QUARANTINED = "quarantined"


class AuditAction(StrEnum):
    """Auditable action names emitted by daemon and CLI flows."""

    TOKEN_ISSUED = "token_issued"
    POLICY_CHECKED = "policy_checked"
    CAPTURE_SAVED = "capture_saved"
    CAPTURE_ATTEMPTED = "capture_attempted"
    SOURCE_RESOLVED = "source_resolved"
    ARTIFACT_REGISTERED = "artifact_registered"
    EVENT_CREATED = "event_created"
    EVENT_LISTED = "event_listed"
    EVENT_READ = "event_read"
    EVENT_DELETED = "event_deleted"
    SEARCH_PERFORMED = "search_performed"
    DISCLOSURE_EVALUATED = "disclosure_evaluated"
    BUNDLE_CREATED = "bundle_created"
    BUNDLE_READ = "bundle_read"
    ARTIFACT_READ = "artifact_read"
    USAGE_RECORDED = "usage_recorded"
    SHARE_CREATED = "share_created"
    SHARE_READ = "share_read"
    SHARE_REVOKED = "share_revoked"
    SHARE_IMPORTED = "share_imported"
    SHARE_SYNCED = "share_synced"
