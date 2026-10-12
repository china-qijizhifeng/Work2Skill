"""Active-capture enum contracts shared across backend producers."""

from __future__ import annotations

from enum import StrEnum


class ActiveCaptureMode(StrEnum):
    """Backend active capture modes."""

    SCREENSHOT_KEYFRAMES = "screenshot_keyframes"
    RECORDING_SESSION = "recording_session"


class ActiveCaptureSessionSource(StrEnum):
    """Producer or session origin for active capture metadata."""

    ORDINARY_SCREENSHOT_ANCHOR = "ordinary_screenshot_anchor"
    HEADLESS_BACKEND = "headless_backend"


class ActiveCaptureStatus(StrEnum):
    """Lifecycle states for an active capture session."""

    CREATED = "created"
    SELECTING_SCOPE = "selecting_scope"
    RECORDING = "recording"
    PAUSED = "paused"
    SCOPE_LOST = "scope_lost"
    STOPPING = "stopping"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ActiveCaptureWarningCode(StrEnum):
    """Typed non-fatal active capture warnings."""

    HOOK_FAILED = "hook_failed"
    KEYFRAME_CAPTURE_FAILED = "keyframe_capture_failed"
    SCOPE_LOST = "scope_lost"
    VIDEO_UNAVAILABLE = "video_unavailable"
    VIDEO_VALIDATION_FAILED = "video_validation_failed"
    TIMELINE_ALIGNMENT_ESTIMATED = "timeline_alignment_estimated"


class RecordingScopeKind(StrEnum):
    """Kinds of scopes an active capture session can bind to."""

    WINDOW = "window"
    REGION = "region"
    CURRENT_APP = "current_app"


class RecordingExportFallbackMode(StrEnum):
    """DOM target fallback sources used while exporting a recording."""

    NORMAL = "normal"
    EVENT_ONLY = "event_only"
    CLICK_ONLY = "click_only"


class KeyframeRole(StrEnum):
    """Semantic role of one keyframe inside a session."""

    ANCHOR = "anchor"
    START = "start"
    FINAL = "final"
    BEFORE_ACTION = "before_action"
    RESULT = "result"
    SETTLE = "settle"
    CHANGE = "change"
    USER_MARK = "user_mark"
    IDLE_ANCHOR = "idle_anchor"
    PROVIDER_COMPLETION = "provider_completion"
    PAUSE_BOUNDARY = "pause_boundary"
    RESUME_BOUNDARY = "resume_boundary"
    ERROR_STATE = "error_state"
    SCROLL_MILESTONE = "scroll_milestone"


class KeyframeTriggerKind(StrEnum):
    """Trigger that produced a keyframe candidate."""

    MANUAL_SCREENSHOT = "manual_screenshot"
    RECORDING_START = "recording_start"
    RECORDING_STOP = "recording_stop"
    USER_MARK = "user_mark"
    ACTION_BEFORE = "action_before"
    ACTION_RESULT_SETTLE = "action_result_settle"
    STABILITY_SETTLE = "stability_settle"
    PROVIDER_COMPLETION = "provider_completion"
    PROVIDER_COMPLETED = "provider_completed"
    OCR_COMPLETED = "ocr_completed"
    SESSION_COMPLETE = "session_complete"
    NAVIGATION_COMMITTED = "navigation_committed"
    MODAL_STATE_CHANGE = "modal_state_change"
    TITLE_URL_CHANGE = "title_url_change"
    SCROLL_STOP = "scroll_stop"
    SCROLL_MILESTONE = "scroll_milestone"
    CLICK_SETTLE = "click_settle"
    TARGET_RESOLUTION_PROBE = "target_resolution_probe"
    HOTKEY_SETTLE = "hotkey_settle"
    TYPING_SETTLE = "typing_settle"
    COMMAND_SUBMITTED = "command_submitted"
    FOCUS_CHANGE = "focus_change"
    ERROR_SURFACE_DETECTED = "error_surface_detected"
    PAUSE_BOUNDARY = "pause_boundary"
    RESUME_BOUNDARY = "resume_boundary"
    VISUAL_CHANGE = "visual_change"
    TEXT_CHANGE = "text_change"
    SURFACE_CHANGE = "surface_change"
    IDLE_FALLBACK = "idle_fallback"


