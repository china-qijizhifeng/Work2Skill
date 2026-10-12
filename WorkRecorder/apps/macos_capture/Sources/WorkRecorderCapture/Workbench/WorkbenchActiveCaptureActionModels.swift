struct WorkbenchRecordingActionSummaryView: Decodable, Equatable {
    let actionId: String
    let actionKind: WorkbenchRecordingActionKind
    let hotkeySemantic: String?
    let keyChord: WorkbenchRecordingKeyChord?
    let typingSummary: WorkbenchRecordingTypingSummary?
    let target: WorkbenchClickTargetView?
    let beforeKeyframeIds: [String]
    let afterKeyframeIds: [String]
    let targetEvidenceKeyframeIds: [String]
    let resultKeyframeId: String?

    enum CodingKeys: String, CodingKey {
        case actionId = "action_id"
        case actionKind = "action_kind"
        case hotkeySemantic = "hotkey_semantic"
        case keyChord = "key_chord"
        case typingSummary = "typing_summary"
        case target
        case beforeKeyframeIds = "before_keyframe_ids"
        case afterKeyframeIds = "after_keyframe_ids"
        case targetEvidenceKeyframeIds = "target_evidence_keyframe_ids"
        case resultKeyframeId = "result_keyframe_id"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        actionId = try container.decode(String.self, forKey: .actionId)
        actionKind = try container.decode(WorkbenchRecordingActionKind.self, forKey: .actionKind)
        hotkeySemantic = try container.decodeIfPresent(String.self, forKey: .hotkeySemantic)
        keyChord = try container.decodeIfPresent(WorkbenchRecordingKeyChord.self, forKey: .keyChord)
        typingSummary = try container.decodeIfPresent(WorkbenchRecordingTypingSummary.self, forKey: .typingSummary)
        target = try container.decodeIfPresent(WorkbenchClickTargetView.self, forKey: .target)
        beforeKeyframeIds = try container.decodeIfPresent([String].self, forKey: .beforeKeyframeIds) ?? []
        afterKeyframeIds = try container.decodeIfPresent([String].self, forKey: .afterKeyframeIds) ?? []
        targetEvidenceKeyframeIds = try container.decodeIfPresent([String].self, forKey: .targetEvidenceKeyframeIds) ?? []
        resultKeyframeId = try container.decodeIfPresent(String.self, forKey: .resultKeyframeId)
    }
}

struct WorkbenchClickTargetView: Decodable, Equatable {
    let resolutionId: String?
    let status: String
    let displayLabel: String
    let semanticKind: String
    let confidence: Double
    let confidenceBand: String
    let sourceBadges: [String]
    let needsReview: Bool
    let evidenceKeyframeIds: [String]
    let hasCoordinates: Bool
    let suppressionReason: String?

    enum CodingKeys: String, CodingKey {
        case resolutionId = "resolution_id"
        case status
        case displayLabel = "display_label"
        case semanticKind = "semantic_kind"
        case confidence
        case confidenceBand = "confidence_band"
        case sourceBadges = "source_badges"
        case needsReview = "needs_review"
        case evidenceKeyframeIds = "evidence_keyframe_ids"
        case hasCoordinates = "has_coordinates"
        case suppressionReason = "suppression_reason"
    }

    var confidencePercent: String { "\(Int((confidence * 100).rounded()))%" }

    var shortDisplayLabel: String {
        displayLabel.count > 28 ? "\(displayLabel.prefix(27))…" : displayLabel
    }

    var semanticTitle: String {
        switch semanticKind {
        case "button": "按钮"
        case "link": "链接"
        case "input": "输入框"
        case "search_field": "搜索框"
        case "menu_item": "菜单项"
        case "nav_item": "导航项"
        case "tab": "标签页"
        case "checkbox": "复选框"
        case "window": "窗口"
        default: "页面元素"
        }
    }

    var confidenceTitle: String {
        switch confidenceBand {
        case "high": "高置信"
        case "medium": "需复核"
        case "low": "低置信"
        default: "待确认"
        }
    }

    var sourceTitle: String {
        let mapped = sourceBadges.map { source -> String in
            switch source {
            case "a11y_snapshot": "辅助功能"
            case "web_dom": "网页"
            case "ocr_box": "OCR"
            case "appshot": "窗口快照"
            case "coordinate_fallback": "坐标"
            case "merged": "融合"
            default: source.replacingOccurrences(of: "_", with: " ")
            }
        }
        return mapped.isEmpty ? "无语义证据" : mapped.joined(separator: " · ")
    }
}

struct WorkbenchRecordingKeyChord: Decodable, Equatable {
    let physicalKeyCode: Int?
    let normalizedKeyLabel: String
    let modifiers: [String]
    let keyboardLayoutId: String?
    let isRepeat: Bool
    let semantic: String?
    let characters: String?

    enum CodingKeys: String, CodingKey {
        case physicalKeyCode = "physical_key_code"
        case normalizedKeyLabel = "normalized_key_label"
        case modifiers
        case keyboardLayoutId = "keyboard_layout_id"
        case isRepeat = "is_repeat"
        case semantic
        case characters
    }

    var displayText: String {
        let modifierText = modifiers.map { modifier in
            switch modifier {
            case "command": "⌘"
            case "control": "⌃"
            case "option": "⌥"
            case "shift": "⇧"
            default: modifier
            }
        }.joined()
        if let characters, !characters.isEmpty {
            let key = switch characters {
            case " ": "Space"
            case "\t": "Tab"
            case "\r", "\n": "Enter"
            default: characters
            }
            return "\(modifierText)\(key)"
        }
        let key = switch normalizedKeyLabel.lowercased() {
        case "enter", "return": "Enter"
        case "escape", "esc": "Esc"
        case "tab": "Tab"
        case "left_arrow": "←"
        case "right_arrow": "→"
        case "up_arrow": "↑"
        case "down_arrow": "↓"
        case "home": "Home"
        case "end": "End"
        case "page_up": "Page Up"
        case "page_down": "Page Down"
        case "space": "Space"
        case "backspace": "Backspace"
        case "delete": "Delete"
        default: normalizedKeyLabel.count == 1 ? normalizedKeyLabel.uppercased() : normalizedKeyLabel
        }
        return "\(modifierText)\(key)"
    }
}

struct WorkbenchRecordingTypingSummary: Decodable, Equatable {
    let eventCount: Int
    let textEventCount: Int
    let characterCount: Int
    let deletionKeyCount: Int
    let nonTextKeyCount: Int
    let compositionUsed: Bool
    let submittedByEnter: Bool
    let durationMs: Int?

    enum CodingKeys: String, CodingKey {
        case eventCount = "event_count"
        case textEventCount = "text_event_count"
        case characterCount = "character_count"
        case deletionKeyCount = "deletion_key_count"
        case nonTextKeyCount = "non_text_key_count"
        case compositionUsed = "composition_used"
        case submittedByEnter = "submitted_by_enter"
        case durationMs = "duration_ms"
    }
}
