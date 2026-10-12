import Foundation

extension CaptureCoordinator {
    func setRecordingStartupBackendSessionId(_ backendSessionId: String, token: UUID) {
        guard recordingStartupToken == token else { return }
        recordingStartupBackendSessionId = backendSessionId
        notifyStateChanged()
    }

    func recordingStartupIsCurrent(
        token: UUID,
        sessionId: UUID,
        backendSessionId: String? = nil
    ) -> Bool {
        guard !Task.isCancelled,
              recordingStartupToken == token,
              activeSessionId == sessionId
        else {
            return false
        }
        guard let backendSessionId else {
            return true
        }
        return activeRecordingContext?.sessionId == backendSessionId
    }

    func handleRecordingStartupCancellation(backendSessionId: String?) async {
        clearFailedRecordingStartup()
        let cleanupWarning = await cancelBackendSessionAfterRecordingStartupFailure(backendSessionId)
        transition(to: .idle, reason: "录制启动已取消")
        if let cleanupWarning {
            log("录制启动已取消：\(cleanupWarning)")
        } else {
            log("录制启动已取消。")
        }
    }
}
