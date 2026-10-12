import AppKit

// MARK: - Shared review window primitives

extension RecordingReviewWindowController {
    func verticalStack(spacing: CGFloat) -> NSStackView {
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.distribution = .fill
        stack.spacing = spacing
        stack.userInterfaceLayoutDirection = .leftToRight
        return stack
    }

    func horizontalStack(spacing: CGFloat) -> NSStackView {
        let stack = NSStackView()
        stack.orientation = .horizontal
        stack.alignment = .centerY
        stack.distribution = .fill
        stack.spacing = spacing
        stack.userInterfaceLayoutDirection = .leftToRight
        return stack
    }

    func flexibleSpacer() -> NSView {
        let view = NSView()
        view.setContentHuggingPriority(.defaultLow, for: .horizontal)
        view.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return view
    }

    func flexibleVerticalSpacer() -> NSView {
        let view = NSView()
        view.setContentHuggingPriority(.defaultLow, for: .vertical)
        view.setContentCompressionResistancePriority(.defaultLow, for: .vertical)
        return view
    }

    func addFullWidth(_ view: NSView, to stack: NSStackView, horizontalInset: CGFloat = 32) {
        view.translatesAutoresizingMaskIntoConstraints = false
        stack.addArrangedSubview(view)
        view.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -horizontalInset).isActive = true
    }

    func label(_ text: String, size: CGFloat, weight: NSFont.Weight, color: NSColor) -> NSTextField {
        let field = NSTextField(labelWithString: WorkRecorderLocalization.text(text))
        field.font = NSFont.systemFont(ofSize: size, weight: weight)
        field.textColor = color
        field.alignment = .left
        field.baseWritingDirection = .leftToRight
        field.maximumNumberOfLines = 0
        field.lineBreakMode = .byWordWrapping
        field.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        return field
    }

    func makeButton(title: String, variant: WorkbenchButton.Variant, symbolName: String? = nil, action: Selector?) -> WorkbenchButton {
        let button = WorkbenchButton(
            title: WorkRecorderLocalization.text(title),
            variant: variant,
            symbolName: symbolName,
            target: self,
            action: action
        )
        button.applyActionRowMinimumWidth()
        return button
    }

    func makeTransportButton(
        title: String,
        style: RecordingReviewTransportButton.Style,
        symbolName: String,
        action: Selector?
    ) -> RecordingReviewTransportButton {
        RecordingReviewTransportButton(
            title: WorkRecorderLocalization.text(title),
            style: style,
            symbolName: symbolName,
            target: self,
            action: action
        )
    }

    func statusPill(text: String, state: WorkbenchPermissionState) -> NSView {
        WorkbenchStatusPill(text: WorkRecorderLocalization.text(text), state: state)
    }

    func applyPanelChrome(
        to view: NSView,
        background: NSColor,
        border: NSColor = WorkbenchDesignTokens.Color.neutralHairline.withAlphaComponent(0.42),
        radius: CGFloat
    ) {
        view.wantsLayer = true
        view.layer?.backgroundColor = background.cgColor
        view.layer?.borderColor = border.cgColor
        view.layer?.borderWidth = 0.8
        view.layer?.cornerRadius = radius
        view.layer?.shadowColor = NSColor(calibratedRed: 0.12, green: 0.24, blue: 0.27, alpha: 0.065).cgColor
        view.layer?.shadowOpacity = 1
        view.layer?.shadowRadius = 16
        view.layer?.shadowOffset = CGSize(width: 0, height: -5)
    }

    func sectionTitle(_ title: String, symbolName: String) -> NSView {
        let row = horizontalStack(spacing: 8)
        if let image = NSImage(systemSymbolName: symbolName, accessibilityDescription: nil) {
            let icon = NSImageView(image: image)
            icon.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 12, weight: .semibold)
            icon.contentTintColor = WorkbenchDesignTokens.Color.tiffanyStrong
            icon.widthAnchor.constraint(equalToConstant: 16).isActive = true
            icon.heightAnchor.constraint(equalToConstant: 16).isActive = true
            row.addArrangedSubview(icon)
        }
        row.addArrangedSubview(label(title, size: 12.6, weight: .semibold, color: WorkbenchDesignTokens.Color.primaryText))
        return row
    }

    func emptyText(_ text: String) -> NSTextField {
        let field = label(text, size: 12.0, weight: .regular, color: WorkbenchDesignTokens.Color.muted)
        field.maximumNumberOfLines = 4
        return field
    }

    func playbackHint(_ text: String, warning: Bool) -> NSView {
        let row = horizontalStack(spacing: 8)
        if let image = NSImage(systemSymbolName: warning ? "exclamationmark.triangle" : "lock.open", accessibilityDescription: nil) {
            let icon = NSImageView(image: image)
            icon.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 12, weight: .semibold)
            icon.contentTintColor = warning ? WorkbenchDesignTokens.Color.warning : WorkbenchDesignTokens.Color.tiffanySoft
            icon.widthAnchor.constraint(equalToConstant: 16).isActive = true
            row.addArrangedSubview(icon)
        }
        let copy = label(
            text,
            size: 11.0,
            weight: .regular,
            color: warning ? WorkbenchDesignTokens.Color.warning : NSColor.white.withAlphaComponent(0.66)
        )
        copy.maximumNumberOfLines = 2
        row.addArrangedSubview(copy)
        return row
    }

    func lightInfoHint(_ text: String) -> NSView {
        let row = horizontalStack(spacing: 8)
        if let image = NSImage(systemSymbolName: "lock.shield", accessibilityDescription: nil) {
            let icon = NSImageView(image: image)
            icon.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 12, weight: .semibold)
            icon.contentTintColor = WorkbenchDesignTokens.Color.tiffanyStrong
            icon.widthAnchor.constraint(equalToConstant: 16).isActive = true
            row.addArrangedSubview(icon)
        }
        let copy = label(text, size: 11.0, weight: .regular, color: WorkbenchDesignTokens.Color.secondaryText)
        copy.maximumNumberOfLines = 2
        row.addArrangedSubview(copy)
        return row
    }

}

