import Foundation

enum WorkbenchRecordingStatus: Equatable, Decodable {
    case created
    case selectingScope
    case recording
    case paused
    case scopeLost
    case stopping
    case finalizing
    case completed
    case completedWithWarnings
    case failed
    case cancelled
    case unknown(String)

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer().decode(String.self)
        switch value {
        case "created":
            self = .created
        case "selecting_scope":
            self = .selectingScope
        case "recording":
            self = .recording
        case "paused":
            self = .paused
        case "scope_lost":
            self = .scopeLost
        case "stopping":
            self = .stopping
        case "finalizing":
            self = .finalizing
        case "completed":
            self = .completed
        case "completed_with_warnings":
            self = .completedWithWarnings
        case "failed":
            self = .failed
        case "cancelled":
            self = .cancelled
        default:
            self = .unknown(value)
        }
    }

    var title: String {
        switch self {
        case .created, .selectingScope:
            return "准备中"
        case .recording:
            return "录制中"
        case .paused:
            return "已暂停"
        case .scopeLost:
            return "窗口状态变化"
        case .stopping:
            return "正在停止"
        case .finalizing:
            return "正在整理"
        case .completed:
            return "已完成"
        case .completedWithWarnings:
            return "已完成，有提醒"
        case .failed:
            return "失败"
        case .cancelled:
            return "已取消"
        case .unknown(let value):
            return value.replacingOccurrences(of: "_", with: " ")
        }
    }
}

enum WorkbenchRecordingTimelineKind: Equatable, Decodable {
    case keyframe
    case action
    case control
    case warning
    case unknown(String)

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer().decode(String.self)
        switch value {
        case "keyframe":
            self = .keyframe
        case "action":
            self = .action
        case "control":
            self = .control
        case "warning":
            self = .warning
        default:
            self = .unknown(value)
        }
    }

    var symbolName: String {
        switch self {
        case .keyframe:
            return "camera.viewfinder"
        case .action:
            return "cursorarrow.click.2"
        case .control:
            return "record.circle"
        case .warning:
            return "exclamationmark.triangle"
        case .unknown:
            return "circle.dotted"
        }
    }
}

enum WorkbenchRecordingActionKind: Equatable, Decodable {
    case click
    case scroll
    case hotkey
    case keyDown
    case keyUp
    case typingPause
    case windowSwitch
    case tabSwitch
    case userMark
    case unknown(String)

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer().decode(String.self)
        switch value {
        case "click":
            self = .click
        case "scroll":
            self = .scroll
        case "hotkey":
            self = .hotkey
        case "key_down":
            self = .keyDown
        case "key_up":
            self = .keyUp
        case "typing_pause":
            self = .typingPause
        case "window_switch":
            self = .windowSwitch
        case "tab_switch":
            self = .tabSwitch
        case "user_mark":
            self = .userMark
        default:
            self = .unknown(value)
        }
    }

    var title: String {
        switch self {
        case .click:
            return "点击"
        case .scroll:
            return "滚动"
        case .hotkey:
            return "按键"
        case .keyDown:
            return "按下"
        case .keyUp:
            return "松开"
        case .typingPause:
            return "文本输入"
        case .windowSwitch:
            return "窗口切换"
        case .tabSwitch:
            return "标签切换"
        case .userMark:
            return "手动标记"
        case .unknown(let value):
            return value.replacingOccurrences(of: "_", with: " ")
        }
    }
}

enum WorkbenchRecordingControlKind: Equatable, Decodable {
    case startSegment
    case endSegment
    case pause
    case resume
    case userMark
    case stop
    case autoStop
    case scopeLost
    case unknown(String)

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer().decode(String.self)
        switch value {
        case "start_segment":
            self = .startSegment
        case "end_segment":
            self = .endSegment
        case "pause":
            self = .pause
        case "resume":
            self = .resume
        case "user_mark":
            self = .userMark
        case "stop":
            self = .stop
        case "auto_stop":
            self = .autoStop
        case "scope_lost":
            self = .scopeLost
        default:
            self = .unknown(value)
        }
    }

    var title: String {
        switch self {
        case .startSegment:
            return "开始片段"
        case .endSegment:
            return "结束片段"
        case .pause:
            return "暂停"
        case .resume:
            return "继续"
        case .userMark:
            return "标记"
        case .stop, .autoStop:
            return "完成"
        case .scopeLost:
            return "范围变化"
        case .unknown(let value):
            return value.replacingOccurrences(of: "_", with: " ")
        }
    }
}