class KeyframeKeepReason(StrEnum):
    """Policy reason for retaining a keyframe."""

    USER_ANCHOR = "user_anchor"
    REQUIRED_BOUNDARY = "required_boundary"
    BEFORE_ACTION_CONTEXT = "before_action_context"
    RESULT_OBSERVED = "result_observed"
    COMMAND_BOUNDARY = "command_boundary"
    NAVIGATION_BOUNDARY = "navigation_boundary"
    SCROLL_MILESTONE = "scroll_milestone"
    ERROR_OBSERVED = "error_observed"
    TARGET_DISAMBIGUATION = "target_disambiguation"
    PAUSE_RESUME_BOUNDARY = "pause_resume_boundary"
    ADAPTIVE_STABILITY = "adaptive_stability"
    USER_MARKED = "user_marked"
    PROVIDER_COMPLETION = "provider_completion"
    PROVIDER_EVIDENCE_ADDED = "provider_evidence_added"
    QUALITY_IMPROVED = "quality_improved"
    VISUAL_DELTA = "visual_delta"
    TEXT_DELTA = "text_delta"
    PRIMARY_SURFACE_CHANGED = "primary_surface_changed"
    IDLE_ANCHOR = "idle_anchor"
    POLICY_ACCEPTED = "policy_accepted"


class KeyframeDropReason(StrEnum):
    """Policy reason for dropping a keyframe candidate."""

    DUPLICATE = "duplicate"
    DUPLICATE_VISUAL = "duplicate_visual"
    LOW_DELTA = "low_delta"
    LOW_INFORMATION_GAIN = "low_information_gain"
    CONTROL_ONLY = "control_only"
    REPLACED_BY_HIGHER_VALUE = "replaced_by_higher_value"
    NO_VISIBLE_CHANGE = "no_visible_change"
    NO_TEXT_CHANGE = "no_text_change"
    ADAPTIVE_TIMEOUT = "adaptive_timeout"
    PRE_ACTION_UNAVAILABLE = "pre_action_unavailable"
    TARGET_SUPPRESSED = "target_suppressed"
    TOO_SOON = "too_soon"
    BUDGET_EXCEEDED = "budget_exceeded"
    SENSITIVE_SURFACE = "sensitive_surface"
    PERMISSION_DENIED = "permission_denied"
    SCOPE_LOST = "scope_lost"
    INVALID_EVIDENCE = "invalid_evidence"
    POLICY_DISABLED = "policy_disabled"


class KeyframeEvidenceRole(StrEnum):
    """Role of evidence linked to a keyframe."""

    SCREENSHOT = "screenshot"
    SYSTEM_APPSHOT = "system_appshot"
    A11Y = "a11y"
    OCR = "ocr"
    WEB = "web"
    SELECTION_TEXT = "selection_text"
    CANONICAL_TEXT = "canonical_text"
    CLEAN_TEXT = "clean_text"
    VIDEO = "video"
    TIMELINE = "timeline"
    SUMMARY = "summary"


class KeyframeBundleStatus(StrEnum):
    """High-level readiness of a keyframe bundle."""

    ANCHOR_ONLY = "anchor_only"
    READY = "ready"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class VideoArtifactState(StrEnum):
    """State of an optional recording video artifact."""

    NOT_RECORDED = "not_recorded"
    RECORDING = "recording"
    STAGED = "staged"
    AVAILABLE = "available"
    FAILED = "failed"
    DELETED = "deleted"


class RecordingControlKind(StrEnum):
    """User or system control applied to a recording session."""

    START_SEGMENT = "start_segment"
    END_SEGMENT = "end_segment"
    PAUSE = "pause"
    RESUME = "resume"
    USER_MARK = "user_mark"
    STOP = "stop"
    AUTO_STOP = "auto_stop"
    SCOPE_LOST = "scope_lost"


