import AppKit
import CoreGraphics
import Foundation

extension CaptureCoordinator {
    func startActiveCaptureInputProducer(
        sessionId: String,
        scopeBounds: CGRect,
        recordingScope: ActiveCaptureRecordingScope? = nil
    ) {
        stopActiveCaptureInputProducer()
        let producer = ActiveCaptureInputEventProducer(
            sessionId: sessionId,
            transport: transport,
            recordFullKeystrokes: ActiveCaptureFullKeystrokePreference.isEnabled(),
            scopeBounds: scopeBounds,
            recordingScope: recordingScope ?? activeCaptureRecordingScope(scopeBounds: scopeBounds),
            settleProbeProvider: { [weak self] in
                await self?.activeCaptureSettleProbeSnapshot(scopeBounds: scopeBounds)
            },
            captureInstructionHandler: { [weak self] instruction in
                Task { @MainActor [weak self] in
                    self?.captureActiveCaptureInstruction(instruction, scopeBounds: scopeBounds)
                }
            },
            diagnosticHandler: { [weak self] message in
                Task { @MainActor [weak self] in
                    self?.markRecordingInputTraceDegraded(message: message)
                }
            }
        )
        do {
            try producer.start()
            activeCaptureInputProducer = producer
            log("Active Capture 输入 producer 已启动：\(sessionId)")
        } catch {
            markRecordingInputTraceDegraded(message: "Active Capture 输入 producer 启动失败：\(error.localizedDescription)")
        }
    }

    func stopActiveCaptureInputProducer(
        flushPendingAggregates: Bool = true,
        cancelPendingCaptureInstructions: Bool = true
    ) {
        activeCaptureInputProducer?.stop(
            flushPendingAggregates: flushPendingAggregates,
            cancelPendingCaptureInstructions: cancelPendingCaptureInstructions
        )
        activeCaptureInputProducer = nil
    }

    func stopAndDrainActiveCaptureInputProducer(
        flushPendingAggregates: Bool = true,
        cancelPendingCaptureInstructions: Bool = true
    ) async {
        guard let producer = activeCaptureInputProducer else { return }
        producer.stop(
            flushPendingAggregates: flushPendingAggregates,
            cancelPendingCaptureInstructions: cancelPendingCaptureInstructions
        )
        activeCaptureInputProducer = nil
        await producer.waitForPendingSubmissions()
    }

    func markRecordingInputTraceDegraded(message: String) {
        recordingInputTraceDegraded = true
        recordingHUDWindow?.setTraceDegraded(true)
        log(message)
    }

