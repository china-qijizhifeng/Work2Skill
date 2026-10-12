import AppKit
import ObjectiveC.runtime

/// Runtime localization for the English WorkRecorder release.
///
/// Chinese source strings remain available to keep the UI implementation
/// readable while the release bundle opts in with `WorkRecorderUILanguage = en`.
/// These
/// AppKit setter hooks translate every user-facing control created by the app,
/// including values updated after a recording changes state.
enum WorkRecorderLocalization {
    static let isEnglishVariant =
        Bundle.main.object(forInfoDictionaryKey: "WorkRecorderUILanguage") as? String == "en"

    nonisolated(unsafe) private static var didInstall = false

    static func installIfNeeded() {
        guard isEnglishVariant, !didInstall else { return }
        didInstall = true

        exchange(NSControl.self, NSSelectorFromString("setStringValue:"), #selector(NSControl.wr_setStringValue(_:)))
        exchange(NSTextField.self, NSSelectorFromString("setPlaceholderString:"), #selector(NSTextField.wr_setPlaceholderString(_:)))
        exchange(NSButton.self, NSSelectorFromString("setTitle:"), #selector(NSButton.wr_setTitle(_:)))
        exchange(NSWindow.self, NSSelectorFromString("setTitle:"), #selector(NSWindow.wr_setTitle(_:)))
        exchange(NSMenuItem.self, NSSelectorFromString("setTitle:"), #selector(NSMenuItem.wr_setTitle(_:)))
        exchange(NSView.self, NSSelectorFromString("setToolTip:"), #selector(NSView.wr_setToolTip(_:)))
        exchange(NSView.self, NSSelectorFromString("setAccessibilityLabel:"), #selector(NSView.wr_setAccessibilityLabel(_:)))
        exchange(NSView.self, NSSelectorFromString("setAccessibilityHelp:"), #selector(NSView.wr_setAccessibilityHelp(_:)))
        exchange(NSImage.self, NSSelectorFromString("setAccessibilityDescription:"), #selector(NSImage.wr_setAccessibilityDescription(_:)))
        exchange(NSTextView.self, NSSelectorFromString("setString:"), #selector(NSTextView.wr_setString(_:)))
        exchange(
            NSSegmentedControl.self,
            NSSelectorFromString("setLabel:forSegment:"),
            #selector(NSSegmentedControl.wr_setLabel(_:forSegment:))
        )
    }

    static func text(_ source: String) -> String {
        isEnglishVariant ? english(source) : source
    }

    static func english(_ source: String) -> String {
        guard containsHan(source) else { return source }
        if let exact = exactTranslations[source] {
            return exact
        }

        var result = source
        let replacements = phraseTranslations + exactTranslations.map { ($0.key, $0.value) }
        for (chinese, english) in replacements.sorted(by: { $0.0.count > $1.0.count }) {
            result = result.replacingOccurrences(of: chinese, with: english)
        }
        for (pattern, replacement) in regexTranslations {
            result = replacingRegex(pattern, in: result, with: replacement)
        }
        result = result
            .replacingOccurrences(of: "，", with: ", ")
            .replacingOccurrences(of: "。", with: ".")
            .replacingOccurrences(of: "；", with: "; ")
            .replacingOccurrences(of: "：", with: ": ")
            .replacingOccurrences(of: "（", with: " (")
            .replacingOccurrences(of: "）", with: ")")
            .replacingOccurrences(of: "“", with: "\"")
            .replacingOccurrences(of: "”", with: "\"")
            .replacingOccurrences(of: "「", with: "\"")
            .replacingOccurrences(of: "」", with: "\"")

        // A rare daemon diagnostic should never leak Chinese into the English
        // UI. Preserve paths, identifiers and native error text around it.
        if containsHan(result) {
            let translatedPortion = replacingRegex("[\\p{Han}]+", in: result, with: "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
            result = translatedPortion.isEmpty ? "Information" : translatedPortion
        }
        return result.replacingOccurrences(of: "  ", with: " ")
    }

    private static func containsHan(_ value: String) -> Bool {
        value.range(of: "\\p{Han}", options: .regularExpression) != nil
    }

    private static func replacingRegex(_ pattern: String, in value: String, with replacement: String) -> String {
        guard let expression = try? NSRegularExpression(pattern: pattern) else { return value }
        let range = NSRange(value.startIndex..<value.endIndex, in: value)
        return expression.stringByReplacingMatches(in: value, range: range, withTemplate: replacement)
    }

    private static func exchange(_ type: AnyClass, _ original: Selector, _ replacement: Selector) {
        guard let originalMethod = class_getInstanceMethod(type, original),
              let replacementMethod = class_getInstanceMethod(type, replacement)
        else { return }
        method_exchangeImplementations(originalMethod, replacementMethod)
    }

    private static let exactTranslations: [String: String] = [
        "WorkRecorder 录制中心": "WorkRecorder Recording Center",
        "WorkRecorder 录制复盘": "WorkRecorder Recording Review",
        "录制复盘": "Recording Review",
        "WorkRecorder 权限引导": "WorkRecorder Permission Guide",
        "录制中心": "Recording Center",
        "搜索录制": "Search recordings",
        "权限": "Permissions",
        "权限引导": "Permission Guide",
        "权限引导…": "Permission Guide…",
        "开始录制": "Start Recording",
        "打开录制中心": "Open Recording Center",
        "退出 WorkRecorder": "Quit WorkRecorder",
        "打开复盘": "Open Review",
        "删除录制": "Delete Recording",
        "删除这段录制？": "Delete this recording?",
        "删除后将无法从录制中心恢复。": "This recording cannot be recovered from the Recording Center after deletion.",
        "未命名录制": "Untitled Recording",
        "回放视频与操作时间线": "Replay video and action timeline",
        "开始第一段录制": "Create Your First Recording",
        "框选工作区域，完成后可回放、备注并保存。": "Select a work area, then replay, annotate, and save it.",
        "录制前准备": "Before Recording",
        "设置 WorkRecorder 权限": "Set Up WorkRecorder Permissions",
        "打开“系统设置 → 隐私与安全性”，给": "Open System Settings → Privacy & Security and enable",
        "和": "and",
        "终端": "Terminal",
        "开启以下权限。": "for the permissions below.",
        "辅助功能": "Accessibility",
        "帮助识别当前窗口、控件和操作目标。": "Helps identify the active window, controls, and action targets.",
        "输入监控": "Input Monitoring",
        "用于记录点击、滚动与键盘操作线索。": "Records click, scroll, and keyboard action cues.",
        "屏幕与系统音频录制": "Screen & System Audio Recording",
        "用于录制框选区域的画面与系统音频。": "Records the selected area and system audio.",
        "已生效": "Enabled",
        "当前未生效": "Not Enabled",
        "打开设置": "Open Settings",
        "若开关已打开但仍显示未生效，请移除旧的 WorkRecorder，再点“+”添加当前应用；通过终端启动时也请检查“终端”。": "If a permission is on but still appears disabled, remove the old WorkRecorder entry, click “+”, and add this app. If launched from Terminal, check Terminal as well.",
        "完成": "Done",
        "录制正在启动": "Recording is starting",
        "控制面板即将出现": "Controls will appear shortly",
        "录制正在处理": "Processing recording",
        "请稍候": "Please wait",
        "录制待保存": "Recording ready to save",
        "请在完成面板中保存或丢弃": "Save or discard it in the completion panel",
        "录制已暂停": "Recording paused",
        "可继续录制或结束": "Resume or finish the recording",
        "正在录制": "Recording",
        "边界与 HUD 已显示": "Boundary and controls are visible",
        "暂停录制": "Pause Recording",
        "继续录制": "Resume Recording",
        "唤起录制控制": "Show Recording Controls",
        "完成录制": "Finish Recording",
        "录制状态": "Recording Status",
        "WorkRecorder · 拖拽选择录制区域      Esc 取消": "WorkRecorder · Drag to select a recording area      Esc Cancel",
        "WorkRecorder · 框选录制区域      Esc 取消      ⌃⌥⌘R 唤起控制": "WorkRecorder · Select a recording area      Esc Cancel      ⌃⌥⌘R Show controls",
        "Esc 取消": "Esc Cancel",
        "将录制此区域": "Record This Area",
        "开始区域录制": "Start Area Recording",
        "重新选择": "Reselect",
        "取消录制": "Cancel Recording",
        "准备中": "Preparing",
        "正在启动": "Starting",
        "标记": "Mark",
        "暂停": "Pause",
        "结束录制": "Finish Recording",
        "已暂停，不会录制": "Paused — not recording",
        "继续": "Resume",
        "正在整理": "Finalizing",
        "输入监听受限": "Input monitoring limited",
        "范围需复核": "Area needs review",
        "录制区域": "Recording Area",
        "已暂停": "Paused",
        "录制完成": "Recording Complete",
        "保存前预览": "Review Before Saving",
        "打开本地预览": "Open Local Preview",
        "录制备注": "Recording Notes",
        "给这段录制一句备注": "Add a short note for this recording",
        "例如：API key 轮换步骤、失败原因、注意事项": "For example: API key rotation steps, failure reason, or notes",
        "可选。保存后可在录制中心搜索、复盘并继续整理。": "Optional. After saving, find and review it in the Recording Center.",
        "保存录制": "Save Recording",
        "丢弃录制": "Discard Recording",
        "返回录制": "Back to Recording",
        "录制已保存": "Recording Saved",
        "录制已丢弃": "Recording Discarded",
        "丢弃这段录制？": "Discard this recording?",
        "临时视频、关键帧和未保存的时间线会被删除；不会进入录制库。": "Temporary video, keyframes, and the unsaved timeline will be deleted and will not appear in the library.",
        "返回": "Back",
        "确认丢弃录制": "Confirm Discard",
        "区域录制权限": "Area Recording Permission",
        "需要屏幕录制权限": "Screen Recording Permission Required",
        "录制没有完成": "Recording Did Not Complete",
        "授权后才能录制你框选的区域。\n开启权限后，重新按下录制快捷键并再次选择边界。": "Permission is required to record the selected area.\nAfter enabling it, start recording again and reselect the area.",
        "打开系统设置": "Open System Settings",
        "关闭": "Close",
        "知道了": "Got It",
        "区域": "Area",
        "来源": "Source",
        "系统": "System",
        "未识别窗口": "Unidentified Window",
        "已完成": "Completed",
        "返回录制中心": "Back to Recording Center",
        "仅播放视频": "Video Only",
        "导出到文件夹": "Export to Folder",
        "复盘内容": "Review Contents",
        "当前步骤": "Current Step",
        "选择时间线步骤后查看关联帧和操作摘要。": "Select a timeline step to view its linked frames and action summary.",
        "证据": "Evidence",
        "当前帧": "Current Frame",
        "文本": "Text",
        "操作线索": "Action Cues",
        "上下文": "Context",
        "上一段": "Previous",
        "当前": "Current",
        "下一段": "Next",
        "章节时间线": "Chapter Timeline",
        "上一步": "Previous Step",
        "下一步": "Next Step",
        "复盘摘要": "Review Summary",
        "复核状态": "Review Status",
        "整体状态": "Overall Status",
        "关键帧复盘": "Keyframe Review",
        "视频": "Video",
        "关键帧": "Keyframe",
        "视频可播放": "Video available",
        "没有待确认步骤": "No items to review",
        "无需复核": "No review needed",
        "播放": "Play",
        "播放 / 暂停": "Play / Pause",
        "后退 5 秒": "Back 5 Seconds",
        "前进 5 秒": "Forward 5 Seconds",
        "恢复跟随": "Resume Follow",
        "跟随步骤": "Follow Steps",
        "跟随播放中": "Following Playback",
        "快捷键": "Shortcuts",
        "前后 5 秒": "Back / Forward 5 Seconds",
        "切换步骤": "Change Step",
        "关闭浮层": "Close Overlay",
        "视频已载入 · Space 播放": "Video loaded · Press Space to play",
        "待播放预览 · 按 Space 开始": "Preview ready · Press Space to play",
        "开始帧": "Start Frame",
        "结束帧": "End Frame",
        "开始": "Start",
        "结束": "End",
        "视频不可用": "Video Unavailable",
        "暂不可用": "Unavailable",
        "预览帧暂不可用": "Preview unavailable",
        "这一帧没有可用文本。可能原因：OCR 未命中、辅助功能权限不足或画面过小。": "No text is available for this frame. OCR may not have matched, Accessibility permission may be missing, or the content may be too small.",
        "没有可播放视频；可用关键帧、时间线和安全文字复盘。": "No playable video. Review the keyframes, timeline, and safe text instead.",
        "视频会通过本机授权读取；控制栏固定在画面下方。": "Video is read locally with permission; playback controls stay below the frame.",
        "原始视频、画面帧和辅助功能数据不会在此直接展开。": "Raw video, frames, and Accessibility data are not exposed here.",
        "这里只展示适合复盘的安全内容。": "Only review-safe content is shown here.",
        "如需查看受限内容，WorkRecorder 会单独请求授权。": "WorkRecorder requests permission separately for restricted content.",
        "导出中…": "Exporting…",
        "导出到此处": "Export Here",
        "选择导出录制内容的目标文件夹": "Choose a destination folder for the recording export",
        "正常（event → click）": "Standard (event → click)",
        "仅 event 兜底": "Event-only fallback",
        "仅 click 兜底": "Click-only fallback",
        "按钮": "Button",
        "链接": "Link",
        "输入框": "Input Field",
        "搜索框": "Search Field",
        "菜单项": "Menu Item",
        "导航项": "Navigation Item",
        "标签页": "Tab",
        "复选框": "Checkbox",
        "窗口": "Window",
        "页面元素": "Page Element",
        "高置信": "High Confidence",
        "需复核": "Review Needed",
        "低置信": "Low Confidence",
        "待确认": "To Review",
        "网页": "Web",
        "窗口快照": "Window Snapshot",
        "坐标": "Coordinates",
        "融合": "Merged",
        "无语义证据": "No semantic evidence",
        "安全摘要": "Safe Summary",
        "正常": "Ready",
        "需要处理": "Action Required",
        "未知": "Unknown",
        "已入库": "Saved",
        "待入库": "Not Saved",
        "可复盘": "Ready to Review",
        "需要复核": "Needs Review",
        "录制中": "Recording",
        "空闲": "Idle",
        "正在框选": "Selecting Area",
        "正在准备录制": "Preparing Recording",
        "等待开始": "Waiting to Start",
        "录制暂停": "Recording Paused",
        "失败": "Failed",
        "未启动": "Not Started",
        "启动中": "Starting",
        "已运行": "Running",
        "端口冲突": "Port Conflict",
        "服务密钥不匹配": "Service Key Mismatch",
        "密钥不一致": "Key Mismatch",
        "窗口状态变化": "Window State Changed",
        "正在停止": "Stopping",
        "已完成，有提醒": "Completed with Warnings",
        "已取消": "Cancelled",
        "未录视频": "No Video",
        "视频失败": "Video Failed",
        "已删除": "Deleted",
        "异常提示": "Issue",
        "复核提示": "Review Notice",
        "有证据帧": "Evidence frame available",
        "证据不足": "Insufficient evidence",
        "目标待确认": "Target to Review",
        "目标识别": "Target Identification",
        "点击目标": "Click Target",
        "窗口变化": "Window Changed",
        "范围变化": "Area Changed",
        "页面变化": "Page Changed",
        "标签切换": "Tab Changed",
        "弹窗变化": "Dialog Changed",
        "窗口切换": "Window Switched",
        "按键": "Key Press",
        "文本输入": "Text Input",
        "滚动": "Scroll",
        "点击": "Click",
        "手动标记": "Manual Mark",
        "步骤": "Step",
        "动作前": "Before Action",
        "动作结果": "Action Result",
        "结果帧": "Result Frame",
        "未关联关键帧": "No linked keyframes",
        "已锁定": "Pinned",
        "此步骤需要人工复核。": "This step requires manual review.",
        "未找到相邻步骤。": "No adjacent steps found.",
        "本次复盘": "This Review",
        "回看材料": "Review Materials",
        "保存备注": "Saved Note",
        "本次录制包含": "This Recording Includes",
        "隐私与访问": "Privacy & Access",
        "屏幕区域": "Screen Area",
        "本机录制": "Local Recording",
        "正在准备视频": "Preparing Video",
        "播放录制": "Play Recording",
        "关键帧复盘模式": "Keyframe Review Mode",
        "返回步骤": "Back to Step",
        "可播放": "Available",
        "暂无": "None",
        "视频回放": "Video Playback",
        "时间线": "Timeline",
        "可用文本": "Available Text",
        "调整复盘播放速度": "Adjust review playback speed",
        "定时关键帧": "Timed Keyframe",
        "暂停边界": "Pause Boundary",
        "继续边界": "Resume Boundary",
        "异常状态": "Error State",
        "滚动章节": "Scroll Chapter",
        "按键完成": "Key Sequence Complete"
    ]

    /// Ordered longest-first so compound UI copy is translated before small
    /// status tokens such as “录制” or “完成”.
    private static let phraseTranslations: [(String, String)] = [
        ("操作线索和窗口范围都需要复核；视频仍按固定区域保存，复盘中会标记需要确认。", "Action cues and the window area need review. Video remains saved to the fixed area and will be flagged in review."),
        ("窗口线索发生变化；视频仍按你框选的固定区域保存，复盘时请确认范围和目标。", "Window context changed. Video remains limited to the selected area; verify the area and target during review."),
        ("输入监听受限；仍可保存视频和关键帧，复盘中会标记需要确认。可在设置里开启辅助功能后重试。", "Input monitoring is limited. Video and keyframes can still be saved, but review items will be flagged. Enable Accessibility in Settings and try again."),
        ("仍会录制视频；开启辅助功能权限后，可更准确识别窗口和控件。", "Video will still be recorded. Enable Accessibility for more accurate window and control identification."),
        ("仍会保存视频和关键帧，但不会记录点击、滚动和快捷键线索。", "Video and keyframes will still be saved, but click, scroll, and shortcut cues will not be recorded."),
        ("WorkRecorder 会保存视频和关键帧；后续动作归因可能需要人工确认。", "WorkRecorder will save video and keyframes; action attribution may require manual review."),
        ("录制仍限定在你框选的固定区域，但窗口线索发生变化，复盘时需要确认。", "Recording remains limited to the selected area, but window context changed and needs review."),
        ("输入监听权限或系统限制导致点击、滚动、键盘轨迹可能不完整。", "Click, scroll, and keyboard traces may be incomplete because of Input Monitoring permission or system limits."),
        ("保存会保留关键帧和诊断信息", "Saving keeps keyframes and diagnostics"),
        ("提交录制视频和关键帧，并完成本次录制。", "Save the video and keyframes and complete this recording."),
        ("取消本次录制并删除本地临时视频。", "Cancel this recording and delete its local temporary video."),
        ("在保存前打开本地临时视频预览。", "Preview the local temporary video before saving."),
        ("可打开本地预览确认内容；保存前不会上传原始视频，丢弃会移除本地临时视频。", "Open a local preview to verify the content. Raw video is not uploaded before saving, and discarding removes the temporary video."),
        ("录制正在提交，请稍候。", "Saving recording. Please wait."),
        ("选择时间线步骤后查看当前帧、文字和操作摘要。", "Select a timeline step to view its frame, text, and action summary."),
        ("复盘窗口优先帮助你确认过程、结果和关键步骤；调试材料留在受控入口。", "Review the process, result, and key steps here. Debug materials remain behind controlled access."),
        ("点击目标已识别；需要结合证据帧复核。", "The click target was identified; verify it against the evidence frame."),
        ("已关联结果帧；点击目标和置信度见下方。", "A result frame is linked. See the target and confidence below."),
        ("目标语义需要复核；不会展示原始选择器、辅助功能路径或 OCR 原文。", "Target semantics need review. Raw selectors, Accessibility paths, and OCR text are not shown."),
        ("录制范围发生变化，需要复核。", "The recording area changed and needs review."),
        ("录制开始，边界已确认。", "Recording started with the area confirmed."),
        ("录制已完成。", "Recording completed."),
        ("录制已暂停。", "Recording paused."),
        ("录制已继续。", "Recording resumed."),
        ("手动标记这一刻。", "Manually marked this moment."),
        ("开始录制片段。", "Started a recording segment."),
        ("结束当前片段。", "Ended the current segment."),
        ("目标识别置信度偏低", "Low target-identification confidence"),
        ("录制视频不可用", "Recording video unavailable"),
        ("长录制内容已折叠", "Long recording content collapsed"),
        ("录制区域曾发生变化", "Recording area changed"),
        ("处受限，保存前建议确认", " restricted items; review before saving"),
        ("没有隐藏的受限内容。", "No restricted content is hidden."),
        ("本地视频文件暂不可用。", "The local video file is unavailable."),
        ("这条录制没有可播放的视频。", "This recording has no playable video."),
        ("录制时间线还在整理。", "The recording timeline is still being prepared."),
        ("打开录制复盘失败", "Could not open recording review"),
        ("录制中心刷新失败", "Could not refresh Recording Center"),
        ("删除录制失败", "Could not delete recording"),
        ("保存录制失败", "Could not save recording"),
        ("丢弃录制失败", "Could not discard recording"),
        ("暂停录制失败", "Could not pause recording"),
        ("继续录制失败", "Could not resume recording"),
        ("区域录制启动失败", "Could not start area recording"),
        ("屏幕录制权限不可用", "Screen Recording permission unavailable"),
        ("打开本地录制预览", "Opened local recording preview"),
        ("打开合成后的本地录制预览", "Opened merged local recording preview"),
        ("视频可播放", "Video available"),
        ("关键帧可回看", "Keyframes available"),
        ("个后台控制", "background controls"),
        ("已折叠", "collapsed"),
        ("个重点步骤", "highlighted steps"),
        ("个重点", "highlights"),
        ("处需要确认", "items to review"),
        ("处待确认", "items to review"),
        ("个步骤", "steps"),
        ("个输入事件", "input events"),
        ("个时间点", "time points"),
        (" 张", " frames"),
        ("约 ", "about "),
        (" 字", " characters"),
        ("段录制", "recordings"),
        ("段", "segments"),
        ("帧", "frames"),
        ("总时长", "Duration"),
        ("当前帧", "Current Frame"),
        ("前一帧", "Before"),
        ("后一帧", "After"),
        ("目标证据", "Target Evidence"),
        ("按下", "Press"),
        ("松开", "Release"),
        ("录制", "Recording")
    ]

    private static let regexTranslations: [(String, String)] = [
        ("^(\\d+) recordings$", "$1 recordings"),
        ("^(\\d+) highlights$", "$1 highlights"),
        ("^(\\d+) time points$", "$1 time points"),
        ("^第 (\\d+) 个, 共 (\\d+) 个$", "$1 of $2"),
        ("^(.+) Recording$", "$1 Recording")
    ]
}

private extension NSControl {
    @objc dynamic func wr_setStringValue(_ value: String) {
        wr_setStringValue(WorkRecorderLocalization.english(value))
    }
}

private extension NSTextField {
    @objc dynamic func wr_setPlaceholderString(_ value: String?) {
        wr_setPlaceholderString(value.map(WorkRecorderLocalization.english))
    }
}

private extension NSButton {
    @objc dynamic func wr_setTitle(_ value: String) {
        wr_setTitle(WorkRecorderLocalization.english(value))
    }
}

private extension NSWindow {
    @objc dynamic func wr_setTitle(_ value: String) {
        wr_setTitle(WorkRecorderLocalization.english(value))
    }
}

private extension NSMenuItem {
    @objc dynamic func wr_setTitle(_ value: String) {
        wr_setTitle(WorkRecorderLocalization.english(value))
    }
}

private extension NSView {
    @objc dynamic func wr_setToolTip(_ value: String?) {
        wr_setToolTip(value.map(WorkRecorderLocalization.english))
    }

    @objc dynamic func wr_setAccessibilityLabel(_ value: String?) {
        wr_setAccessibilityLabel(value.map(WorkRecorderLocalization.english))
    }

    @objc dynamic func wr_setAccessibilityHelp(_ value: String?) {
        wr_setAccessibilityHelp(value.map(WorkRecorderLocalization.english))
    }
}

private extension NSImage {
    @objc dynamic func wr_setAccessibilityDescription(_ value: String?) {
        wr_setAccessibilityDescription(value.map(WorkRecorderLocalization.english))
    }
}

private extension NSTextView {
    @objc dynamic func wr_setString(_ value: String) {
        wr_setString(WorkRecorderLocalization.english(value))
    }
}

private extension NSSegmentedControl {
    @objc dynamic func wr_setLabel(_ value: String, forSegment segment: Int) {
        wr_setLabel(WorkRecorderLocalization.english(value), forSegment: segment)
    }
}
