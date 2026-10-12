import Foundation

enum RecordingMenuStatus: Equatable {
    case inactive
    case recording
    case paused
    case review
    case busy
}

struct RecordingMenuPresentation: Equatable {
    let status: RecordingMenuStatus
    let statusTitle: String
    let statusDetail: String?
    let pauseToggleTitle: String
    let canFocusControls: Bool
    let canTogglePause: Bool
    let canFinish: Bool
    let showsRecordingBadge: Bool

    static let inactive = RecordingMenuPresentation(
        status: .inactive,
        statusTitle: "",
        statusDetail: nil,
        pauseToggleTitle: "暂停录制",
        canFocusControls: false,
        canTogglePause: false,
        canFinish: false,
        showsRecordingBadge: false
    )

    static func make(
        state: CaptureCoordinator.State,
        hasActiveRecordingContext: Bool,
        hasRecordingStartup: Bool,
        hasPendingCompletion: Bool,
        isControlInFlight: Bool
    ) -> RecordingMenuPresentation {
        if hasRecordingStartup {
            return RecordingMenuPresentation(
                status: .busy,
                statusTitle: "录制正在启动",
                statusDetail: "控制面板即将出现",
                pauseToggleTitle: "暂停录制",
                canFocusControls: true,
                canTogglePause: false,
                canFinish: false,
                showsRecordingBadge: true
            )
        }
        if isControlInFlight, hasActiveRecordingContext || hasPendingCompletion {
            return RecordingMenuPresentation(
                status: .busy,
                statusTitle: "录制正在处理",
                statusDetail: "请稍候",
                pauseToggleTitle: "暂停录制",
                canFocusControls: true,
                canTogglePause: false,
                canFinish: false,
                showsRecordingBadge: true
            )
        }
        if hasPendingCompletion || isRecordingReview(state) {
            return RecordingMenuPresentation(
                status: .review,
                statusTitle: "录制待保存",
                statusDetail: "请在完成面板中保存或丢弃",
                pauseToggleTitle: "暂停录制",
                canFocusControls: true,
                canTogglePause: false,
                canFinish: false,
                showsRecordingBadge: true
            )
        }
        if isRecordingPaused(state), hasActiveRecordingContext {
            return RecordingMenuPresentation(
                status: .paused,
                statusTitle: "录制已暂停",
                statusDetail: "可继续录制或结束",
                pauseToggleTitle: "继续录制",
                canFocusControls: true,
                canTogglePause: true,
                canFinish: true,
                showsRecordingBadge: true
            )
        }
        if isRecording(state), hasActiveRecordingContext {
            return RecordingMenuPresentation(
                status: .recording,
                statusTitle: "正在录制",
                statusDetail: "边界与 HUD 已显示",
                pauseToggleTitle: "暂停录制",
                canFocusControls: true,
                canTogglePause: true,
                canFinish: true,
                showsRecordingBadge: true
            )
        }
        if hasActiveRecordingContext {
            return RecordingMenuPresentation(
                status: .busy,
                statusTitle: "录制正在启动",
                statusDetail: "控制面板即将出现",
                pauseToggleTitle: "暂停录制",
                canFocusControls: true,
                canTogglePause: false,
                canFinish: false,
                showsRecordingBadge: true
            )
        }
        return .inactive
    }

    private static func isRecording(_ state: CaptureCoordinator.State) -> Bool {
        if case .recording = state {
            return true
        }
        return false
    }

    private static func isRecordingPaused(_ state: CaptureCoordinator.State) -> Bool {
        if case .recordingPaused = state {
            return true
        }
        return false
    }

    private static func isRecordingReview(_ state: CaptureCoordinator.State) -> Bool {
        if case .recordingReview = state {
            return true
        }
        return false
    }
}
