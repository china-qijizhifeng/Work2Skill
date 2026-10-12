import AppKit
import ApplicationServices
import Foundation

private enum RecordingStartupStage {
    case creatingBackendSession
    case loadingSegmentManifest
    case preparingLocalChrome
    case startingVideoSegment
    case capturingStartKeyframe
    case startingInputProducer
}

enum RecordingE2EControlAction: String, CaseIterable {
    case mark
    case pause
    case resume
    case finish
}

struct RecordingE2EControlStep: Equatable {
    let action: RecordingE2EControlAction
    let delayMilliseconds: Int
}

struct RecordingE2EControlScript: Equatable {
    let steps: [RecordingE2EControlStep]

    static func parse(_ rawValue: String?) -> RecordingE2EControlScript? {
        guard let rawValue else { return nil }
        let chunks = rawValue
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        guard !chunks.isEmpty else { return nil }
        var steps: [RecordingE2EControlStep] = []
        for chunk in chunks {
            let parts = chunk.split(separator: ":", maxSplits: 1).map(String.init)
            guard parts.count == 2,
                  let action = RecordingE2EControlAction(rawValue: parts[0].trimmingCharacters(in: .whitespacesAndNewlines)),
                  let delay = Int(parts[1].trimmingCharacters(in: .whitespacesAndNewlines))
            else {
                return nil
            }
            steps.append(RecordingE2EControlStep(action: action, delayMilliseconds: max(0, min(delay, 60_000))))
        }
        return RecordingE2EControlScript(steps: steps.sorted { $0.delayMilliseconds < $1.delayMilliseconds })
    }
}

// MARK: - Region recording preparation and startup

extension CaptureCoordinator {
    func startRegionRecordingPreparation() {
        NSLog("WorkRecorder region recording requested")
        if hasRecordingSessionSurface {
            log("录制正在进行或待保存，已唤起录制控制。")
            focusRecordingControls()
            return
        }
        closeHUD()
        let sessionId = UUID()
        activeSessionId = sessionId
        transition(to: .selecting(sessionId), reason: "收到区域录制请求")
        armedSourceBinding = windowResolver.resolve()
        if startConfiguredE2ERecording(sessionId: sessionId) {
            NSLog("WorkRecorder E2E configured recording preparation started")
            return
        }
        overlayWindows = NSScreen.screens.map { screen in
            CaptureOverlayWindow(
                screen: screen,
                prompt: "WorkRecorder · 框选录制区域      Esc 取消      ⌃⌥⌘R 唤起控制",
                completion: { [weak self] selection in
                    self?.completeRecordingSelection(selection, sessionId: sessionId)
                },
                cancel: { [weak self] in self?.cancelCapture(sessionId: sessionId) }
            )
        }
        installSelectionEscapeMonitors(sessionId: sessionId)
    }

    func completeRecordingSelection(_ selection: SelectionResult, sessionId: UUID) {
        guard activeSessionId == sessionId else { return }
        let sourceBinding = windowResolver.resolve(selectionScreenRect: selection.screenRect)
        armedSourceBinding = nil
        closeOverlay()
        transition(to: .confirming(sessionId), reason: "录制选区完成，等待开始确认")
        showAnchorOverlay(for: selection)
        showRecordingPreparation(selection: selection, sourceBinding: sourceBinding, sessionId: sessionId)
    }

    private func showRecordingPreparation(
        selection: SelectionResult,
        sourceBinding: SourceBinding,
        sessionId: UUID
    ) {
        retireWindow(recordingPreparationWindow)
        let window = RecordingPreparationWindow(
            anchor: selection.screenRect,
            screen: selection.screen,
            sourceBinding: sourceBinding,
            warning: recordingPreparationWarning(for: sourceBinding),
            onStart: { [weak self] in
                self?.beginRecording(selection: selection, sourceBinding: sourceBinding, sessionId: sessionId)
            },
            onReselect: { [weak self] in
                guard self?.activeSessionId == sessionId else { return }
                self?.closeHUD()
                self?.startRegionRecordingPreparation()
            },
            onCancel: { [weak self] in
                self?.cancelCapture(sessionId: sessionId)
            }
        )
        recordingPreparationWindow = window
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
        autoStartConfiguredE2ERecordingIfNeeded(selection: selection, sourceBinding: sourceBinding, sessionId: sessionId)
    }

