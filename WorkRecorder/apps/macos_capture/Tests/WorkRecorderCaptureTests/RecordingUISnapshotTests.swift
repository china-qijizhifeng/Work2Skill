import AppKit
import Carbon
import Testing
@testable import WorkRecorderCapture

@MainActor
@Suite(.serialized)
struct RecordingUISnapshotTests {
    private struct RecordingSnapshotFacts {
        let name: String
        let width: Int
        let height: Int
        let uniqueSampleCount: Int
    }

    @Test func recordingUISurfacesRenderWithRealisticMockData() throws {
        let screen = try #require(NSScreen.main)
        let fixture = try RecordingUISnapshotFixture(screen: screen)
        defer { fixture.cleanup() }

        let snapshots = try Self.processSnapshots(fixture: fixture) + Self.completionAndPermissionSnapshots(fixture: fixture)

        #expect(snapshots.count == 22)
        for snapshot in snapshots {
            #expect(snapshot.width >= 42, "\(snapshot.name) width is too small")
            #expect(snapshot.height >= 40, "\(snapshot.name) height is too small")
            let minimumUniqueSamples = snapshot.name.contains("boundary") ? 2 : 6
            #expect(snapshot.uniqueSampleCount >= minimumUniqueSamples, "\(snapshot.name) looks blank or visually collapsed")
        }
    }

    private static func processSnapshots(fixture: RecordingUISnapshotFixture) throws -> [RecordingSnapshotFacts] {
        try [
            snapshot(name: "01-trigger-menu-recording-active", view: menuStatusSnapshotView()),
            snapshot(name: "02-region-preparation-chrome-docs", view: try fixture.preparationWindow(appName: "Chrome", title: "WorkRecorder API 文档").contentView),
            snapshot(name: "03-region-preparation-figma-prototype", view: try fixture.preparationWindow(appName: "Figma", title: "Recording HUD Prototype").contentView),
            snapshot(name: "04-countdown-three", view: try fixture.countdownWindow(value: "3").contentView),
            snapshot(name: "05-countdown-recording", view: try fixture.countdownWindow(value: "录制中").contentView),
            snapshot(name: "06-hud-recording", view: try fixture.hudWindow(
                mode: .recording, elapsedMilliseconds: 27_300, traceDegraded: false
            ).contentView),
            snapshot(name: "07-hud-paused", view: try fixture.hudWindow(
                mode: .paused, elapsedMilliseconds: 41_900, traceDegraded: false
            ).contentView),
            snapshot(name: "08-hud-input-trace-degraded", view: try fixture.hudWindow(
                mode: .recording, elapsedMilliseconds: 58_200, traceDegraded: true
            ).contentView),
            snapshot(name: "09-hud-user-marked", view: try fixture.hudWindow(
                mode: .recording,
                elapsedMilliseconds: 61_400,
                traceDegraded: false,
                transientStatus: "已标记"
            ).contentView),
            snapshot(name: "10-hud-finalizing", view: try fixture.hudWindow(
                mode: .stopping, elapsedMilliseconds: 73_100, traceDegraded: false
            ).contentView),
            snapshot(name: "11-boundary-recording", view: try fixture.boundaryWindow(paused: false).contentView),
            snapshot(name: "12-boundary-paused", view: try fixture.boundaryWindow(paused: true).contentView),
        ]
    }