class RecordingControlSource(StrEnum):
    """Trusted source that requested a recording control."""

    API = "api"
    NATIVE_CLIENT = "native_client"
    POLICY = "policy"
    TEST = "test"


class RecordingSegmentState(StrEnum):
    """Lifecycle state for one contiguous recording segment."""

    RECORDING = "recording"
    PAUSED = "paused"
    FINALIZING = "finalizing"
    AVAILABLE = "available"
    FAILED = "failed"


class RecordingSegmentCloseReason(StrEnum):
    """Typed reason a recording segment ended."""

    PAUSED = "paused"
    RESUMED_NEW_SEGMENT = "resumed_new_segment"
    STOPPED = "stopped"
    MAX_DURATION = "max_duration"
    SCOPE_LOST = "scope_lost"
    VIDEO_FAILED = "video_failed"


class KeyframeTriggerCandidateStatus(StrEnum):
    """Status of an event-driven keyframe trigger candidate."""

    RECEIVED = "received"
    DEBOUNCED = "debounced"
    ACCEPTED = "accepted"
    DROPPED = "dropped"
    EXPIRED = "expired"
    CAPTURED = "captured"


class SettleSignalKind(StrEnum):
    """Low-sensitive signal family observed during adaptive settle polling."""

    VISUAL = "visual"
    TEXT = "text"
    PROVIDER_READINESS = "provider_readiness"
    SCOPE = "scope"
    DEGRADED = "degraded"


class SettleSampleStatus(StrEnum):
    """State of one safe adaptive-settle sample."""

    OBSERVED = "observed"
    CHANGED = "changed"
    STABLE = "stable"
    PENDING = "pending"
    DEGRADED = "degraded"
    SUPPRESSED = "suppressed"
    FAILED = "failed"


class SettleDecisionStatus(StrEnum):
    """Decision produced after evaluating adaptive-settle samples."""

    OBSERVING = "observing"
    READY_TO_CAPTURE = "ready_to_capture"
    TIMEOUT_CAPTURE = "timeout_capture"
    SUPPRESSED = "suppressed"
    FAILED = "failed"


class SettleStopReason(StrEnum):
    """Why an adaptive settle window stopped observing."""

    NOT_DUE = "not_due"
    STABLE_AFTER_CHANGE = "stable_after_change"
    PROVIDER_READY = "provider_ready"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    TIMEOUT = "timeout"
    SENSITIVE_SURFACE = "sensitive_surface"
    SCOPE_LOST = "scope_lost"
    BUDGET_EXCEEDED = "budget_exceeded"
    SAMPLE_FAILED = "sample_failed"


class ProviderReadinessState(StrEnum):
    """Coarse provider readiness state safe for audit storage."""

    UNKNOWN = "unknown"
    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    SUPPRESSED = "suppressed"


class VisualProbeMode(StrEnum):
    """Adaptive settle probe strategy without exposing raw sample material."""

    TEXT_PROVIDER_ONLY = "text_provider_only"
    VISUAL_PROBE_ONLY = "visual_probe_only"
    HYBRID = "hybrid"


class TextDiffMethod(StrEnum):
    """Safe text-diff method used during settle polling."""

    FINGERPRINT = "fingerprint"
    LENGTH_DELTA = "length_delta"
    SOURCE_COUNT = "source_count"


class KeyframePriorityBand(StrEnum):
    """Priority bucket used before applying keyframe budget decisions."""

    REQUIRED = "required"
    HIGH = "high"
    NORMAL = "normal"
    IDLE = "idle"


class HumanDemonstrationTraceStatus(StrEnum):
    """Readiness state for a human demonstration trace."""

    ACTIVE = "active"
    FINALIZING = "finalizing"
    READY = "ready"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"