    private func captureActiveCaptureInstruction(
        _ instruction: ActiveCaptureCaptureInstruction,
        scopeBounds: CGRect
    ) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            guard self.shouldCaptureActiveCaptureInstruction(instruction) else {
                self.log("Active Capture keyframe 跳过：录制已结束或会话不匹配。")
                await self.reportActiveCaptureInstructionFailure(
                    instruction,
                    reason: "scope_lost",
                    diagnostic: "native_capture_instruction_skipped_session_inactive"
                )
                return
            }
            do {
                let result = try await self.captureActiveCaptureInstructionNow(instruction, scopeBounds: scopeBounds)
                self.onCaptureSaved?(result.eventId)
                self.log("Active Capture keyframe 已保存：\(instruction.candidateId)")
            } catch {
                self.log("Active Capture keyframe 保存失败：\(error.localizedDescription)")
                await self.reportActiveCaptureInstructionFailure(
                    instruction,
                    reason: "invalid_evidence",
                    diagnostic: "native_capture_instruction_failed"
                )
            }
        }
    }

    private func shouldCaptureActiveCaptureInstruction(_ instruction: ActiveCaptureCaptureInstruction) -> Bool {
        if let pending = pendingRecordingCompletion, pending.sessionId == instruction.sessionId {
            return recordingCompletionCaptureDrainAllowed && !recordingCompletionSubmitting
        }
        if activeRecordingContext?.sessionId == instruction.sessionId {
            return true
        }
        if recordingStartupBackendSessionId == instruction.sessionId {
            return true
        }
        return false
    }

    func reportActiveCaptureInstructionFailure(
        _ instruction: ActiveCaptureCaptureInstruction,
        reason: String,
        diagnostic: String
    ) async {
        do {
            try await transport.reportCaptureInstructionFailure(
                sessionId: instruction.sessionId,
                candidateId: instruction.candidateId,
                reason: reason,
                diagnostic: diagnostic
            )
        } catch {
            log("Active Capture keyframe failure ack 未写入：\(error.localizedDescription)")
        }
    }

    func activeCaptureSettleProbeSnapshot(scopeBounds: CGRect) async -> ActiveCaptureSettleProbeSnapshot? {
        guard let screen = screenForE2ERect(scopeBounds),
              let selection = clippedE2ERect(probeSamplingBounds(for: scopeBounds), to: screen)
        else {
            return nil
        }
        do {
            let probe = try await screenCapture.probeRegionFingerprint(selection, on: screen)
            return ActiveCaptureSettleProbeSnapshot(
                sampleId: "kfs_native_\(UUID().uuidString.replacingOccurrences(of: "-", with: ""))",
                sampledAtMonotonicMs: monotonicMilliseconds(),
                visual: ActiveCaptureVisualDiffSummary(
                    mode: .hybrid,
                    sampleFingerprint: probe.sampleFingerprint,
                    diagnostics: [
                        "native_visual_probe_16x16",
                        "sampled_pixels_\(probe.sampledPixelCount)",
                    ]
                ),
                diagnostics: ["native visual probe sampled recording scope"],
                metadata: ["probe_source": .string("macos_cgdisplay_in_memory")]
            )
        } catch {
            markRecordingInputTraceDegraded(message: "Active Capture 稳定性采样降级：\(error.localizedDescription)")
            return nil
        }
    }

    private func probeSamplingBounds(for scopeBounds: CGRect) -> CGRect {
        let inset = min(6, max(0, min(scopeBounds.width, scopeBounds.height) / 12))
        guard inset > 0 else { return scopeBounds }
        let candidate = scopeBounds.insetBy(dx: inset, dy: inset)
        guard candidate.width >= 8, candidate.height >= 8 else { return scopeBounds }
        return candidate
    }

    func drainPendingActiveCaptureInstructionsForReview(
        sessionId: String,
        scopeBounds: CGRect,
        maxAttempts: Int = 4
    ) async {
        var capturedKeys = Set<String>()
        for attempt in 0..<maxAttempts {
            if attempt > 0 {
                try? await Task.sleep(nanoseconds: 300_000_000)
            }
            guard activeRecordingContext?.sessionId == sessionId || pendingRecordingCompletion?.sessionId == sessionId else {
                return
            }
            do {
                let initial = try await transport.pollPendingCaptureInstructions(
                    sessionId: sessionId,
                    probeSnapshot: nil,
                    allowDegradedSample: attempt >= maxAttempts - 1
                )
                var instructions = initial.captureInstructions
                if initial.probeRequiredCandidateCount > 0 {
                    let probe = await activeCaptureSettleProbeSnapshot(scopeBounds: scopeBounds)
                    let probed = try await transport.pollPendingCaptureInstructions(
                        sessionId: sessionId,
                        probeSnapshot: probe,
                        allowDegradedSample: true
                    )
                    instructions.append(contentsOf: probed.captureInstructions)
                }
                var didCapture = false
                for instruction in instructions {
                    let key = instruction.binding.metadata.stringValue(for: "settle_capture_claim_id")
                        ?? instruction.candidateId
                    guard capturedKeys.insert(key).inserted else { continue }
                    guard shouldCaptureActiveCaptureInstruction(instruction) else {
                        await reportActiveCaptureInstructionFailure(
                            instruction,
                            reason: "scope_lost",
                            diagnostic: "native_finish_drain_skipped_session_inactive"
                        )
                        continue
                    }
                    do {
                        _ = try await captureActiveCaptureInstructionNow(instruction, scopeBounds: scopeBounds)
                        log("完成录制前已补收关键帧：\(instruction.candidateId)")
                        didCapture = true
                    } catch {
                        await reportActiveCaptureInstructionFailure(
                            instruction,
                            reason: "invalid_evidence",
                            diagnostic: "native_finish_drain_capture_failed"
                        )
                        log("完成录制前补收关键帧失败：\(error.localizedDescription)")
                    }
                }
                if !didCapture && initial.observedCandidateCount == 0 {
                    return
                }
            } catch {
                log("完成录制前轮询关键帧失败：\(error.localizedDescription)")
                return
            }
        }
    }

    func captureActiveCaptureInstructionNow(
        _ instruction: ActiveCaptureCaptureInstruction,
        scopeBounds: CGRect
    ) async throws -> CaptureSaveResult {
        let now = monotonicMilliseconds()
        let shouldSuppressChrome = RecordingChromeCapturePolicy().shouldSuppressChrome(
            for: instruction,
            nowMonotonicMilliseconds: now,
            lastSuppressedAtMonotonicMilliseconds: lastRecordingChromeSuppressionMonotonicMilliseconds
        )
        let hiddenChrome = shouldSuppressChrome ? hideRecordingChromeForKeyframeCapture() : nil
        if shouldSuppressChrome {
            lastRecordingChromeSuppressionMonotonicMilliseconds = now
        }
        defer {
            if let hiddenChrome {
                restoreRecordingChromeAfterKeyframeCapture(hiddenChrome)
            }
        }
        if hiddenChrome?.didHideChrome == true {
            try await Task.sleep(nanoseconds: 80_000_000)
        }
        guard let screen = screenForE2ERect(scopeBounds),
              let selection = clippedE2ERect(scopeBounds, to: screen)
        else {
            throw CaptureTransportError.unsupported("录制关键帧已跳过：目标区域不在可录制屏幕内。")
        }
        let sourceBinding = windowResolver.resolve(selectionScreenRect: selection)
        let captureRect = Geometry.screencaptureRect(from: selection, on: screen)
        let output = try await screenCapture.captureRegion(selection, on: screen)
        let draft = makeDraft(
            selection: SelectionResult(screen: screen, screenRect: selection, captureRect: captureRect),
            stagedFile: output.file,
            sourceBinding: sourceBinding
        )
        let request = activeCaptureRequest(draft: draft, instruction: instruction)
        return try await transport.saveCapture(request, trustedNativeTiming: true)
    }

    private func hideRecordingChromeForKeyframeCapture() -> RecordingChromeVisibilitySnapshot {
        let snapshot = RecordingChromeVisibilitySnapshot(
            hudWindow: recordingHUDWindow,
            boundaryWindow: recordingBoundaryWindow,
            completionWindow: recordingCompletionWindow,
            hudWasVisible: recordingHUDWindow?.isVisible == true,
            boundaryWasVisible: recordingBoundaryWindow?.isVisible == true,
            completionWasVisible: recordingCompletionWindow?.isVisible == true
        )
        if snapshot.hudWasVisible {
            recordingHUDWindow?.orderOut(nil)
        }
        if snapshot.boundaryWasVisible {
            recordingBoundaryWindow?.orderOut(nil)
        }
        if snapshot.completionWasVisible {
            recordingCompletionWindow?.orderOut(nil)
        }
        return snapshot
    }

    private func restoreRecordingChromeAfterKeyframeCapture(_ snapshot: RecordingChromeVisibilitySnapshot) {
        if snapshot.boundaryWasVisible, recordingBoundaryWindow === snapshot.boundaryWindow {
            snapshot.boundaryWindow?.orderFrontRegardless()
        }
        if snapshot.hudWasVisible, recordingHUDWindow === snapshot.hudWindow {
            snapshot.hudWindow?.orderFrontRegardless()
        }
        if snapshot.completionWasVisible, recordingCompletionWindow === snapshot.completionWindow {
            snapshot.completionWindow?.orderFrontRegardless()
        }
    }

    func activeCaptureRequest(
        draft: CaptureDraft,
        instruction: ActiveCaptureCaptureInstruction
    ) -> CaptureAttemptRequest {
        CaptureAttemptRequest(
            schemaVersion: 1,
            trigger: TriggerEnvelope(
                triggerId: "trg_\(UUID().uuidString.replacingOccurrences(of: "-", with: ""))",
                triggerType: draft.trigger.triggerType,
                captureStrategy: draft.trigger.captureStrategy,
                actor: draft.trigger.actor,
                occurredAt: Date(),
                selection: draft.trigger.selection,
                intentText: nil,
                surfaceId: draft.trigger.surfaceId,
                deviceId: draft.trigger.deviceId,
                metadata: [
                    "capture_shell": .string("macos_appkit"),
                    "active_capture_candidate_id": .string(instruction.candidateId),
                ]
            ),
            selectionGeometry: draft.selectionGeometry,
            windowHints: draft.windowHints,
            workspace: WorkspaceSelection(workspaceId: "active-capture", label: "Active Capture", auto: true),
            actor: draft.actor,
            stagedArtifact: StagedArtifactRef(
                localPath: draft.stagedFile.path,
                artifactType: "screenshot",
                contentType: "image/png",
                filename: draft.stagedFile.lastPathComponent,
                metadata: [:]
            ),
            intentText: nil,
            activeCapture: instruction.binding,
            nativeTimingReceipt: NativeCaptureTimingReceipt(
                authority: "macos_capture",
                capturedAtMonotonicMs: monotonicMilliseconds(),
                sourceClock: "system_uptime_ms",
                recordedAtWallTime: Date(),
                metadata: [:]
            ),
            metadata: ["ui": .string("active_capture_input_producer")]
        )
    }

    func activeCaptureRecordingScope(scopeBounds: CGRect) -> ActiveCaptureRecordingScope {
        let screen = screenForE2ERect(scopeBounds)
        let displayId = screen?.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")].map { "\($0)" }
        let box = Geometry.intBox(from: scopeBounds, coordinateSpace: "macos_global")
        let primaryHint = windowResolver.resolveWindowHints(selectionScreenRect: scopeBounds).first
        return ActiveCaptureRecordingScope(
            kind: .region,
            displayId: displayId ?? "main",
            scaleFactor: screen.map { Double($0.backingScaleFactor) },
            windowId: primaryHint?.windowId,
            processId: primaryHint?.processId,
            bundleId: primaryHint?.bundleId,
            appName: primaryHint?.appName,
            title: primaryHint?.title,
            bounds: primaryHint?.frame,
            selectionRegion: box,
            scopeConfidence: 0.9,
            occlusionEstimate: nil,
            metadata: [:]
        )
    }
}