    private static func completionAndPermissionSnapshots(
        fixture: RecordingUISnapshotFixture
    ) throws -> [RecordingSnapshotFacts] {
        try [
            snapshot(name: "13-completion-ready-to-save", view: try fixture.completionWindow(degraded: false, segments: fixture.completedSegments).contentView),
            snapshot(name: "14-completion-input-trace-degraded", view: try fixture.completionWindow(degraded: true, segments: fixture.completedSegments).contentView),
            snapshot(name: "15-completion-scope-needs-review", view: try fixture.completionWindow(
                degraded: false,
                segments: fixture.completedSegments,
                scopeNeedsReview: true
            ).contentView),
            snapshot(name: "16-completion-multi-segment", view: try fixture.completionWindow(degraded: false, segments: fixture.multiSegmentResults).contentView),
            snapshot(name: "17-completion-saving", view: try fixture.completionWindow(
                degraded: false,
                segments: fixture.completedSegments,
                submitting: true
            ).contentView),
            snapshot(name: "18-completion-save-failure", view: try fixture.completionWindow(
                degraded: false,
                segments: fixture.completedSegments,
                errorMessage: "保存录制失败：vault 临时不可用。请重试保存或先打开本地预览确认内容。"
            ).contentView),
            snapshot(name: "19-completion-missing-preview-frame", view: try fixture.completionWindow(degraded: false, segments: fixture.missingPreviewFrameSegments).contentView),
            snapshot(name: "20-discard-confirmation", view: try fixture.discardConfirmationWindow().contentView),
            snapshot(name: "21-region-preparation-accessibility-degraded", view: try fixture.preparationWindow(
                appName: "Chrome",
                title: "WorkRecorder API 文档",
                warning: .accessibilityDegraded
            ).contentView),
            snapshot(name: "22-recording-permission-screen-recording-denied", view: try fixture.permissionIssueWindow().contentView),
        ]
    }

    @Test func failedRecordingStartupClearsBlockingSessionState() throws {
        let screen = try #require(NSScreen.main)
        let fixture = try RecordingUISnapshotFixture(screen: screen)
        defer { fixture.cleanup() }
        let stagingDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("workrecorder-recording-cleanup-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: stagingDirectory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: stagingDirectory) }
        let coordinator = CaptureCoordinator(
            environment: CaptureEnvironment(
                daemonURL: URL(string: "http://127.0.0.1:8765")!,
                installSecret: "install-secret",
                nativeCaptureSecret: "native-secret",
                providerRegistrationSecret: "provider-secret",
                stagingDirectory: stagingDirectory
            )
        )
        coordinator.activeSessionId = UUID()
        coordinator.activeRecordingContext = fixture.runtimeContext
        coordinator.recordingControlInFlight = true
        coordinator.recordingInputTraceDegraded = true
        coordinator.recordingCountdownWindow = try fixture.countdownWindow(value: "2")
        coordinator.recordingHUDWindow = try fixture.hudWindow(
            mode: .preparing,
            elapsedMilliseconds: 0,
            traceDegraded: true
        )
        coordinator.recordingBoundaryWindow = try fixture.boundaryWindow(paused: false)

        coordinator.clearFailedRecordingStartup()

        #expect(coordinator.activeRecordingContext == nil)
        #expect(coordinator.activeRecordingSegment == nil)
        #expect(coordinator.recordingCountdownWindow == nil)
        #expect(coordinator.recordingHUDWindow == nil)
        #expect(coordinator.recordingBoundaryWindow == nil)
        #expect(coordinator.recordingControlInFlight == false)
        #expect(coordinator.recordingInputTraceDegraded == false)
        #expect(coordinator.hasRecordingSessionSurface == false)
    }

    @Test func closingDuringRecordingStartupClearsStartupState() throws {
        let stagingDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("workrecorder-recording-startup-cancel-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: stagingDirectory, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: stagingDirectory) }
        let coordinator = CaptureCoordinator(
            environment: CaptureEnvironment(
                daemonURL: URL(string: "http://127.0.0.1:8765")!,
                installSecret: "install-secret",
                nativeCaptureSecret: "native-secret",
                providerRegistrationSecret: "provider-secret",
                stagingDirectory: stagingDirectory
            )
        )
        let sessionId = UUID()
        coordinator.activeSessionId = sessionId
        coordinator.transition(to: .capturing(sessionId), reason: "test startup")
        coordinator.recordingStartupToken = UUID()
        coordinator.recordingStartupTask = Task { @MainActor in }

        #expect(coordinator.hasRecordingSessionSurface)
        coordinator.closeHUD()

        #expect(coordinator.recordingStartupTask == nil)
        #expect(coordinator.recordingStartupToken == nil)
        #expect(coordinator.recordingStartupBackendSessionId == nil)
        #expect(coordinator.activeSessionId == nil)
        #expect(coordinator.hasRecordingSessionSurface == false)
    }

    @Test func hudKeyboardShortcutsRequireVisibleConfirmationForStop() throws {
        let screen = try #require(NSScreen.main)
        let fixture = try RecordingUISnapshotFixture(screen: screen)
        defer { fixture.cleanup() }
        var pauseToggled = false
        var stopRequested = false
        let window = try #require(RecordingHUDWindow(
            anchor: fixture.selection.screenRect,
            screen: screen,
            onMark: {},
            onPauseToggle: { pauseToggled = true },
            onFinish: {},
            onStopRequest: { stopRequested = true }
        ))
        window.setMode(.recording)

        window.keyDown(with: try Self.keyEvent(keyCode: CaptureKeyCode.space, characters: " ", windowNumber: window.windowNumber))
        window.keyDown(with: try Self.keyEvent(keyCode: CaptureKeyCode.escape, characters: "\u{1b}", windowNumber: window.windowNumber))

        #expect(pauseToggled)
        #expect(stopRequested)
    }

