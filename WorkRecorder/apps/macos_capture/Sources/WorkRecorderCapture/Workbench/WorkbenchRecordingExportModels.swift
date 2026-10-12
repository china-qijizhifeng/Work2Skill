import Foundation

enum WorkbenchRecordingExportFallbackMode: String, CaseIterable, Encodable, Equatable, Sendable {
    case normal
    case eventOnly = "event_only"
    case clickOnly = "click_only"

    var title: String {
        switch self {
        case .normal:
            "正常（event → click）"
        case .eventOnly:
            "仅 event 兜底"
        case .clickOnly:
            "仅 click 兜底"
        }
    }
}

struct WorkbenchRecordingExportRequest: Encodable {
    let outputRoot: String
    let purpose: String
    let fallbackMode: WorkbenchRecordingExportFallbackMode

    enum CodingKeys: String, CodingKey {
        case outputRoot = "output_root"
        case purpose
        case fallbackMode = "fallback_mode"
    }
}

struct WorkbenchRecordingExportView: Decodable, Equatable, Sendable {
    let sessionId: String
    let outputDir: String
    let keyframeDirCount: Int
    let evidenceFileCount: Int
    let actionCount: Int
    let videoFileCount: Int
    let vmA11yRecordCount: Int?
    let vmEventLogCount: Int?
    let vmClickLogCount: Int?
    let fallbackWarning: String?

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case outputDir = "output_dir"
        case keyframeDirCount = "keyframe_dir_count"
        case evidenceFileCount = "evidence_file_count"
        case actionCount = "action_count"
        case videoFileCount = "video_file_count"
        case vmA11yRecordCount = "vm_a11y_record_count"
        case vmEventLogCount = "vm_event_log_count"
        case vmClickLogCount = "vm_click_log_count"
        case fallbackWarning = "fallback_warning"
    }
}
