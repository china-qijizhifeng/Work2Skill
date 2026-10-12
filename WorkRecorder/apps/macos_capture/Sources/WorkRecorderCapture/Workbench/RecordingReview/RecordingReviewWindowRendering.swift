import AppKit
import WorkRecorderCaptureDesign

extension RecordingReviewWindowController {
    func headerView(
        request: RecordingReviewOpenRequest,
        recording: WorkbenchActiveCaptureInspectView
    ) -> NSView {
        let header = horizontalStack(spacing: 14)
        header.edgeInsets = NSEdgeInsets(top: 10, left: 14, bottom: 10, right: 14)
        applyPanelChrome(to: header, background: NSColor.white.withAlphaComponent(0.56), radius: 16)
        header.heightAnchor.constraint(greaterThanOrEqualToConstant: 66).isActive = true

        let copy = verticalStack(spacing: 4)
        let title = request.inspect.source.title.isEmpty ? "录制复盘" : request.inspect.source.title
        let titleLabel = label(title, size: 16.2, weight: .semibold, color: WorkbenchDesignTokens.Color.primaryText)
        titleLabel.maximumNumberOfLines = 1
        titleLabel.lineBreakMode = .byTruncatingTail
        copy.addArrangedSubview(titleLabel)
        let meta = [
            request.inspect.source.appName ?? "屏幕区域",
            recording.timeline.flatMap { formatDuration($0.durationMs) },
            "\(recording.timeline.map { RecordingReviewCore.userFacingStepCount($0.steps) } ?? 0) 个重点",
            recording.videoRef?.state.title,
            recording.skillReadiness.state.title,
        ].compactMap { $0 }.joined(separator: " · ")
        let metaLabel = label(meta, size: 11.5, weight: .medium, color: WorkbenchDesignTokens.Color.secondaryText)
        metaLabel.maximumNumberOfLines = 1
        metaLabel.lineBreakMode = .byTruncatingTail
        copy.addArrangedSubview(metaLabel)
        header.addArrangedSubview(copy)
        header.addArrangedSubview(flexibleSpacer())

        let canPlay = recordingCanPlay(recording)
        header.addArrangedSubview(statusPill(text: recording.status.title, state: permissionState(recording.status)))
        header.addArrangedSubview(makeButton(title: "返回录制中心", variant: .secondary, symbolName: "sidebar.left", action: #selector(closeReviewAction)))
        let externalPlayback = makeButton(
            title: canPlay ? "仅播放视频" : "视频不可用",
            variant: .secondary,
            symbolName: canPlay ? "arrow.up.right.square" : "video.slash",
            action: canPlay ? #selector(openExternalPlaybackAction) : nil
        )
        externalPlayback.isEnabled = canPlay
        header.addArrangedSubview(externalPlayback)
        let export = makeButton(
            title: isExportInProgress ? "导出中…" : "导出到文件夹",
            variant: .secondary,
            symbolName: "folder.badge.plus",
            action: isExportInProgress ? nil : #selector(exportRecordingAction)
        )
        export.isEnabled = !isExportInProgress
        header.addArrangedSubview(export)
        header.addArrangedSubview(makeButton(title: state.showsMaterialsPanel ? "返回步骤" : "复盘内容", variant: .secondary, symbolName: "rectangle.stack", action: #selector(toggleMaterialsAction)))
        return header
    }

    func playbackPane(
        request: RecordingReviewOpenRequest,
        recording: WorkbenchActiveCaptureInspectView
    ) -> NSView {
        let stack = verticalStack(spacing: 10)
        stack.edgeInsets = NSEdgeInsets(top: 14, left: 14, bottom: 14, right: 14)
        applyPanelChrome(
            to: stack,
            background: NSColor(calibratedRed: 0.060, green: 0.082, blue: 0.092, alpha: 0.96),
            border: WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.20),
            radius: 18
        )
        stack.widthAnchor.constraint(greaterThanOrEqualToConstant: 560).isActive = true

        let canPlay = recordingCanPlay(recording)
        if let session = playbackController.playbackSession {
            let playback = RecordingEmbeddedPlaybackView(playbackSession: session, posterImage: request.thumbnail)
            playback.translatesAutoresizingMaskIntoConstraints = false
            playback.heightAnchor.constraint(greaterThanOrEqualToConstant: 260).isActive = true
            playback.setContentHuggingPriority(.defaultLow, for: .vertical)
            addFullWidth(playback, to: stack, horizontalInset: 28)
        } else if !canPlay {
            let storyboard = RecordingKeyframeStoryboardView(
                thumbnail: request.thumbnail,
                title: request.inspect.source.title.isEmpty ? "关键帧复盘" : request.inspect.source.title,
                subtitle: request.inspect.source.appName ?? "本机录制",
                durationText: recording.timeline.flatMap { formatDuration($0.durationMs) },
                stepCount: recording.timeline?.steps.count ?? 0
            )
            storyboard.translatesAutoresizingMaskIntoConstraints = false
            storyboard.heightAnchor.constraint(greaterThanOrEqualToConstant: 260).isActive = true
            storyboard.setContentHuggingPriority(.defaultLow, for: .vertical)
            addFullWidth(storyboard, to: stack, horizontalInset: 28)
        } else {
            let preview = RecordingVideoPreviewView(
                image: request.thumbnail,
                title: request.thumbnail == nil ? (request.inspect.source.title.isEmpty ? "录制复盘" : request.inspect.source.title) : "",
                subtitle: request.thumbnail == nil ? (request.inspect.source.appName ?? "本机录制") : "",
                durationText: recording.timeline.flatMap { formatDuration($0.durationMs) },
                ctaText: playbackController.isLoading ? "正在准备视频" : "播放录制",
                affordanceSymbolName: playbackController.isLoading ? "hourglass" : "play.fill",
                showsPlaybackChrome: false,
                compact: false,
                contentMode: .fit,
                target: self,
                action: #selector(loadPlaybackAction)
            )
            preview.translatesAutoresizingMaskIntoConstraints = false
            preview.heightAnchor.constraint(greaterThanOrEqualToConstant: 260).isActive = true
            preview.setContentHuggingPriority(.defaultLow, for: .vertical)
            addFullWidth(preview, to: stack, horizontalInset: 28)
        }

        if let timeline = recording.timeline, !timeline.steps.isEmpty {
            let markerVisibility = RecordingReviewCore.visibleTimelineSteps(
                timeline.steps,
                selectedStepId: selectedStep()?.stepId,
                filter: state.timelineFilter,
                density: .default
            )
            let marker = RecordingTimelineMarkerBarView(
                steps: markerVisibility.visibleSteps,
                selectedStepId: selectedStep()?.stepId,
                durationMs: timeline.durationMs,
                target: self,
                action: #selector(selectReviewStep(_:))
            )
            marker.translatesAutoresizingMaskIntoConstraints = false
            marker.heightAnchor.constraint(equalToConstant: 42).isActive = true
            addFullWidth(marker, to: stack, horizontalInset: 28)
        }
        addFullWidth(playbackControls(recording: recording, canPlay: canPlay), to: stack, horizontalInset: 28)
        if let error = playbackController.errorMessage, !error.isEmpty {
            addFullWidth(playbackHint(error, warning: true), to: stack, horizontalInset: 28)
        } else {
            let hint = canPlay
                ? "视频会通过本机授权读取；控制栏固定在画面下方。"
                : "没有可播放视频；可用关键帧、时间线和安全文字复盘。"
            addFullWidth(playbackHint(hint, warning: false), to: stack, horizontalInset: 28)
        }
        return stack
    }

    func playbackControls(recording: WorkbenchActiveCaptureInspectView, canPlay: Bool) -> NSView {
        let row = horizontalStack(spacing: 9)
        row.alignment = .centerY
        if !canPlay {
            row.addArrangedSubview(makeTransportButton(title: "上一步", style: .secondary, symbolName: "chevron.left", action: #selector(selectPreviousStepAction)))
            row.addArrangedSubview(makeTransportButton(title: "下一步", style: .secondary, symbolName: "chevron.right", action: #selector(selectNextStepAction)))
            let mode = label("关键帧复盘模式", size: 11.8, weight: .semibold, color: NSColor.white.withAlphaComponent(0.78))
            row.addArrangedSubview(mode)
            row.addArrangedSubview(flexibleSpacer())
            let time = formatDuration(recording.timeline?.durationMs) ?? "--:--"
            let timeLabel = label("总时长 \(time)", size: 11.5, weight: .semibold, color: NSColor.white.withAlphaComponent(0.68))
            timeLabel.font = NSFont.monospacedDigitSystemFont(ofSize: 11.5, weight: .semibold)
            row.addArrangedSubview(timeLabel)
            return row
        }
        let isPlaying = (playbackController.playbackSession?.player.rate ?? 0) != 0
        let playTitle = isPlaying ? "暂停" : "播放"
        row.addArrangedSubview(makeTransportButton(title: playTitle, style: .primary, symbolName: "playpause.fill", action: #selector(togglePlaybackAction)))
        row.addArrangedSubview(makeTransportButton(title: "后退 5 秒", style: .secondary, symbolName: "gobackward.5", action: #selector(seekBackwardAction)))
        row.addArrangedSubview(makeTransportButton(title: "前进 5 秒", style: .secondary, symbolName: "goforward.5", action: #selector(seekForwardAction)))
        let current = playbackController.currentMediaTimeMs(fallback: state.currentMediaTimeMs)
        let time = "\(formatDuration(current) ?? "00:00") / \(formatDuration(recording.timeline?.durationMs) ?? "--:--")"
        let timeLabel = label(time, size: 11.5, weight: .semibold, color: NSColor.white.withAlphaComponent(0.78))
        timeLabel.font = NSFont.monospacedDigitSystemFont(ofSize: 11.5, weight: .semibold)
        row.addArrangedSubview(timeLabel)
        row.addArrangedSubview(flexibleSpacer())
        let rate = NSSegmentedControl(labels: ["0.5x", "1x", "1.25x", "1.5x", "2x"], trackingMode: .selectOne, target: self, action: #selector(playbackRateChanged(_:)))
        rate.selectedSegment = [0.5, 1.0, 1.25, 1.5, 2.0].firstIndex(of: Double(state.playbackRate)) ?? 1
        rate.toolTip = "调整复盘播放速度"
        row.addArrangedSubview(rate)
        return row
    }

    @objc private func seekBackwardAction() {
        seekRelative(-5_000)
    }

    @objc private func seekForwardAction() {
        seekRelative(5_000)
    }

    func inspectorPanel(recording: WorkbenchActiveCaptureInspectView) -> NSView {
        let stack = verticalStack(spacing: 12)
        stack.edgeInsets = NSEdgeInsets(top: 16, left: 16, bottom: 16, right: 16)
        applyPanelChrome(to: stack, background: NSColor.white.withAlphaComponent(0.66), radius: 16)
        guard let step = selectedStep() else {
            addFullWidth(sectionTitle("当前步骤", symbolName: "scope"), to: stack)
            addFullWidth(emptyText("选择时间线步骤后查看关联帧和操作摘要。"), to: stack)
            return stack
        }

        addFullWidth(inspectorFollowHeader(step: step, canPlay: recordingCanPlay(recording)), to: stack)
        addFullWidth(stepSummarySection(step: step), to: stack)
        if step.actionSummary?.target != nil {
            addFullWidth(clickTargetSection(step: step), to: stack)
        }
        addFullWidth(evidenceSection(recording: recording, step: step), to: stack)
        addFullWidth(actionTraceSection(step: step), to: stack)
        addFullWidth(stepContextSection(recording: recording, step: step), to: stack)
        if step.needsReview || !step.readiness.reasons.isEmpty || !step.readiness.missingEvidence.isEmpty {
            addFullWidth(warningSection(step: step), to: stack)
        }
        addFullWidth(sessionOverviewSection(recording: recording), to: stack)
        addFullWidth(reviewShortcutsSection(canPlay: recordingCanPlay(recording)), to: stack)
        stack.addArrangedSubview(flexibleVerticalSpacer())
        return stack
    }

    func materialsPanel(
        inspect: WorkbenchEventInspectView,
        recording: WorkbenchActiveCaptureInspectView
    ) -> NSView {
        let stack = verticalStack(spacing: 12)
        stack.edgeInsets = NSEdgeInsets(top: 16, left: 16, bottom: 16, right: 16)
        applyPanelChrome(to: stack, background: NSColor.white.withAlphaComponent(0.72), radius: 16)
        let header = horizontalStack(spacing: 8)
        header.addArrangedSubview(sectionTitle("复盘内容", symbolName: "rectangle.stack"))
        header.addArrangedSubview(flexibleSpacer())
        header.addArrangedSubview(makeButton(title: "关闭", variant: .quiet, symbolName: "xmark", action: #selector(toggleMaterialsAction)))
        addFullWidth(header, to: stack)
        addFullWidth(materialGroup(title: "本次录制包含", rows: [
            "视频回放：\(recording.videoRef?.state == .available ? "可播放" : "暂不可用")",
            "关键帧：\(recording.timeline?.steps.filter { $0.kind == .keyframe }.count ?? 0) 张",
            "时间线：\(recording.timeline.map { RecordingReviewCore.userFacingStepCount($0.steps) } ?? 0) 个重点步骤",
            "可用文本：\(recording.safeTextBlocks.isEmpty ? "暂无" : "\(recording.safeTextBlocks.count) 段")",
        ]), to: stack)
        addFullWidth(materialGroup(
            title: "隐私与访问",
            rows: [
                "这里只展示适合复盘的安全内容。",
                "原始视频、画面帧和辅助功能数据不会在此直接展开。",
                inspect.rawArtifacts.isEmpty ? "没有隐藏的受限内容。" : "如需查看受限内容，WorkRecorder 会单独请求授权。",
            ]
        ), to: stack)
        stack.addArrangedSubview(flexibleVerticalSpacer())
        addFullWidth(lightInfoHint("复盘窗口优先帮助你确认过程、结果和关键步骤；调试材料留在受控入口。"), to: stack)
        return stack
    }

    func timelinePanel(recording: WorkbenchActiveCaptureInspectView) -> NSView {
        let stack = verticalStack(spacing: 9)
        stack.alignment = .width
        stack.edgeInsets = NSEdgeInsets(top: 12, left: 14, bottom: 12, right: 14)
        applyPanelChrome(to: stack, background: NSColor.white.withAlphaComponent(0.58), radius: 16)
        guard let timeline = recording.timeline, !timeline.steps.isEmpty else {
            stack.addArrangedSubview(emptyText("录制时间线还在整理。"))
            return stack
        }
        let visibility = RecordingReviewCore.visibleTimelineSteps(
            timeline.steps,
            selectedStepId: state.selectedStepId,
            filter: state.timelineFilter,
            density: .default
        )
        addFullWidth(
            timelinePanelHeader(visibleCount: visibility.visibleSteps.count, hiddenCount: visibility.hiddenLowValueStepCount),
            to: stack,
            horizontalInset: 28
        )

        if visibility.visibleSteps.count <= 3 {
            let row = compactTimelineRow(recording: recording, steps: visibility.visibleSteps)
            row.translatesAutoresizingMaskIntoConstraints = false
            stack.addArrangedSubview(row)
            row.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -28).isActive = true
            return stack
        }

        let scroll = NSScrollView()
        scroll.drawsBackground = false
        scroll.hasHorizontalScroller = visibility.visibleSteps.count > 5
        scroll.hasVerticalScroller = false
        scroll.autohidesScrollers = true
        let strip = horizontalStack(spacing: 9)
        strip.edgeInsets = NSEdgeInsets(top: 0, left: 0, bottom: 5, right: 8)
        let stepWidth: CGFloat = 148
        let stepHeight: CGFloat = 92
        let contentWidth = max(720, CGFloat(visibility.visibleSteps.count) * (stepWidth + 9) + 12)
        strip.frame = NSRect(x: 0, y: 0, width: contentWidth, height: stepHeight + 6)
        for step in visibility.visibleSteps {
            let chip = RecordingTimelineStepChipView(
                stepId: step.stepId,
                title: stepTitle(step),
                timeText: formatDuration(step.mediaTimeMs) ?? "--:--",
                caption: middleTruncate(stepCaption(step), maxLength: 42),
                symbolName: step.kind.symbolName,
                selected: step.stepId == selectedStep()?.stepId,
                needsReview: step.needsReview,
                target: self,
                action: #selector(selectReviewStep(_:))
            )
            chip.translatesAutoresizingMaskIntoConstraints = false
            chip.widthAnchor.constraint(equalToConstant: stepWidth).isActive = true
            chip.heightAnchor.constraint(equalToConstant: stepHeight).isActive = true
            strip.addArrangedSubview(chip)
        }
        scroll.documentView = strip
        scroll.translatesAutoresizingMaskIntoConstraints = false
        scroll.heightAnchor.constraint(equalToConstant: stepHeight + 16).isActive = true
        stack.addArrangedSubview(scroll)
        scroll.widthAnchor.constraint(equalTo: stack.widthAnchor, constant: -28).isActive = true
        addFullWidth(timelineDenseSummaryBar(recording: recording), to: stack, horizontalInset: 28)
        return stack
    }

    func compactTimelineRow(
        recording: WorkbenchActiveCaptureInspectView,
        steps: [WorkbenchRecordingTimelineStepView]
    ) -> NSView {
        let row = horizontalStack(spacing: 10)
        row.alignment = .top
        for step in steps {
            let chip = RecordingTimelineStepChipView(
                stepId: step.stepId,
                title: stepTitle(step),
                timeText: formatDuration(step.mediaTimeMs) ?? "--:--",
                caption: middleTruncate(stepCaption(step), maxLength: 40),
                symbolName: step.kind.symbolName,
                selected: step.stepId == selectedStep()?.stepId,
                needsReview: step.needsReview,
                target: self,
                action: #selector(selectReviewStep(_:))
            )
            chip.translatesAutoresizingMaskIntoConstraints = false
            chip.widthAnchor.constraint(equalToConstant: 174).isActive = true
            chip.heightAnchor.constraint(equalToConstant: 94).isActive = true
            row.addArrangedSubview(chip)
        }
        row.addArrangedSubview(timelineSummaryTile(recording: recording))
        return row
    }

    func recordingCanPlay(_ recording: WorkbenchActiveCaptureInspectView) -> Bool {
        recording.videoRef?.state == .available && recording.videoRef?.artifactId?.isEmpty == false
    }
}
