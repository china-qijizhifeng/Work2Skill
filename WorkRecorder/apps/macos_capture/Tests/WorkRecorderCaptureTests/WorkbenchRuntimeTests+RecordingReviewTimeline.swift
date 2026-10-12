import AppKit
import Foundation
import Testing
@testable import WorkRecorderCapture

extension WorkbenchRuntimeTests {
    @MainActor
    @Test func recordingReviewCoreFollowsPreviousStepAndCollapsesLowValueFrames() throws {
        let start = Self.previewRecordingStartStep()
        let timerA = Self.recordingTimerStep(id: "timer_a", mediaTimeMs: 1_000, sequenceIndex: 1)
        let timerB = Self.recordingTimerStep(id: "timer_b", mediaTimeMs: 2_000, sequenceIndex: 2)
        let typingTimeout = WorkbenchRecordingTimelineStepView(
            stepId: "typing_timeout",
            kind: .keyframe,
            occurredAt: "2026-05-18T13:08:03Z",
            mediaTimeMs: 3_000,
            sequenceIndex: 3,
            keyframeId: "kf_typing_timeout",
            visibilityClass: "folded",
            foldReason: "timeout_no_change",
            actionId: nil,
            controlId: nil,
            keyframeRole: "result",
            triggerKind: "typing_settle",
            actionKind: nil,
            actionSummary: nil,
            controlKind: nil,
            safeCaption: "输入暂停",
            needsReview: true,
            readiness: Self.readyRecordingStep()
        )
        let action = WorkbenchRecordingTimelineStepView(
            stepId: "action_click",
            kind: .action,
            occurredAt: "2026-05-18T13:08:05Z",
            mediaTimeMs: 5_000,
            sequenceIndex: 4,
            keyframeId: nil,
            actionId: "act_click",
            controlId: nil,
            keyframeRole: nil,
            triggerKind: "click_settle",
            actionKind: .click,
            actionSummary: nil,
            controlKind: nil,
            safeCaption: "点击确认按钮。",
            needsReview: false,
            readiness: Self.readyRecordingStep()
        )
        let foldedTypingAction = WorkbenchRecordingTimelineStepView(
            stepId: "action_typing_pause",
            kind: .action,
            occurredAt: "2026-05-18T13:08:05Z",
            mediaTimeMs: 5_200,
            sequenceIndex: 5,
            keyframeId: nil,
            visibilityClass: "folded",
            foldReason: "typing_trace_only",
            actionId: "act_typing_pause",
            controlId: nil,
            keyframeRole: nil,
            triggerKind: "typing_settle",
            actionKind: .typingPause,
            actionSummary: nil,
            controlKind: nil,
            safeCaption: "输入暂停",
            needsReview: false,
            readiness: Self.readyRecordingStep()
        )
        let targetProbe = WorkbenchRecordingTimelineStepView(
            stepId: "target_probe",
            kind: .keyframe,
            occurredAt: "2026-05-18T13:08:05Z",
            mediaTimeMs: 5_400,
            sequenceIndex: 5,
            keyframeId: "kf_target_probe",
            actionId: nil,
            controlId: nil,
            keyframeRole: "result",
            triggerKind: "target_resolution_probe",
            actionKind: nil,
            actionSummary: nil,
            controlKind: nil,
            safeCaption: "目标待确认",
            needsReview: true,
            readiness: Self.readyRecordingStep()
        )
        let timerC = Self.recordingTimerStep(id: "timer_c", mediaTimeMs: 6_000, sequenceIndex: 6)
        let stop = Self.previewRecordingStopStep(mediaTimeMs: 10_000, sequenceIndex: 7)
        let steps = [timerB, stop, targetProbe, start, timerC, foldedTypingAction, action, typingTimeout, timerA]

        let visibility = RecordingReviewCore.visibleTimelineSteps(
            steps,
            selectedStepId: nil,
            density: RecordingReviewTimelineDensityConfig(representativeTimerIntervalMs: 8_000)
        )
        #expect(visibility.visibleSteps.map { $0.stepId } == ["step_start", "timer_a", "action_click", "step_stop"])
        #expect(visibility.hiddenLowValueStepCount == 5)
        #expect(RecordingReviewCore.followStep(in: visibility.visibleSteps, mediaTimeMs: 4_900)?.stepId == "timer_a")
        #expect(RecordingReviewCore.followStep(in: visibility.visibleSteps, mediaTimeMs: 5_001)?.stepId == "action_click")
    }

