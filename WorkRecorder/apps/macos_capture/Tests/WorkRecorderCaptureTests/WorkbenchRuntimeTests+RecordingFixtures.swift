import Foundation
@testable import WorkRecorderCapture

extension WorkbenchRuntimeTests {
    static func previewRecordingCard() -> SearchCardView {
        previewRecordingCard(
            eventId: "evt_recording_checkout_flow",
            source: previewRecordingSource(),
            note: "演示从文档定位 API key 页面、打开命令面板、完成轮换并验证请求。",
            snippet: "录制时间线、快捷键和输入摘要已整理。",
            hasVideo: true
        )
    }

    static func previewRecordingVideoOnlyMarkerCard() -> SearchCardView {
        SearchCardView(
            eventId: "evt_recording_video_only_marker",
            eventType: "screen.region.captured",
            capturedAt: "2026-05-18T13:10:00Z",
            source: previewRecordingSource(),
            selectionBBox: previewRecordingBounds(),
            userNote: "真实后端保存的录制卡片，只有 recording_video artifact marker。",
            selectionText: nil,
            selectionTextSnippet: "真实录制视频已入库。",
            selectionTextTruncated: false,
            previewConfidence: 0,
            hiddenArtifacts: ["recording_video", "screenshot"],
            sourceKind: "desktop_window"
        )
    }

    static func previewRecordingCard(
        eventId: String,
        source: SearchSourceView,
        note: String,
        snippet: String,
        hasVideo: Bool
    ) -> SearchCardView {
        var hiddenArtifacts = [
            "active_capture_raw_materials",
            "active_capture_recording",
            "screenshot",
            "a11y_tree",
        ]
        if hasVideo {
            hiddenArtifacts.append("recording_video")
        }
        return SearchCardView(
            eventId: eventId,
            eventType: "screen.recording.completed",
            capturedAt: "2026-05-18T13:08:00Z",
            source: source,
            selectionBBox: previewRecordingBounds(),
            userNote: note,
            selectionText: nil,
            selectionTextSnippet: snippet,
            selectionTextTruncated: false,
            previewConfidence: 0.0,
            hiddenArtifacts: hiddenArtifacts,
            providerContributions: ["system.recording", "macos.accessibility"],
            providerDiagnosticsCount: 0,
            sourceKind: "region_recording"
        )
    }

    static func previewRecordingInspect() -> WorkbenchEventInspectView {
        previewRecordingInspect(
            eventId: "evt_recording_checkout_flow",
            source: previewRecordingSource(),
            activeCapture: previewActiveCaptureInspect()
        )
    }

    static func previewRecordingInspect(
        eventId: String,
        source: SearchSourceView,
        activeCapture: WorkbenchActiveCaptureInspectView
    ) -> WorkbenchEventInspectView {
        WorkbenchEventInspectView(
            eventId: eventId,
            capturedAt: "2026-05-18T13:08:00Z",
            source: source,
            selectionBBox: previewRecordingBounds(),
            canonicalText: "",
            cleanPageText: "",
            readableEvidence: previewRecordingReadableEvidence(),
            rawArtifacts: previewRecordingRawArtifacts(),
            hiddenArtifacts: previewRecordingHiddenArtifacts(),
            activeCapture: activeCapture,
            disclosureDecision: WorkbenchDisclosureDecisionView(allowed: true, redactionState: "redacted")
        )
    }

    static func previewActiveCaptureInspect() -> WorkbenchActiveCaptureInspectView {
        WorkbenchActiveCaptureInspectView(
            sessionId: "acs_recording_checkout_flow",
            mode: .recordingSession,
            primaryEventId: "evt_recording_checkout_flow",
            status: .completedWithWarnings,
            startedAt: "2026-05-18T13:08:00Z",
            endedAt: "2026-05-18T13:08:46Z",
            userNote: "演示从文档定位 API key 页面、打开命令面板、完成轮换并验证请求。",
            warnings: ["辅助功能权限缺失，目标识别降级为窗口级摘要。"],
            timeline: previewRecordingTimeline(),
            safeTextBlocks: previewRecordingSafeTextBlocks(),
            videoRef: previewRecordingVideoRef(),
            skillReadiness: previewRecordingSkillReadiness(),
            projection: WorkbenchProjectionTruncationSummary(truncated: false, truncatedCounts: [:], nextCursor: nil)
        )
    }

    private static func previewRecordingSource() -> SearchSourceView {
        SearchSourceView(
            appName: "Google Chrome",
            title: "录制复盘：API 文档里完成密钥轮换流程",
            origin: "https://platform.openai.com",
            sanitizedURL: "https://platform.openai.com/docs"
        )
    }

