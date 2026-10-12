import AppKit
import Foundation
import Testing
@testable import WorkRecorderCapture

@MainActor
final class RecordingReviewPlaybackClientStub: RecordingPlaybackLoadingClient, RecordingExportingClient {
    var requests: [RecordingPlaybackLoadRequest] = []
    var playbackFileURL: URL?
    struct ExportCall: Equatable {
        let sessionId: String
        let outputRoot: String
        let purpose: String
        let fallbackMode: WorkbenchRecordingExportFallbackMode
    }
    var exportCalls: [ExportCall] = []
    var exportError: Error?

    func recordingExport(
        sessionId: String,
        outputRoot: String,
        purpose: String,
        fallbackMode: WorkbenchRecordingExportFallbackMode
    ) async throws -> WorkbenchRecordingExportView {
        exportCalls.append(
            ExportCall(
                sessionId: sessionId,
                outputRoot: outputRoot,
                purpose: purpose,
                fallbackMode: fallbackMode
            )
        )
        if let exportError {
            throw exportError
        }
        return WorkbenchRecordingExportView(
            sessionId: sessionId,
            outputDir: "\(outputRoot)/\(sessionId)",
            keyframeDirCount: 2,
            evidenceFileCount: 4,
            actionCount: 1,
            videoFileCount: 1,
            vmA11yRecordCount: 1,
            vmEventLogCount: 2,
            vmClickLogCount: 3,
            fallbackWarning: nil
        )
    }

    func recordingVideoPlayback(
        sessionId: String,
        eventId: String,
        artifactId: String,
        purpose: String
    ) async throws -> WorkbenchRecordingVideoPlaybackView {
        requests.append(
            RecordingPlaybackLoadRequest(
                sessionId: sessionId,
                eventId: eventId,
                artifactId: artifactId,
                purpose: purpose,
                initialMediaTimeMs: nil
            )
        )
        if let playbackFileURL {
            return WorkbenchRecordingVideoPlaybackView(
                sessionId: sessionId,
                eventId: eventId,
                artifactId: artifactId,
                contentType: "video/mp4",
                byteSize: 8,
                playbackFilePath: playbackFileURL.path,
                contentBase64: nil
            )
        }
        return WorkbenchRecordingVideoPlaybackView(
            sessionId: sessionId,
            eventId: eventId,
            artifactId: artifactId,
            contentType: "video/mp4",
            byteSize: 8,
            playbackFilePath: nil,
            contentBase64: Data("ftypdemo".utf8).base64EncodedString()
        )
    }
}

