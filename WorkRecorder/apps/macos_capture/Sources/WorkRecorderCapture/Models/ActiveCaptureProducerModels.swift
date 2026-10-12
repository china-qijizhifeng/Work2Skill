import CoreGraphics
import Foundation

enum ActiveCaptureProducerEventKind: String, Codable {
    case pointerClick = "pointer_click"
    case pointerDrag = "pointer_drag"
    case scroll
    case keyDown = "key_down"
    case keyUp = "key_up"
    case hotkey
    case typingPause = "typing_pause"
    case windowFocus = "window_focus"
    case tabSwitch = "tab_switch"
}

enum ActiveCapturePointerButton: String, Codable {
    case left
    case right
    case middle
    case other
}

enum ActiveCaptureScrollPhase: String, Codable {
    case began
    case changed
    case ended
    case momentum
    case cancelled
    case unknown
}

enum ActiveCaptureKeyboardEventKind: String, Codable {
    case keyDown = "key_down"
    case keyUp = "key_up"
    case flagsChanged = "flags_changed"
    case hotkey
    case typingPause = "typing_pause"
}

enum ActiveCaptureModifierKey: String, Codable, Comparable {
    case command
    case shift
    case option
    case control
    case function
    case capsLock = "caps_lock"

    static func < (lhs: ActiveCaptureModifierKey, rhs: ActiveCaptureModifierKey) -> Bool {
        lhs.rawValue < rhs.rawValue
    }
}

enum ActiveCaptureKeyboardInputClass: String, Codable {
    case shortcut
    case navigationKey = "navigation_key"
    case editingKey = "editing_key"
    case textInput = "text_input"
    case composition
    case systemReserved = "system_reserved"
    case unknown
}

enum ActiveCaptureKeyCapturePolicy: String, Codable {
    case keyChordAllowed = "key_chord_allowed"
    case fullContent = "full_content"
    case semanticOnly = "semantic_only"
    case aggregateOnly = "aggregate_only"
    case blocked
}

enum ActiveCaptureHotkeySemantic: String, Codable {
    case copy
    case cut
    case paste
    case submit
    case search
    case save
    case close
    case newItem = "new_item"
    case delete
    case refresh
    case selectAll = "select_all"
    case undo
    case redo
    case navigateBack = "navigate_back"
    case navigateForward = "navigate_forward"
    case openCommand = "open_command"
    case escapeCancel = "escape_cancel"
    case unknown
}

enum ActiveCaptureKeyframeRole: String, Codable {
    case start
    case final
    case anchor
    case beforeAction = "before_action"
    case result
    case settle
    case change
    case userMark = "user_mark"
    case idleAnchor = "idle_anchor"
    case providerCompletion = "provider_completion"
    case pauseBoundary = "pause_boundary"
    case resumeBoundary = "resume_boundary"
    case errorState = "error_state"
    case scrollMilestone = "scroll_milestone"
}

enum ActiveCaptureKeyframeTriggerKind: String, Codable {
    case recordingStart = "recording_start"
    case recordingStop = "recording_stop"
    case sessionComplete = "session_complete"
    case manualScreenshot = "manual_screenshot"
    case actionBefore = "action_before"
    case actionResultSettle = "action_result_settle"
    case clickSettle = "click_settle"
    case scrollStop = "scroll_stop"
    case scrollMilestone = "scroll_milestone"
    case targetResolutionProbe = "target_resolution_probe"
    case hotkeySettle = "hotkey_settle"
    case typingSettle = "typing_settle"
    case commandSubmitted = "command_submitted"
    case navigationCommitted = "navigation_committed"
    case modalStateChange = "modal_state_change"
    case focusChange = "focus_change"
    case surfaceChange = "surface_change"
    case errorSurfaceDetected = "error_surface_detected"
    case pauseBoundary = "pause_boundary"
    case resumeBoundary = "resume_boundary"
    case userMark = "user_mark"
    case idleFallback = "idle_fallback"
    case providerCompleted = "provider_completed"
    case providerCompletion = "provider_completion"
    case ocrCompleted = "ocr_completed"
    case titleUrlChange = "title_url_change"
    case visualChange = "visual_change"
    case textChange = "text_change"
    case stabilitySettle = "stability_settle"
}

enum ActiveCaptureKeyframeKeepReason: String, Codable {
    case userAnchor = "user_anchor"
    case requiredBoundary = "required_boundary"
    case beforeActionContext = "before_action_context"
    case resultObserved = "result_observed"
    case commandBoundary = "command_boundary"
    case navigationBoundary = "navigation_boundary"
    case scrollMilestone = "scroll_milestone"
    case errorObserved = "error_observed"
    case targetDisambiguation = "target_disambiguation"
    case pauseResumeBoundary = "pause_resume_boundary"
    case adaptiveStability = "adaptive_stability"
    case userMarked = "user_marked"
    case providerCompletion = "provider_completion"
    case providerEvidenceAdded = "provider_evidence_added"
    case qualityImproved = "quality_improved"
    case visualDelta = "visual_delta"
    case textDelta = "text_delta"
    case primarySurfaceChanged = "primary_surface_changed"
    case idleAnchor = "idle_anchor"
    case policyAccepted = "policy_accepted"
}