    private func beginRecording(selection: SelectionResult, sourceBinding: SourceBinding, sessionId: UUID) {
        guard activeSessionId == sessionId else { return }
        retireWindow(recordingPreparationWindow)
        recordingPreparationWindow = nil
        retireWindow(anchorOverlay)
        anchorOverlay = nil
        transition(to: .capturing(sessionId), reason: "创建录制会话")
        let scope = activeCaptureRecordingScope(scopeBounds: selection.screenRect)
        let startupToken = UUID()
        recordingStartupToken = startupToken
        recordingStartupTask?.cancel()
        recordingStartupTask = Task { @MainActor [weak self] in
            guard let self else { return }
            var backendSessionId: String?
            var startupStage = RecordingStartupStage.creatingBackendSession
            defer {
                if recordingStartupToken == startupToken {
                    recordingStartupTask = nil
                    recordingStartupToken = nil
                    recordingStartupBackendSessionId = nil
                    notifyStateChanged()
                }
            }
            do {
                let created = try await transport.createActiveCaptureSession(scope: scope)
                backendSessionId = created.session.sessionId
                setRecordingStartupBackendSessionId(created.session.sessionId, token: startupToken)
                if !recordingStartupIsCurrent(token: startupToken, sessionId: sessionId) {
                    _ = await cancelBackendSessionAfterRecordingStartupFailure(created.session.sessionId)
                    return
                }
                startupStage = .loadingSegmentManifest
                let manifest = try await transport.getRecordingSegmentManifest(sessionId: created.session.sessionId)
                if !recordingStartupIsCurrent(token: startupToken, sessionId: sessionId) {
                    _ = await cancelBackendSessionAfterRecordingStartupFailure(created.session.sessionId)
                    return
                }
                guard let initialSegment = manifest.segments.sorted(by: { $0.sequenceIndex < $1.sequenceIndex }).last else {
                    throw CaptureTransportError.invalidResponse
                }
                let context = RecordingRuntimeContext(
                    sessionId: created.session.sessionId,
                    selection: selection,
                    sourceBinding: sourceBinding,
                    scope: scope,
                    startedAtMonotonicMilliseconds: monotonicMilliseconds(),
                    currentSegmentId: initialSegment.segmentId,
                    completedSegments: []
                )
                activeRecordingContext = context
                recordingInputTraceDegraded = false
                recordingScopeNeedsReview = false
                recordingLastScopeHealthCheckMonotonicMilliseconds = 0
                notifyStateChanged()
                startupStage = .preparingLocalChrome
                try await playRecordingCountdown(selection: selection)
                guard recordingStartupIsCurrent(
                    token: startupToken, sessionId: sessionId, backendSessionId: created.session.sessionId
                ) else {
                    _ = await cancelBackendSessionAfterRecordingStartupFailure(created.session.sessionId)
                    return
                }
                showRecordingActiveChrome(selection: selection, sessionId: sessionId, mode: .preparing)
                startupStage = .startingVideoSegment
                let segment = try await startVideoSegment(segmentId: initialSegment.segmentId, selection: selection, scope: scope)
                activeRecordingSegment = segment
                recordingSessionController.activateRecording()
                syncRecordingControlFieldsFromSessionController()
                startupStage = .capturingStartKeyframe
                _ = try? await captureRecordingBoundaryKeyframe(
                    sessionId: created.session.sessionId,
                    triggerKind: .recordingStart,
                    role: .start,
                    selection: selection,
                    scope: scope
                )
                recordingHUDWindow?.setMode(.recording)
                startupStage = .startingInputProducer
                startActiveCaptureInputProducer(
                    sessionId: created.session.sessionId,
                    scopeBounds: selection.screenRect,
                    recordingScope: scope
                )
                transition(to: .recording(sessionId), reason: "录制已开始")
                log("区域录制已开始：\(created.session.sessionId)")
                if !scheduleConfiguredE2ERecordingControlsIfNeeded(sessionId: sessionId) {
                    scheduleConfiguredE2ERecordingFinishIfNeeded(sessionId: sessionId)
                }
            } catch is CancellationError {
                await handleRecordingStartupCancellation(backendSessionId: backendSessionId)
            } catch {
                clearFailedRecordingStartup()
                let cleanupWarning = await cancelBackendSessionAfterRecordingStartupFailure(backendSessionId)
                transition(to: .failed(sessionId, error.localizedDescription), reason: "录制启动失败")
                log("区域录制启动失败：\(error.localizedDescription)")
                if let issue = recordingPermissionIssue(
                    for: error,
                    startupStage: startupStage,
                    selection: selection,
                    sourceBinding: sourceBinding,
                    cleanupWarning: cleanupWarning
                ) {
                    showRecordingIssue(
                        issue,
                        selection: selection,
                        sessionId: sessionId
                    )
                } else {
                    showRecordingIssue(
                        RecordingPermissionIssue(
                            kind: .startupFailed(userFacingRecordingError(error, cleanupWarning: cleanupWarning)),
                            selectedRegionDescription: "\(Int(selection.screenRect.width.rounded())) × \(Int(selection.screenRect.height.rounded()))",
                            sourceDescription: recordingSourceDescription(sourceBinding),
                            diagnostic: combinedRecordingDiagnostic(error: error, cleanupWarning: cleanupWarning)
                        ),
                        selection: selection,
                        sessionId: sessionId
                    )
                }
            }
        }
    }

}