extension WorkbenchRuntimeTests {
    @MainActor
    @Test func recordingReviewWindowShowsSafeClickTargetAsPrimaryStepInfo() throws {
        let target = WorkbenchClickTargetView(
            resolutionId: "ctr_save",
            status: "resolved",
            displayLabel: "保存",
            semanticKind: "button",
            confidence: 0.91,
            confidenceBand: "high",
            sourceBadges: ["a11y_snapshot"],
            needsReview: false,
            evidenceKeyframeIds: ["kf_after"],
            hasCoordinates: true,
            suppressionReason: nil
        )
        let step = WorkbenchRecordingTimelineStepView(
            stepId: "action_click_save",
            kind: .action,
            occurredAt: "2026-05-18T13:08:05Z",
            mediaTimeMs: 5_000,
            sequenceIndex: 3,
            keyframeId: nil,
            actionId: "act_click_save",
            controlId: nil,
            keyframeRole: nil,
            triggerKind: "click_settle",
            actionKind: .click,
            actionSummary: WorkbenchRecordingActionSummaryView(
                actionId: "act_click_save",
                actionKind: .click,
                keyChord: nil,
                typingSummary: nil,
                target: target,
                beforeKeyframeIds: ["kf_before"],
                afterKeyframeIds: ["kf_after"],
                targetEvidenceKeyframeIds: ["kf_probe"],
                resultKeyframeId: "kf_after"
            ),
            controlKind: nil,
            safeCaption: "点击「保存」",
            needsReview: false,
            readiness: Self.readyRecordingStep()
        )
        let controller = RecordingReviewWindowController(client: RecordingReviewPlaybackClientStub(), logStore: AppLogStore())

        #expect(controller.stepTitle(step) == "点击「保存」")
        #expect(controller.stepActionSummary(step).contains("按钮"))
        let labels = Self.textLabels(in: controller.clickTargetSection(step: step))
        #expect(labels.contains("点击目标"))
        #expect(labels.contains("保存"))
        #expect(labels.contains { $0.contains("辅助功能") })
        #expect(controller.stepKeyframeSummary(step).contains("目标证据 1"))
        let recording = WorkbenchActiveCaptureInspectView(
            sessionId: "acs_click_target",
            mode: .recordingSession,
            primaryEventId: nil,
            status: .completed,
            startedAt: nil,
            endedAt: nil,
            userNote: nil,
            warnings: [],
            timeline: WorkbenchRecordingTimelineInspectView(
                sessionId: "acs_click_target",
                durationMs: 5_000,
                alignmentErrorMs: nil,
                steps: [step]
            ),
            safeTextBlocks: [
                WorkbenchRecordingSafeTextBlock(
                    blockId: "txt_probe",
                    sourceField: "target_probe_summary",
                    eventId: "evt_probe",
                    keyframeId: "kf_probe",
                    text: "保存按钮附近的安全文本",
                    textTruncated: false,
                    confidence: 0.81
                ),
            ],
            videoRef: nil,
            skillReadiness: Self.readyRecordingStep(),
            projection: WorkbenchProjectionTruncationSummary(truncated: false, truncatedCounts: [:], nextCursor: nil)
        )
        #expect(RecordingReviewCore.safeTextForStep(recording, step: step)?.blockId == "txt_probe")
    }

    @MainActor
    @Test func recordingReviewSafeTextDoesNotGuessSharedEventTextForSpecificKeyframe() throws {
        let first = WorkbenchRecordingTimelineStepView(
            stepId: "kf_first",
            kind: .keyframe,
            occurredAt: "2026-05-18T13:08:01Z",
            mediaTimeMs: 1_000,
            sequenceIndex: 1,
            keyframeId: "kf_first",
            keyframeEventId: "evt_shared",
            actionId: nil,
            controlId: nil,
            keyframeRole: "result",
            triggerKind: "click_settle",
            actionKind: nil,
            actionSummary: nil,
            controlKind: nil,
            safeCaption: "结果帧",
            needsReview: false,
            readiness: Self.readyRecordingStep()
        )
        let second = WorkbenchRecordingTimelineStepView(
            stepId: "kf_second",
            kind: .keyframe,
            occurredAt: "2026-05-18T13:08:02Z",
            mediaTimeMs: 2_000,
            sequenceIndex: 2,
            keyframeId: "kf_second",
            keyframeEventId: "evt_shared",
            actionId: nil,
            controlId: nil,
            keyframeRole: "result",
            triggerKind: "click_settle",
            actionKind: nil,
            actionSummary: nil,
            controlKind: nil,
            safeCaption: "结果帧",
            needsReview: false,
            readiness: Self.readyRecordingStep()
        )
        let recording = WorkbenchActiveCaptureInspectView(
            sessionId: "acs_shared_event_text",
            mode: .recordingSession,
            primaryEventId: nil,
            status: .completed,
            startedAt: nil,
            endedAt: nil,
            userNote: nil,
            warnings: [],
            timeline: WorkbenchRecordingTimelineInspectView(
                sessionId: "acs_shared_event_text",
                durationMs: 2_000,
                alignmentErrorMs: nil,
                steps: [first, second]
            ),
            safeTextBlocks: [
                WorkbenchRecordingSafeTextBlock(
                    blockId: "txt_event_scoped",
                    sourceField: "ocr",
                    eventId: "evt_shared",
                    text: "event scoped text",
                    textTruncated: false,
                    confidence: 0.6
                ),
            ],
            videoRef: nil,
            skillReadiness: Self.readyRecordingStep(),
            projection: WorkbenchProjectionTruncationSummary(truncated: false, truncatedCounts: [:], nextCursor: nil)
        )

        #expect(RecordingReviewCore.safeTextForStep(recording, step: first) == nil)
        #expect(RecordingReviewCore.safeTextForStep(recording, step: second) == nil)
    }