struct ActiveCaptureBinding: Codable {
    let sessionId: String
    let role: ActiveCaptureKeyframeRole
    let triggerKind: ActiveCaptureKeyframeTriggerKind
    let keepReason: ActiveCaptureKeyframeKeepReason?
    let candidateId: String?
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case role
        case triggerKind = "trigger_kind"
        case keepReason = "keep_reason"
        case candidateId = "candidate_id"
        case metadata
    }
}

struct NativeCaptureTimingReceipt: Codable {
    let authority: String
    let capturedAtMonotonicMs: Int
    let sourceClock: String
    let recordedAtWallTime: Date?
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case authority
        case capturedAtMonotonicMs = "captured_at_monotonic_ms"
        case sourceClock = "source_clock"
        case recordedAtWallTime = "recorded_at_wall_time"
        case metadata
    }
}

struct ActiveCaptureCaptureInstruction: Codable {
    let candidateId: String
    let sessionId: String
    let role: ActiveCaptureKeyframeRole
    let triggerKind: ActiveCaptureKeyframeTriggerKind
    let binding: ActiveCaptureBinding
    let executeAfterMonotonicMs: Int?

    enum CodingKeys: String, CodingKey {
        case candidateId = "candidate_id"
        case sessionId = "session_id"
        case role
        case triggerKind = "trigger_kind"
        case binding
        case executeAfterMonotonicMs = "execute_after_monotonic_ms"
    }
}

enum ActiveCaptureSettleSampleStatus: String, Codable {
    case observed
    case changed
    case stable
    case pending
    case degraded
    case suppressed
    case failed
}

enum ActiveCaptureVisualProbeMode: String, Codable {
    case textProviderOnly = "text_provider_only"
    case visualProbeOnly = "visual_probe_only"
    case hybrid
}

struct ActiveCaptureVisualDiffSummary: Codable {
    let enabled: Bool
    let mode: ActiveCaptureVisualProbeMode
    let status: ActiveCaptureSettleSampleStatus
    let visualDelta: Double?
    let perceptualHashDistance: Double?
    let sampleFingerprint: String?
    let diagnostics: [String]

    init(
        enabled: Bool = true,
        mode: ActiveCaptureVisualProbeMode = .hybrid,
        status: ActiveCaptureSettleSampleStatus = .observed,
        visualDelta: Double? = nil,
        perceptualHashDistance: Double? = nil,
        sampleFingerprint: String? = nil,
        diagnostics: [String] = []
    ) {
        self.enabled = enabled
        self.mode = mode
        self.status = status
        self.visualDelta = visualDelta
        self.perceptualHashDistance = perceptualHashDistance
        self.sampleFingerprint = sampleFingerprint
        self.diagnostics = diagnostics
    }

    enum CodingKeys: String, CodingKey {
        case enabled
        case mode
        case status
        case visualDelta = "visual_delta"
        case perceptualHashDistance = "perceptual_hash_distance"
        case sampleFingerprint = "sample_fingerprint"
        case diagnostics
    }
}

struct ActiveCaptureSettleProbeSnapshot: Codable {
    let sampleId: String
    let sampledAtMonotonicMs: Int
    let visual: ActiveCaptureVisualDiffSummary?
    let diagnostics: [String]
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case sampleId = "sample_id"
        case sampledAtMonotonicMs = "sampled_at_monotonic_ms"
        case visual
        case diagnostics
        case metadata
    }
}

struct ActiveCaptureRecordingScope: Codable {
    let kind: ActiveCaptureRecordingScopeKind
    let displayId: String?
    let scaleFactor: Double?
    let windowId: String?
    let processId: Int?
    let bundleId: String?
    let appName: String?
    let title: String?
    let bounds: BoundingBox?
    let selectionRegion: BoundingBox?
    let scopeConfidence: Double
    let occlusionEstimate: Double?
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case kind
        case displayId = "display_id"
        case scaleFactor = "scale_factor"
        case windowId = "window_id"
        case processId = "process_id"
        case bundleId = "bundle_id"
        case appName = "app_name"
        case title
        case bounds
        case selectionRegion = "selection_region"
        case scopeConfidence = "scope_confidence"
        case occlusionEstimate = "occlusion_estimate"
        case metadata
    }
}

