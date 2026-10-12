import AppKit
import CoreGraphics
import Foundation

enum RecordingSaveFailure: LocalizedError {
    case backendRejected

    var errorDescription: String? {
        switch self {
        case .backendRejected:
            return "后端没有接受这段录制。WorkRecorder 已保留本地临时视频，请重试或丢弃。"
        }
    }
}

// MARK: - Recording save and final keyframe persistence

extension CaptureCoordinator {
    func abortActiveRecordingForHUDClose() {
        guard let context = activeRecordingContext else { return }
        let activeSegment = activeRecordingSegment
        activeRecordingSegment = nil
        stopActiveCaptureInputProducer()
        deleteRecordingTemporaryFiles(context.completedSegments)
        Task { @MainActor [weak self] in
            guard let self else { return }
            if let activeSegment,
               let result = try? await activeSegment.stop(closeReason: .videoFailed)
            {
                deleteRecordingTemporaryFiles([result])
            }
            _ = try? await transport.cancelActiveCaptureSession(
                sessionId: context.sessionId,
                reason: "ui_closed_during_recording"
            )
            log("录制已终止并取消：\(context.sessionId)")
        }
    }

    func savePendingRecording(note: String = "", openWorkbenchAfterSave: Bool = false) {
        guard let draft = pendingRecordingCompletion else { return }
        guard !recordingCompletionSubmitting else {
            log("录制正在提交，请稍候。")
            return
        }
        recordingCompletionCaptureDrainAllowed = false
        recordingCompletionSubmitting = true
        notifyStateChanged()
        recordingCompletionWindow?.setSubmitting(true)
        Task { @MainActor [weak self] in
            guard let self else { return }
            var stitchedVideoURL: URL?
            do {
                await ensureRecordingCompletionKeyframeIfNeeded(draft)
                let stitchedVideo: RecordingVideoStitchingResult?
                var completionWarnings: [ActiveCaptureWarning] = []
                do {
                    stitchedVideo = try await prepareTopLevelRecordingVideoIfNeeded(draft)
                } catch {
                    stitchedVideo = nil
                    completionWarnings.append(
                        ActiveCaptureWarning(
                            code: .videoUnavailable,
                            message: "多段录制已保存为分段视频，但本机暂时无法合成为单个回放文件：\(error.localizedDescription)",
                            createdAt: Date()
                        )
                    )
                    log("多段录制合成失败，将使用分段视频完成保存：\(error.localizedDescription)")
                }
                stitchedVideoURL = stitchedVideo?.videoURL
                for segment in draft.segments {
                    _ = try await transport.attachRecordingSegment(
                        sessionId: draft.sessionId,
                        request: AttachRecordingSegmentRequest(
                            segmentId: segment.segmentId,
                            state: .available,
                            startedAtMonotonicMs: segment.startedMonotonicMilliseconds,
                            mediaStartMonotonicMs: segment.firstFrameMonotonicMilliseconds
                                ?? segment.startedMonotonicMilliseconds,
                            mediaStartWallTimeEpochMs: segment.firstFrameWallTimeEpochMilliseconds,
                            endedAtMonotonicMs: segment.endedMonotonicMilliseconds,
                            durationMs: segment.durationMilliseconds,
                            closeReason: segment.closeReason,
                            stagedVideo: StagedRecordingVideoRef(
                                localPath: segment.videoURL.path,
                                contentType: "video/mp4",
                                filename: segment.videoURL.lastPathComponent,
                                durationMs: segment.containerDurationMilliseconds,
                                metadata: [
                                    "frame_count": .int(segment.frameCount),
                                    "video_width": .int(segment.videoWidth),
                                    "video_height": .int(segment.videoHeight),
                                ]
                            ),
                            metadata: ["ui": .string("macos_recording")]
                        )
                    )
                }
                let completed = try await transport.completeActiveCaptureSession(
                    sessionId: draft.sessionId,
                    userNote: note,
                    video: stitchedVideo.map { result in
                        StagedRecordingVideoRef(
                            localPath: result.videoURL.path,
                            contentType: "video/mp4",
                            filename: result.videoURL.lastPathComponent,
                            durationMs: result.durationMilliseconds,
                            metadata: [
                                "producer": .string("macos_recording_stitched_segments"),
                                "segment_count": .int(result.segmentCount),
                            ]
                        )
                    },
                    warnings: completionWarnings
                )
                if completed.session.status == .failed {
                    throw RecordingSaveFailure.backendRejected
                }
                if let stitchedVideoURL {
                    deleteTemporaryRecordingFile(stitchedVideoURL)
                }
                deleteRecordingTemporaryFiles(draft.segments)
                log("录制已保存：\(draft.sessionId)")
                let savedEventId = completed.session.primaryEventId
                if let savedEventId, !savedEventId.isEmpty {
                    onCaptureSaved?(savedEventId)
                }
                if openWorkbenchAfterSave {
                    if let openRecordingsLibrary {
                        openRecordingsLibrary()
                    } else {
                        openRecentCaptures?()
                    }
                }
                if RecordingE2ELaunchResolver.shouldOpenLargeReviewAfterSave(
                    environment: ProcessInfo.processInfo.environment
                ) {
                    if let savedEventId, !savedEventId.isEmpty {
                        openRecordingReviewForSavedEvent?(savedEventId)
                    } else {
                        log("E2E 复盘窗口未打开：录制完成响应缺少 primary event id。")
                    }
                }
                forceCloseHUD(reason: "录制已保存")
            } catch {
                recordingCompletionSubmitting = false
                notifyStateChanged()
                recordingCompletionWindow?.setSubmitting(false)
                if let stitchedVideoURL {
                    deleteTemporaryRecordingFile(stitchedVideoURL)
                }
                let message = userFacingRecordingError(error)
                recordingCompletionWindow?.setErrorMessage(message)
                recordingCompletionWindow?.orderFrontRegardless()
                log("保存录制失败：\(error.localizedDescription)")
            }
        }
    }