    @MainActor
    @Test func recordingReviewWindowPlacementFollowsSourceWorkbenchScreen() throws {
        let sourceScreen = NSRect(x: -1680, y: 48, width: 1680, height: 1000)
        let sourceWindow = NSRect(x: -1460, y: 220, width: 920, height: 640)

        let frame = RecordingReviewWindowPlacementPolicy.preferredFrame(
            defaultSize: NSSize(width: 1280, height: 820),
            minSize: NSSize(width: 1100, height: 720),
            sourceWindowFrame: sourceWindow,
            sourceScreenVisibleFrame: sourceScreen
        )

        #expect(frame.minX >= sourceScreen.minX + 18)
        #expect(frame.maxX <= sourceScreen.maxX - 18)
        #expect(frame.minY >= sourceScreen.minY + 18)
        #expect(frame.maxY <= sourceScreen.maxY - 18)
        #expect(frame.midX < 0)
        #expect(abs(frame.midX - sourceWindow.midX) < 1)
    }

    @MainActor
    @Test func recordingReviewWindowRendersWorkspaceAndMaterialsPanel() throws {
        let client = RecordingReviewPlaybackClientStub()
        let controller = RecordingReviewWindowController(client: client, logStore: AppLogStore())
        controller.present(
            RecordingReviewOpenRequest(
                inspect: Self.previewRecordingInspect(),
                thumbnail: Self.previewThumbnail(),
                selectedStepId: "step_hotkey",
                currentMediaTimeMs: 8_120,
                onCommit: { _ in }
            )
        )
        var content = try #require(controller.window?.contentView)
        var labels = Self.textLabels(in: content)
        var buttons = Self.buttonTitles(in: content)
        #expect(labels.contains { $0.contains("录制复盘：API 文档") })
        #expect(labels.contains("章节时间线"))
        #expect(labels.contains("操作线索"))
        #expect(buttons.contains("返回录制中心"))
        #expect(buttons.contains("仅播放视频"))
        #expect(buttons.contains("复盘内容"))

        controller.toggleMaterialsAction()
        content = try #require(controller.window?.contentView)
        labels = Self.textLabels(in: content)
        buttons = Self.buttonTitles(in: content)
        #expect(labels.contains("本次录制包含"))
        #expect(labels.contains("隐私与访问"))
        #expect(!labels.contains("受限原始材料"))
        #expect(buttons.contains("关闭"))
        controller.commitAndClose()
    }

    @MainActor
    @Test func recordingReviewWindowLoadsPlaybackThroughDedicatedClientAndCommitsState() async throws {
        let client = RecordingReviewPlaybackClientStub()
        let sourceVideo = FileManager.default.temporaryDirectory
            .appendingPathComponent("workrecorder-large-review-source-\(UUID().uuidString).mp4")
        try Data("ftypdemo".utf8).write(to: sourceVideo)
        defer { try? FileManager.default.removeItem(at: sourceVideo) }
        client.playbackFileURL = sourceVideo
        let controller = RecordingReviewWindowController(client: client, logStore: AppLogStore())
        var committed: RecordingReviewCommit?
        controller.present(
            RecordingReviewOpenRequest(
                inspect: Self.previewRecordingInspect(),
                thumbnail: Self.previewThumbnail(),
                selectedStepId: "step_typing",
                currentMediaTimeMs: 19_460,
                onCommit: { commit in
                    committed = commit
                }
            )
        )

        controller.loadPlaybackAction()
        try await Self.waitForAsyncWorkbenchUpdate {
            controller.playbackController.playbackSession != nil || controller.playbackController.errorMessage != nil
        }

        let request = try #require(client.requests.first)
        #expect(request.sessionId == "acs_recording_checkout_flow")
        #expect(request.eventId == "evt_recording_checkout_flow")
        #expect(request.artifactId == "art_recording_video")
        #expect(request.purpose == "workbench_large_recording_review")
        let session = try #require(controller.playbackController.playbackSession)
        #expect(session.lastRequestedSeekMediaTimeMs == 19_460)
        #expect(FileManager.default.fileExists(atPath: session.fileURL.path))
        #expect(session.fileURL.path != sourceVideo.path)

        controller.selectStep(offset: -1)
        #expect(session.lastRequestedSeekMediaTimeMs == 8_120)
        controller.commitAndClose()
        let commit = try #require(committed)
        #expect(commit.eventId == "evt_recording_checkout_flow")
        #expect(commit.sessionId == "acs_recording_checkout_flow")
        #expect(commit.selectedStepId == "step_hotkey")
        #expect(!FileManager.default.fileExists(atPath: session.fileURL.path))
    }

