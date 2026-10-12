import Foundation
@testable import WorkRecorderCapture

extension WorkbenchRuntimeTests {
    static func previewLongRecordingCard() -> SearchCardView {
        previewRecordingCard(
            eventId: "evt_recording_long_checkout_flow",
            source: previewLongRecordingSource(),
            note: "这是一条故意很长的保存备注，用来确认录制卡片不会因为备注、标题和来源同时变长而互相挤压；列表里应该优先展示预览图和复盘意图。",
            snippet: "长标题、长备注、复杂来源都应稳定截断。",
            hasVideo: true
        )
    }

    static func previewRecordingWithoutVideoCard() -> SearchCardView {
        previewRecordingCard(
            eventId: "evt_recording_keyframes_only",
            source: previewKeyframeOnlyRecordingSource(),
            note: "视频未入库，但关键帧、点击和滚动摘要仍可复盘。",
            snippet: "只有关键帧时间线，没有原始视频。",
            hasVideo: false
        )
    }

    static func previewDenseRecordingInspect() -> WorkbenchEventInspectView {
        previewRecordingInspect(
            eventId: "evt_recording_long_checkout_flow",
            source: previewLongRecordingSource(),
            activeCapture: previewDenseActiveCaptureInspect()
        )
    }

    static func previewRecordingWithoutVideoInspect() -> WorkbenchEventInspectView {
        previewRecordingInspect(
            eventId: "evt_recording_keyframes_only",
            source: previewKeyframeOnlyRecordingSource(),
            activeCapture: previewKeyframeOnlyActiveCaptureInspect()
        )
    }

    static func previewControlHeavyRecordingInspect() -> WorkbenchEventInspectView {
        previewRecordingInspect(
            eventId: "evt_control_heavy",
            source: SearchSourceView(
                appName: "Code",
                title: "agent_runtime_surface_trace_design.md — nexcua",
                origin: nil,
                sanitizedURL: nil
            ),
            activeCapture: previewControlHeavyActiveCaptureInspect()
        )
    }

    static func previewDenseActiveCaptureInspect() -> WorkbenchActiveCaptureInspectView {
        WorkbenchActiveCaptureInspectView(
            sessionId: "acs_recording_long_checkout_flow",
            mode: .recordingSession,
            primaryEventId: "evt_recording_long_checkout_flow",
            status: .completedWithWarnings,
            startedAt: "2026-05-18T13:08:00Z",
            endedAt: "2026-05-18T13:11:18Z",
            userNote: "这是一条故意很长的保存备注，用来确认详情页在高密度时间线下仍然有清楚层级。",
            warnings: ["15 个步骤里有 2 个目标置信度偏低，播放前仍保持安全摘要。"],
            timeline: previewDenseRecordingTimeline(),
            safeTextBlocks: previewRecordingSafeTextBlocks(),
            videoRef: WorkbenchRecordingVideoInspectRef(
                artifactId: "art_recording_video_long",
                state: .available,
                contentType: "video/mp4",
                durationMs: 198_000,
                byteSize: 84_200_000,
                alignmentErrorMs: 46
            ),
            skillReadiness: WorkbenchSkillReadinessSummary(
                state: .needsReview,
                reasons: ["target_low_confidence", "long_session_truncated"],
                reviewItemCount: 2,
                blockedItemCount: 0,
                missingEvidence: []
            ),
            projection: WorkbenchProjectionTruncationSummary(
                truncated: true,
                truncatedCounts: ["timeline_steps": 9],
                nextCursor: "142000:12"
            )
        )
    }