    private func prepareTopLevelRecordingVideoIfNeeded(
        _ draft: RecordingCompletionDraft
    ) async throws -> RecordingVideoStitchingResult? {
        guard draft.segments.count > 1 else { return nil }
        let outputDirectory = recordingOutputDirectory(sessionId: draft.sessionId)
        let result = try await RecordingVideoStitcher().stitchedVideoIfNeeded(
            segments: draft.segments,
            outputDirectory: outputDirectory,
            sessionId: draft.sessionId
        )
        if result != nil {
            log("多段录制已合成为可播放视频：\(draft.sessionId)")
        }
        return result
    }

    private func ensureRecordingCompletionKeyframeIfNeeded(_ draft: RecordingCompletionDraft) async {
        guard draft.finalKeyframeEventId == nil else {
            return
        }
        let saved = await captureRecordingFinalKeyframe(
            sessionId: draft.sessionId,
            selection: draft.selection,
            scope: draft.scope,
            segments: draft.segments
        )
        if saved == nil {
            log("录制保存仍缺少 final keyframe；completion 会交由后端质量策略标记 warning。")
        }
    }

    func captureRecordingFinalKeyframe(
        sessionId: String,
        selection: SelectionResult,
        scope: ActiveCaptureRecordingScope,
        segments: [RecordingSegmentCaptureResult]
    ) async -> CaptureSaveResult? {
        if let finalFrame = segments.last?.finalFrameURL,
           FileManager.default.fileExists(atPath: finalFrame.path)
        {
            do {
                let saved = try await captureRecordingFrameKeyframe(
                    sessionId: sessionId,
                    triggerKind: .recordingStop,
                    role: .final,
                    selection: selection,
                    scope: scope,
                    stagedFrameURL: finalFrame,
                    metadata: ["producer": .string("recording_segment_final_frame")]
                )
                if let eventId = saved?.eventId, !eventId.isEmpty {
                    log("录制 final frame 已保存为最终关键帧：\(eventId)")
                    return saved
                }
                log("录制 final frame 未生成最终关键帧：后端未下发捕获指令。")
            } catch {
                log("录制 final frame 最终关键帧保存失败：\(error.localizedDescription)")
            }
        } else {
            log("录制 final keyframe 缺少 segment final frame，将尝试现场截图兜底。")
        }

        do {
            let saved = try await captureRecordingBoundaryKeyframe(
                sessionId: sessionId,
                triggerKind: .recordingStop,
                role: .final,
                selection: selection,
                scope: scope,
                metadata: ["producer": .string("recording_boundary_fallback")]
            )
            if let eventId = saved?.eventId, !eventId.isEmpty {
                log("录制现场截图已保存为最终关键帧：\(eventId)")
                return saved
            }
            log("录制现场截图没有生成最终关键帧：后端未下发捕获指令。")
        } catch {
            log("录制现场截图最终关键帧保存失败：\(error.localizedDescription)")
        }
        return nil
    }