    @MainActor
    @Test func recordingReviewWindowExternalPlaybackUsesDedicatedPlaybackRoute() async throws {
        let client = RecordingReviewPlaybackClientStub()
        let sourceVideo = FileManager.default.temporaryDirectory
            .appendingPathComponent("workrecorder-large-review-external-source-\(UUID().uuidString).mp4")
        try Data("ftypdemo".utf8).write(to: sourceVideo)
        defer { try? FileManager.default.removeItem(at: sourceVideo) }
        client.playbackFileURL = sourceVideo
        var opened: [URL] = []
        let controller = RecordingReviewWindowController(
            client: client,
            logStore: AppLogStore(),
            openPlaybackFile: { url in
                opened.append(url)
                return true
            }
        )
        controller.present(
            RecordingReviewOpenRequest(
                inspect: Self.previewRecordingInspect(),
                thumbnail: Self.previewThumbnail(),
                selectedStepId: "step_hotkey",
                currentMediaTimeMs: nil,
                onCommit: { _ in }
            )
        )

        controller.openExternalPlaybackAction()
        try await Self.waitForAsyncWorkbenchUpdate {
            !client.requests.isEmpty && !opened.isEmpty
        }

        let request = try #require(client.requests.first)
        #expect(request.sessionId == "acs_recording_checkout_flow")
        #expect(request.artifactId == "art_recording_video")
        #expect(request.purpose == "workbench_large_recording_review")
        let openedURL = try #require(opened.first)
        #expect(openedURL.path != sourceVideo.path)
        #expect(FileManager.default.fileExists(atPath: openedURL.path))
        controller.commitAndClose()
        #expect(!FileManager.default.fileExists(atPath: openedURL.path))
    }

    @MainActor
    @Test func recordingReviewWindowNoVideoStateDoesNotExposePlaybackActions() throws {
        let controller = RecordingReviewWindowController(client: RecordingReviewPlaybackClientStub(), logStore: AppLogStore())
        controller.present(
            RecordingReviewOpenRequest(
                inspect: Self.previewRecordingWithoutVideoInspect(),
                thumbnail: nil,
                selectedStepId: "step_stop",
                currentMediaTimeMs: nil,
                onCommit: { _ in }
            )
        )
        let content = try #require(controller.window?.contentView)
        let labels = Self.textLabels(in: content)
        let buttons = Self.buttons(in: content)
        #expect(labels.contains { $0.contains("没有可播放视频") })
        #expect(buttons.first { $0.title == "视频不可用" }?.isEnabled == false)
        #expect(!buttons.map(\.title).contains("播放"))
        #expect(!buttons.map(\.title).contains("仅播放视频"))
        #expect(buttons.map(\.title).contains("上一步"))
        #expect(buttons.map(\.title).contains("下一步"))
        #expect(buttons.map(\.title).contains("导出到文件夹"))
        controller.commitAndClose()
    }