enum ActiveCaptureRecordingScopeKind: String, Codable {
    case region
    case window
    case currentApp = "current_app"
    case display
    case unknown
}

struct ActiveCaptureActionPoint: Codable {
    let x: Double
    let y: Double
    let coordinateSpace: String
    let displayId: String?
    let scaleFactor: Double?

    enum CodingKeys: String, CodingKey {
        case x
        case y
        case coordinateSpace = "coordinate_space"
        case displayId = "display_id"
        case scaleFactor = "scale_factor"
    }
}

struct ActiveCaptureActionCoordinates: Codable {
    let screenAbs: ActiveCaptureActionPoint?
    let screenshotRel: ActiveCaptureActionPoint?
    let scopeRel: ActiveCaptureActionPoint?
    let targetBounds: BoundingBox?

    enum CodingKeys: String, CodingKey {
        case screenAbs = "screen_abs"
        case screenshotRel = "screenshot_rel"
        case scopeRel = "scope_rel"
        case targetBounds = "target_bounds"
    }
}

struct ActiveCapturePointerPayload: Codable {
    let button: ActiveCapturePointerButton
    let clickCount: Int
    let coordinates: ActiveCaptureActionCoordinates

    enum CodingKeys: String, CodingKey {
        case button
        case clickCount = "click_count"
        case coordinates
    }
}

struct ActiveCaptureScrollPayload: Codable {
    let deltaX: Double
    let deltaY: Double
    let phase: ActiveCaptureScrollPhase
    let durationMs: Int?
    let velocityBucket: Int?
    let coordinates: ActiveCaptureActionCoordinates?

    enum CodingKeys: String, CodingKey {
        case deltaX = "delta_x"
        case deltaY = "delta_y"
        case phase
        case durationMs = "duration_ms"
        case velocityBucket = "velocity_bucket"
        case coordinates
    }
}

struct ActiveCaptureKeyChord: Codable {
    let physicalKeyCode: Int
    let normalizedKeyLabel: String
    let modifiers: [ActiveCaptureModifierKey]
    let keyboardLayoutId: String?
    let isRepeat: Bool
    let semantic: ActiveCaptureHotkeySemantic
    let characters: String?

    enum CodingKeys: String, CodingKey {
        case physicalKeyCode = "physical_key_code"
        case normalizedKeyLabel = "normalized_key_label"
        case modifiers
        case keyboardLayoutId = "keyboard_layout_id"
        case isRepeat = "is_repeat"
        case semantic
        case characters
    }
}

struct ActiveCaptureTypingSummary: Codable {
    let eventCount: Int
    let textEventCount: Int
    let characterCount: Int
    let deletionKeyCount: Int
    let nonTextKeyCount: Int
    let compositionUsed: Bool
    let submittedByEnter: Bool
    let durationMs: Int?

    enum CodingKeys: String, CodingKey {
        case eventCount = "event_count"
        case textEventCount = "text_event_count"
        case characterCount = "character_count"
        case deletionKeyCount = "deletion_key_count"
        case nonTextKeyCount = "non_text_key_count"
        case compositionUsed = "composition_used"
        case submittedByEnter = "submitted_by_enter"
        case durationMs = "duration_ms"
    }
}

struct ActiveCaptureKeyboardPayload: Codable {
    let keyboardEventKind: ActiveCaptureKeyboardEventKind
    let inputClass: ActiveCaptureKeyboardInputClass
    let capturePolicy: ActiveCaptureKeyCapturePolicy
    let keyChord: ActiveCaptureKeyChord?
    let typingSummary: ActiveCaptureTypingSummary?
    let hotkeySemantic: ActiveCaptureHotkeySemantic?

    enum CodingKeys: String, CodingKey {
        case keyboardEventKind = "keyboard_event_kind"
        case inputClass = "input_class"
        case capturePolicy = "capture_policy"
        case keyChord = "key_chord"
        case typingSummary = "typing_summary"
        case hotkeySemantic = "hotkey_semantic"
    }
}

struct ActiveCaptureProducerEventCommand: Codable {
    let eventKind: ActiveCaptureProducerEventKind
    let producerKind: String
    let producerVersion: String?
    let occurredAtWallTime: Date?
    let occurredAtMonotonicMs: Int?
    let scope: ActiveCaptureRecordingScope?
    let pointer: ActiveCapturePointerPayload?
    let scroll: ActiveCaptureScrollPayload?
    let keyboard: ActiveCaptureKeyboardPayload?
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case eventKind = "event_kind"
        case producerKind = "producer_kind"
        case producerVersion = "producer_version"
        case occurredAtWallTime = "occurred_at_wall_time"
        case occurredAtMonotonicMs = "occurred_at_monotonic_ms"
        case scope
        case pointer
        case scroll
        case keyboard
        case metadata
    }
}