// MARK: - Step inspector sections

extension RecordingReviewWindowController {
    func materialGroup(title: String, rows: [String]) -> NSView {
        let group = verticalStack(spacing: 7)
        group.alignment = .leading
        group.edgeInsets = NSEdgeInsets(top: 11, left: 12, bottom: 11, right: 12)
        applyPanelChrome(to: group, background: NSColor.white.withAlphaComponent(0.48), radius: 12)
        group.addArrangedSubview(label(title, size: 12.0, weight: .semibold, color: WorkbenchDesignTokens.Color.primaryText))
        for rowText in rows {
            let row = label(rowText, size: 11.2, weight: .regular, color: WorkbenchDesignTokens.Color.secondaryText)
            row.maximumNumberOfLines = 2
            group.addArrangedSubview(row)
        }
        return group
    }

    func inspectorFollowHeader(step: WorkbenchRecordingTimelineStepView, canPlay: Bool) -> NSView {
        let row = horizontalStack(spacing: 8)
        row.addArrangedSubview(sectionTitle("当前步骤", symbolName: step.kind.symbolName))
        row.addArrangedSubview(flexibleSpacer())
        switch state.selectionMode {
        case .follow:
            row.addArrangedSubview(statusPill(text: canPlay ? "跟随播放中" : "跟随步骤", state: .granted))
        case .pinned:
            row.addArrangedSubview(statusPill(text: "已锁定", state: .unknown))
            row.addArrangedSubview(makeButton(title: "恢复跟随", variant: .quiet, symbolName: "dot.radiowaves.left.and.right", action: #selector(restoreFollowAction)))
        }
        return row
    }

    func stepSummarySection(step: WorkbenchRecordingTimelineStepView) -> NSView {
        let group = verticalStack(spacing: 5)
        group.alignment = .leading
        group.edgeInsets = NSEdgeInsets(top: 12, left: 13, bottom: 12, right: 13)
        applyPanelChrome(to: group, background: NSColor.white.withAlphaComponent(0.50), radius: 13)
        let title = label("\(formatDuration(step.mediaTimeMs) ?? "--:--") · \(stepTitle(step))", size: 14.0, weight: .semibold, color: WorkbenchDesignTokens.Color.primaryText)
        title.maximumNumberOfLines = 2
        group.addArrangedSubview(title)
        let caption = label(stepCaption(step), size: 12.2, weight: .regular, color: WorkbenchDesignTokens.Color.secondaryText)
        caption.maximumNumberOfLines = 4
        group.addArrangedSubview(caption)
        return group
    }

    func evidenceSection(
        recording: WorkbenchActiveCaptureInspectView,
        step: WorkbenchRecordingTimelineStepView
    ) -> NSView {
        let group = verticalStack(spacing: 7)
        group.alignment = .leading
        group.edgeInsets = NSEdgeInsets(top: 10, left: 12, bottom: 10, right: 12)
        applyPanelChrome(to: group, background: NSColor.white.withAlphaComponent(0.38), radius: 12)
        group.addArrangedSubview(sectionTitle("证据", symbolName: "photo.on.rectangle"))
        let frames = RecordingReviewCore.evidenceFrames(in: recording, for: step)
        if frames.isEmpty {
            group.addArrangedSubview(emptyText("未关联关键帧"))
        } else {
            for frame in frames {
                let button = WorkbenchButton(
                    title: "\(frame.role.title) · \(formatDuration(frame.mediaTimeMs) ?? "--:--")",
                    variant: .quiet,
                    symbolName: "photo",
                    target: self,
                    action: #selector(selectEvidenceFrame(_:))
                )
                button.applyCompactMinimumWidth()
                button.tag = frame.mediaTimeMs
                button.identifier = NSUserInterfaceItemIdentifier("evidence-frame-\(frame.keyframeId)")
                button.setAccessibilityHelp("Show this frame in the recording preview")
                group.addArrangedSubview(button)
            }
        }
        return group
    }

    func clickTargetSection(step: WorkbenchRecordingTimelineStepView) -> NSView {
        guard let target = step.actionSummary?.target else {
            return NSView()
        }
        let group = verticalStack(spacing: 8)
        group.alignment = .leading
        group.edgeInsets = NSEdgeInsets(top: 11, left: 12, bottom: 11, right: 12)
        applyPanelChrome(
            to: group,
            background: NSColor(calibratedRed: 0.90, green: 0.985, blue: 0.982, alpha: 0.54),
            border: WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.26),
            radius: 12
        )
        let header = horizontalStack(spacing: 8)
        header.addArrangedSubview(sectionTitle("点击目标", symbolName: "scope"))
        header.addArrangedSubview(flexibleSpacer())
        header.addArrangedSubview(statusPill(text: target.confidenceTitle, state: target.needsReview ? .unknown : .granted))
        group.addArrangedSubview(header)

        let targetTitle = label(target.displayLabel, size: 13.4, weight: .semibold, color: WorkbenchDesignTokens.Color.primaryText)
        targetTitle.maximumNumberOfLines = 2
        group.addArrangedSubview(targetTitle)

        let meta = [
            target.semanticTitle,
            target.confidencePercent,
            target.sourceTitle,
            target.evidenceKeyframeIds.isEmpty ? "未关联关键帧" : "有证据帧",
        ].joined(separator: " · ")
        let metaLabel = label(meta, size: 11.2, weight: .medium, color: WorkbenchDesignTokens.Color.secondaryText)
        metaLabel.maximumNumberOfLines = 2
        group.addArrangedSubview(metaLabel)
        if target.needsReview {
            let hint = label("目标语义需要复核；不会展示原始选择器、辅助功能路径或 OCR 原文。", size: 10.8, weight: .regular, color: WorkbenchDesignTokens.Color.muted)
            hint.maximumNumberOfLines = 2
            group.addArrangedSubview(hint)
        }
        return group
    }

    func actionTraceSection(step: WorkbenchRecordingTimelineStepView) -> NSView {
        let group = verticalStack(spacing: 6)
        group.alignment = .leading
        group.edgeInsets = NSEdgeInsets(top: 10, left: 12, bottom: 10, right: 12)
        applyPanelChrome(to: group, background: NSColor.white.withAlphaComponent(0.38), radius: 12)
        group.addArrangedSubview(sectionTitle("操作线索", symbolName: "cursorarrow.click.2"))
        group.addArrangedSubview(label(stepActionSummary(step), size: 11.5, weight: .medium, color: WorkbenchDesignTokens.Color.secondaryText))
        return group
    }

    func stepContextSection(
        recording: WorkbenchActiveCaptureInspectView,
        step: WorkbenchRecordingTimelineStepView
    ) -> NSView {
        let group = verticalStack(spacing: 8)
        group.alignment = .leading
        group.edgeInsets = NSEdgeInsets(top: 10, left: 12, bottom: 10, right: 12)
        applyPanelChrome(to: group, background: NSColor.white.withAlphaComponent(0.38), radius: 12)
        group.addArrangedSubview(sectionTitle("上下文", symbolName: "list.bullet.indent"))
        let ordered = recording.timeline.map { RecordingReviewCore.orderedSteps($0.steps) } ?? []
        guard let currentIndex = ordered.firstIndex(where: { $0.stepId == step.stepId }) else {
            group.addArrangedSubview(emptyText("未找到相邻步骤。"))
            return group
        }
        let ranges = [
            (label: "上一段", index: currentIndex - 1),
            (label: "当前", index: currentIndex),
            (label: "下一段", index: currentIndex + 1),
        ]
        for item in ranges where ordered.indices.contains(item.index) {
            group.addArrangedSubview(stepContextRow(labelText: item.label, step: ordered[item.index], selected: item.index == currentIndex))
        }
        return group
    }

    private func stepContextRow(labelText: String, step: WorkbenchRecordingTimelineStepView, selected: Bool) -> NSView {
        let row = horizontalStack(spacing: 7)
        row.edgeInsets = NSEdgeInsets(top: 4, left: 0, bottom: 4, right: 0)
        let stateColor = selected ? WorkbenchDesignTokens.Color.tiffanyStrong : WorkbenchDesignTokens.Color.muted
        let prefix = label(labelText, size: 10.4, weight: .semibold, color: stateColor)
        prefix.widthAnchor.constraint(equalToConstant: 42).isActive = true
        row.addArrangedSubview(prefix)
        let title = "\(formatDuration(step.mediaTimeMs) ?? "--:--") · \(stepTitle(step))"
        let value = label(title, size: 11.2, weight: selected ? .semibold : .medium, color: WorkbenchDesignTokens.Color.secondaryText)
        value.maximumNumberOfLines = 1
        value.lineBreakMode = .byTruncatingTail
        row.addArrangedSubview(value)
        return row
    }

    func warningSection(step: WorkbenchRecordingTimelineStepView) -> NSView {
        let group = verticalStack(spacing: 6)
        group.alignment = .leading
        group.edgeInsets = NSEdgeInsets(top: 10, left: 12, bottom: 10, right: 12)
        applyPanelChrome(
            to: group,
            background: WorkbenchDesignTokens.Color.warning.withAlphaComponent(0.10),
            border: WorkbenchDesignTokens.Color.warning.withAlphaComponent(0.34),
            radius: 12
        )
        group.addArrangedSubview(sectionTitle("需要复核", symbolName: "exclamationmark.triangle"))
        let reasons = step.readiness.reasons + step.readiness.missingEvidence
        if reasons.isEmpty {
            group.addArrangedSubview(label("此步骤需要人工复核。", size: 11.4, weight: .regular, color: WorkbenchDesignTokens.Color.secondaryText))
        } else {
            for reason in reasons.prefix(4) {
                group.addArrangedSubview(label(reviewReasonTitle(reason), size: 11.2, weight: .regular, color: WorkbenchDesignTokens.Color.secondaryText))
            }
        }
        return group
    }

    func sessionOverviewSection(recording: WorkbenchActiveCaptureInspectView) -> NSView {
        let group = verticalStack(spacing: 9)
        group.alignment = .leading
        group.edgeInsets = NSEdgeInsets(top: 12, left: 13, bottom: 12, right: 13)
        applyPanelChrome(to: group, background: NSColor.white.withAlphaComponent(0.44), radius: 12)
        group.addArrangedSubview(sectionTitle("本次复盘", symbolName: "rectangle.and.text.magnifyingglass"))
        let stepCount = recording.timeline?.steps.count ?? 0
        let visibleStepCount = recording.timeline.map { RecordingReviewCore.userFacingStepCount($0.steps) } ?? stepCount
        let duration = formatDuration(recording.timeline?.durationMs) ?? "--:--"
        let material = recording.videoRef?.state == .available
            ? "视频可播放 · \(visibleStepCount) 个重点 · \(duration)"
            : "关键帧可回看 · \(visibleStepCount) 个重点 · \(duration)"
        group.addArrangedSubview(overviewRow(title: "回看材料", value: material))
        group.addArrangedSubview(overviewRow(title: "复核提示", value: reviewOverviewText(recording)))
        let note = recording.userNote?.trimmingCharacters(in: .whitespacesAndNewlines)
        if let note, !note.isEmpty {
            let noteBlock = verticalStack(spacing: 4)
            noteBlock.alignment = .leading
            noteBlock.addArrangedSubview(label("保存备注", size: 10.4, weight: .semibold, color: WorkbenchDesignTokens.Color.muted))
            let noteLabel = label(middleTruncate(note, maxLength: 120), size: 11.3, weight: .regular, color: WorkbenchDesignTokens.Color.secondaryText)
            noteLabel.maximumNumberOfLines = 4
            noteBlock.addArrangedSubview(noteLabel)
            group.addArrangedSubview(noteBlock)
        }
        if let warning = recording.warnings.first {
            let warningLabel = label(middleTruncate(warning, maxLength: 130), size: 11.1, weight: .regular, color: WorkbenchDesignTokens.Color.warning)
            warningLabel.maximumNumberOfLines = 3
            group.addArrangedSubview(warningLabel)
        }
        return group
    }

    func overviewRow(title: String, value: String) -> NSView {
        let row = horizontalStack(spacing: 10)
        row.alignment = .centerY
        let titleLabel = label(title, size: 10.4, weight: .semibold, color: WorkbenchDesignTokens.Color.muted)
        titleLabel.maximumNumberOfLines = 1
        titleLabel.widthAnchor.constraint(equalToConstant: 58).isActive = true
        row.addArrangedSubview(titleLabel)
        let valueLabel = label(value, size: 11.3, weight: .medium, color: WorkbenchDesignTokens.Color.secondaryText)
        valueLabel.maximumNumberOfLines = 2
        valueLabel.lineBreakMode = .byWordWrapping
        row.addArrangedSubview(valueLabel)
        return row
    }

    func reviewOverviewText(_ recording: WorkbenchActiveCaptureInspectView) -> String {
        let reviewCount = recording.skillReadiness.reviewItemCount
        let blockedCount = recording.skillReadiness.blockedItemCount
        if blockedCount > 0 {
            return "\(blockedCount) 处受限，保存前建议确认"
        }
        if reviewCount > 0 {
            return "\(reviewCount) 处需要确认"
        }
        return "没有待确认步骤"
    }

    func reviewShortcutsSection(canPlay: Bool) -> NSView {
        let group = verticalStack(spacing: 8)
        group.alignment = .leading
        group.edgeInsets = NSEdgeInsets(top: 10, left: 12, bottom: 10, right: 12)
        applyPanelChrome(to: group, background: NSColor.white.withAlphaComponent(0.36), radius: 12)
        group.addArrangedSubview(sectionTitle("快捷键", symbolName: "keyboard"))
        if canPlay {
            group.addArrangedSubview(shortcutHintRow(keys: "Space", action: "播放 / 暂停"))
            group.addArrangedSubview(shortcutHintRow(keys: "Shift ← / →", action: "前后 5 秒"))
        }
        group.addArrangedSubview(shortcutHintRow(keys: "← / →", action: "切换步骤"))
        group.addArrangedSubview(shortcutHintRow(keys: "Esc", action: "关闭浮层"))
        return group
    }

    func shortcutHintRow(keys: String, action: String) -> NSView {
        let row = horizontalStack(spacing: 10)
        row.alignment = .centerY
        row.addArrangedSubview(keyCap(keys))
        let actionLabel = label(action, size: 11.2, weight: .medium, color: WorkbenchDesignTokens.Color.secondaryText)
        actionLabel.maximumNumberOfLines = 1
        actionLabel.lineBreakMode = .byTruncatingTail
        row.addArrangedSubview(actionLabel)
        return row
    }

    func keyCap(_ text: String) -> NSView {
        let cap = horizontalStack(spacing: 0)
        cap.alignment = .centerY
        cap.edgeInsets = NSEdgeInsets(top: 3, left: 8, bottom: 3, right: 8)
        applyPanelChrome(
            to: cap,
            background: NSColor.white.withAlphaComponent(0.54),
            border: WorkbenchDesignTokens.Color.neutralHairline.withAlphaComponent(0.34),
            radius: 8
        )
        cap.widthAnchor.constraint(greaterThanOrEqualToConstant: 78).isActive = true
        let textLabel = label(text, size: 10.7, weight: .semibold, color: WorkbenchDesignTokens.Color.primaryText.withAlphaComponent(0.82))
        textLabel.maximumNumberOfLines = 1
        textLabel.alignment = .center
        cap.addArrangedSubview(textLabel)
        return cap
    }

}

// MARK: - Timeline and summary sections

extension RecordingReviewWindowController {
    func timelinePanelHeader(visibleCount: Int, hiddenCount: Int) -> NSView {
        let header = horizontalStack(spacing: 14)
        header.alignment = .centerY
        header.heightAnchor.constraint(greaterThanOrEqualToConstant: 36).isActive = true

        let titleGroup = horizontalStack(spacing: 10)
        titleGroup.alignment = .centerY
        titleGroup.addArrangedSubview(sectionTitle("章节时间线", symbolName: "point.topleft.down.curvedto.point.bottomright.up"))
        let metaText = hiddenCount > 0
            ? "\(visibleCount) 个重点 · 已折叠 \(hiddenCount) 个后台控制"
            : "\(visibleCount) 个重点"
        let meta = label(metaText, size: 11.2, weight: .medium, color: WorkbenchDesignTokens.Color.muted)
        meta.maximumNumberOfLines = 1
        meta.lineBreakMode = .byTruncatingTail
        titleGroup.addArrangedSubview(meta)
        titleGroup.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        header.addArrangedSubview(titleGroup)

        header.addArrangedSubview(flexibleSpacer())

        let navigation = horizontalStack(spacing: 8)
        navigation.alignment = .centerY
        let previous = WorkbenchButton(
            title: "上一步",
            variant: .secondary,
            symbolName: "chevron.left",
            target: self,
            action: #selector(selectPreviousStepAction)
        )
        previous.applyCompactMinimumWidth()
        let next = WorkbenchButton(
            title: "下一步",
            variant: .secondary,
            symbolName: "chevron.right",
            target: self,
            action: #selector(selectNextStepAction)
        )
        next.applyCompactMinimumWidth()
        navigation.addArrangedSubview(previous)
        navigation.addArrangedSubview(next)
        header.addArrangedSubview(navigation)
        return header
    }

