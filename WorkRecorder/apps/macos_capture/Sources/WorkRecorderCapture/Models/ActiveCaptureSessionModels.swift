import Foundation

enum ActiveCaptureMode: String, Codable {
    case screenshotKeyframes = "screenshot_keyframes"
    case recordingSession = "recording_session"
}

enum ActiveCaptureStatus: String, Codable {
    case created
    case selectingScope = "selecting_scope"
    case recording
    case paused
    case scopeLost = "scope_lost"
    case stopping
    case finalizing
    case completed
    case completedWithWarnings = "completed_with_warnings"
    case failed
    case cancelled
}

enum ActiveCaptureRecordingControlKind: String, Codable {
    case startSegment = "start_segment"
    case endSegment = "end_segment"
    case pause
    case resume
    case userMark = "user_mark"
    case stop
    case autoStop = "auto_stop"
    case scopeLost = "scope_lost"
}

enum ActiveCaptureRecordingControlSource: String, Codable {
    case nativeClient = "native_client"
}

enum ActiveCaptureRecordingSegmentState: String, Codable {
    case recording
    case paused
    case finalizing
    case available
    case failed
}

enum ActiveCaptureRecordingSegmentCloseReason: String, Codable {
    case paused
    case resumedNewSegment = "resumed_new_segment"
    case stopped
    case maxDuration = "max_duration"
    case scopeLost = "scope_lost"
    case videoFailed = "video_failed"
}

enum ActiveCaptureVideoArtifactState: String, Codable {
    case notRecorded = "not_recorded"
    case recording
    case staged
    case available
    case failed
    case deleted
}

enum ActiveCaptureWarningCode: String, Codable {
    case videoUnavailable = "video_unavailable"
    case videoValidationFailed = "video_validation_failed"
}

struct ActiveCaptureWarning: Codable, Equatable {
    let code: ActiveCaptureWarningCode
    let message: String
    let createdAt: Date

    enum CodingKeys: String, CodingKey {
        case code
        case message
        case createdAt = "created_at"
    }
}

struct ActiveCaptureSessionSummary: Codable, Equatable {
    let sessionId: String
    let mode: ActiveCaptureMode
    let status: ActiveCaptureStatus
    let primaryEventId: String?
    let startedAt: Date?
    let endedAt: Date?
    let userNote: String?

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case mode
        case status
        case primaryEventId = "primary_event_id"
        case startedAt = "started_at"
        case endedAt = "ended_at"
        case userNote = "user_note"
    }
}

struct ActiveCaptureSessionPublicView: Codable, Equatable {
    let session: ActiveCaptureSessionSummary
}

struct RecordingControlApplyResult {
    let session: ActiveCaptureSessionPublicView
    let captureInstruction: ActiveCaptureCaptureInstruction?
}

struct CreateActiveCaptureSessionRequest: Codable {
    let mode: ActiveCaptureMode
    let scope: ActiveCaptureRecordingScope
    let startRecording: Bool
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case mode
        case scope
        case startRecording = "start_recording"
        case metadata
    }
}

struct ApplyRecordingControlRequest: Codable {
    let kind: ActiveCaptureRecordingControlKind
    let source: ActiveCaptureRecordingControlSource
    let occurredAtMonotonicMs: Int?
    let note: String?
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case kind
        case source
        case occurredAtMonotonicMs = "occurred_at_monotonic_ms"
        case note
        case metadata
    }
}

struct SubmitKeyframeTriggerRequest: Codable {
    let triggerKind: ActiveCaptureKeyframeTriggerKind
    let role: ActiveCaptureKeyframeRole?
    let occurredAtMonotonicMs: Int?
    let scope: ActiveCaptureRecordingScope?
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case triggerKind = "trigger_kind"
        case role
        case occurredAtMonotonicMs = "occurred_at_monotonic_ms"
        case scope
        case metadata
    }
}

struct KeyframeTriggerSubmissionResponse: Codable {
    let captureInstruction: ActiveCaptureCaptureInstruction?