    @MainActor
    @Test func recordingReviewWindowConversionFailureRevealsRawExports() async throws {
        final class RevealBox { var url: URL? }
        let stub = RecordingReviewPlaybackClientStub()
        let outputRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("workrecorder-export-\(UUID().uuidString)")
        let revealed = RevealBox()
        let controller = RecordingReviewWindowController(client: stub, logStore: AppLogStore())
        controller.chooseExportDirectory = { outputRoot }
        controller.revealInFinder = { revealed.url = $0 }
        controller.convertExportToBenchmark = { _, _ in
            throw WorkbenchRecordingBenchmarkConversionError.commandFailed(status: 1, output: "conversion failed")
        }
        controller.present(
            RecordingReviewOpenRequest(
                inspect: Self.previewRecordingInspect(),
                thumbnail: Self.previewThumbnail(),
                selectedStepId: "step_hotkey",
                currentMediaTimeMs: nil,
                onCommit: { _ in }
            )
        )

        controller.exportRecordingAction()
        try await Self.waitForAsyncWorkbenchUpdate {
            stub.exportCalls.count == 1 && !controller.isExportInProgress
        }

        let rawRoot = WorkbenchRecordingBenchmarkConverter.taskExportRoot(
            selectedDirectory: outputRoot, userNote: Self.previewActiveCaptureInspect().userNote
        )
        #expect(stub.exportCalls.allSatisfy { $0.sessionId == "acs_recording_checkout_flow" })
        #expect(stub.exportCalls.allSatisfy { $0.outputRoot == rawRoot.path })
        #expect(stub.exportCalls.allSatisfy { $0.purpose == "workbench_user_export_recording" })
        #expect(stub.exportCalls.map(\.fallbackMode) == [.normal])
        #expect(revealed.url == rawRoot)
        #expect(controller.logStore.entries.contains { $0.contains("benchmark 转换失败") })
        controller.commitAndClose()
    }

    @MainActor
    @Test func recordingReviewWindowExportsNormalAndConvertsToBenchmark() async throws {
        final class ConversionBox { var taskExportRoot: URL? }
        final class RevealBox { var url: URL? }
        let stub = RecordingReviewPlaybackClientStub()
        let selectedDirectory = FileManager.default.temporaryDirectory
            .appendingPathComponent("workrecorder-full-export-\(UUID().uuidString)")
        let expectedTaskRoot = selectedDirectory.appendingPathComponent(
            WorkbenchRecordingBenchmarkConverter.safeFolderComponent(
                Self.previewActiveCaptureInspect().userNote ?? "recording"
            )
        ).appendingPathComponent("video", isDirectory: true)
        let benchmarkTaskDirectory = selectedDirectory
            .appendingPathComponent("benchmark/demo-task", isDirectory: true)
        let conversion = ConversionBox()
        let revealed = RevealBox()
        let controller = RecordingReviewWindowController(client: stub, logStore: AppLogStore())
        controller.chooseExportDirectory = { selectedDirectory }
        controller.convertExportToBenchmark = { taskExportRoot, sessionId in
            conversion.taskExportRoot = taskExportRoot
            #expect(sessionId == "acs_recording_checkout_flow")
            return WorkbenchRecordingBenchmarkConversionResult(
                taskExportRoot: taskExportRoot,
                benchmarkOutputRoot: benchmarkTaskDirectory.deletingLastPathComponent(),
                benchmarkTaskDirectory: benchmarkTaskDirectory,
                command: "/opt/homebrew/bin/uv run python highlight_then_benchmark.py",
                output: "converted normal recording"
            )
        }
        controller.revealInFinder = { revealed.url = $0 }
        controller.present(
            RecordingReviewOpenRequest(
                inspect: Self.previewRecordingInspect(),
                thumbnail: Self.previewThumbnail(),
                selectedStepId: "step_hotkey",
                currentMediaTimeMs: nil,
                onCommit: { _ in }
            )
        )

        controller.exportRecordingAction()
        try await Self.waitForAsyncWorkbenchUpdate {
            stub.exportCalls.count == 1 && conversion.taskExportRoot != nil && !controller.isExportInProgress
        }

        #expect(stub.exportCalls.map(\.fallbackMode) == [.normal])
        #expect(stub.exportCalls.allSatisfy { $0.outputRoot == expectedTaskRoot.path })
        #expect(conversion.taskExportRoot == expectedTaskRoot)
        #expect(revealed.url == benchmarkTaskDirectory)
        #expect(controller.logStore.entries.contains { $0.contains("benchmark 转换命令") })
        #expect(controller.logStore.entries.contains { $0.contains("完整导出与 benchmark 转换已完成") })
        controller.commitAndClose()
    }

}
