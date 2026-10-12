import AppKit
import Foundation

enum RegionRecordingFailure: Error, LocalizedError {
    case displayUnavailable
    case screenCapturePermissionDenied(String)
    case noFramesWritten
    case writerTimedOut
    case writerFailed(String)
    case frameProcessingFailed(String)
    case pngWriteFailed(String)
    case assetDurationUnavailable(String)

    var errorDescription: String? {
        switch self {
        case .displayUnavailable:
            return "无法识别要录制的显示器。"
        case .screenCapturePermissionDenied(let message):
            return "屏幕录制权限不可用：\(message)"
        case .noFramesWritten:
            return "录制没有收到可用画面，请检查屏幕录制权限。"
        case .writerTimedOut:
            return "录制文件写入超时。"
        case .writerFailed(let message):
            return "录制文件写入失败：\(message)"
        case .frameProcessingFailed(let message):
            return "录制画面处理失败：\(message)"
        case .pngWriteFailed(let message):
            return "关键帧预览写入失败：\(message)"
        case .assetDurationUnavailable(let message):
            return "无法读取录制时长：\(message)"
        }
    }
}

enum RecordingPreparationWarning: Equatable {
    case accessibilityDegraded
    case inputMonitoringDegraded
    case lowSourceConfidence

    var title: String {
        switch self {
        case .accessibilityDegraded:
            return "窗口识别已降级"
        case .inputMonitoringDegraded:
            return "操作线索未启用"
        case .lowSourceConfidence:
            return "窗口识别置信度较低"
        }
    }

    var detail: String {
        switch self {
        case .accessibilityDegraded:
            return "仍会录制视频；开启辅助功能权限后，可更准确识别窗口和控件。"
        case .inputMonitoringDegraded:
            return "仍会保存视频和关键帧，但不会记录点击、滚动和快捷键线索。"
        case .lowSourceConfidence:
            return "WorkRecorder 会保存视频和关键帧；后续动作归因可能需要人工确认。"
        }
    }
}

enum RecordingPermissionIssueKind: Equatable {
    case screenRecordingDenied
    case startupFailed(String)

    var title: String {
        switch self {
        case .screenRecordingDenied:
            return "需要屏幕录制权限"
        case .startupFailed:
            return "录制没有完成"
        }
    }

    var detail: String {
        switch self {
        case .screenRecordingDenied:
            return "授权后才能录制你框选的区域。\n开启权限后，重新按下录制快捷键并再次选择边界。"
        case .startupFailed(let message):
            return message
        }
    }

    var primaryActionTitle: String {
        switch self {
        case .screenRecordingDenied:
            return "打开系统设置"
        case .startupFailed:
            return "关闭"
        }
    }

    var opensSystemSettings: Bool {
        self == .screenRecordingDenied
    }
}

struct RecordingPermissionIssue: Equatable {
    let kind: RecordingPermissionIssueKind
    let selectedRegionDescription: String
    let sourceDescription: String?
    let diagnostic: String?
}

struct RegionRecordingTarget {
    let selection: SelectionResult
    let scope: ActiveCaptureRecordingScope
    let outputDirectory: URL
}

struct RecordingSegmentCaptureResult {
    let segmentId: String
    let videoURL: URL
    let startFrameURL: URL
    let finalFrameURL: URL
    let durationMilliseconds: Int
    let containerDurationMilliseconds: Int
    let frameCount: Int
    let videoWidth: Int
    let videoHeight: Int
    let startedMonotonicMilliseconds: Int
    let firstFrameMonotonicMilliseconds: Int?
    let firstFrameWallTimeEpochMilliseconds: Int?
    let finalFrameMonotonicMilliseconds: Int?
    let endedMonotonicMilliseconds: Int
    let closeReason: ActiveCaptureRecordingSegmentCloseReason
}

struct RecordingCompletionDraft {
    let sessionId: String
    let selection: SelectionResult
    let scope: ActiveCaptureRecordingScope
    let sourceBinding: SourceBinding
    let segments: [RecordingSegmentCaptureResult]
    let startedAtMonotonicMilliseconds: Int
    let endedAtMonotonicMilliseconds: Int
    let finalKeyframeEventId: String?
    let inputTraceDegraded: Bool
    let scopeNeedsReview: Bool

    var totalDurationMilliseconds: Int {
        segments.reduce(0) { $0 + $1.durationMilliseconds }
    }

    var totalFrameCount: Int {
        segments.reduce(0) { $0 + $1.frameCount }
    }

    var previewURL: URL? {
        previewImageCandidates.first
    }

    var previewImageCandidates: [URL] {
        var candidates: [URL] = []
        for segment in segments.reversed() {
            candidates.append(segment.finalFrameURL)
            candidates.append(segment.startFrameURL)
        }
        return candidates
    }

    var primaryVideoURL: URL? {
        segments.last?.videoURL ?? segments.first?.videoURL
    }

    var videoCandidates: [URL] {
        segments.reversed().map(\.videoURL)
    }
}

struct RecordingRuntimeContext {
    let sessionId: String
    let selection: SelectionResult
    let sourceBinding: SourceBinding
    let scope: ActiveCaptureRecordingScope
    let startedAtMonotonicMilliseconds: Int
    var currentSegmentId: String
    var completedSegments: [RecordingSegmentCaptureResult]
    var scopeNeedsReview: Bool = false
}