    @Test func completionNoteSupportsCommandVPaste() throws {
        let screen = try #require(NSScreen.main)
        let fixture = try RecordingUISnapshotFixture(screen: screen)
        defer { fixture.cleanup() }
        var savedNote: String?
        let window = try fixture.completionWindow(
            degraded: false,
            segments: fixture.completedSegments,
            onSave: { savedNote = $0 }
        )
        defer { window.close() }
        window.makeKeyAndOrderFront(nil)
        window.focusNote()

        let pasteboard = NSPasteboard.general
        let originalPasteboardItems = pasteboard.pasteboardItems ?? []
        defer {
            pasteboard.clearContents()
            if !originalPasteboardItems.isEmpty {
                pasteboard.writeObjects(originalPasteboardItems)
            }
        }
        pasteboard.clearContents()
        pasteboard.setString("从剪贴板粘贴的录制备注", forType: .string)
        let paste = try Self.keyEvent(
            keyCode: UInt16(kVK_ANSI_V),
            characters: "v",
            modifiers: [.command],
            windowNumber: window.windowNumber
        )

        #expect(window.performKeyEquivalent(with: paste))
        window.keyDown(with: try Self.keyEvent(
            keyCode: CaptureKeyCode.return,
            characters: "\r",
            windowNumber: window.windowNumber
        ))
        #expect(savedNote == "从剪贴板粘贴的录制备注")
    }

    @Test func hudPlacementFallsBackToVisibleScreenEdgeForNearFullscreenSelection() throws {
        let screen = try #require(NSScreen.main)

        let frame = RecordingHUDWindow.placementFrame(anchor: screen.visibleFrame, screen: screen)

        #expect(screen.visibleFrame.contains(frame))
        #expect(frame.width > 0)
        #expect(frame.height > 0)
    }

    @Test func discardConfirmationReturnIsNonDestructive() throws {
        let screen = try #require(NSScreen.main)
        let fixture = try RecordingUISnapshotFixture(screen: screen)
        defer { fixture.cleanup() }
        var confirmed = false
        var cancelled = false
        let window = RecordingDiscardConfirmationWindow(
            anchor: fixture.selection.screenRect,
            screen: screen,
            onConfirm: { confirmed = true },
            onCancel: { cancelled = true }
        )

        window.keyDown(with: try Self.keyEvent(keyCode: CaptureKeyCode.return, characters: "\r", windowNumber: window.windowNumber))

        #expect(!confirmed)
        #expect(cancelled)
    }