    func timelineSummaryTile(recording: WorkbenchActiveCaptureInspectView) -> NSView {
        let tile = verticalStack(spacing: 6)
        tile.alignment = .leading
        tile.edgeInsets = NSEdgeInsets(top: 12, left: 14, bottom: 12, right: 14)
        applyPanelChrome(to: tile, background: NSColor.white.withAlphaComponent(0.42), radius: 13)
        tile.setContentHuggingPriority(.defaultLow, for: .horizontal)
        tile.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        tile.widthAnchor.constraint(greaterThanOrEqualToConstant: 360).isActive = true
        tile.addArrangedSubview(sectionTitle("复盘摘要", symbolName: "chart.line.uptrend.xyaxis"))
        let duration = formatDuration(recording.timeline?.durationMs) ?? "--:--"
        let stepCount = recording.timeline.map { RecordingReviewCore.userFacingStepCount($0.steps) } ?? 0
        let reviewCount = recording.skillReadiness.reviewItemCount + recording.skillReadiness.blockedItemCount
        let video = recording.videoRef?.state == .available ? "视频可播放" : "关键帧复盘"
        let detailRow = horizontalStack(spacing: 18)
        detailRow.alignment = .top
        if let step = selectedStep() {
            detailRow.addArrangedSubview(timelineSummaryTextBlock(
                eyebrow: "当前步骤",
                title: "\(formatDuration(step.mediaTimeMs) ?? "--:--") · \(stepTitle(step))",
                minimumWidth: 190
            ))
        }
        let reviewText = reviewCount > 0 ? "\(reviewCount) 处需要确认" : "没有待确认步骤"
        detailRow.addArrangedSubview(timelineSummaryTextBlock(
            eyebrow: "复核状态",
            title: "\(duration) · \(stepCount) 个重点 · \(video) · \(reviewText)",
            minimumWidth: 240
        ))
        tile.addArrangedSubview(detailRow)
        return tile
    }