class HumanActionKind(StrEnum):
    """Low-sensitive human action kinds stored during active capture."""

    CLICK = "click"
    DRAG = "drag"
    SCROLL = "scroll"
    HOTKEY = "hotkey"
    KEY_DOWN = "key_down"
    KEY_UP = "key_up"
    TYPING_PAUSE = "typing_pause"
    WINDOW_SWITCH = "window_switch"
    TAB_SWITCH = "tab_switch"
    USER_MARK = "user_mark"


class HumanActionTargetKind(StrEnum):
    """Target reference kind for a human action."""

    DOM_SELECTOR = "dom_selector"
    A11Y_ELEMENT = "a11y_element"
    OCR_BOX = "ocr_box"
    APPSHOT_COMPONENT = "appshot_component"
    KEYFRAME = "keyframe"
    WINDOW = "window"
    UNKNOWN = "unknown"


class HumanActionOutcomeStatus(StrEnum):
    """Observed result status after a human action."""

    UNKNOWN = "unknown"
    OBSERVED = "observed"
    NO_VISIBLE_CHANGE = "no_visible_change"
    FAILED = "failed"


class HumanActionEvidenceRole(StrEnum):
    """Evidence role linked to one human action event."""

    BEFORE_KEYFRAME = "before_keyframe"
    AFTER_KEYFRAME = "after_keyframe"
    TARGET_EVIDENCE = "target_evidence"
    RESULT_EVIDENCE = "result_evidence"


class HotkeySemantic(StrEnum):
    """Allowed hotkey semantic categories without storing raw typed text."""

    COPY = "copy"
    CUT = "cut"
    PASTE = "paste"
    SUBMIT = "submit"
    SEARCH = "search"
    SAVE = "save"
    CLOSE = "close"
    NEW_ITEM = "new_item"
    DELETE = "delete"
    REFRESH = "refresh"
    SELECT_ALL = "select_all"
    UNDO = "undo"
    REDO = "redo"
    NAVIGATE_BACK = "navigate_back"
    NAVIGATE_FORWARD = "navigate_forward"
    OPEN_COMMAND = "open_command"
    ESCAPE_CANCEL = "escape_cancel"
    UNKNOWN = "unknown"


class ProducerInputEventKind(StrEnum):
    """Trusted native input event kinds accepted by active capture."""

    POINTER_CLICK = "pointer_click"
    POINTER_DRAG = "pointer_drag"
    SCROLL = "scroll"
    KEY_DOWN = "key_down"
    KEY_UP = "key_up"
    HOTKEY = "hotkey"
    TYPING_PAUSE = "typing_pause"
    WINDOW_FOCUS = "window_focus"
    TAB_SWITCH = "tab_switch"


class PointerButton(StrEnum):
    """Pointer button observed by a trusted producer."""

    LEFT = "left"
    RIGHT = "right"
    MIDDLE = "middle"
    OTHER = "other"


class ScrollPhase(StrEnum):
    """Native scroll gesture lifecycle phase."""

    BEGAN = "began"
    CHANGED = "changed"
    ENDED = "ended"
    MOMENTUM = "momentum"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class KeyboardEventKind(StrEnum):
    """Low-level keyboard event shape before privacy policy is applied."""

    KEY_DOWN = "key_down"
    KEY_UP = "key_up"
    FLAGS_CHANGED = "flags_changed"
    HOTKEY = "hotkey"
    TYPING_PAUSE = "typing_pause"


class ModifierKey(StrEnum):
    """Normalized keyboard modifiers stored for shortcut replay."""

    COMMAND = "command"
    SHIFT = "shift"
    OPTION = "option"
    CONTROL = "control"
    FUNCTION = "function"
    CAPS_LOCK = "caps_lock"


class KeyboardInputClass(StrEnum):
    """Privacy-aware keyboard classification used before storage."""

    SHORTCUT = "shortcut"
    NAVIGATION_KEY = "navigation_key"
    EDITING_KEY = "editing_key"
    TEXT_INPUT = "text_input"
    COMPOSITION = "composition"
    SYSTEM_RESERVED = "system_reserved"
    UNKNOWN = "unknown"