    @Test func activeRecordingBlocksApplicationTerminationWithoutDeletingState() throws {
        let screen = try #require(NSScreen.main)
        let fixture = try RecordingUISnapshotFixture(screen: screen)
        defer { fixture.cleanup() }
        let coordinator = CaptureCoordinator(
            environment: CaptureEnvironment(
                daemonURL: URL(string: "http://127.0.0.1:8765")!,
                installSecret: "install-secret",
                nativeCaptureSecret: "native-secret",
                providerRegistrationSecret: "provider-secret",
                stagingDirectory: FileManager.default.temporaryDirectory
            )
        )
        coordinator.activeRecordingContext = fixture.runtimeContext

        #expect(coordinator.blockApplicationTerminationForRecordingIfNeeded())
        #expect(coordinator.activeRecordingContext != nil)
        #expect(coordinator.pendingRecordingCompletion == nil)
    }

    @Test func recordingStartupErrorCopySeparatesBackendAndScreenRecordingPermission() {
        let coordinator = CaptureCoordinator(
            environment: CaptureEnvironment(
                daemonURL: URL(string: "http://127.0.0.1:8765")!,
                installSecret: "install-secret",
                nativeCaptureSecret: "native-secret",
                providerRegistrationSecret: "provider-secret",
                stagingDirectory: FileManager.default.temporaryDirectory
            )
        )

        let backendMessage = coordinator.userFacingRecordingError(CaptureTransportError.invalidResponse)
        #expect(backendMessage.contains("daemon"))
        #expect(!backendMessage.contains("屏幕录制权限"))

        let cleanupMessage = coordinator.userFacingRecordingError(
            CaptureTransportError.invalidResponse,
            cleanupWarning: "后端录制会话清理失败，请在诊断页重试或复制日志。"
        )
        #expect(cleanupMessage.contains("清理失败"))
        #expect(!cleanupMessage.contains("屏幕录制权限"))

        let permissionMessage = coordinator.userFacingRecordingError(
            RegionRecordingFailure.screenCapturePermissionDenied("未授权屏幕录制")
        )
        #expect(permissionMessage.contains("屏幕录制权限"))
    }

    private static func snapshot(name: String, view: NSView?) throws -> RecordingSnapshotFacts {
        let view = try #require(view)
        view.layoutSubtreeIfNeeded()
        let image = try image(for: view)
        try writeSnapshotIfRequested(image, name: name)
        return try facts(name: name, image: image)
    }

    private static func image(for view: NSView) throws -> NSImage {
        let bounds = view.bounds
        #expect(bounds.width > 0)
        #expect(bounds.height > 0)
        let rep = try #require(view.bitmapImageRepForCachingDisplay(in: bounds))
        view.cacheDisplay(in: bounds, to: rep)
        let image = NSImage(size: bounds.size)
        image.lockFocus()
        NSColor(calibratedRed: 0.955, green: 0.985, blue: 0.99, alpha: 1).setFill()
        NSBezierPath(rect: bounds).fill()
        rep.draw(in: bounds)
        image.unlockFocus()
        return image
    }

    private static func facts(name: String, image: NSImage) throws -> RecordingSnapshotFacts {
        let data = try #require(image.tiffRepresentation)
        let bitmap = try #require(NSBitmapImageRep(data: data))
        var samples = Set<UInt32>()
        let stepX = max(1, bitmap.pixelsWide / 120)
        let stepY = max(1, bitmap.pixelsHigh / 120)
        for y in stride(from: 0, to: bitmap.pixelsHigh, by: stepY) {
            for x in stride(from: 0, to: bitmap.pixelsWide, by: stepX) {
                samples.insert((bitmap.colorAt(x: x, y: y) ?? .clear).sampleKey)
            }
        }
        return RecordingSnapshotFacts(
            name: name,
            width: bitmap.pixelsWide,
            height: bitmap.pixelsHigh,
            uniqueSampleCount: samples.count
        )
    }