enum WorkbenchRecordingVideoState: Equatable, Decodable {
    case notRecorded
    case recording
    case staged
    case available
    case failed
    case deleted
    case unknown(String)

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer().decode(String.self)
        switch value {
        case "not_recorded":
            self = .notRecorded
        case "recording":
            self = .recording
        case "staged":
            self = .staged
        case "available":
            self = .available
        case "failed":
            self = .failed
        case "deleted":
            self = .deleted
        default:
            self = .unknown(value)
        }
    }

    var title: String {
        switch self {
        case .notRecorded:
            return "未录视频"
        case .recording:
            return "录制中"
        case .staged:
            return "待入库"
        case .available:
            return "已入库"
        case .failed:
            return "视频失败"
        case .deleted:
            return "已删除"
        case .unknown(let value):
            return value.replacingOccurrences(of: "_", with: " ")
        }
    }
}

enum WorkbenchSkillReadinessState: Equatable, Decodable {
    case ready
    case needsReview
    case blocked
    case unknown(String)

    init(from decoder: Decoder) throws {
        let value = try decoder.singleValueContainer().decode(String.self)
        switch value {
        case "ready":
            self = .ready
        case "needs_review":
            self = .needsReview
        case "blocked":
            self = .blocked
        default:
            self = .unknown(value)
        }
    }

    var title: String {
        switch self {
        case .ready:
            return "可复盘"
        case .needsReview:
            return "需复核"
        case .blocked:
            return "证据不足"
        case .unknown(let value):
            return value.replacingOccurrences(of: "_", with: " ")
        }
    }
}

struct WorkbenchActiveCaptureInspectView: Decodable, Equatable {
    let sessionId: String
    let mode: ActiveCaptureMode
    let primaryEventId: String?
    let status: WorkbenchRecordingStatus
    let startedAt: String?
    let endedAt: String?
    let userNote: String?
    let warnings: [String]
    let timeline: WorkbenchRecordingTimelineInspectView?
    let safeTextBlocks: [WorkbenchRecordingSafeTextBlock]
    let videoRef: WorkbenchRecordingVideoInspectRef?
    let skillReadiness: WorkbenchSkillReadinessSummary
    let projection: WorkbenchProjectionTruncationSummary?

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case mode
        case primaryEventId = "primary_event_id"
        case status
        case startedAt = "started_at"
        case endedAt = "ended_at"
        case userNote = "user_note"
        case warnings
        case timeline
        case safeTextBlocks = "safe_text_blocks"
        case videoRef = "video_ref"
        case skillReadiness = "skill_readiness"
        case projection
    }

    var isRecordingSession: Bool {
        mode == .recordingSession
    }
}

struct WorkbenchRecordingTimelineInspectView: Decodable, Equatable {
    let sessionId: String
    let durationMs: Int?
    let alignmentErrorMs: Int?
    let steps: [WorkbenchRecordingTimelineStepView]

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case durationMs = "duration_ms"
        case alignmentErrorMs = "alignment_error_ms"
        case steps
    }
}

struct WorkbenchRecordingTimelineStepView: Decodable, Equatable {
    let stepId: String
    let kind: WorkbenchRecordingTimelineKind
    let occurredAt: String
    let mediaTimeMs: Int?
    let sequenceIndex: Int?
    let keyframeId: String?
    let keyframeEventId: String?
    let visibilityClass: String?
    let foldReason: String?
    let safeTextRefIds: [String]
    let actionId: String?
    let controlId: String?
    let keyframeRole: String?
    let triggerKind: String?
    let actionKind: WorkbenchRecordingActionKind?
    let actionSummary: WorkbenchRecordingActionSummaryView?
    let controlKind: WorkbenchRecordingControlKind?
    let safeCaption: String
    let needsReview: Bool
    let readiness: WorkbenchSkillReadinessSummary

    enum CodingKeys: String, CodingKey {
        case stepId = "step_id"
        case kind
        case occurredAt = "occurred_at"
        case mediaTimeMs = "media_time_ms"
        case sequenceIndex = "sequence_index"
        case keyframeId = "keyframe_id"
        case keyframeEventId = "keyframe_event_id"
        case visibilityClass = "visibility_class"
        case foldReason = "fold_reason"
        case safeTextRefIds = "safe_text_ref_ids"
        case actionId = "action_id"
        case controlId = "control_id"
        case keyframeRole = "keyframe_role"
        case triggerKind = "trigger_kind"
        case actionKind = "action_kind"
        case actionSummary = "action_summary"
        case controlKind = "control_kind"
        case safeCaption = "safe_caption"
        case needsReview = "needs_review"
        case readiness
    }