// MARK: - Deterministic E2E recording harness

extension CaptureCoordinator {
    func startConfiguredE2ERecording(sessionId: UUID) -> Bool {
        let environment = ProcessInfo.processInfo.environment
        guard environment["WORKRECORDER_E2E_RECORDING_ENABLED"] == "1" else {
            return false
        }
        guard let rawRect = environment["WORKRECORDER_E2E_RECORDING_RECT"] ?? environment["WORKRECORDER_E2E_CAPTURE_RECT"] else {
            NSLog("WorkRecorder E2E recording requested but WORKRECORDER_E2E_RECORDING_RECT is missing")
            return false
        }
        guard let requested = parseE2ERect(rawRect),
              let screen = screenForE2ERect(requested),
              let clipped = clippedE2ERect(requested, to: screen)
        else {
            NSLog("WorkRecorder E2E recording rect invalid or outside all screens raw=\(rawRect)")
            return false
        }
        let selection = SelectionResult(
            screen: screen,
            screenRect: clipped,
            captureRect: Geometry.screencaptureRect(from: clipped, on: screen)
        )
        completeRecordingSelection(selection, sessionId: sessionId)
        return true
    }

    private func autoStartConfiguredE2ERecordingIfNeeded(
        selection: SelectionResult,
        sourceBinding: SourceBinding,
        sessionId: UUID
    ) {
        guard ProcessInfo.processInfo.environment["WORKRECORDER_E2E_RECORDING_AUTO_START"] == "1" else {
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
            guard self?.activeSessionId == sessionId else { return }
            self?.beginRecording(selection: selection, sourceBinding: sourceBinding, sessionId: sessionId)
        }
    }

    private func scheduleConfiguredE2ERecordingFinishIfNeeded(sessionId: UUID) {
        let environment = ProcessInfo.processInfo.environment
        guard environment["WORKRECORDER_E2E_RECORDING_AUTO_FINISH"] == "1" else {
            return
        }
        let requestedMs = Int(environment["WORKRECORDER_E2E_RECORDING_DURATION_MS"] ?? "") ?? 3200
        let durationMs = max(800, min(requestedMs, 20_000))
        DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(durationMs)) { [weak self] in
            guard self?.activeSessionId == sessionId, self?.activeRecordingContext != nil else { return }
            self?.finishRecordingForReview()
        }
    }

    @discardableResult
    private func scheduleConfiguredE2ERecordingControlsIfNeeded(sessionId: UUID) -> Bool {
        guard let script = RecordingE2EControlScript.parse(
            ProcessInfo.processInfo.environment["WORKRECORDER_E2E_RECORDING_CONTROLS_SCRIPT"]
        ) else {
            return false
        }
        for step in script.steps {
            DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(step.delayMilliseconds)) { [weak self] in
                guard self?.activeSessionId == sessionId, self?.activeRecordingContext != nil else { return }
                self?.performConfiguredE2ERecordingControl(step.action)
            }
        }
        return true
    }

    private func performConfiguredE2ERecordingControl(_ action: RecordingE2EControlAction) {
        switch action {
        case .mark:
            markRecordingMoment()
        case .pause:
            guard case .recording = state else {
                log("E2E 录制控制跳过 pause：当前状态不是录制中。")
                return
            }
            toggleRecordingPause()
        case .resume:
            guard case .recordingPaused = state else {
                log("E2E 录制控制跳过 resume：当前状态不是暂停中。")
                return
            }
            toggleRecordingPause()
        case .finish:
            finishRecordingForReview()
        }
    }

}