class KeyCapturePolicy(StrEnum):
    """Storage policy for one keyboard observation."""

    KEY_CHORD_ALLOWED = "key_chord_allowed"
    FULL_CONTENT = "full_content"
    SEMANTIC_ONLY = "semantic_only"
    AGGREGATE_ONLY = "aggregate_only"
    BLOCKED = "blocked"


class ProducerDecisionStatus(StrEnum):
    """Final ingestion decision for a trusted producer event."""

    ACCEPTED = "accepted"
    DROPPED = "dropped"
    BLOCKED = "blocked"
    DEBOUNCED = "debounced"
    ACTION_ONLY = "action_only"
    TRIGGER_ONLY = "trigger_only"


class ProducerDecisionReason(StrEnum):
    """Typed reason for producer/backend decisions."""

    ACCEPTED = "accepted"
    CLICK_SETTLED = "click_settled"
    DRAG_SETTLED = "drag_settled"
    SCROLL_STOPPED = "scroll_stopped"
    HOTKEY_SETTLED = "hotkey_settled"
    TYPING_SETTLED = "typing_settled"
    COMMAND_SUBMITTED = "command_submitted"
    FOCUS_CHANGED = "focus_changed"
    SCOPE_LOST = "scope_lost"
    SENSITIVE_TARGET = "sensitive_target"
    ORDINARY_TEXT_AGGREGATED = "ordinary_text_aggregated"
    RAW_KEYSTROKES_REJECTED = "raw_keystrokes_rejected"
    RAW_KEYSTROKE_CAPTURED = "raw_keystroke_captured"
    LOW_DELTA = "low_delta"
    TOO_SOON = "too_soon"
    BUDGET_EXCEEDED = "budget_exceeded"
    PRODUCER_DROPPED = "producer_dropped"
    UNSUPPORTED_EVENT = "unsupported_event"


class ActiveCaptureMetricName(StrEnum):
    """Low-cardinality active-capture telemetry event names."""

    SESSION_TRANSITION = "session_transition"
    VIDEO_VALIDATION = "video_validation"
    TRIGGER_ACCEPTED = "trigger_accepted"
    TRIGGER_DROPPED = "trigger_dropped"
    PRODUCER_INGEST = "producer_ingest"
    INSPECT_TRUNCATED = "inspect_truncated"
    INDEX_SUPPRESSED = "index_suppressed"
    RAW_GATE_DENIED = "raw_gate_denied"


class ClickTargetResolutionStatus(StrEnum):
    """Lifecycle for semantic click target resolution."""

    PENDING = "pending"
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    LOW_CONFIDENCE = "low_confidence"
    SUPPRESSED = "suppressed"
    FAILED = "failed"


class ClickTargetSourceKind(StrEnum):
    """Evidence source family used to infer a click target."""

    A11Y_SNAPSHOT = "a11y_snapshot"
    WEB_DOM = "web_dom"
    OCR_BOX = "ocr_box"
    APPSHOT = "appshot"
    COORDINATE_FALLBACK = "coordinate_fallback"
    MERGED = "merged"


class ClickTargetSemanticKind(StrEnum):
    """User-facing semantic role inferred for a click target."""

    BUTTON = "button"
    LINK = "link"
    INPUT = "input"
    SEARCH_FIELD = "search_field"
    MENU_ITEM = "menu_item"
    NAV_ITEM = "nav_item"
    TAB = "tab"
    CHECKBOX = "checkbox"
    WINDOW = "window"
    UNKNOWN = "unknown"