    func timelineSummaryTextBlock(eyebrow: String, title: String, minimumWidth: CGFloat = 168) -> NSView {
        let stack = verticalStack(spacing: 3)
        stack.alignment = .leading
        stack.widthAnchor.constraint(greaterThanOrEqualToConstant: minimumWidth).isActive = true
        stack.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        let eyebrowLabel = label(eyebrow, size: 9.8, weight: .semibold, color: WorkbenchDesignTokens.Color.muted)
        eyebrowLabel.maximumNumberOfLines = 1
        stack.addArrangedSubview(eyebrowLabel)
        let titleLabel = label(title, size: 11.0, weight: .semibold, color: WorkbenchDesignTokens.Color.secondaryText)
        titleLabel.maximumNumberOfLines = 1
        titleLabel.lineBreakMode = .byTruncatingTail
        stack.addArrangedSubview(titleLabel)
        return stack
    }

    func timelineDenseSummaryBar(recording: WorkbenchActiveCaptureInspectView) -> NSView {
        let bar = horizontalStack(spacing: 18)
        bar.alignment = .centerY
        bar.edgeInsets = NSEdgeInsets(top: 10, left: 14, bottom: 10, right: 14)
        applyPanelChrome(to: bar, background: NSColor.white.withAlphaComponent(0.46), radius: 13)
        bar.heightAnchor.constraint(greaterThanOrEqualToConstant: 52).isActive = true
        bar.addArrangedSubview(sectionTitle("复盘摘要", symbolName: "chart.line.uptrend.xyaxis"))
        let duration = formatDuration(recording.timeline?.durationMs) ?? "--:--"
        let stepCount = recording.timeline.map { RecordingReviewCore.userFacingStepCount($0.steps) } ?? 0
        let reviewCount = recording.skillReadiness.reviewItemCount + recording.skillReadiness.blockedItemCount
        let reviewText = reviewCount > 0 ? "\(reviewCount) 处待确认" : "无需复核"
        let video = recording.videoRef?.state == .available ? "视频" : "关键帧"
        if let step = selectedStep() {
            bar.addArrangedSubview(timelineSummaryTextBlock(
                eyebrow: "当前步骤",
                title: "\(formatDuration(step.mediaTimeMs) ?? "--:--") · \(stepTitle(step))",
                minimumWidth: 260
            ))
        }
        bar.addArrangedSubview(flexibleSpacer())
        bar.addArrangedSubview(timelineSummaryTextBlock(
            eyebrow: "整体状态",
            title: "\(duration) · \(stepCount) 个重点 · \(video) · \(reviewText)",
            minimumWidth: 300
        ))
        return bar
    }

    func permissionState(_ status: WorkbenchRecordingStatus) -> WorkbenchPermissionState {
        switch status {
        case .completed, .recording, .paused, .finalizing, .stopping:
            return .granted
        case .completedWithWarnings, .scopeLost:
            return .unknown
        case .failed, .cancelled:
            return .denied
        case .created, .selectingScope, .unknown:
            return .unknown
        }
    }

}