    static func previewKeyframeOnlyActiveCaptureInspect() -> WorkbenchActiveCaptureInspectView {
        WorkbenchActiveCaptureInspectView(
            sessionId: "acs_recording_keyframes_only",
            mode: .recordingSession,
            primaryEventId: "evt_recording_keyframes_only",
            status: .completedWithWarnings,
            startedAt: "2026-05-18T13:08:00Z",
            endedAt: "2026-05-18T13:08:22Z",
            userNote: "视频未入库，但关键帧、点击和滚动摘要仍可复盘。",
            warnings: ["视频文件未通过入库校验，已保留关键帧时间线。"],
            timeline: WorkbenchRecordingTimelineInspectView(
                sessionId: "acs_recording_keyframes_only",
                durationMs: 22_000,
                alignmentErrorMs: nil,
                steps: [previewRecordingStartStep(), previewRecordingStopStep(mediaTimeMs: 22_000)]
            ),
            safeTextBlocks: previewRecordingSafeTextBlocks(),
            videoRef: WorkbenchRecordingVideoInspectRef(
                artifactId: nil,
                state: .failed,
                contentType: nil,
                durationMs: nil,
                byteSize: nil,
                alignmentErrorMs: nil
            ),
            skillReadiness: WorkbenchSkillReadinessSummary(
                state: .needsReview,
                reasons: ["video_missing"],
                reviewItemCount: 1,
                blockedItemCount: 0,
                missingEvidence: ["recording_video"]
            ),
            projection: WorkbenchProjectionTruncationSummary(truncated: false, truncatedCounts: [:], nextCursor: nil)
        )
    }

    static func previewControlHeavyActiveCaptureInspect() -> WorkbenchActiveCaptureInspectView {
        let steps = [
            previewRecordingStartStep(),
            previewControlHeavyMarkStep(),
            previewControlHeavyStep(id: "ctrl_pause", kind: .pause, mediaTimeMs: nil, sequenceIndex: 2),
            previewControlHeavyStep(id: "ctrl_resume", kind: .resume, mediaTimeMs: nil, sequenceIndex: 3),
            previewControlHeavyStep(id: "ctrl_user_mark_a", kind: .userMark, mediaTimeMs: nil, sequenceIndex: 4),
            previewControlHeavyStep(id: "ctrl_user_mark_b", kind: .userMark, mediaTimeMs: nil, sequenceIndex: 5),
            previewControlHeavyStep(id: "ctrl_start_segment", kind: .startSegment, mediaTimeMs: nil, sequenceIndex: 6),
            previewRecordingStopStep(mediaTimeMs: 5_000, sequenceIndex: 7),
        ]
        return WorkbenchActiveCaptureInspectView(
            sessionId: "acs_control_heavy",
            mode: .recordingSession,
            primaryEventId: "evt_control_heavy",
            status: .completed,
            startedAt: "2026-05-18T13:08:00Z",
            endedAt: "2026-05-18T13:08:05Z",
            userNote: "保存后复查：暂停和继续已折叠为后台控制。",
            warnings: [],
            timeline: WorkbenchRecordingTimelineInspectView(
                sessionId: "acs_control_heavy",
                durationMs: 5_000,
                alignmentErrorMs: nil,
                steps: steps
            ),
            safeTextBlocks: [
                WorkbenchRecordingSafeTextBlock(
                    blockId: "summary",
                    sourceField: "human_demo_summary",
                    eventId: "evt_control_heavy",
                    text: "录制包含一次手动标记，暂停和继续已折叠到后台控制记录。",
                    textTruncated: false,
                    confidence: 0.84
                ),
                WorkbenchRecordingSafeTextBlock(
                    blockId: "mark_text",
                    sourceField: "keyframe_caption",
                    eventId: "kf_mark",
                    text: "用户在文档页面手动标记了关键段落。",
                    textTruncated: false,
                    confidence: 0.88
                ),
            ],
            videoRef: WorkbenchRecordingVideoInspectRef(
                artifactId: "art_control_heavy_video",
                state: .available,
                contentType: "video/mp4",
                durationMs: 5_000,
                byteSize: 191_044,
                alignmentErrorMs: nil
            ),
            skillReadiness: readyRecordingStep(),
            projection: WorkbenchProjectionTruncationSummary(truncated: false, truncatedCounts: [:], nextCursor: nil)
        )
    }

    private static func previewLongRecordingSource() -> SearchSourceView {
        SearchSourceView(
            appName: "Google Chrome",
            title: "录制复盘：从非常长的后台控制台标题里定位 OAuth 回调配置、批量复制环境变量并完成生产验证",
            origin: "https://console.example.com",
            sanitizedURL: "https://console.example.com/settings/integrations"
        )
    }