class ClickTargetConfidenceBand(StrEnum):
    """Coarse confidence band for public target projections."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNAVAILABLE = "unavailable"


class ClickTargetSuppressionReason(StrEnum):
    """Typed reason a target label or resolution is hidden/degraded."""

    SENSITIVE_LABEL = "sensitive_label"
    HIDDEN_EVIDENCE = "hidden_evidence"
    RAW_LOCATOR_BLOCKED = "raw_locator_blocked"
    SCOPE_MISMATCH = "scope_mismatch"
    NO_CANDIDATE = "no_candidate"
    LOW_CONFIDENCE = "low_confidence"
    POLICY_DENIED = "policy_denied"


class RecordingStoryboardItemKind(StrEnum):
    """Safe storyboard item kinds exposed by active-capture projections."""

    KEYFRAME = "keyframe"
    ACTION = "action"
    CONTROL = "control"
    WARNING = "warning"


class RecordingAvailableField(StrEnum):
    """Typed public fields available for future recording UI projections."""

    ACTIVE_CAPTURE_SUMMARY = "active_capture_summary"
    RECORDING_TIMELINE = "recording_timeline"
    KEYFRAME_REFS = "keyframe_refs"
    VIDEO_REF = "video_ref"
    HUMAN_DEMO_SUMMARY = "human_demo_summary"


class RecordingHiddenMaterial(StrEnum):
    """Typed materials intentionally hidden behind explicit disclosure gates."""

    RAW_KEYFRAME_IMAGES = "raw_keyframe_images"
    RECORDING_VIDEO = "recording_video"
    RAW_DOM = "raw_dom"
    RAW_A11Y_TREE = "raw_a11y_tree"
    OCR_BOXES = "ocr_boxes"
    ACTION_RAW_METADATA = "action_raw_metadata"


class SensitiveActionMetadataKey(StrEnum):
    """Metadata keys that must not be accepted for human action traces."""

    RAW_TEXT = "raw_text"
    INPUT_TEXT = "input_text"
    TYPED_TEXT = "typed_text"
    KEYSTROKES = "keystrokes"
    RAW_KEYSTROKES = "raw_keystrokes"
    PASSWORD = "password"
    SECRET = "secret"


class RecordingVideoContentType(StrEnum):
    """Supported active-capture recording video MIME types."""

    MP4 = "video/mp4"


class RecordingVideoMetadataKey(StrEnum):
    """Reserved metadata keys owned by the recording video backend."""

    SESSION_ID = "session_id"
    SEGMENT_ID = "segment_id"
    SEGMENT_SEQUENCE_INDEX = "segment_sequence_index"
    DURATION_MS = "duration_ms"


class VideoArtifactFailureReason(StrEnum):
    """Typed reason an optional recording video is unavailable."""

    VIDEO_DISABLED = "video_disabled"
    ADAPTER_MISSING = "adapter_missing"
    PROMOTION_DISABLED = "promotion_disabled"
    VALIDATION_FAILED = "validation_failed"


class TimelineAlignmentConfidence(StrEnum):
    """Confidence of media-time alignment for a timeline entry."""

    EXACT = "exact"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


class TimelineAlignmentStatus(StrEnum):
    """Typed reason for a timeline media-time alignment outcome."""

    ALIGNED = "aligned"
    CLIENT_MEDIA_HINT = "client_media_hint"
    MISSING_CLOCK = "missing_clock"
    BEFORE_VIDEO_START = "before_video_start"
    OUTSIDE_VIDEO_DURATION = "outside_video_duration"


class RecordingTimelineStepVisibilityClass(StrEnum):
    """Default user-facing visibility for one recording timeline step."""

    VISIBLE = "visible"
    FOLDED = "folded"


class RecordingTimelineStepFoldReason(StrEnum):
    """Typed reason a recording timeline step is folded by default."""

    TYPING_TRACE_ONLY = "typing_trace_only"
    TARGET_PROBE = "target_probe"
    CONTROL_ONLY = "control_only"
    TIMEOUT_NO_CHANGE = "timeout_no_change"
    DUPLICATE = "duplicate"
    LOW_INFORMATION_GAIN = "low_information_gain"


class NativeCaptureTimingAuthority(StrEnum):
    """Trusted local producer that emitted a capture timing receipt."""

    MACOS_CAPTURE = "macos_capture"


class NativeTimingClock(StrEnum):
    """Monotonic clock families accepted from trusted native producers."""

    SYSTEM_UPTIME_MS = "system_uptime_ms"
