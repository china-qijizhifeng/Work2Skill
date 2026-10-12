import AppKit
import Foundation
import Testing
@testable import WorkRecorderCapture

extension WorkbenchRuntimeTests {
    @MainActor
    @Test func recordingReviewWindowMaterialsPanelUsesUserFacingSummary() throws {
        let controller = RecordingReviewWindowController(client: RecordingReviewPlaybackClientStub(), logStore: AppLogStore())
        controller.present(
            RecordingReviewOpenRequest(
                inspect: Self.previewRecordingInspect(),
                thumbnail: Self.previewThumbnail(),
                selectedStepId: "step_hotkey",
                currentMediaTimeMs: nil,
                onCommit: { _ in }
            )
        )
        controller.toggleMaterialsAction()
        var content = try #require(controller.window?.contentView)
        var labels = Self.textLabels(in: content)
        #expect(labels.contains { $0.contains("视频回放：可播放") })
        #expect(labels.contains { $0.contains("这里只展示适合复盘的安全内容。") })
        #expect(!labels.contains { $0.contains("原始录制视频") })
        #expect(!labels.contains { $0.contains("受限原始材料") })
        #expect(!labels.contains { $0.contains("read_raw_artifact") })
        #expect(!labels.contains { $0.contains("recording_video") })

        controller.toggleMaterialsAction()
        content = try #require(controller.window?.contentView)
        labels = Self.textLabels(in: content)
        #expect(labels.contains("当前步骤"))
        #expect(!labels.contains("本次录制包含"))
        controller.commitAndClose()
    }

    @MainActor
    @Test func recordingReviewWindowSnapshotsCoverLargeReviewScenarios() throws {
        let scenarios: [(String, WorkbenchEventInspectView, NSImage?, String?, CGSize, Bool)] = [
            ("recording-review-default", Self.previewRecordingInspect(), Self.previewThumbnail(), "step_hotkey", CGSize(width: 1280, height: 820), false),
            ("recording-review-materials-panel", Self.previewRecordingInspect(), Self.previewThumbnail(), "step_typing", CGSize(width: 1280, height: 820), true),
            ("recording-review-dense-long-title", Self.previewDenseRecordingInspect(), Self.previewThumbnail(), "step_dense_8", CGSize(width: 1440, height: 900), false),
            ("recording-review-keyframes-only", Self.previewRecordingWithoutVideoInspect(), Self.previewThumbnail(), "step_stop", CGSize(width: 1280, height: 820), false),
            ("recording-review-controls-folded", Self.previewControlHeavyRecordingInspect(), Self.previewThumbnail(), "ctrl_pause", CGSize(width: 1280, height: 820), false),
            ("recording-review-four-step-min-size", Self.previewRecordingInspect(), Self.previewThumbnail(), "step_hotkey", CGSize(width: 1100, height: 720), false),
            ("recording-review-narrow", Self.previewDenseRecordingInspect(), Self.previewThumbnail(), "step_dense_3", CGSize(width: 1100, height: 760), false),
            ("recording-review-min-size", Self.previewDenseRecordingInspect(), Self.previewThumbnail(), "step_dense_3", CGSize(width: 1100, height: 720), false),
        ]

        var snapshots: [SnapshotFacts] = []
        for scenario in scenarios {
            let controller = RecordingReviewWindowController(client: RecordingReviewPlaybackClientStub(), logStore: AppLogStore())
            controller.present(
                RecordingReviewOpenRequest(
                    inspect: scenario.1,
                    thumbnail: scenario.2,
                    selectedStepId: scenario.3,
                    currentMediaTimeMs: nil,
                    onCommit: { _ in }
                )
            )
            controller.window?.setContentSize(scenario.4)
            if scenario.5 {
                controller.toggleMaterialsAction()
            }
            let image = try Self.recordingReviewSnapshotImage(controller: controller)
            try Self.writeSnapshotIfRequested(image, name: scenario.0)
            let facts = try Self.snapshotFacts(image)
            snapshots.append(facts)
            controller.commitAndClose()
        }

        #expect(snapshots.count == scenarios.count)
        for snapshot in snapshots {
            #expect(snapshot.width >= 1_000)
            #expect(snapshot.height >= 700)
            #expect(snapshot.uniqueSampleCount >= 10)
            #expect(snapshot.averageLuminance > 0.24)
        }
    }

    @MainActor
    @Test func recordingReviewWindowLoadedPlaybackSnapshotUsesLargeReviewRoute() async throws {
        let client = RecordingReviewPlaybackClientStub()
        let sourceVideo = FileManager.default.temporaryDirectory
            .appendingPathComponent("workrecorder-large-review-loaded-source-\(UUID().uuidString).mp4")
        try Data("ftypdemo".utf8).write(to: sourceVideo)
        defer { try? FileManager.default.removeItem(at: sourceVideo) }
        client.playbackFileURL = sourceVideo
        let controller = RecordingReviewWindowController(client: client, logStore: AppLogStore())
        controller.present(
            RecordingReviewOpenRequest(
                inspect: Self.previewRecordingInspect(),
                thumbnail: Self.previewThumbnail(),
                selectedStepId: "step_hotkey",
                currentMediaTimeMs: nil,
                onCommit: { _ in }
            )
        )
        controller.loadPlaybackAction()
        try await Self.waitForAsyncWorkbenchUpdate {
            controller.playbackController.playbackSession != nil || controller.playbackController.errorMessage != nil
        }
        let image = try Self.recordingReviewSnapshotImage(controller: controller)
        try Self.writeSnapshotIfRequested(image, name: "recording-review-loaded-playback")
        let facts = try Self.snapshotFacts(image)
        #expect(facts.width >= 1_000)
        #expect(facts.height >= 700)
        #expect(facts.uniqueSampleCount >= 10)
        let request = try #require(client.requests.first)
        #expect(request.purpose == "workbench_large_recording_review")
        let session = try #require(controller.playbackController.playbackSession)
        controller.commitAndClose()
        #expect(!FileManager.default.fileExists(atPath: session.fileURL.path))
    }

    @MainActor
    private static func recordingReviewSnapshotImage(controller: RecordingReviewWindowController) throws -> NSImage {
        let content = try #require(controller.window?.contentView)
        content.layoutSubtreeIfNeeded()
        let bounds = content.bounds
        #expect(bounds.width > 0)
        #expect(bounds.height > 0)
        let rep = try #require(content.bitmapImageRepForCachingDisplay(in: bounds))
        content.cacheDisplay(in: bounds, to: rep)
        let image = NSImage(size: bounds.size)
        image.lockFocus()
        NSColor(calibratedRed: 0.955, green: 0.985, blue: 0.99, alpha: 1).setFill()
        NSBezierPath(rect: bounds).fill()
        rep.draw(in: bounds)
        image.unlockFocus()
        return image
    }

    static func recordingTimerStep(
        id: String,
        mediaTimeMs: Int,
        sequenceIndex: Int
    ) -> WorkbenchRecordingTimelineStepView {
        WorkbenchRecordingTimelineStepView(
            stepId: id,
            kind: .keyframe,
            occurredAt: "2026-05-18T13:08:00Z",
            mediaTimeMs: mediaTimeMs,
            sequenceIndex: sequenceIndex,
            keyframeId: "kf_\(id)",
            actionId: nil,
            controlId: nil,
            keyframeRole: "timer",
            triggerKind: "timer",
            actionKind: nil,
            actionSummary: nil,
            controlKind: nil,
            safeCaption: "低变化定时帧。",
            needsReview: false,
            readiness: readyRecordingStep()
        )
    }
}