    private func captureRecordingFrameKeyframe(
        sessionId: String,
        triggerKind: ActiveCaptureKeyframeTriggerKind,
        role: ActiveCaptureKeyframeRole,
        selection: SelectionResult,
        scope: ActiveCaptureRecordingScope,
        stagedFrameURL: URL,
        metadata: [String: JSONScalar]
    ) async throws -> CaptureSaveResult? {
        var requestMetadata = ["ui": JSONScalar.string("macos_recording")]
        metadata.forEach { requestMetadata[$0.key] = $0.value }
        guard let instruction = try await transport.submitKeyframeTrigger(
            sessionId: sessionId,
            triggerKind: triggerKind,
            role: role,
            scope: scope,
            metadata: requestMetadata
        ) else {
            return nil
        }
        let draft = makeDraft(
            selection: selection,
            stagedFile: stagedFrameURL,
            sourceBinding: draftSourceBinding(for: selection)
        )
        let request = activeCaptureRequest(draft: draft, instruction: instruction)
        do {
            return try await transport.saveCapture(request, trustedNativeTiming: true)
        } catch {
            await reportActiveCaptureInstructionFailure(
                instruction,
                reason: "invalid_evidence",
                diagnostic: "native_recording_frame_keyframe_failed"
            )
            throw error
        }
    }

    private func draftSourceBinding(for selection: SelectionResult) -> SourceBinding {
        windowResolver.resolve(selectionScreenRect: selection.screenRect)
    }

}

// MARK: - Recording preview, discard, and termination cleanup

extension CaptureCoordinator {
    func previewPendingRecording() {
        guard let draft = pendingRecordingCompletion else {
            log("录制预览不可用：没有本地视频段。")
            return
        }
        guard draft.segments.count > 1 else {
            guard let url = draft.primaryVideoURL else {
                log("录制预览不可用：没有本地视频段。")
                return
            }
            let opened = NSWorkspace.shared.open(url)
            log(opened ? "已打开本地录制预览：\(url.lastPathComponent)" : "录制预览打开失败：\(url.lastPathComponent)")
            return
        }
        Task { @MainActor [weak self] in
            guard let self, self.pendingRecordingCompletion?.sessionId == draft.sessionId else { return }
            do {
                if let recordingPreviewVideoURL {
                    deleteTemporaryRecordingFile(recordingPreviewVideoURL)
                    self.recordingPreviewVideoURL = nil
                }
                guard let stitchedVideo = try await prepareTopLevelRecordingVideoIfNeeded(draft) else {
                    log("录制预览不可用：多段视频没有生成合成文件。")
                    return
                }
                recordingPreviewVideoURL = stitchedVideo.videoURL
                let opened = NSWorkspace.shared.open(stitchedVideo.videoURL)
                log(
                    opened
                        ? "已打开合成后的本地录制预览：\(stitchedVideo.videoURL.lastPathComponent)"
                        : "合成录制预览打开失败：\(stitchedVideo.videoURL.lastPathComponent)"
                )
            } catch {
                recordingCompletionWindow?.setErrorMessage(userFacingRecordingError(error))
                recordingCompletionWindow?.orderFrontRegardless()
                log("合成录制预览失败：\(error.localizedDescription)")
            }
        }
    }