// MARK: - Recording chrome, permissions, and local segment startup

extension CaptureCoordinator {
    func startVideoSegment(
        segmentId: String,
        selection: SelectionResult,
        scope: ActiveCaptureRecordingScope
    ) async throws -> ScreenCaptureKitRegionRecordingSegment {
        let outputDirectory = recordingOutputDirectory(sessionId: activeRecordingContext?.sessionId ?? segmentId)
        return try await regionRecorder.startSegment(
            segmentId: segmentId,
            target: RegionRecordingTarget(selection: selection, scope: scope, outputDirectory: outputDirectory)
        )
    }

    private func playRecordingCountdown(selection: SelectionResult) async throws {
        let reduceMotion = NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
        let window = RecordingCountdownWindow(
            anchor: selection.screenRect,
            screen: selection.screen,
            onCancel: { [weak self] in
                self?.closeHUD()
            }
        )
        recordingCountdownWindow = window
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
        let stepDelay: UInt64 = reduceMotion ? 260_000_000 : 420_000_000
        let finalDelay: UInt64 = reduceMotion ? 180_000_000 : 260_000_000
        for value in ["3", "2", "1"] {
            guard activeSessionId != nil else { break }
            window.setValue(value)
            try await Task.sleep(nanoseconds: stepDelay)
        }
        window.setValue("Recording")
        try await Task.sleep(nanoseconds: finalDelay)
        retireWindow(window)
        if recordingCountdownWindow === window {
            recordingCountdownWindow = nil
        }
    }

    private func showRecordingActiveChrome(
        selection: SelectionResult,
        sessionId: UUID,
        mode: RecordingHUDMode = .recording
    ) {
        retireWindow(recordingBoundaryWindow)
        retireWindow(recordingHUDWindow)
        let boundary = RecordingBoundaryOverlayWindow(screen: selection.screen, selection: selection.screenRect)
        let hud = RecordingHUDWindow(
            anchor: selection.screenRect,
            screen: selection.screen,
            onMark: { [weak self] in self?.markRecordingMoment() },
            onPauseToggle: { [weak self] in self?.toggleRecordingPause() },
            onFinish: { [weak self] in self?.finishRecordingForReview() },
            onStopRequest: { [weak self] in self?.confirmFinishRecordingForReview() }
        )
        recordingBoundaryWindow = boundary
        recordingHUDWindow = hud
        boundary.orderFrontRegardless()
        if let hud {
            hud.orderFrontRegardless()
            hud.setMode(mode)
            hud.setScopeNeedsReview(recordingScopeNeedsReview)
        } else {
            log("录制区域没有足够的外部空间显示 HUD；已保留菜单栏控制，避免遮挡录制内容。")
        }
        startRecordingHUDTimer(sessionId: sessionId)
    }