    private static func previewRecordingBounds() -> WorkbenchBoundingBoxView {
        WorkbenchBoundingBoxView(x: 240, y: 164, width: 1280, height: 760, coordinateSpace: "macos_global")
    }

    private static func previewRecordingReadableEvidence() -> [WorkbenchReadableEvidenceView] {
        [
            WorkbenchReadableEvidenceView(
                artifactId: "art_recording_safe_summary",
                artifactType: "recording_timeline",
                role: "human_demo_summary",
                evidenceId: "ev_recording_safe_summary",
                disclosureClass: "safe_metadata",
                text: "打开 API 文档，使用 ⌘K 搜索 API key，滚动到轮换说明，输入参数摘要并提交验证。",
                confidence: 0.91,
                truncated: false
            )
        ]
    }

    private static func previewRecordingRawArtifacts() -> [WorkbenchRawArtifactRef] {
        [
            WorkbenchRawArtifactRef(
                artifactId: "art_recording_video",
                artifactType: "recording_video",
                role: "video",
                contentType: "video/mp4",
                disclosureClass: "raw_visual_evidence",
                requiresScope: "read_raw_artifact"
            )
        ]
    }

    private static func previewRecordingHiddenArtifacts() -> [WorkbenchHiddenArtifactSummary] {
        [
            WorkbenchHiddenArtifactSummary(
                artifactType: "recording_video",
                role: "video",
                disclosureClass: "raw_visual_evidence",
                reason: "原始录制视频默认锁定"
            ),
            WorkbenchHiddenArtifactSummary(
                artifactType: "a11y_tree",
                role: "ui_structure",
                disclosureClass: "raw_source_material",
                reason: "界面结构默认锁定"
            ),
        ]
    }

    private static func previewRecordingTimeline() -> WorkbenchRecordingTimelineInspectView {
        WorkbenchRecordingTimelineInspectView(
            sessionId: "acs_recording_checkout_flow",
            durationMs: 46_000,
            alignmentErrorMs: 38,
            steps: [
                previewRecordingStartStep(),
                previewRecordingHotkeyStep(),
                previewRecordingTypingStep(),
                previewRecordingStopStep(),
            ]
        )
    }

    static func previewRecordingStartStep() -> WorkbenchRecordingTimelineStepView {
        WorkbenchRecordingTimelineStepView(
            stepId: "step_start",
            kind: .keyframe,
            occurredAt: "2026-05-18T13:08:00Z",
            mediaTimeMs: 0,
            sequenceIndex: 0,
            keyframeId: "kf_start",
            actionId: nil,
            controlId: nil,
            keyframeRole: "start",
            triggerKind: "recording_start",
            actionKind: nil,
            actionSummary: nil,
            controlKind: nil,
            safeCaption: "录制开始，边界已确认。",
            needsReview: false,
            readiness: readyRecordingStep()
        )
    }

    private static func previewRecordingHotkeyStep() -> WorkbenchRecordingTimelineStepView {
        WorkbenchRecordingTimelineStepView(
            stepId: "step_hotkey",
            kind: .action,
            occurredAt: "2026-05-18T13:08:08Z",
            mediaTimeMs: 8_120,
            sequenceIndex: 1,
            keyframeId: nil,
            actionId: "act_cmd_k",
            controlId: nil,
            keyframeRole: nil,
            triggerKind: "hotkey_settle",
            actionKind: .hotkey,
            actionSummary: previewRecordingHotkeyAction(),
            controlKind: nil,
            safeCaption: "按下 ⌘K 打开命令面板。",
            needsReview: false,
            readiness: readyRecordingStep()
        )
    }

    private static func previewRecordingTypingStep() -> WorkbenchRecordingTimelineStepView {
        WorkbenchRecordingTimelineStepView(
            stepId: "step_typing",
            kind: .action,
            occurredAt: "2026-05-18T13:08:19Z",
            mediaTimeMs: 19_460,
            sequenceIndex: 2,
            keyframeId: nil,
            actionId: "act_typing",
            controlId: nil,
            keyframeRole: nil,
            triggerKind: "typing_settle",
            actionKind: .typingPause,
            actionSummary: previewRecordingTypingAction(),
            controlKind: nil,
            safeCaption: "输入一段查询摘要，并通过 Enter 提交。",
            needsReview: true,
            readiness: reviewRecordingStep()
        )
    }

    static func previewRecordingStopStep() -> WorkbenchRecordingTimelineStepView {
        previewRecordingStopStep(mediaTimeMs: 46_000)
    }

