import AppKit
import Foundation

extension CaptureCoordinator {
    func closeOverlay() {
        removeSelectionEscapeMonitors()
        retireWindows(overlayWindows)
        overlayWindows.removeAll()
    }

    func closeHUD() {
        if pendingRecordingCompletion != nil {
            log("录制待保存，请在完成面板中保存或丢弃。")
            focusRecordingControls()
            return
        }
        if activeRecordingContext != nil {
            log("录制仍在进行，请先在控制条中完成录制。")
            focusRecordingControls()
            return
        }
        if cancelRecordingStartupIfNeeded(reason: "recording_startup_closed") {
            log("录制启动已取消。")
            forceCloseHUD(reason: "录制启动已取消")
            return
        }
        forceCloseHUD(reason: "HUD 已关闭")
    }

    func forceCloseHUD(reason: String) {
        cancelRecordingStartupIfNeeded(reason: "recording_surface_force_closed")
        closeOverlay()
        retireTransientHUDWindows()
        activeRecordingSegment = nil
        activeRecordingContext = nil
        recordingStartupTask = nil
        recordingStartupToken = nil
        recordingStartupBackendSessionId = nil
        pendingRecordingCompletion = nil
        recordingCompletionCaptureDrainAllowed = false
        if let recordingPreviewVideoURL {
            deleteTemporaryRecordingFile(recordingPreviewVideoURL)
        }
        recordingPreviewVideoURL = nil
        recordingCompletionSubmitting = false
        recordingInputTraceDegraded = false
        recordingScopeNeedsReview = false
        recordingLastScopeHealthCheckMonotonicMilliseconds = 0
        recordingSessionController.reset()
        syncRecordingControlFieldsFromSessionController()
        stopActiveCaptureInputProducer()
        closeOrphanHUDWindows()
        armedSourceBinding = nil
        activeSessionId = nil
        transition(to: .idle, reason: reason)
    }

    func clearFailedRecordingStartup() {
        stopActiveCaptureInputProducer()
        recordingStartupTask?.cancel()
        recordingStartupTask = nil
        recordingStartupToken = nil
        recordingStartupBackendSessionId = nil
        activeRecordingSegment = nil
        activeRecordingContext = nil
        pendingRecordingCompletion = nil
        recordingCompletionCaptureDrainAllowed = false
        recordingInputTraceDegraded = false
        recordingScopeNeedsReview = false
        recordingLastScopeHealthCheckMonotonicMilliseconds = 0
        recordingSessionController.reset()
        syncRecordingControlFieldsFromSessionController()
        recordingCompletionSubmitting = false
        retireWindow(recordingPreparationWindow)
        recordingPreparationWindow = nil
        retireWindow(recordingHUDWindow)
        recordingHUDWindow = nil
        retireWindow(recordingBoundaryWindow)
        recordingBoundaryWindow = nil
        retireWindow(recordingCountdownWindow)
        recordingCountdownWindow = nil
        retireWindow(recordingPermissionIssueWindow)
        recordingPermissionIssueWindow = nil
        recordingHUDTimer?.invalidate()
        recordingHUDTimer = nil
        notifyStateChanged()
    }

    @discardableResult
    func cancelRecordingStartupIfNeeded(reason: String) -> Bool {
        let task = recordingStartupTask
        let backendSessionId = recordingStartupBackendSessionId
        guard task != nil || backendSessionId != nil else {
            return false
        }
        task?.cancel()
        recordingStartupTask = nil
        recordingStartupToken = nil
        recordingStartupBackendSessionId = nil
        if let backendSessionId {
            Task { @MainActor [weak self] in
                guard let self else { return }
                do {
                    _ = try await transport.cancelActiveCaptureSession(sessionId: backendSessionId, reason: reason)
                    log("已取消启动中的录制会话：\(backendSessionId)")
                } catch {
                    log("取消启动中的录制会话失败：\(error.localizedDescription)")
                }
            }
        }
        notifyStateChanged()
        return true
    }

    func closeOrphanHUDWindows() {
        let orphanWindows = NSApplication.shared.windows.compactMap { window -> NSWindow? in
            switch window {
            case is CaptureOverlayWindow,
                 is CaptureAnchorOverlayWindow,
                 is RecordingPreparationWindow,
                 is RecordingHUDWindow,
                 is RecordingBoundaryOverlayWindow,
                 is RecordingCountdownWindow,
                 is RecordingCompletionWindow,
                 is RecordingDiscardConfirmationWindow,
                 is RecordingPermissionIssueWindow:
                return window
            default:
                return nil
            }
        }
        retireWindows(orphanWindows)
    }

    func installSelectionEscapeMonitors(sessionId: UUID) {
        removeSelectionEscapeMonitors()
        selectionLocalKeyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard event.keyCode == CaptureKeyCode.escape else { return event }
            Task { @MainActor [weak self] in
                self?.cancelCapture(sessionId: sessionId)
            }
            return nil
        }
        selectionGlobalKeyMonitor = NSEvent.addGlobalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard event.keyCode == CaptureKeyCode.escape else { return }
            Task { @MainActor [weak self] in
                self?.cancelCapture(sessionId: sessionId)
            }
        }
    }

    func removeSelectionEscapeMonitors() {
        if let selectionLocalKeyMonitor {
            NSEvent.removeMonitor(selectionLocalKeyMonitor)
        }
        if let selectionGlobalKeyMonitor {
            NSEvent.removeMonitor(selectionGlobalKeyMonitor)
        }
        selectionLocalKeyMonitor = nil
        selectionGlobalKeyMonitor = nil
    }

    private func retireTransientHUDWindows() {
        retireWindow(anchorOverlay)
        anchorOverlay = nil
        retireWindow(recordingPreparationWindow)
        recordingPreparationWindow = nil
        retireWindow(recordingHUDWindow)
        recordingHUDWindow = nil
        retireWindow(recordingBoundaryWindow)
        recordingBoundaryWindow = nil
        retireWindow(recordingCountdownWindow)
        recordingCountdownWindow = nil
        retireWindow(recordingCompletionWindow)
        recordingCompletionWindow = nil
        retireWindow(recordingDiscardConfirmationWindow)
        recordingDiscardConfirmationWindow = nil
        retireWindow(recordingPermissionIssueWindow)
        recordingPermissionIssueWindow = nil
        recordingHUDTimer?.invalidate()
        recordingHUDTimer = nil
    }
}
