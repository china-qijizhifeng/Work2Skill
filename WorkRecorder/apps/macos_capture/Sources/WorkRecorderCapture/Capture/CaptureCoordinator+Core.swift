import AppKit
import CoreGraphics
import Foundation

extension CaptureCoordinator {
    enum State: Equatable {
        case idle
        case selecting(UUID)
        case capturing(UUID)
        case confirming(UUID)
        case recording(UUID)
        case recordingPaused(UUID)
        case recordingReview(UUID)
        case failed(UUID, String)

        var label: String {
            switch self {
            case .idle:
                return "空闲"
            case .selecting:
                return "正在框选"
            case .capturing:
                return "正在准备录制"
            case .confirming:
                return "等待开始"
            case .recording:
                return "正在录制"
            case .recordingPaused:
                return "录制暂停"
            case .recordingReview:
                return "录制待保存"
            case .failed:
                return "失败"
            }
        }
    }

    func cancelCapture(sessionId: UUID) {
        guard activeSessionId == sessionId else { return }
        closeHUD()
    }

    /// Builds the still-frame envelope used inside a recording session.
    /// This is recording evidence, not a standalone screenshot command.
    func makeDraft(
        selection: SelectionResult,
        stagedFile: URL,
        sourceBinding: SourceBinding
    ) -> CaptureDraft {
        let actor = ActorRef(actorId: "macos-capture", displayName: "WorkRecorder")
        let selectedBox = Geometry.intBox(from: selection.screenRect, coordinateSpace: "macos_global")
        let pixelBox = Geometry.intBox(from: selection.captureRect, coordinateSpace: "screen_px")
        let displayFrame = Geometry.intBox(from: selection.screen.frame, coordinateSpace: "macos_global")
        let display = DisplayGeometry(
            displayId: selection.screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")].map { "\($0)" } ?? "main",
            frame: displayFrame,
            scaleFactor: selection.screen.backingScaleFactor
        )
        let trigger = TriggerEnvelope(
            triggerId: "trg_\(UUID().uuidString.replacingOccurrences(of: "-", with: ""))",
            triggerType: "recording_keyframe",
            captureStrategy: "recording_region_keyframe",
            actor: actor,
            occurredAt: Date(),
            selection: selectedBox,
            intentText: nil,
            surfaceId: sourceBinding.sourceRef.externalId,
            deviceId: Host.current().localizedName,
            metadata: [
                "capture_shell": .string("macos_appkit"),
                "capture_mode": .string("recording_keyframe"),
                "source_confidence": .double(sourceBinding.confidence),
            ]
        )
        return CaptureDraft(
            stagedFile: stagedFile,
            screen: selection.screen,
            sourceBinding: sourceBinding,
            windowHints: windowResolver.resolveWindowHints(selectionScreenRect: selection.screenRect),
            selectionGeometry: SelectionGeometry(
                selectedRegion: selectedBox,
                display: display,
                pixelRegion: pixelBox
            ),
            trigger: trigger,
            actor: actor,
            sourceTitle: sourceBinding.sourceRef.title,
            nativeTimingReceipt: nil
        )
    }

    func showAnchorOverlay(for selection: SelectionResult) {
        showAnchorOverlay(screen: selection.screen, selection: selection.screenRect)
    }

    func showAnchorOverlay(screen: NSScreen, selection: CGRect) {
        retireWindow(anchorOverlay)
        let panelSize = CGSize(width: min(548, max(476, screen.visibleFrame.width - 36)), height: 306)
        let placement = Geometry.recordingOverlayPlacement(
            anchor: selection,
            panelSize: panelSize,
            visibleFrame: screen.visibleFrame
        )
        anchorOverlay = CaptureAnchorOverlayWindow(
            screen: screen,
            selection: selection,
            associationEdge: placement.edge
        )
    }

    func parseE2ERect(_ rawValue: String) -> CGRect? {
        let parts = rawValue.split(separator: ",").compactMap { Double($0.trimmingCharacters(in: .whitespaces)) }
        guard parts.count == 4, parts[2] > 0, parts[3] > 0 else { return nil }
        return CGRect(x: parts[0], y: parts[1], width: parts[2], height: parts[3])
    }

    func screenForE2ERect(_ requested: CGRect) -> NSScreen? {
        NSScreen.screens.max { first, second in
            rectArea(first.frame.intersection(requested)) < rectArea(second.frame.intersection(requested))
        }
    }

    func clippedE2ERect(_ requested: CGRect, to screen: NSScreen) -> CGRect? {
        let clipped = requested.intersection(screen.frame)
        guard !clipped.isNull, clipped.width > 0, clipped.height > 0 else { return nil }
        return clipped
    }

    private func rectArea(_ rect: CGRect) -> CGFloat {
        guard !rect.isNull, rect.width > 0, rect.height > 0 else { return 0 }
        return rect.width * rect.height
    }

    func retireWindow(_ window: NSWindow?) {
        guard let window else { return }
        retireWindows([window])
    }

    func retireWindows(_ windows: [NSWindow]) {
        guard !windows.isEmpty else { return }
        windows.forEach { $0.orderOut(nil) }
        retiredHUDWindows.append(contentsOf: windows)
        if retiredHUDWindows.count > 18 {
            retiredHUDWindows.removeFirst(retiredHUDWindows.count - 18)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self] in
            self?.trimRetiredHUDWindows()
        }
    }

    func trimRetiredHUDWindows() {
        guard retiredHUDWindows.count > 6 else { return }
        retiredHUDWindows.removeFirst(retiredHUDWindows.count - 6)
    }

    func openScreenRecordingSettings() {
        guard let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture") else {
            return
        }
        NSWorkspace.shared.open(url)
    }

    func transition(to newState: State, reason: String) {
        state = newState
        log("录制状态：\(newState.label) · \(reason)")
        notifyStateChanged()
    }

    func notifyStateChanged() {
        onStateChanged?(state)
    }

    func log(_ message: String) {
        NSLog("WorkRecorder \(message)")
        logStore?.append(message)
    }
}