    static func previewRecordingStopStep(mediaTimeMs: Int, sequenceIndex: Int = 3) -> WorkbenchRecordingTimelineStepView {
        WorkbenchRecordingTimelineStepView(
            stepId: "step_stop",
            kind: .control,
            occurredAt: "2026-05-18T13:08:46Z",
            mediaTimeMs: mediaTimeMs,
            sequenceIndex: sequenceIndex,
            keyframeId: "kf_final",
            actionId: nil,
            controlId: "ctrl_stop",
            keyframeRole: "final",
            triggerKind: "recording_stop",
            actionKind: nil,
            actionSummary: nil,
            controlKind: .stop,
            safeCaption: "录制结束，已生成最终关键帧。",
            needsReview: false,
            readiness: readyRecordingStep()
        )
    }

    static func previewRecordingHotkeyAction() -> WorkbenchRecordingActionSummaryView {
        WorkbenchRecordingActionSummaryView(
            actionId: "act_cmd_k",
            actionKind: .hotkey,
            keyChord: WorkbenchRecordingKeyChord(
                physicalKeyCode: 40,
                normalizedKeyLabel: "k",
                modifiers: ["command"],
                keyboardLayoutId: "com.apple.keylayout.US",
                isRepeat: false,
                semantic: "command_palette",
                characters: nil
            ),
            typingSummary: nil,
            beforeKeyframeIds: ["kf_start"],
            afterKeyframeIds: ["kf_cmdk_after"],
            resultKeyframeId: "kf_cmdk_after"
        )
    }

    private static func previewRecordingTypingAction() -> WorkbenchRecordingActionSummaryView {
        WorkbenchRecordingActionSummaryView(
            actionId: "act_typing",
            actionKind: .typingPause,
            keyChord: nil,
            typingSummary: WorkbenchRecordingTypingSummary(
                eventCount: 18,
                textEventCount: 13,
                characterCount: 14,
                deletionKeyCount: 1,
                nonTextKeyCount: 4,
                compositionUsed: false,
                submittedByEnter: true,
                durationMs: 3_800
            ),
            beforeKeyframeIds: ["kf_cmdk_after"],
            afterKeyframeIds: ["kf_typing_after"],
            resultKeyframeId: "kf_typing_after"
        )
    }

    static func previewRecordingSafeTextBlocks() -> [WorkbenchRecordingSafeTextBlock] {
        [
            WorkbenchRecordingSafeTextBlock(
                blockId: "safe_recording_summary",
                sourceField: "human_demo_summary",
                eventId: "evt_recording_checkout_flow",
                text: "快捷键、输入摘要和关键帧已对齐；普通输入没有保存原文。",
                textTruncated: false,
                confidence: 0.91
            ),
            WorkbenchRecordingSafeTextBlock(
                blockId: "safe_start",
                sourceField: "keyframe_caption",
                eventId: "kf_start",
                text: "录制开始：Chrome 文档窗口位于选区内。",
                textTruncated: false,
                confidence: 0.88
            ),
            WorkbenchRecordingSafeTextBlock(
                blockId: "safe_cmdk_after",
                sourceField: "keyframe_caption",
                eventId: "kf_cmdk_after",
                text: "命令面板已打开，当前焦点在搜索输入框。",
                textTruncated: false,
                confidence: 0.90
            ),
            WorkbenchRecordingSafeTextBlock(
                blockId: "safe_typing_after",
                sourceField: "keyframe_caption",
                eventId: "kf_typing_after",
                text: "输入摘要提交后出现验证结果列表。",
                textTruncated: false,
                confidence: 0.86
            ),
            WorkbenchRecordingSafeTextBlock(
                blockId: "safe_final",
                sourceField: "keyframe_caption",
                eventId: "kf_final",
                text: "录制结束，最终窗口停留在验证结果页。",
                textTruncated: false,
                confidence: 0.92
            )
        ]
    }

    private static func previewRecordingVideoRef() -> WorkbenchRecordingVideoInspectRef {
        WorkbenchRecordingVideoInspectRef(
            artifactId: "art_recording_video",
            state: .available,
            contentType: "video/mp4",
            durationMs: 46_000,
            byteSize: 18_400_000,
            alignmentErrorMs: 38
        )
    }

    static func readyRecordingStep() -> WorkbenchSkillReadinessSummary {
        WorkbenchSkillReadinessSummary(state: .ready, reasons: [], reviewItemCount: 0, blockedItemCount: 0, missingEvidence: [])
    }

    static func reviewRecordingStep() -> WorkbenchSkillReadinessSummary {
        WorkbenchSkillReadinessSummary(
            state: .needsReview,
            reasons: ["target_low_confidence"],
            reviewItemCount: 1,
            blockedItemCount: 0,
            missingEvidence: []
        )
    }

    private static func previewRecordingSkillReadiness() -> WorkbenchSkillReadinessSummary {
        reviewRecordingStep()
    }
}
