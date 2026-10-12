import AppKit
import Foundation

extension CaptureCoordinator {
    func markRecordingMoment() {
        guard let context = activeRecordingContext else { return }
        recordingHUDWindow?.showTransientStatus("正在标记")
        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                let control = try await transport.applyRecordingControl(
                    sessionId: context.sessionId,
                    kind: .userMark,
                    metadata: ["ui": .string("recording_hud")]
                )
                do {
                    let saved = try await captureRecordingControlInstruction(
                        control.captureInstruction,
                        context: context
                    )
                    if saved != nil {
                        recordingHUDWindow?.showTransientStatus("已标记")
                        log("录制标记和关键帧已添加。")
                    } else {
                        recordingHUDWindow?.showTransientStatus("已标记 · 等待关键帧")
                        log("录制标记已添加；后端未下发关键帧指令。")
                    }
                } catch {
                    recordingHUDWindow?.showTransientStatus("已标记 · 关键帧失败")
                    log("录制标记已添加，但关键帧捕获失败：\(error.localizedDescription)")
                }
            } catch {
                recordingHUDWindow?.showTransientStatus("标记失败")
                log("录制标记失败：\(error.localizedDescription)")
            }
        }
    }

    func toggleRecordingPause() {
        let controlSnapshot = recordingSessionController.snapshot
        guard !controlSnapshot.inFlight else {
            log("录制控制正在处理，请稍候。")
            return
        }
        guard !controlSnapshot.isPaused else {
            resumeRecording()
            return
        }
        pauseRecording()
    }

    private func pauseRecording() {
        guard let context = activeRecordingContext, let activeSegment = activeRecordingSegment else { return }
        let transaction: RecordingPauseTransaction
        do {
            transaction = try recordingSessionController.beginPause(
                nowMonotonicMilliseconds: monotonicMilliseconds(),
                hasActiveVideoSegment: activeRecordingSegment != nil
            )
        } catch {
            syncRecordingControlFieldsFromSessionController()
            log("暂停录制失败：\(error.localizedDescription)")
            return
        }
        syncRecordingControlFieldsFromSessionController()
        notifyStateChanged()
        Task { @MainActor [weak self] in
            guard let self else { return }
            var backendPaused = false
            defer {
                syncRecordingControlFieldsFromSessionController()
                notifyStateChanged()
            }
            do {
                await stopAndDrainActiveCaptureInputProducer()
                let control = try await transport.applyRecordingControl(
                    sessionId: context.sessionId,
                    kind: .pause,
                    metadata: ["ui": .string("recording_hud")]
                )
                backendPaused = true
                await captureRecordingControlBoundaryBestEffort(
                    control.captureInstruction,
                    context: context,
                    label: "暂停边界"
                )
                let result = try await activeSegment.stop(closeReason: .paused)
                activeRecordingSegment = nil
                var updated = context
                updated.completedSegments.append(result)
                activeRecordingContext = updated
                recordingSessionController.commitPause(transaction)
                recordingBoundaryWindow?.setPaused(true)
                transition(to: .recordingPaused(activeSessionId ?? UUID()), reason: "用户暂停录制")
                recordingHUDWindow?.showTransientStatus("已暂停")
                log("录制已暂停。")
            } catch {
                if backendPaused {
                    _ = try? await transport.applyRecordingControl(
                        sessionId: context.sessionId,
                        kind: transaction.rollbackBackendKind,
                        metadata: ["ui": .string("pause_video_stop_failed")]
                    )
                }
                recordingSessionController.rollbackPause()
                startActiveCaptureInputProducer(
                    sessionId: context.sessionId,
                    scopeBounds: context.selection.screenRect,
                    recordingScope: context.scope
                )
                log("暂停录制失败：\(error.localizedDescription)")
            }
        }
    }

    private func resumeRecording() {
        guard let context = activeRecordingContext else { return }
        let transaction: RecordingResumeTransaction
        do {
            transaction = try recordingSessionController.beginResume()
        } catch {
            syncRecordingControlFieldsFromSessionController()
            log("继续录制失败：\(error.localizedDescription)")
            return
        }
        syncRecordingControlFieldsFromSessionController()
        notifyStateChanged()
        Task { @MainActor [weak self] in
            guard let self else { return }
            var backendResumed = false
            defer {
                syncRecordingControlFieldsFromSessionController()
                notifyStateChanged()
            }
            do {
                let control = try await transport.applyRecordingControl(
                    sessionId: context.sessionId,
                    kind: .resume,
                    metadata: ["ui": .string("recording_hud")]
                )
                backendResumed = true
                let manifest = try await transport.getRecordingSegmentManifest(sessionId: context.sessionId)
                guard let segment = manifest.segments.sorted(by: { $0.sequenceIndex < $1.sequenceIndex }).last else {
                    throw CaptureTransportError.invalidResponse
                }
                do {
                    activeRecordingSegment = try await startVideoSegment(
                        segmentId: segment.segmentId,
                        selection: context.selection,
                        scope: context.scope
                    )
                } catch {
                    throw error
                }
                var updated = context
                updated.currentSegmentId = segment.segmentId
                activeRecordingContext = updated
                recordingSessionController.commitResume(
                    transaction,
                    nowMonotonicMilliseconds: monotonicMilliseconds()
                )
                recordingBoundaryWindow?.setPaused(false)
                startActiveCaptureInputProducer(
                    sessionId: context.sessionId,
                    scopeBounds: context.selection.screenRect,
                    recordingScope: context.scope
                )
                await captureRecordingControlBoundaryBestEffort(
                    control.captureInstruction,
                    context: updated,
                    label: "继续边界"
                )
                transition(to: .recording(activeSessionId ?? UUID()), reason: "用户继续录制")
                recordingHUDWindow?.showTransientStatus("已继续")
                log("录制已继续。")
            } catch {
                if backendResumed {
                    _ = try? await transport.applyRecordingControl(
                        sessionId: context.sessionId,
                        kind: transaction.rollbackBackendKind,
                        metadata: ["ui": .string("resume_failed_rollback")]
                    )
                    recordingSessionController.rollbackResume()
                    recordingBoundaryWindow?.setPaused(true)
                    transition(to: .recordingPaused(activeSessionId ?? UUID()), reason: "继续录制失败，已回滚为暂停")
                    recordingHUDWindow?.showTransientStatus("继续失败，仍已暂停")
                } else {
                    recordingSessionController.rollbackResume()
                }
                log("继续录制失败：\(error.localizedDescription)")
            }
        }
    }

    private func captureRecordingControlInstruction(
        _ instruction: ActiveCaptureCaptureInstruction?,
        context: RecordingRuntimeContext
    ) async throws -> CaptureSaveResult? {
        guard let instruction else { return nil }
        do {
            return try await captureActiveCaptureInstructionNow(instruction, scopeBounds: context.selection.screenRect)
        } catch {
            await reportActiveCaptureInstructionFailure(
                instruction,
                reason: "invalid_evidence",
                diagnostic: "native_recording_control_keyframe_failed"
            )
            throw error
        }
    }

    private func captureRecordingControlBoundaryBestEffort(
        _ instruction: ActiveCaptureCaptureInstruction?,
        context: RecordingRuntimeContext,
        label: String
    ) async {
        guard let instruction else {
            log("\(label)未收到关键帧指令。")
            return
        }
        do {
            _ = try await captureActiveCaptureInstructionNow(instruction, scopeBounds: context.selection.screenRect)
            log("\(label)关键帧已保存。")
        } catch {
            await reportActiveCaptureInstructionFailure(
                instruction,
                reason: "invalid_evidence",
                diagnostic: "native_recording_control_boundary_failed"
            )
            log("\(label)关键帧保存失败：\(error.localizedDescription)")
        }
    }

    func finishRecordingForReview() {
        guard let context = activeRecordingContext else { return }
        guard !recordingControlInFlight else {
            log("录制控制正在处理，请稍候。")
            return
        }
        let transaction: RecordingFinishTransaction
        do {
            transaction = try recordingSessionController.beginFinishForReview()
        } catch {
            syncRecordingControlFieldsFromSessionController()
            log("完成录制失败：\(error.localizedDescription)")
            return
        }
        syncRecordingControlFieldsFromSessionController()
        notifyStateChanged()
        let uiSessionId = activeSessionId ?? UUID()
        recordingHUDTimer?.invalidate()
        recordingHUDTimer = nil
        refreshRecordingHUD()
        recordingHUDWindow?.setMode(.stopping)
        recordingBoundaryWindow?.setPaused(true)
        transition(to: .recordingReview(uiSessionId), reason: "用户完成录制，进入本地复核")

        // Freeze the input timeline at the user's stop intent instead of after
        // pending network submissions have drained. Keep the producer alive
        // locally so its already-queued events can finish uploading below.
        let inputProducerToDrain = activeCaptureInputProducer
        inputProducerToDrain?.stop(
            flushPendingAggregates: true,
            cancelPendingCaptureInstructions: false
        )
        activeCaptureInputProducer = nil

        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                // Video shutdown and pending input upload are independent. Start
                // draining in parallel, but stop ScreenCaptureKit first so slow
                // retries can never extend the recorded media tail.
                let inputDrainTask = Task {
                    await inputProducerToDrain?.waitForPendingSubmissions()
                }
                var completedSegments = context.completedSegments
                if let activeSegment = activeRecordingSegment {
                    completedSegments.append(try await activeSegment.stop(closeReason: transaction.closeReason))
                    activeRecordingSegment = nil
                }
                await inputDrainTask.value
                await drainPendingActiveCaptureInstructionsForReview(
                    sessionId: context.sessionId,
                    scopeBounds: context.selection.screenRect
                )
                let final = await captureRecordingFinalKeyframe(
                    sessionId: context.sessionId,
                    selection: context.selection,
                    scope: context.scope,
                    segments: completedSegments
                )
                do {
                    _ = try await transport.applyRecordingControl(
                        sessionId: context.sessionId,
                        kind: .stop,
                        metadata: ["ui": .string("recording_hud")]
                    )
                } catch {
                    log("录制停止控制写入失败，将在保存时由 completion 兜底终结 session：\(error.localizedDescription)")
                }
                let draft = RecordingCompletionDraft(
                    sessionId: context.sessionId,
                    selection: context.selection,
                    scope: context.scope,
                    sourceBinding: context.sourceBinding,
                    segments: completedSegments,
                    startedAtMonotonicMilliseconds: context.startedAtMonotonicMilliseconds,
                    endedAtMonotonicMilliseconds: monotonicMilliseconds(),
                    finalKeyframeEventId: final?.eventId,
                    inputTraceDegraded: recordingInputTraceDegraded,
                    scopeNeedsReview: recordingScopeNeedsReview || context.scopeNeedsReview
                )
                pendingRecordingCompletion = draft
                recordingCompletionCaptureDrainAllowed = true
                retireWindow(recordingHUDWindow)
                recordingHUDWindow = nil
                retireWindow(recordingBoundaryWindow)
                recordingBoundaryWindow = nil
                showRecordingCompletion(draft: draft)
                recordingSessionController.commitFinishForReview()
                syncRecordingControlFieldsFromSessionController()
                notifyStateChanged()
            } catch {
                if activeRecordingSegment == nil, activeRecordingContext != nil {
                    stopActiveCaptureInputProducer()
                }
                recordingSessionController.rollbackFinishForReviewToPaused()
                syncRecordingControlFieldsFromSessionController()
                recordingHUDWindow?.setMode(.paused)
                recordingBoundaryWindow?.setPaused(true)
                transition(to: .recordingPaused(uiSessionId), reason: "完成录制失败，等待用户重试或丢弃")
                notifyStateChanged()
                log("完成录制失败：\(error.localizedDescription)")
                showRecordingIssue(
                    RecordingPermissionIssue(
                        kind: .startupFailed(userFacingRecordingError(error)),
                        selectedRegionDescription: "\(Int(context.selection.screenRect.width.rounded())) × \(Int(context.selection.screenRect.height.rounded()))",
                        sourceDescription: context.sourceBinding.sourceRef.appName ?? context.sourceBinding.sourceRef.title,
                        diagnostic: error.localizedDescription
                    ),
                    selection: context.selection,
                    sessionId: uiSessionId
                )
            }
        }
    }

    private func showRecordingCompletion(draft: RecordingCompletionDraft) {
        retireWindow(recordingCompletionWindow)
        let window = RecordingCompletionWindow(
            draft: draft,
            screen: draft.selection.screen,
            onSave: { [weak self] note in self?.savePendingRecording(note: note) },
            onDiscard: { [weak self] in self?.confirmDiscardPendingRecording() },
            onPreview: { [weak self] in self?.previewPendingRecording() }
        )
        recordingCompletionWindow = window
        window.makeKeyAndOrderFront(nil)
        window.orderFrontRegardless()
        window.focusNote()
        autoSaveConfiguredE2ERecordingIfNeeded(draft: draft)
    }

    private func autoSaveConfiguredE2ERecordingIfNeeded(draft: RecordingCompletionDraft) {
        let environment = ProcessInfo.processInfo.environment
        guard environment["WORKRECORDER_E2E_RECORDING_AUTO_SAVE"] == "1" else {
            return
        }
        let note = environment["WORKRECORDER_E2E_RECORDING_NOTE"] ?? "WorkRecorder E2E region recording"
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.45) { [weak self] in
            guard self?.pendingRecordingCompletion?.sessionId == draft.sessionId else { return }
            self?.savePendingRecording(note: note, openWorkbenchAfterSave: true)
        }
    }

    func confirmFinishRecordingForReview() {
        guard activeRecordingContext != nil else { return }
        let alert = NSAlert()
        alert.messageText = "Finish this recording?"
        alert.informativeText = "WorkRecorder will stop recording and open the review screen. You can still preview, add a note, save, or discard it."
        alert.alertStyle = .informational
        alert.addButton(withTitle: "Back to Recording")
        alert.addButton(withTitle: "Finish Recording")
        if alert.runModal() == .alertSecondButtonReturn {
            finishRecordingForReview()
        } else {
            focusRecordingControls()
            log("已取消结束录制。")
        }
    }

}