    private static func writeSnapshotIfRequested(_ image: NSImage, name: String) throws {
        guard ProcessInfo.processInfo.environment["WORKRECORDER_WRITE_RECORDING_UI_SNAPSHOTS"] == "1" else {
            return
        }
        let root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
            .appendingPathComponent("../../.qa/recording-ui", isDirectory: true)
            .standardizedFileURL
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try image.writePNG(to: root.appendingPathComponent("\(name).png"))
    }

    private static func keyEvent(
        keyCode: UInt16,
        characters: String,
        modifiers: NSEvent.ModifierFlags = [],
        windowNumber: Int
    ) throws -> NSEvent {
        try #require(
            NSEvent.keyEvent(
                with: .keyDown,
                location: .zero,
                modifierFlags: modifiers,
                timestamp: 0,
                windowNumber: windowNumber,
                context: nil,
                characters: characters,
                charactersIgnoringModifiers: characters,
                isARepeat: false,
                keyCode: keyCode
            )
        )
    }

    private static func menuStatusSnapshotView() -> NSView {
        let presentation = RecordingMenuPresentation(
            status: .recording,
            statusTitle: "正在录制",
            statusDetail: "边界与 HUD 已显示 · 00:12",
            pauseToggleTitle: "暂停录制",
            canFocusControls: true,
            canTogglePause: true,
            canFinish: true,
            showsRecordingBadge: true
        )
        let view = NSStackView()
        view.orientation = .vertical
        view.alignment = .leading
        view.spacing = 8
        view.edgeInsets = NSEdgeInsets(top: 14, left: 18, bottom: 14, right: 24)
        view.frame = CGRect(x: 0, y: 0, width: 336, height: 132)
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor(calibratedRed: 0.96, green: 0.985, blue: 0.99, alpha: 1).cgColor
        view.layer?.borderColor = NSColor(calibratedRed: 0.70, green: 0.89, blue: 0.93, alpha: 0.9).cgColor
        view.layer?.borderWidth = 1
        view.layer?.cornerRadius = 18

        let title = NSTextField(labelWithString: presentation.statusTitle)
        title.font = NSFont.systemFont(ofSize: 14.5, weight: .semibold)
        title.textColor = WorkRecorderTheme.primaryText
        let detail = NSTextField(labelWithString: presentation.statusDetail ?? "")
        detail.font = WorkRecorderTheme.Font.metadata
        detail.textColor = WorkRecorderTheme.secondaryText
        let row = NSStackView()
        row.orientation = .horizontal
        row.spacing = 6
        row.addArrangedSubview(WorkRecorderPillButton(title: "显示控制条", variant: .secondary, target: nil, action: nil))
        row.addArrangedSubview(WorkRecorderPillButton(title: presentation.pauseToggleTitle, variant: .secondary, target: nil, action: nil))
        row.addArrangedSubview(WorkRecorderPillButton(title: "结束录制", variant: .primary, target: nil, action: nil))
        view.addArrangedSubview(title)
        view.addArrangedSubview(detail)
        view.addArrangedSubview(row)
        return view
    }
}

@MainActor
private final class RecordingUISnapshotFixture {
    let screen: NSScreen
    let selection: SelectionResult
    let sourceBinding: SourceBinding
    let recordingScope: ActiveCaptureRecordingScope
    let runtimeContext: RecordingRuntimeContext
    let completedSegments: [RecordingSegmentCaptureResult]
    let multiSegmentResults: [RecordingSegmentCaptureResult]
    let missingPreviewFrameSegments: [RecordingSegmentCaptureResult]
    private let root: URL