    init(
        stepId: String,
        kind: WorkbenchRecordingTimelineKind,
        occurredAt: String,
        mediaTimeMs: Int?,
        sequenceIndex: Int?,
        keyframeId: String?,
        keyframeEventId: String? = nil,
        visibilityClass: String? = nil,
        foldReason: String? = nil,
        safeTextRefIds: [String] = [],
        actionId: String?,
        controlId: String?,
        keyframeRole: String?,
        triggerKind: String?,
        actionKind: WorkbenchRecordingActionKind?,
        actionSummary: WorkbenchRecordingActionSummaryView?,
        controlKind: WorkbenchRecordingControlKind?,
        safeCaption: String,
        needsReview: Bool,
        readiness: WorkbenchSkillReadinessSummary
    ) {
        self.stepId = stepId
        self.kind = kind
        self.occurredAt = occurredAt
        self.mediaTimeMs = mediaTimeMs
        self.sequenceIndex = sequenceIndex
        self.keyframeId = keyframeId
        self.keyframeEventId = keyframeEventId
        self.visibilityClass = visibilityClass
        self.foldReason = foldReason
        self.safeTextRefIds = safeTextRefIds
        self.actionId = actionId
        self.controlId = controlId
        self.keyframeRole = keyframeRole
        self.triggerKind = triggerKind
        self.actionKind = actionKind
        self.actionSummary = actionSummary
        self.controlKind = controlKind
        self.safeCaption = safeCaption
        self.needsReview = needsReview
        self.readiness = readiness
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        stepId = try container.decode(String.self, forKey: .stepId)
        kind = try container.decode(WorkbenchRecordingTimelineKind.self, forKey: .kind)
        occurredAt = try container.decode(String.self, forKey: .occurredAt)
        mediaTimeMs = try container.decodeIfPresent(Int.self, forKey: .mediaTimeMs)
        sequenceIndex = try container.decodeIfPresent(Int.self, forKey: .sequenceIndex)
        keyframeId = try container.decodeIfPresent(String.self, forKey: .keyframeId)
        keyframeEventId = try container.decodeIfPresent(String.self, forKey: .keyframeEventId)
        visibilityClass = try container.decodeIfPresent(String.self, forKey: .visibilityClass)
        foldReason = try container.decodeIfPresent(String.self, forKey: .foldReason)
        safeTextRefIds = try container.decodeIfPresent([String].self, forKey: .safeTextRefIds) ?? []
        actionId = try container.decodeIfPresent(String.self, forKey: .actionId)
        controlId = try container.decodeIfPresent(String.self, forKey: .controlId)
        keyframeRole = try container.decodeIfPresent(String.self, forKey: .keyframeRole)
        triggerKind = try container.decodeIfPresent(String.self, forKey: .triggerKind)
        actionKind = try container.decodeIfPresent(WorkbenchRecordingActionKind.self, forKey: .actionKind)
        actionSummary = try container.decodeIfPresent(WorkbenchRecordingActionSummaryView.self, forKey: .actionSummary)
        controlKind = try container.decodeIfPresent(WorkbenchRecordingControlKind.self, forKey: .controlKind)
        safeCaption = try container.decode(String.self, forKey: .safeCaption)
        needsReview = try container.decode(Bool.self, forKey: .needsReview)
        readiness = try container.decode(WorkbenchSkillReadinessSummary.self, forKey: .readiness)
    }
}

struct WorkbenchRecordingVideoInspectRef: Decodable, Equatable {
    let artifactId: String?
    let state: WorkbenchRecordingVideoState
    let contentType: String?
    let durationMs: Int?
    let byteSize: Int?
    let alignmentErrorMs: Int?

    enum CodingKeys: String, CodingKey {
        case artifactId = "artifact_id"
        case state
        case contentType = "content_type"
        case durationMs = "duration_ms"
        case byteSize = "byte_size"
        case alignmentErrorMs = "alignment_error_ms"
    }
}

struct WorkbenchRecordingSafeTextBlock: Decodable, Equatable {
    let blockId: String
    let sourceField: String
    let eventId: String
    let keyframeId: String?
    let text: String
    let textTruncated: Bool
    let confidence: Double?

    enum CodingKeys: String, CodingKey {
        case blockId = "block_id"
        case sourceField = "source_field"
        case eventId = "event_id"
        case keyframeId = "keyframe_id"
        case text
        case textTruncated = "text_truncated"
        case confidence
    }

    init(
        blockId: String,
        sourceField: String,
        eventId: String,
        keyframeId: String? = nil,
        text: String,
        textTruncated: Bool,
        confidence: Double?
    ) {
        self.blockId = blockId
        self.sourceField = sourceField
        self.eventId = eventId
        self.keyframeId = keyframeId
        self.text = text
        self.textTruncated = textTruncated
        self.confidence = confidence
    }
}

struct WorkbenchSkillReadinessSummary: Decodable, Equatable {
    let state: WorkbenchSkillReadinessState
    let reasons: [String]
    let reviewItemCount: Int
    let blockedItemCount: Int
    let missingEvidence: [String]

    enum CodingKeys: String, CodingKey {
        case state
        case reasons
        case reviewItemCount = "review_item_count"
        case blockedItemCount = "blocked_item_count"
        case missingEvidence = "missing_evidence"
    }
}

struct WorkbenchProjectionTruncationSummary: Decodable, Equatable {
    let truncated: Bool
    let truncatedCounts: [String: Int]
    let nextCursor: String?

    enum CodingKeys: String, CodingKey {
        case truncated
        case truncatedCounts = "truncated_counts"
        case nextCursor = "next_cursor"
    }
}