enum ActiveCaptureFullKeystrokePreference {
    static let defaultsKey = "WorkRecorder.ActiveCapture.RecordFullKeystrokes"
    static let environmentKey = "WORKRECORDER_ACTIVE_CAPTURE_FULL_KEYSTROKES"

    static func isEnabled(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        defaults: UserDefaults = .standard
    ) -> Bool {
        if let raw = environment[environmentKey]?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
            return ["1", "true", "yes", "on"].contains(raw)
        }
        return defaults.bool(forKey: defaultsKey)
    }
}

private struct RecordingChromeVisibilitySnapshot {
    let hudWindow: RecordingHUDWindow?
    let boundaryWindow: RecordingBoundaryOverlayWindow?
    let completionWindow: RecordingCompletionWindow?
    let hudWasVisible: Bool
    let boundaryWasVisible: Bool
    let completionWasVisible: Bool

    var didHideChrome: Bool {
        hudWasVisible || boundaryWasVisible || completionWasVisible
    }
}

private extension Dictionary where Key == String, Value == JSONScalar {
    func stringValue(for key: String) -> String? {
        guard case .string(let value) = self[key], !value.isEmpty else {
            return nil
        }
        return value
    }
}

struct RecordingChromeCapturePolicy {
    let minSuppressionGapMilliseconds: Int = 1_200

    func shouldSuppressChrome(
        for instruction: ActiveCaptureCaptureInstruction,
        nowMonotonicMilliseconds: Int,
        lastSuppressedAtMonotonicMilliseconds: Int?
    ) -> Bool {
        guard !isRequiredBoundary(instruction) else { return true }
        return false
    }

    private func isRequiredBoundary(_ instruction: ActiveCaptureCaptureInstruction) -> Bool {
        switch instruction.triggerKind {
        case .recordingStart, .recordingStop, .sessionComplete, .manualScreenshot, .userMark:
            return true
        default:
            return instruction.role == .start || instruction.role == .final || instruction.role == .userMark
        }
    }

}