    init(screen: NSScreen) throws {
        self.screen = screen
        root = FileManager.default.temporaryDirectory
            .appendingPathComponent("workrecorder-recording-ui-snapshots-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let region = screen.visibleFrame.insetBy(dx: max(80, screen.visibleFrame.width * 0.18), dy: max(80, screen.visibleFrame.height * 0.20))
        selection = SelectionResult(
            screen: screen,
            screenRect: region,
            captureRect: Geometry.screencaptureRect(from: region, on: screen)
        )
        sourceBinding = SourceBinding(
            bindingId: "src_recording_ui_review",
            sourceRef: SourceRef(
                sourceType: "desktop_region",
                title: "WorkRecorder API 文档",
                appName: "Chrome",
                url: nil,
                origin: nil,
                connectorName: "macos_region_recording",
                externalId: "recording-ui-review",
                version: nil
            ),
            confidence: 0.91,
            resolvedAt: Date(timeIntervalSince1970: 1_780_000_000)
        )
        recordingScope = ActiveCaptureRecordingScope(
            kind: .region,
            displayId: screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")].map { "\($0)" },
            scaleFactor: Double(screen.backingScaleFactor),
            windowId: "93214",
            processId: 4421,
            bundleId: "com.google.Chrome",
            appName: "Chrome",
            title: "WorkRecorder API 文档",
            bounds: Geometry.intBox(from: region, coordinateSpace: "macos_global"),
            selectionRegion: Geometry.intBox(from: region, coordinateSpace: "macos_global"),
            scopeConfidence: 0.91,
            occlusionEstimate: 0.04,
            metadata: [
                "review_fixture": .bool(true),
                "mock_data_kind": .string("recording_ui"),
            ]
        )
        let segmentOne = try Self.segment(
            root: root,
            index: 1,
            durationMilliseconds: 18_400,
            frameCount: 548,
            closeReason: .stopped,
            title: "开始录制"
        )
        let segmentTwo = try Self.segment(
            root: root,
            index: 2,
            durationMilliseconds: 9_700,
            frameCount: 286,
            closeReason: .paused,
            title: "暂停前"
        )
        let segmentThree = try Self.segment(
            root: root,
            index: 3,
            durationMilliseconds: 12_200,
            frameCount: 354,
            closeReason: .stopped,
            title: "继续后"
        )
        completedSegments = [segmentOne]
        multiSegmentResults = [segmentOne, segmentTwo, segmentThree]
        missingPreviewFrameSegments = [try Self.segmentWithoutPreviewFrame(
            root: root,
            index: 4,
            durationMilliseconds: 7_600,
            frameCount: 211,
            closeReason: .stopped
        )]
        runtimeContext = RecordingRuntimeContext(
            sessionId: "acs_recording_ui_review",
            selection: selection,
            sourceBinding: sourceBinding,
            scope: recordingScope,
            startedAtMonotonicMilliseconds: 3_000_000,
            currentSegmentId: "rseg_snapshot_1",
            completedSegments: completedSegments
        )
    }

    func cleanup() {
        try? FileManager.default.removeItem(at: root)
    }

    func preparationWindow(
        appName: String,
        title: String,
        warning: RecordingPreparationWarning? = nil
    ) throws -> RecordingPreparationWindow {
        RecordingPreparationWindow(
            anchor: selection.screenRect,
            screen: screen,
            sourceBinding: binding(appName: appName, title: title),
            warning: warning,
            onStart: {},
            onReselect: {},
            onCancel: {}
        )
    }

    func countdownWindow(value: String) throws -> RecordingCountdownWindow {
        let window = RecordingCountdownWindow(anchor: selection.screenRect, screen: screen)
        window.setValue(value)
        return window
    }

    func hudWindow(
        mode: RecordingHUDMode,
        elapsedMilliseconds: Int,
        traceDegraded: Bool,
        transientStatus: String? = nil
    ) throws -> RecordingHUDWindow {
        let window = try #require(RecordingHUDWindow(
            anchor: selection.screenRect,
            screen: screen,
            onMark: {},
            onPauseToggle: {},
            onFinish: {},
            onStopRequest: {}
        ))
        window.setTraceDegraded(traceDegraded)
        switch mode {
        case .preparing:
            window.setMode(.preparing)
        case .recording:
            window.update(elapsedMilliseconds: elapsedMilliseconds, paused: false)
        case .paused:
            window.update(elapsedMilliseconds: elapsedMilliseconds, paused: true)
        case .stopping:
            window.update(elapsedMilliseconds: elapsedMilliseconds, paused: false)
            window.setMode(.stopping)
        }
        if let transientStatus {
            window.showTransientStatus(transientStatus)
        }
        return window
    }

    func boundaryWindow(paused: Bool) throws -> RecordingBoundaryOverlayWindow {
        let window = RecordingBoundaryOverlayWindow(screen: screen, selection: selection.screenRect)
        window.setPaused(paused)
        return window
    }

    func completionWindow(
        degraded: Bool,
        segments: [RecordingSegmentCaptureResult],
        scopeNeedsReview: Bool = false,
        submitting: Bool = false,
        errorMessage: String? = nil,
        onSave: @escaping (String) -> Void = { _ in }
    ) throws -> RecordingCompletionWindow {
        let window = RecordingCompletionWindow(
            draft: RecordingCompletionDraft(
                sessionId: "acs_recording_ui_review",
                selection: selection,
                scope: recordingScope,
                sourceBinding: sourceBinding,
                segments: segments,
                startedAtMonotonicMilliseconds: 3_000_000,
                endedAtMonotonicMilliseconds: 3_000_000 + segments.reduce(0) { $0 + $1.durationMilliseconds },
                finalKeyframeEventId: "evt_recording_final",
                inputTraceDegraded: degraded,
                scopeNeedsReview: scopeNeedsReview
            ),
            screen: screen,
            onSave: onSave,
            onDiscard: {},
            onPreview: {}
        )
        window.setSubmitting(submitting)
        window.setErrorMessage(errorMessage)
        return window
    }

    func discardConfirmationWindow() throws -> RecordingDiscardConfirmationWindow {
        RecordingDiscardConfirmationWindow(anchor: selection.screenRect, screen: screen, onConfirm: {}, onCancel: {})
    }

    func permissionIssueWindow() throws -> RecordingPermissionIssueWindow {
        RecordingPermissionIssueWindow(
            anchor: selection.screenRect,
            screen: screen,
            issue: RecordingPermissionIssue(
                kind: .screenRecordingDenied,
                selectedRegionDescription: "\(Int(selection.screenRect.width.rounded())) × \(Int(selection.screenRect.height.rounded()))",
                sourceDescription: "Chrome · WorkRecorder API 文档",
                diagnostic: "未授权屏幕录制"
            ),
            onPrimaryAction: {},
            onDismiss: {}
        )
    }

    private func binding(appName: String, title: String) -> SourceBinding {
        SourceBinding(
            bindingId: "src_\(appName.lowercased())_review",
            sourceRef: SourceRef(
                sourceType: "desktop_region",
                title: title,
                appName: appName,
                url: nil,
                origin: nil,
                connectorName: "macos_region_recording",
                externalId: "mock-\(appName.lowercased())",
                version: nil
            ),
            confidence: 0.9,
            resolvedAt: Date(timeIntervalSince1970: 1_780_000_000)
        )
    }

    private static func segment(
        root: URL,
        index: Int,
        durationMilliseconds: Int,
        frameCount: Int,
        closeReason: ActiveCaptureRecordingSegmentCloseReason,
        title: String
    ) throws -> RecordingSegmentCaptureResult {
        let start = root.appendingPathComponent("segment-\(index)-start.png")
        let final = root.appendingPathComponent("segment-\(index)-final.png")
        let video = root.appendingPathComponent("segment-\(index).mp4")
        try previewImage(title: title, index: index).writePNG(to: start)
        try previewImage(title: "\(title)完成", index: index + 10).writePNG(to: final)
        try Data("mp4 fixture \(index)".utf8).write(to: video)
        let startMs = 3_000_000 + (index - 1) * 20_000
        return RecordingSegmentCaptureResult(
            segmentId: "rseg_snapshot_\(index)",
            videoURL: video,
            startFrameURL: start,
            finalFrameURL: final,
            durationMilliseconds: durationMilliseconds,
            containerDurationMilliseconds: durationMilliseconds,
            frameCount: frameCount,
            videoWidth: 1280,
            videoHeight: 720,
            startedMonotonicMilliseconds: startMs,
            firstFrameMonotonicMilliseconds: startMs + 42,
            firstFrameWallTimeEpochMilliseconds: 1_782_300_000_000 + startMs + 42,
            finalFrameMonotonicMilliseconds: startMs + durationMilliseconds - 42,
            endedMonotonicMilliseconds: startMs + durationMilliseconds,
            closeReason: closeReason
        )
    }

    private static func segmentWithoutPreviewFrame(
        root: URL,
        index: Int,
        durationMilliseconds: Int,
        frameCount: Int,
        closeReason: ActiveCaptureRecordingSegmentCloseReason
    ) throws -> RecordingSegmentCaptureResult {
        let start = root.appendingPathComponent("segment-\(index)-missing-start.png")
        let final = root.appendingPathComponent("segment-\(index)-missing-final.png")
        let video = root.appendingPathComponent("segment-\(index)-video-only.mp4")
        try Data("mp4 fixture without preview \(index)".utf8).write(to: video)
        let startMs = 3_000_000 + (index - 1) * 20_000
        return RecordingSegmentCaptureResult(
            segmentId: "rseg_snapshot_missing_preview_\(index)",
            videoURL: video,
            startFrameURL: start,
            finalFrameURL: final,
            durationMilliseconds: durationMilliseconds,
            containerDurationMilliseconds: durationMilliseconds,
            frameCount: frameCount,
            videoWidth: 1280,
            videoHeight: 720,
            startedMonotonicMilliseconds: startMs,
            firstFrameMonotonicMilliseconds: startMs + 42,
            firstFrameWallTimeEpochMilliseconds: 1_782_300_000_000 + startMs + 42,
            finalFrameMonotonicMilliseconds: startMs + durationMilliseconds - 42,
            endedMonotonicMilliseconds: startMs + durationMilliseconds,
            closeReason: closeReason
        )
    }

    private static func previewImage(title: String, index: Int) -> NSImage {
        let size = CGSize(width: 296, height: 192)
        let image = NSImage(size: size)
        image.lockFocus()
        let rect = CGRect(origin: .zero, size: size)
        NSColor(calibratedRed: 0.91, green: 0.98, blue: 0.99, alpha: 1).setFill()
        NSBezierPath(rect: rect).fill()
        NSColor(calibratedRed: 0.09, green: 0.25, blue: 0.30, alpha: 0.86).setFill()
        NSBezierPath(roundedRect: rect.insetBy(dx: 16, dy: 18), xRadius: 16, yRadius: 16).fill()
        NSColor(calibratedRed: 0.35 + CGFloat(index % 4) * 0.08, green: 0.83, blue: 0.88, alpha: 0.92).setFill()
        NSBezierPath(roundedRect: CGRect(x: 34, y: 118, width: 112, height: 20), xRadius: 10, yRadius: 10).fill()
        NSColor.white.withAlphaComponent(0.72).setFill()
        NSBezierPath(roundedRect: CGRect(x: 34, y: 76, width: 214, height: 13), xRadius: 6, yRadius: 6).fill()
        NSBezierPath(roundedRect: CGRect(x: 34, y: 52, width: 166, height: 13), xRadius: 6, yRadius: 6).fill()
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 15, weight: .semibold),
            .foregroundColor: NSColor.white,
        ]
        title.draw(at: CGPoint(x: 34, y: 144), withAttributes: attributes)
        image.unlockFocus()
        return image
    }
}