    enum CodingKeys: String, CodingKey {
        case captureInstruction = "capture_instruction"
    }
}

struct ApplyRecordingControlResponse: Codable {
    let session: ActiveCaptureSessionSummary
    let controlTrigger: KeyframeTriggerSubmissionResponse?

    enum CodingKeys: String, CodingKey {
        case session
        case controlTrigger = "control_trigger"
    }
}

struct StagedRecordingVideoRef: Codable {
    let localPath: String
    let contentType: String
    let filename: String?
    let durationMs: Int?
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case localPath = "local_path"
        case contentType = "content_type"
        case filename
        case durationMs = "duration_ms"
        case metadata
    }
}

struct AttachRecordingSegmentRequest: Codable {
    let segmentId: String
    let state: ActiveCaptureRecordingSegmentState
    let startedAtMonotonicMs: Int?
    let mediaStartMonotonicMs: Int?
    let mediaStartWallTimeEpochMs: Int?
    let endedAtMonotonicMs: Int?
    let durationMs: Int?
    let closeReason: ActiveCaptureRecordingSegmentCloseReason?
    let stagedVideo: StagedRecordingVideoRef?
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case segmentId = "segment_id"
        case state
        case startedAtMonotonicMs = "started_at_monotonic_ms"
        case mediaStartMonotonicMs = "media_start_monotonic_ms"
        case mediaStartWallTimeEpochMs = "media_start_wall_time_epoch_ms"
        case endedAtMonotonicMs = "ended_at_monotonic_ms"
        case durationMs = "duration_ms"
        case closeReason = "close_reason"
        case stagedVideo = "staged_video"
        case metadata
    }
}

struct RecordingVideoPublicSummary: Codable, Equatable {
    let artifactId: String?
    let state: ActiveCaptureVideoArtifactState
    let contentType: String?
    let durationMs: Int?

    enum CodingKeys: String, CodingKey {
        case artifactId = "artifact_id"
        case state
        case contentType = "content_type"
        case durationMs = "duration_ms"
    }
}

struct RecordingVideoSegmentPublicSummary: Codable, Equatable {
    let segmentId: String
    let sessionId: String
    let sequenceIndex: Int
    let state: ActiveCaptureRecordingSegmentState
    let startedAtMonotonicMs: Int?
    let mediaStartMonotonicMs: Int?
    let endedAtMonotonicMs: Int?
    let durationMs: Int?
    let closeReason: ActiveCaptureRecordingSegmentCloseReason?
    let video: RecordingVideoPublicSummary?

    enum CodingKeys: String, CodingKey {
        case segmentId = "segment_id"
        case sessionId = "session_id"
        case sequenceIndex = "sequence_index"
        case state
        case startedAtMonotonicMs = "started_at_monotonic_ms"
        case mediaStartMonotonicMs = "media_start_monotonic_ms"
        case endedAtMonotonicMs = "ended_at_monotonic_ms"
        case durationMs = "duration_ms"
        case closeReason = "close_reason"
        case video
    }
}

struct RecordingSegmentManifestPublicView: Codable, Equatable {
    let manifestId: String
    let sessionId: String
    let segments: [RecordingVideoSegmentPublicSummary]
    let totalRecordedDurationMs: Int
    let totalPausedDurationMs: Int

    enum CodingKeys: String, CodingKey {
        case manifestId = "manifest_id"
        case sessionId = "session_id"
        case segments
        case totalRecordedDurationMs = "total_recorded_duration_ms"
        case totalPausedDurationMs = "total_paused_duration_ms"
    }
}

struct CompleteActiveCaptureSessionRequest: Codable {
    let warnings: [ActiveCaptureWarning]
    let userNote: String?
    let video: StagedRecordingVideoRef?
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case warnings
        case userNote = "user_note"
        case video
        case metadata
    }
}

struct CancelActiveCaptureSessionRequest: Codable {
    let reason: String
    let metadata: [String: JSONScalar]
}