    private func startRecordingHUDTimer(sessionId: UUID) {
        recordingHUDTimer?.invalidate()
        recordingHUDTimer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.activeSessionId == sessionId else { return }
                self.refreshRecordingHUD()
            }
        }
        refreshRecordingHUD()
    }

    func refreshRecordingHUD() {
        guard let context = activeRecordingContext else { return }
        let now = monotonicMilliseconds()
        refreshRecordingScopeHealth(context: context, nowMonotonicMilliseconds: now)
        let pausedDelta = recordingPausedAtMonotonicMilliseconds.map { now - $0 } ?? 0
        let elapsed = now - context.startedAtMonotonicMilliseconds - recordingPausedAccumulatedMilliseconds - pausedDelta
        recordingHUDWindow?.update(elapsedMilliseconds: elapsed, paused: recordingPausedAtMonotonicMilliseconds != nil)
    }

    func focusRecordingControls() {
        if let hud = recordingHUDWindow {
            hud.makeKeyAndOrderFront(nil)
            hud.orderFrontRegardless()
        } else if let completion = recordingCompletionWindow {
            completion.makeKeyAndOrderFront(nil)
            completion.orderFrontRegardless()
        } else if let issue = recordingPermissionIssueWindow {
            issue.makeKeyAndOrderFront(nil)
            issue.orderFrontRegardless()
        }
    }

    func recordingOutputDirectory(sessionId: String) -> URL {
        environment.stagingDirectory
            .appendingPathComponent("recordings", isDirectory: true)
            .appendingPathComponent(sessionId, isDirectory: true)
    }

    private func recordingPreparationWarning(for sourceBinding: SourceBinding) -> RecordingPreparationWarning? {
        if !AXIsProcessTrusted() {
            return .accessibilityDegraded
        }
        if sourceBinding.confidence < 0.45 {
            return .lowSourceConfidence
        }
        return nil
    }

    private func recordingPermissionIssue(
        for error: Error,
        startupStage: RecordingStartupStage,
        selection: SelectionResult,
        sourceBinding: SourceBinding,
        cleanupWarning: String?
    ) -> RecordingPermissionIssue? {
        guard startupStage == .startingVideoSegment, isScreenRecordingPermissionFailure(error) else { return nil }
        return RecordingPermissionIssue(
            kind: .screenRecordingDenied,
            selectedRegionDescription: "\(Int(selection.screenRect.width.rounded())) × \(Int(selection.screenRect.height.rounded()))",
            sourceDescription: recordingSourceDescription(sourceBinding),
            diagnostic: combinedRecordingDiagnostic(error: error, cleanupWarning: cleanupWarning)
        )
    }

    private func combinedRecordingDiagnostic(error: Error, cleanupWarning: String?) -> String? {
        var parts: [String] = []
        if case RegionRecordingFailure.screenCapturePermissionDenied(let message) = error {
            parts.append(message)
        }
        if let cleanupWarning {
            parts.append(cleanupWarning)
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private func recordingSourceDescription(_ sourceBinding: SourceBinding) -> String? {
        let source = [sourceBinding.sourceRef.appName, sourceBinding.sourceRef.title]
            .compactMap { value -> String? in
                let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines)
                return trimmed?.isEmpty == false ? trimmed : nil
            }
            .joined(separator: " · ")
        return source.isEmpty ? nil : source
    }

    func cancelBackendSessionAfterRecordingStartupFailure(_ backendSessionId: String?) async -> String? {
        guard let backendSessionId else { return nil }
        do {
            _ = try await transport.cancelActiveCaptureSession(
                sessionId: backendSessionId,
                reason: "native_recording_start_failed"
            )
            return nil
        } catch {
            let warning = "录制会话清理失败，请稍后重试。"
            log("\(warning) session=\(backendSessionId) error=\(error.localizedDescription)")
            return warning
        }
    }

    func showRecordingIssue(
        _ issue: RecordingPermissionIssue,
        selection: SelectionResult,
        sessionId: UUID
    ) {
        retireWindow(recordingPermissionIssueWindow)
        let window = RecordingPermissionIssueWindow(
            anchor: selection.screenRect,
            screen: selection.screen,
            issue: issue,
            onPrimaryAction: { [weak self] in
                if issue.kind.opensSystemSettings {
                    self?.openScreenRecordingSettings()
                }
                self?.cancelCapture(sessionId: sessionId)
            },
            onDismiss: { [weak self] in
                self?.cancelCapture(sessionId: sessionId)
            }
        )
        recordingPermissionIssueWindow = window
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
    }
}