    @MainActor
    @Test func recordingReviewWindowKeyboardStepNavigationSkipsFoldedLowValueFrames() throws {
        let start = Self.previewRecordingStartStep()
        let timerA = Self.recordingTimerStep(id: "timer_a", mediaTimeMs: 1_000, sequenceIndex: 1)
        let timerB = Self.recordingTimerStep(id: "timer_b", mediaTimeMs: 2_000, sequenceIndex: 2)
        let action = WorkbenchRecordingTimelineStepView(
            stepId: "action_click",
            kind: .action,
            occurredAt: "2026-05-18T13:08:05Z",
            mediaTimeMs: 5_000,
            sequenceIndex: 3,
            keyframeId: nil,
            actionId: "act_click",
            controlId: nil,
            keyframeRole: nil,
            triggerKind: "click_settle",
            actionKind: .click,
            actionSummary: nil,
            controlKind: nil,
            safeCaption: "点击确认按钮。",
            needsReview: false,
            readiness: Self.readyRecordingStep()
        )
        let timerC = Self.recordingTimerStep(id: "timer_c", mediaTimeMs: 6_000, sequenceIndex: 4)
        let stop = Self.previewRecordingStopStep(mediaTimeMs: 10_000, sequenceIndex: 5)
        let recording = WorkbenchActiveCaptureInspectView(
            sessionId: "acs_folded_timeline",
            mode: .recordingSession,
            primaryEventId: "evt_folded_timeline",
            status: .completed,
            startedAt: "2026-05-18T13:08:00Z",
            endedAt: "2026-05-18T13:08:10Z",
            userNote: nil,
            warnings: [],
            timeline: WorkbenchRecordingTimelineInspectView(
                sessionId: "acs_folded_timeline",
                durationMs: 10_000,
                alignmentErrorMs: nil,
                steps: [start, timerA, timerB, action, timerC, stop]
            ),
            safeTextBlocks: [],
            videoRef: WorkbenchRecordingVideoInspectRef(
                artifactId: nil,
                state: .failed,
                contentType: nil,
                durationMs: nil,
                byteSize: nil,
                alignmentErrorMs: nil
            ),
            skillReadiness: Self.readyRecordingStep(),
            projection: WorkbenchProjectionTruncationSummary(truncated: false, truncatedCounts: [:], nextCursor: nil)
        )
        let inspect = Self.previewRecordingInspect(
            eventId: "evt_folded_timeline",
            source: SearchSourceView(appName: "Chrome", title: "折叠时间线测试", origin: nil, sanitizedURL: nil),
            activeCapture: recording
        )
        let controller = RecordingReviewWindowController(client: RecordingReviewPlaybackClientStub(), logStore: AppLogStore())
        controller.present(
            RecordingReviewOpenRequest(
                inspect: inspect,
                thumbnail: nil,
                selectedStepId: "timer_a",
                currentMediaTimeMs: 1_000,
                onCommit: { _ in }
            )
        )

        controller.selectStep(offset: 1)

        #expect(controller.state.selectedStepId == "action_click")
        controller.commitAndClose()
    }

