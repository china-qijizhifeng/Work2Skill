import AppKit
import Foundation

@MainActor
final class RecordingReviewWindowCoordinator {
    private let client: RecordingPlaybackLoadingClient
    private let logStore: AppLogStore
    private var windowController: RecordingReviewWindowController?

    init(client: RecordingPlaybackLoadingClient, logStore: AppLogStore) {
        self.client = client
        self.logStore = logStore
    }

    func open(_ request: RecordingReviewOpenRequest) {
        guard request.recording?.isRecordingSession == true else {
            logStore.append("无法打开录制复盘：当前记录不是录制 session。")
            return
        }
        let controller: RecordingReviewWindowController
        if let existing = windowController {
            controller = existing
        } else {
            controller = RecordingReviewWindowController(client: client, logStore: logStore)
            windowController = controller
            controller.onClosed = { [weak self, weak controller] in
                guard let self else { return }
                if self.windowController === controller {
                    self.windowController = nil
                }
            }
        }
        controller.present(request)
    }

    func close() {
        windowController?.commitAndClose()
        windowController = nil
    }
}
