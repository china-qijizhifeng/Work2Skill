import AppKit

extension RecordingReviewWindowController {
    func stepTitle(_ step: WorkbenchRecordingTimelineStepView) -> String {
        if let action = step.actionKind ?? step.actionSummary?.actionKind {
            if action == .click, let target = step.actionSummary?.target {
                if target.needsReview || target.shortDisplayLabel == "目标待确认" {
                    return "点击（\(target.shortDisplayLabel)）"
                }
                return "点击「\(target.shortDisplayLabel)」"
            }
            if (action == .hotkey || action == .keyDown), let chord = step.actionSummary?.keyChord {
                return "按下 \(chord.displayText)"
            }
            if action == .keyUp, let chord = step.actionSummary?.keyChord {
                return "松开 \(chord.displayText)"
            }
            if action == .typingPause {
                return "文本输入"
            }
            return action.title
        }
        if let control = step.controlKind {
            return control.title
        }
        if let trigger = step.triggerKind {
            switch trigger {
            case "recording_start":
                return "开始录制"
            case "recording_stop":
                return "结束录制"
            case "user_mark":
                return "手动标记"
            case "hotkey_settle":
                return "按键完成"
            case "typing_settle":
                return "文本输入"
            case "click_settle":
                return "点击"
            case "scroll_stop":
                return "滚动"
            default:
                break
            }
        }
        if let role = step.keyframeRole {
            return localizedKeyframeRole(role)
        }
        return step.kind == .keyframe ? "关键帧" : "步骤"
    }

    func stepCaption(_ step: WorkbenchRecordingTimelineStepView) -> String {
        if let control = step.controlKind {
            switch control {
            case .startSegment:
                return "开始录制片段。"
            case .endSegment:
                return "结束当前片段。"
            case .pause:
                return "录制已暂停。"
            case .resume:
                return "录制已继续。"
            case .userMark:
                return "手动标记这一刻。"
            case .stop, .autoStop:
                return "录制已完成。"
            case .scopeLost:
                return "录制范围发生变化，需要复核。"
            case .unknown:
                break
            }
        }
        let caption = step.safeCaption.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !caption.isEmpty else {
            return stepActionSummary(step)
        }
        if (step.actionKind ?? step.actionSummary?.actionKind) == .click, step.actionSummary?.target != nil {
            if step.actionSummary?.resultKeyframeId != nil {
                return "已关联结果帧；点击目标和置信度见下方。"
            }
            return "点击目标已识别；需要结合证据帧复核。"
        }
        let lower = caption.lowercased()
        if lower.hasPrefix("recording control:") || lower == "user marked this moment" {
            return stepActionSummary(step)
        }
        switch lower {
        case "recording started":
            return "录制开始，边界已确认。"
        case "recording ended":
            return "录制已完成。"
        case "manual mark", "user mark":
            return "手动标记这一刻。"
        default:
            break
        }
        return caption
    }

    func stepKeyframeSummary(_ step: WorkbenchRecordingTimelineStepView) -> String {
        var refs: [String] = []
        if step.keyframeId?.isEmpty == false {
            refs.append("当前帧")
        }
        if let before = step.actionSummary?.beforeKeyframeIds.count, before > 0 {
            refs.append("前一帧 \(before)")
        }
        if let after = step.actionSummary?.afterKeyframeIds.count, after > 0 {
            refs.append("后一帧 \(after)")
        }
        if let targetEvidence = step.actionSummary?.targetEvidenceKeyframeIds.count, targetEvidence > 0 {
            refs.append("目标证据 \(targetEvidence)")
        }
        if step.actionSummary?.resultKeyframeId != nil {
            refs.append("结果帧")
        }
        return refs.isEmpty ? "未关联关键帧" : refs.joined(separator: " · ")
    }

    func stepActionSummary(_ step: WorkbenchRecordingTimelineStepView) -> String {
        if let chord = step.actionSummary?.keyChord {
            if (step.actionKind ?? step.actionSummary?.actionKind) == .keyUp {
                return "松开 \(chord.displayText)"
            }
            return "按下 \(chord.displayText)"
        }
        if let typing = step.actionSummary?.typingSummary {
            return "文本输入 · 约 \(typing.characterCount) 字 · \(typing.eventCount) 个输入事件"
        }
        if let target = step.actionSummary?.target {
            return "\(target.semanticTitle) · \(target.confidenceTitle) · \(target.sourceTitle)"
        }
        if let action = step.actionKind ?? step.actionSummary?.actionKind {
            return action.title
        }
        if let control = step.controlKind {
            return control.title
        }
        if let trigger = step.triggerKind {
            return localizedTriggerTitle(trigger)
        }
        if let role = step.keyframeRole {
            return localizedKeyframeRole(role)
        }
        return step.kind == .keyframe ? "关键帧" : "安全摘要"
    }

    func formatDuration(_ milliseconds: Int?) -> String? {
        guard let milliseconds else { return nil }
        let totalSeconds = max(0, milliseconds / 1000)
        let minutes = totalSeconds / 60
        let seconds = totalSeconds % 60
        return String(format: "%02d:%02d", minutes, seconds)
    }

    func middleTruncate(_ value: String, maxLength: Int) -> String {
        guard value.count > maxLength, maxLength > 12 else {
            return value
        }
        let headCount = maxLength / 2 - 1
        let tailCount = maxLength - headCount - 1
        return "\(value.prefix(headCount))…\(value.suffix(tailCount))"
    }

    func reviewReasonTitle(_ reason: String) -> String {
        switch reason {
        case "target_low_confidence":
            return "目标识别置信度偏低"
        case "video_missing", "recording_video":
            return "录制视频不可用"
        case "long_session_truncated":
            return "长录制内容已折叠"
        case "scope_lost":
            return "录制区域曾发生变化"
        default:
            return reason.replacingOccurrences(of: "_", with: " ")
        }
    }

    private func localizedKeyframeRole(_ role: String) -> String {
        switch role.lowercased() {
        case "start":
            return "开始录制"
        case "final", "end":
            return "结束录制"
        case "user_mark", "manual_mark":
            return "手动标记"
        case "timer", "interval":
            return "定时关键帧"
        case "before_action":
            return "动作前"
        case "result":
            return "动作结果"
        case "pause_boundary":
            return "暂停边界"
        case "resume_boundary":
            return "继续边界"
        case "error_state":
            return "异常状态"
        case "scroll_milestone":
            return "滚动章节"
        default:
            return role.replacingOccurrences(of: "_", with: " ")
        }
    }

    private func localizedTriggerTitle(_ trigger: String) -> String {
        switch trigger.lowercased() {
        case "recording_start":
            return "开始录制"
        case "recording_stop":
            return "结束录制"
        case "user_mark":
            return "手动标记"
        case "hotkey_settle":
            return "按键完成"
        case "typing_settle":
            return "文本输入"
        case "click_settle":
            return "点击"
        case "scroll_stop":
            return "滚动"
        case "action_before":
            return "动作前"
        case "action_result_settle":
            return "动作结果"
        case "navigation_committed", "title_url_change":
            return "页面变化"
        case "modal_state_change":
            return "弹窗变化"
        case "scroll_milestone":
            return "滚动章节"
        case "target_resolution_probe":
            return "目标识别"
        case "error_surface_detected":
            return "异常提示"
        case "pause_boundary":
            return "暂停边界"
        case "resume_boundary":
            return "继续边界"
        case "focus_change", "surface_change":
            return "窗口变化"
        default:
            return trigger.replacingOccurrences(of: "_", with: " ")
        }
    }
}