    @MainActor
    @Test func recordingReviewCoreKeepsTypingMilestoneWhenItHasResultEvidence() throws {
        let start = Self.previewRecordingStartStep()
        let typing = WorkbenchRecordingTimelineStepView(
            stepId: "action_typing_result",
            kind: .action,
            occurredAt: "2026-05-18T13:08:03Z",
            mediaTimeMs: 3_000,
            sequenceIndex: 2,
            keyframeId: nil,
            visibilityClass: "visible",
            foldReason: nil,
            actionId: "act_typing_result",
            controlId: nil,
            keyframeRole: nil,
            triggerKind: "typing_settle",
            actionKind: .typingPause,
            actionSummary: WorkbenchRecordingActionSummaryView(
                actionId: "act_typing_result",
                actionKind: .typingPause,
                keyChord: nil,
                typingSummary: WorkbenchRecordingTypingSummary(
                    eventCount: 12,
                    textEventCount: 12,
                    characterCount: 12,
                    deletionKeyCount: 0,
                    nonTextKeyCount: 0,
                    compositionUsed: false,
                    submittedByEnter: false,
                    durationMs: 900
                ),
                beforeKeyframeIds: [],
                afterKeyframeIds: ["kf_typing_after"],
                resultKeyframeId: "kf_typing_after"
            ),
            controlKind: nil,
            safeCaption: "文本输入 · 约 12 字",
            needsReview: false,
            readiness: Self.readyRecordingStep()
        )
        let stop = Self.previewRecordingStopStep(mediaTimeMs: 6_000, sequenceIndex: 3)

        let visibility = RecordingReviewCore.visibleTimelineSteps([stop, typing, start], selectedStepId: nil)

        #expect(visibility.visibleSteps.map(\.stepId) == ["step_start", "action_typing_result", "step_stop"])
        #expect(visibility.hiddenLowValueStepCount == 0)
    }

    @MainActor
    @Test func recordingReviewWindowHidesInternalControlsAndLocalizesControlCaptions() throws {
        let inspect = Self.previewControlHeavyRecordingInspect()
        let recording = try #require(inspect.activeCapture)
        let visibility = RecordingReviewCore.visibleTimelineSteps(recording.timeline?.steps ?? [], selectedStepId: "ctrl_pause")
        #expect(visibility.visibleSteps.map(\.stepId) == ["step_start", "step_user_mark", "step_stop"])
        #expect(visibility.hiddenLowValueStepCount == 5)

        let controller = RecordingReviewWindowController(client: RecordingReviewPlaybackClientStub(), logStore: AppLogStore())
        controller.present(
            RecordingReviewOpenRequest(
                inspect: inspect,
                thumbnail: Self.previewThumbnail(),
                selectedStepId: "ctrl_pause",
                currentMediaTimeMs: nil,
                onCommit: { _ in }
            )
        )
        let content = try #require(controller.window?.contentView)
        let labels = Self.textLabels(in: content)
        let markerBar = try #require(Self.views(ofType: RecordingTimelineMarkerBarView.self, in: content).first)
        #expect(markerBar.representedStepIds == ["step_start", "step_user_mark", "step_stop"])
        #expect(labels.contains { $0.contains("手动标记") })
        #expect(labels.contains { $0.contains("录制包含一次手动标记") })
        #expect(labels.contains("本次复盘"))
        #expect(labels.contains("保存备注"))
        #expect(labels.contains { $0.contains("暂停和继续已折叠") })
        #expect(labels.contains("快捷键"))
        #expect(labels.contains("播放 / 暂停"))
        #expect(labels.contains { $0.contains("已折叠 5 个后台控制") })
        #expect(!labels.contains { $0.contains("user mark") })
        #expect(!labels.contains { $0.contains("recording control") })
        #expect(!labels.contains { $0.contains("recording started") })
        #expect(!labels.contains { $0.contains("recording ended") })
        #expect(!labels.contains("录制概况"))
        #expect(!labels.contains { $0.contains("开始片段") })
        #expect(!labels.contains { $0.contains("已锁定") })
        controller.commitAndClose()
    }
}