    private static func previewKeyframeOnlyRecordingSource() -> SearchSourceView {
        SearchSourceView(
            appName: "Finder",
            title: "关键帧复盘：整理本地发票文件夹",
            origin: nil,
            sanitizedURL: nil
        )
    }

    private static func previewDenseRecordingTimeline() -> WorkbenchRecordingTimelineInspectView {
        let actions: [WorkbenchRecordingActionKind] = [
            .click, .scroll, .hotkey, .typingPause, .click, .scroll,
            .windowSwitch, .tabSwitch, .hotkey, .typingPause, .userMark, .click,
        ]
        let steps = [previewRecordingStartStep()] + actions.enumerated().map { index, action in
            WorkbenchRecordingTimelineStepView(
                stepId: "step_dense_\(index)",
                kind: .action,
                occurredAt: "2026-05-18T13:08:\(String(format: "%02d", min(59, 4 + index * 9)))Z",
                mediaTimeMs: 4_000 + index * 11_200,
                sequenceIndex: index + 1,
                keyframeId: nil,
                actionId: "act_dense_\(index)",
                controlId: nil,
                keyframeRole: nil,
                triggerKind: action == .typingPause ? "typing_settle" : "action_settle",
                actionKind: action,
                actionSummary: action == .hotkey ? previewRecordingHotkeyAction() : nil,
                controlKind: nil,
                safeCaption: denseCaption(action: action, index: index),
                needsReview: index == 3 || index == 8,
                readiness: index == 3 || index == 8 ? reviewRecordingStep() : readyRecordingStep()
            )
        } + [previewRecordingStopStep(mediaTimeMs: 198_000, sequenceIndex: 13)]
        return WorkbenchRecordingTimelineInspectView(
            sessionId: "acs_recording_long_checkout_flow",
            durationMs: 198_000,
            alignmentErrorMs: 46,
            steps: steps
        )
    }

    private static func previewControlHeavyMarkStep() -> WorkbenchRecordingTimelineStepView {
        WorkbenchRecordingTimelineStepView(
            stepId: "step_user_mark",
            kind: .control,
            occurredAt: "2026-05-18T13:08:03Z",
            mediaTimeMs: 3_000,
            sequenceIndex: 1,
            keyframeId: "kf_mark",
            actionId: nil,
            controlId: "ctrl_mark",
            keyframeRole: "user_mark",
            triggerKind: "user_mark",
            actionKind: nil,
            actionSummary: nil,
            controlKind: .userMark,
            safeCaption: "user marked this moment",
            needsReview: false,
            readiness: readyRecordingStep()
        )
    }

    private static func previewControlHeavyStep(
        id: String,
        kind: WorkbenchRecordingControlKind,
        mediaTimeMs: Int?,
        sequenceIndex: Int
    ) -> WorkbenchRecordingTimelineStepView {
        WorkbenchRecordingTimelineStepView(
            stepId: id,
            kind: .control,
            occurredAt: "2026-05-18T13:08:03Z",
            mediaTimeMs: mediaTimeMs,
            sequenceIndex: sequenceIndex,
            keyframeId: nil,
            actionId: nil,
            controlId: id,
            keyframeRole: nil,
            triggerKind: nil,
            actionKind: nil,
            actionSummary: nil,
            controlKind: kind,
            safeCaption: "recording control: \(kind.title.lowercased())",
            needsReview: false,
            readiness: readyRecordingStep()
        )
    }

    private static func denseCaption(action: WorkbenchRecordingActionKind, index: Int) -> String {
        switch action {
        case .click:
            return "点击设置面板中的第 \(index + 1) 个配置入口"
        case .scroll:
            return "滚动到下一组配置，并保持边界在录制区域内"
        case .hotkey:
            return "使用 ⌘K 打开命令面板并定位配置项"
        case .typingPause:
            return "输入参数摘要后暂停，普通文本没有保存原文"
        case .windowSwitch:
            return "窗口焦点切换，后续步骤需要确认目标"
        case .tabSwitch:
            return "切换到验证结果标签页"
        case .userMark:
            return "用户手动标记了关键验证节点"
        case .unknown(let value):
            return value
        }
    }
}