    func confirmDiscardPendingRecording() {
        guard pendingRecordingCompletion != nil else {
            closeHUD()
            return
        }
        guard !recordingCompletionSubmitting else {
            log("录制正在提交，请稍候。")
            return
        }
        guard let draft = pendingRecordingCompletion else { return }
        retireWindow(recordingDiscardConfirmationWindow)
        let window = RecordingDiscardConfirmationWindow(
            anchor: draft.selection.screenRect,
            screen: draft.selection.screen,
            onConfirm: { [weak self] in
                self?.retireWindow(self?.recordingDiscardConfirmationWindow)
                self?.recordingDiscardConfirmationWindow = nil
                self?.discardPendingRecording()
            },
            onCancel: { [weak self] in
                self?.retireWindow(self?.recordingDiscardConfirmationWindow)
                self?.recordingDiscardConfirmationWindow = nil
                self?.recordingCompletionWindow?.makeKeyAndOrderFront(nil)
                self?.recordingCompletionWindow?.orderFrontRegardless()
                self?.log("已取消丢弃录制。")
            }
        )
        recordingDiscardConfirmationWindow = window
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
    }

    func discardPendingRecording() {
        guard let draft = pendingRecordingCompletion else {
            closeHUD()
            return
        }
        guard !recordingCompletionSubmitting else {
            log("录制正在提交，请稍候。")
            return
        }
        recordingCompletionCaptureDrainAllowed = false
        recordingCompletionSubmitting = true
        notifyStateChanged()
        recordingCompletionWindow?.setSubmitting(true)
        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                _ = try await transport.cancelActiveCaptureSession(sessionId: draft.sessionId, reason: "discarded_before_save")
                deleteRecordingTemporaryFiles(draft.segments)
                log("录制已丢弃：\(draft.sessionId)")
                forceCloseHUD(reason: "录制已丢弃")
            } catch {
                recordingCompletionSubmitting = false
                notifyStateChanged()
                recordingCompletionWindow?.setSubmitting(false)
                recordingCompletionWindow?.setErrorMessage("暂时无法确认本次录制已取消。WorkRecorder 已保留本地临时视频，请重试丢弃或保存。")
                recordingCompletionWindow?.orderFrontRegardless()
                log("丢弃录制失败：\(error.localizedDescription)")
            }
        }
    }

    func prepareForApplicationTermination(_ completion: @escaping () -> Void) -> Bool {
        guard activeRecordingContext != nil || pendingRecordingCompletion != nil else { return false }
        guard !recordingCompletionSubmitting else {
            log("录制保存/丢弃仍在处理中，已暂缓退出。")
            let deadline = Date().addingTimeInterval(15)
            func waitForSubmission() {
                if !recordingCompletionSubmitting {
                    completion()
                    return
                }
                if Date() >= deadline {
                    log("录制保存/丢弃等待超时，继续执行退出清理。")
                    completion()
                    return
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                    waitForSubmission()
                }
            }
            waitForSubmission()
            return true
        }
        recordingCompletionSubmitting = true
        notifyStateChanged()
        let draft = pendingRecordingCompletion
        let context = activeRecordingContext
        let activeSegment = activeRecordingSegment
        activeRecordingSegment = nil
        stopActiveCaptureInputProducer()
        Task { @MainActor [weak self] in
            guard let self else {
                completion()
                return
            }
            var stagedSegments = draft?.segments ?? context?.completedSegments ?? []
            if let activeSegment,
               let stopped = try? await activeSegment.stop(closeReason: .videoFailed)
            {
                stagedSegments.append(stopped)
            }
            if let sessionId = draft?.sessionId ?? context?.sessionId {
                do {
                    _ = try await transport.cancelActiveCaptureSession(sessionId: sessionId, reason: "app_terminated_before_save")
                    log("退出前已取消录制：\(sessionId)")
                } catch {
                    log("退出前取消录制失败：\(error.localizedDescription)")
                    forceCloseHUD(reason: "退出前清理录制状态；临时视频已保留")
                    completion()
                    return
                }
            }
            deleteRecordingTemporaryFiles(stagedSegments)
            forceCloseHUD(reason: "退出前清理录制")
            completion()
        }
        return true
    }

    @discardableResult
    func blockApplicationTerminationForRecordingIfNeeded() -> Bool {
        guard activeRecordingContext != nil || pendingRecordingCompletion != nil else { return false }
        focusRecordingControls()
        if pendingRecordingCompletion != nil {
            log("录制待保存；请先保存或丢弃，再退出 WorkRecorder。")
        } else {
            log("录制仍在进行；请先结束录制并完成保存/丢弃，再退出 WorkRecorder。")
        }
        return true
    }

    func captureRecordingBoundaryKeyframe(
        sessionId: String,
        triggerKind: ActiveCaptureKeyframeTriggerKind,
        role: ActiveCaptureKeyframeRole,
        selection: SelectionResult,
        scope: ActiveCaptureRecordingScope,
        metadata: [String: JSONScalar] = [:]
    ) async throws -> CaptureSaveResult? {
        var requestMetadata = ["ui": JSONScalar.string("macos_recording")]
        metadata.forEach { requestMetadata[$0.key] = $0.value }
        guard let instruction = try await transport.submitKeyframeTrigger(
            sessionId: sessionId,
            triggerKind: triggerKind,
            role: role,
            scope: scope,
            metadata: requestMetadata
        ) else {
            return nil
        }
        do {
            return try await captureActiveCaptureInstructionNow(instruction, scopeBounds: selection.screenRect)
        } catch {
            await reportActiveCaptureInstructionFailure(
                instruction,
                reason: "invalid_evidence",
                diagnostic: "native_recording_boundary_keyframe_failed"
            )
            throw error
        }
    }

    func userFacingRecordingError(_ error: Error, cleanupWarning: String? = nil) -> String {
        let base: String
        if isScreenRecordingPermissionFailure(error) {
            base = "WorkRecorder 需要屏幕录制权限才能录制选区。开启后再试一次。"
        } else if let localized = error as? LocalizedError, let description = localized.errorDescription {
            base = description
        } else {
            base = "录制没有完成，请稍后重试或复制诊断信息。"
        }
        guard let cleanupWarning else {
            return base
        }
        return "\(base)\n\(cleanupWarning)"
    }

    func isScreenRecordingPermissionFailure(_ error: Error) -> Bool {
        switch error {
        case RegionRecordingFailure.screenCapturePermissionDenied:
            return true
        case RegionRecordingFailure.noFramesWritten:
            if #available(macOS 11.0, *) {
                return !CGPreflightScreenCaptureAccess()
            }
            return false
        default:
            return false
        }
    }

    private func deleteRecordingTemporaryFiles(_ segments: [RecordingSegmentCaptureResult]) {
        for segment in segments {
            deleteTemporaryRecordingFile(segment.videoURL)
            deleteTemporaryRecordingFile(segment.startFrameURL)
            deleteTemporaryRecordingFile(segment.finalFrameURL)
        }
    }

    func deleteTemporaryRecordingFile(_ url: URL) {
        do {
            try FileManager.default.removeItem(at: url)
        } catch CocoaError.fileNoSuchFile {
            return
        } catch {
            log("临时录制文件删除失败：\(url.lastPathComponent) · \(error.localizedDescription)")
        }
    }
}
