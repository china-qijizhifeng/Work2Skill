import AppKit

@MainActor
final class RecordingPreparationWindow: NSPanel {
    private let preparationView: RecordingPreparationView

    init(
        anchor: CGRect,
        screen: NSScreen,
        sourceBinding: SourceBinding,
        warning: RecordingPreparationWarning? = nil,
        onStart: @escaping () -> Void,
        onReselect: @escaping () -> Void,
        onCancel: @escaping () -> Void
    ) {
        let size = CGSize(width: min(540, max(420, screen.visibleFrame.width - 36)), height: warning == nil ? 138 : 202)
        let frame = Geometry.recordingOverlayFrame(anchor: anchor, panelSize: size, visibleFrame: screen.visibleFrame)
        let view = RecordingPreparationView(
            selection: anchor,
            sourceTitle: sourceBinding.sourceRef.title,
            appName: sourceBinding.sourceRef.appName,
            warning: warning,
            onStart: onStart,
            onReselect: onReselect,
            onCancel: onCancel
        )
        preparationView = view
        super.init(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isOpaque = false
        backgroundColor = .clear
        level = .floating
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        contentView = view
    }

    override var canBecomeKey: Bool { true }

    override func keyDown(with event: NSEvent) {
        switch event.keyCode {
        case CaptureKeyCode.escape:
            preparationView.cancel()
        case 36, 76:
            preparationView.start()
        default:
            super.keyDown(with: event)
        }
    }
}
final class RecordingPreparationView: NSView {
    private let titleLabel = NSTextField(labelWithString: "将录制此区域")
    private let detailLabel = NSTextField(labelWithString: "")
    private let onStart: () -> Void
    private let onReselect: () -> Void
    private let onCancel: () -> Void

    init(
        selection: CGRect,
        sourceTitle: String?,
        appName: String?,
        warning: RecordingPreparationWarning?,
        onStart: @escaping () -> Void,
        onReselect: @escaping () -> Void,
        onCancel: @escaping () -> Void
    ) {
        self.onStart = onStart
        self.onReselect = onReselect
        self.onCancel = onCancel
        super.init(frame: .zero)
        wantsLayer = true
        setup(selection: selection, sourceTitle: sourceTitle, appName: appName, warning: warning)
    }

    required init?(coder: NSCoder) {
        nil
    }

    private func setup(
        selection: CGRect,
        sourceTitle: String?,
        appName: String?,
        warning: RecordingPreparationWarning?
    ) {
        titleLabel.font = NSFont.systemFont(ofSize: 14.2, weight: .semibold)
        titleLabel.textColor = WorkRecorderTheme.primaryText
        detailLabel.font = WorkRecorderTheme.Font.metadata
        detailLabel.textColor = WorkRecorderTheme.secondaryText
        detailLabel.maximumNumberOfLines = 2
        let source = [appName, sourceTitle].compactMap { value in
            let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines)
            return trimmed?.isEmpty == false ? trimmed : nil
        }.joined(separator: " · ")
        let dimensions = "\(Int(selection.width.rounded())) × \(Int(selection.height.rounded()))"
        detailLabel.stringValue = source.isEmpty ? dimensions : "\(dimensions) · \(source)"

        let start = WorkRecorderPillButton(title: "开始录制", variant: .primary, target: self, action: #selector(startPressed))
        start.setAccessibilityLabel("开始区域录制")
        let reselect = WorkRecorderPillButton(title: "重新选择", variant: .secondary, target: self, action: #selector(reselectPressed))
        let cancel = WorkRecorderPillButton(title: "取消录制", variant: .secondary, target: self, action: #selector(cancelPressed))

        let copy = NSStackView(views: [titleLabel, detailLabel])
        copy.orientation = .vertical
        copy.alignment = .leading
        copy.spacing = 5
        let buttons = NSStackView(views: [start, reselect, cancel])
        buttons.orientation = .horizontal
        buttons.alignment = .centerY
        buttons.spacing = 9
        var rows: [NSView] = [copy]
        if let warning {
            rows.append(Self.warningRow(warning))
        }
        rows.append(buttons)
        let root = NSStackView(views: rows)
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = warning == nil ? 18 : 12
        root.translatesAutoresizingMaskIntoConstraints = false
        addSubview(root)
        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 22),
            root.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor, constant: -22),
            root.centerYAnchor.constraint(equalTo: centerYAnchor),
        ])
    }

    private static func warningRow(_ warning: RecordingPreparationWarning) -> NSView {
        let icon = NSTextField(labelWithString: "!")
        icon.font = NSFont.systemFont(ofSize: 10.5, weight: .bold)
        icon.alignment = .center
        icon.textColor = WorkRecorderTheme.warning
        icon.wantsLayer = true
        icon.layer?.cornerRadius = 7
        icon.layer?.borderWidth = 0.8
        icon.layer?.borderColor = WorkRecorderTheme.warning.withAlphaComponent(0.32).cgColor
        icon.layer?.backgroundColor = WorkRecorderTheme.warning.withAlphaComponent(0.08).cgColor
        icon.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            icon.widthAnchor.constraint(equalToConstant: 15),
            icon.heightAnchor.constraint(equalToConstant: 15),
        ])

        let title = NSTextField(labelWithString: warning.title)
        title.font = NSFont.systemFont(ofSize: 11.6, weight: .semibold)
        title.textColor = WorkRecorderTheme.warning
        let detail = NSTextField(labelWithString: warning.detail)
        detail.font = WorkRecorderTheme.Font.metadata
        detail.textColor = WorkRecorderTheme.secondaryText
        detail.maximumNumberOfLines = 2
        detail.lineBreakMode = .byWordWrapping
        detail.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        let textStack = NSStackView(views: [title, detail])
        textStack.orientation = .vertical
        textStack.alignment = .leading
        textStack.spacing = 2
        let row = NSStackView(views: [icon, textStack])
        row.orientation = .horizontal
        row.alignment = .top
        row.spacing = 9
        row.translatesAutoresizingMaskIntoConstraints = false

        let panel = NSView()
        panel.wantsLayer = true
        panel.layer?.cornerRadius = 13
        panel.layer?.backgroundColor = WorkRecorderTheme.warning.withAlphaComponent(0.06).cgColor
        panel.layer?.borderColor = WorkRecorderTheme.warning.withAlphaComponent(0.18).cgColor
        panel.layer?.borderWidth = 0.8
        panel.addSubview(row)
        NSLayoutConstraint.activate([
            row.leadingAnchor.constraint(equalTo: panel.leadingAnchor, constant: 11),
            row.trailingAnchor.constraint(equalTo: panel.trailingAnchor, constant: -11),
            row.topAnchor.constraint(equalTo: panel.topAnchor, constant: 9),
            row.bottomAnchor.constraint(equalTo: panel.bottomAnchor, constant: -9),
            detail.widthAnchor.constraint(lessThanOrEqualToConstant: 420),
            panel.widthAnchor.constraint(lessThanOrEqualToConstant: 492),
        ])
        panel.setAccessibilityLabel("\(warning.title)。\(warning.detail)")
        return panel
    }

    @objc private func startPressed() { start() }
    @objc private func reselectPressed() { onReselect() }
    @objc private func cancelPressed() { cancel() }

    func start() { onStart() }

    func cancel() { onCancel() }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let panel = bounds.insetBy(dx: 1, dy: 1)
        let path = WorkRecorderTheme.roundedRectPath(panel, radius: 22)
        NSGradient(colors: [
            WorkRecorderTheme.Material.panelGlassTop.withAlphaComponent(0.96),
            WorkRecorderTheme.Material.panelGlassBottom.withAlphaComponent(0.92),
        ])?.draw(in: path, angle: 92)
        WorkRecorderTheme.Prism.tiffanyBlue.withAlphaComponent(0.16).setStroke()
        path.lineWidth = 1.2
        path.stroke()
    }
}
final class RecordingHUDWindow: NSPanel {
    private let hudView: RecordingHUDView

    init?(
        anchor: CGRect,
        screen: NSScreen,
        onMark: @escaping () -> Void,
        onPauseToggle: @escaping () -> Void,
        onFinish: @escaping () -> Void,
        onStopRequest: @escaping () -> Void
    ) {
        let frame = Self.placementFrame(anchor: anchor, screen: screen)
        hudView = RecordingHUDView(
            onMark: onMark,
            onPauseToggle: onPauseToggle,
            onFinish: onFinish,
            onStopRequest: onStopRequest
        )
        super.init(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isOpaque = false
        backgroundColor = .clear
        level = .screenSaver
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        contentView = hudView
    }

    override var canBecomeKey: Bool { true }

    override func keyDown(with event: NSEvent) {
        switch event.keyCode {
        case CaptureKeyCode.space:
            hudView.togglePauseFromKeyboard()
        case CaptureKeyCode.escape:
            hudView.requestStopFromKeyboard()
        default:
            super.keyDown(with: event)
        }
    }

    func update(elapsedMilliseconds: Int, paused: Bool) {
        hudView.update(elapsedMilliseconds: elapsedMilliseconds, paused: paused)
    }

    func setMode(_ mode: RecordingHUDMode) {
        hudView.setMode(mode)
    }

    func setTraceDegraded(_ degraded: Bool) {
        hudView.setTraceDegraded(degraded)
    }

    func setScopeNeedsReview(_ needsReview: Bool) {
        hudView.setScopeNeedsReview(needsReview)
    }

    func showTransientStatus(_ message: String) {
        hudView.showTransientStatus(message)
    }

    static func placementFrame(anchor: CGRect, screen: NSScreen) -> CGRect {
        let padding: CGFloat = 12
        let gap: CGFloat = 10
        let visible = screen.visibleFrame.insetBy(dx: padding, dy: padding)
        let preferredWidth = min(424, max(330, visible.width))
        let size = CGSize(width: min(preferredWidth, visible.width), height: 46)
        let outsideAnchor = anchor.insetBy(dx: -2, dy: -2)
        func clamped(_ value: CGFloat, lower: CGFloat, upper: CGFloat) -> CGFloat {
            min(max(value, lower), upper)
        }
        let centeredX = clamped(anchor.midX - size.width / 2, lower: visible.minX, upper: visible.maxX - size.width)
        let centeredY = clamped(anchor.midY - size.height / 2, lower: visible.minY, upper: visible.maxY - size.height)
        let candidates = [
            CGRect(x: centeredX, y: anchor.maxY + gap, width: size.width, height: size.height),
            CGRect(x: centeredX, y: anchor.minY - size.height - gap, width: size.width, height: size.height),
            CGRect(x: anchor.maxX + gap, y: centeredY, width: size.width, height: size.height),
            CGRect(x: anchor.minX - size.width - gap, y: centeredY, width: size.width, height: size.height),
        ]
        if let outside = candidates.first(where: { visible.contains($0) && !$0.intersects(outsideAnchor) }) {
            return outside
        }
        // Near-fullscreen recordings leave no outside slot. Keep the control HUD
        // visible at the screen edge; ScreenCaptureKit excludes WorkRecorder's
        // own process, so the user keeps trustworthy controls without recording
        // the overlay into the video artifact.
        return CGRect(
            x: clamped(visible.maxX - size.width, lower: visible.minX, upper: visible.maxX - size.width),
            y: clamped(visible.maxY - size.height, lower: visible.minY, upper: visible.maxY - size.height),
            width: size.width,
            height: size.height
        )
    }
}

enum RecordingHUDMode: Equatable {
    case preparing
    case recording
    case paused
    case stopping
}
private final class RecordingHUDView: NSView {
    private let elapsedLabel = NSTextField(labelWithString: "00:00")
    private let statusLabel = NSTextField(labelWithString: "正在启动")
    private let statusIndicator = RecordingStatusIndicator()
    private let markButton: WorkRecorderPillButton
    private let pauseButton: WorkRecorderPillButton
    private let finishButton: WorkRecorderPillButton
    private let onMark: () -> Void
    private let onPauseToggle: () -> Void
    private let onFinish: () -> Void
    private let onStopRequest: () -> Void
    private var mode: RecordingHUDMode = .preparing
    private var traceDegraded = false
    private var scopeNeedsReview = false
    private var transientStatus: String?
    private var transientStatusToken = UUID()

    init(
        onMark: @escaping () -> Void,
        onPauseToggle: @escaping () -> Void,
        onFinish: @escaping () -> Void,
        onStopRequest: @escaping () -> Void
    ) {
        self.onMark = onMark
        self.onPauseToggle = onPauseToggle
        self.onFinish = onFinish
        self.onStopRequest = onStopRequest
        markButton = WorkRecorderPillButton(title: "标记", variant: .quiet, target: nil, action: nil)
        pauseButton = WorkRecorderPillButton(title: "暂停", variant: .secondary, target: nil, action: nil)
        finishButton = WorkRecorderPillButton(title: "结束录制", variant: .primary, target: nil, action: nil)
        super.init(frame: .zero)
        wantsLayer = true
        setup()
    }

    required init?(coder: NSCoder) {
        nil
    }

    private func setup() {
        elapsedLabel.font = NSFont.monospacedDigitSystemFont(ofSize: 13.2, weight: .semibold)
        elapsedLabel.textColor = WorkRecorderTheme.primaryText
        statusLabel.font = WorkRecorderTheme.Font.metadata
        statusLabel.textColor = WorkRecorderTheme.secondaryText
        statusLabel.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        markButton.target = self
        markButton.action = #selector(markPressed)
        markButton.setAccessibilityLabel("添加录制标记")
        pauseButton.target = self
        pauseButton.action = #selector(pausePressed)
        pauseButton.setAccessibilityLabel("暂停或继续录制")
        finishButton.target = self
        finishButton.action = #selector(finishPressed)
        finishButton.setAccessibilityLabel("完成录制并进入保存确认")
        let stack = NSStackView(views: [statusIndicator, elapsedLabel, statusLabel, markButton, pauseButton, finishButton])
        stack.orientation = .horizontal
        stack.alignment = .centerY
        stack.spacing = 9
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 13),
            stack.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -13),
            stack.centerYAnchor.constraint(equalTo: centerYAnchor),
        ])
    }

    func update(elapsedMilliseconds: Int, paused: Bool) {
        elapsedLabel.stringValue = Self.formatted(milliseconds: elapsedMilliseconds)
        setMode(paused ? .paused : .recording)
    }

    func setMode(_ mode: RecordingHUDMode) {
        self.mode = mode
        updateModePresentation()
        setAccessibilityLabel("WorkRecorder \(statusLabel.stringValue)，时长 \(elapsedLabel.stringValue)")
        needsDisplay = true
    }

    func setTraceDegraded(_ degraded: Bool) {
        traceDegraded = degraded
        updateModePresentation()
        setAccessibilityHelp(degraded ? "输入监听权限或系统限制导致点击、滚动、键盘轨迹可能不完整。" : nil)
        needsDisplay = true
    }

    func setScopeNeedsReview(_ needsReview: Bool) {
        scopeNeedsReview = needsReview
        updateModePresentation()
        let help = needsReview ? "录制仍限定在你框选的固定区域，但窗口线索发生变化，复盘时需要确认。" : nil
        setAccessibilityHelp(help)
        needsDisplay = true
    }

    func showTransientStatus(_ message: String) {
        transientStatus = message
        transientStatusToken = UUID()
        let token = transientStatusToken
        updateModePresentation()
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) { [weak self] in
            guard let self, self.transientStatusToken == token else { return }
            self.transientStatus = nil
            self.updateModePresentation()
        }
    }

    private func updateModePresentation() {
        statusIndicator.mode = mode
        statusIndicator.traceDegraded = traceDegraded
        statusIndicator.scopeNeedsReview = scopeNeedsReview
        let fallbackText: String
        switch mode {
        case .preparing:
            fallbackText = degradedStatusText(defaultText: "正在启动")
            pauseButton.title = "暂停"
            [markButton, pauseButton, finishButton].forEach { $0.isEnabled = false }
        case .recording:
            fallbackText = degradedStatusText(defaultText: "正在录制")
            pauseButton.title = "暂停"
            [markButton, pauseButton, finishButton].forEach { $0.isEnabled = true }
        case .paused:
            fallbackText = degradedStatusText(defaultText: "已暂停，不会录制", prefix: "已暂停")
            pauseButton.title = "继续"
            [markButton, pauseButton, finishButton].forEach { $0.isEnabled = true }
        case .stopping:
            fallbackText = "正在整理"
            pauseButton.title = "暂停"
            [markButton, pauseButton, finishButton].forEach { $0.isEnabled = false }
        }
        statusLabel.stringValue = transientStatus ?? fallbackText
        statusLabel.textColor = if transientStatus != nil {
            WorkRecorderTheme.Prism.tiffanyBlue
        } else {
            (traceDegraded || scopeNeedsReview) && mode != .stopping ? WorkRecorderTheme.warning : WorkRecorderTheme.secondaryText
        }
    }

    private func degradedStatusText(defaultText: String, prefix: String? = nil) -> String {
        let parts = [
            traceDegraded ? "输入监听受限" : nil,
            scopeNeedsReview ? "范围需复核" : nil,
        ].compactMap(\.self)
        guard !parts.isEmpty else { return defaultText }
        if let prefix {
            return "\(prefix) · \(parts.joined(separator: " · "))"
        }
        return parts.joined(separator: " · ")
    }

    @objc private func markPressed() { onMark() }
    @objc private func pausePressed() { onPauseToggle() }
    @objc private func finishPressed() { onFinish() }

    func togglePauseFromKeyboard() {
        guard pauseButton.isEnabled else { return }
        onPauseToggle()
    }

    func requestStopFromKeyboard() {
        guard finishButton.isEnabled else { return }
        onStopRequest()
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let panel = bounds.insetBy(dx: 0.5, dy: 0.5)
        let path = WorkRecorderTheme.roundedRectPath(panel, radius: 23)
        let isPassive = mode == .paused || mode == .preparing || mode == .stopping
        let top = isPassive ? WorkRecorderTheme.Material.panelGlassTop : NSColor(calibratedRed: 1.0, green: 0.968, blue: 0.956, alpha: 0.97)
        let bottom = isPassive ? WorkRecorderTheme.Material.panelGlassBottom : NSColor(calibratedRed: 0.972, green: 0.912, blue: 0.898, alpha: 0.94)
        NSGradient(colors: [top, bottom])?.draw(in: path, angle: 92)
        let hasWarning = traceDegraded || scopeNeedsReview
        let stroke = switch mode {
        case .paused:
            WorkRecorderTheme.warning
        case .preparing, .stopping:
            hasWarning ? WorkRecorderTheme.warning : WorkRecorderTheme.Prism.tiffanyBlue
        case .recording:
            hasWarning ? WorkRecorderTheme.warning : NSColor(calibratedRed: 0.78, green: 0.18, blue: 0.16, alpha: 1.0)
        }
        stroke
            .withAlphaComponent(0.26)
            .setStroke()
        path.lineWidth = 1
        path.stroke()
    }

    private static func formatted(milliseconds: Int) -> String {
        let totalSeconds = max(0, milliseconds / 1000)
        return String(format: "%02d:%02d", totalSeconds / 60, totalSeconds % 60)
    }
}

@MainActor
final class RecordingBoundaryOverlayWindow: NSPanel {
    private let boundaryView: RecordingBoundaryOverlayView

    init(screen: NSScreen, selection: CGRect) {
        boundaryView = RecordingBoundaryOverlayView(selection: Geometry.overlayRect(for: selection, on: screen))
        super.init(contentRect: screen.frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isOpaque = false
        backgroundColor = .clear
        level = .screenSaver
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        ignoresMouseEvents = true
        contentView = boundaryView
    }

    func setPaused(_ paused: Bool) {
        boundaryView.paused = paused
    }
}

@MainActor
private final class RecordingBoundaryOverlayView: NSView {
    override var isFlipped: Bool { true }
    let selection: CGRect
    var paused = false {
        didSet { needsDisplay = true }
    }

    init(selection: CGRect) {
        self.selection = selection
        super.init(frame: .zero)
        wantsLayer = true
    }

    required init?(coder: NSCoder) {
        nil
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let rect = selection.insetBy(dx: 0.5, dy: 0.5)
        let halo = NSBezierPath(rect: rect)
        halo.lineWidth = paused ? 4.2 : 3.6
        if paused {
            WorkRecorderTheme.warning.withAlphaComponent(0.08).setStroke()
        } else {
            NSColor(calibratedRed: 0.86, green: 0.14, blue: 0.12, alpha: 0.075).setStroke()
        }
        halo.stroke()

        let border = NSBezierPath(rect: rect)
        border.lineWidth = paused ? 1.35 : 1.25
        if paused {
            border.setLineDash([7, 5], count: 2, phase: 0)
            WorkRecorderTheme.warning.withAlphaComponent(0.76).setStroke()
        } else {
            NSColor(calibratedRed: 0.86, green: 0.14, blue: 0.12, alpha: 0.68).setStroke()
        }
        border.stroke()
        drawCornerTicks(in: rect)
        drawStatusBadge(in: rect)
    }

    private func drawCornerTicks(in rect: CGRect) {
        let tickLength: CGFloat = 22
        let tick = NSBezierPath()
        tick.move(to: CGPoint(x: rect.minX, y: rect.minY + tickLength))
        tick.line(to: CGPoint(x: rect.minX, y: rect.minY))
        tick.line(to: CGPoint(x: rect.minX + tickLength, y: rect.minY))
        tick.move(to: CGPoint(x: rect.maxX - tickLength, y: rect.minY))
        tick.line(to: CGPoint(x: rect.maxX, y: rect.minY))
        tick.line(to: CGPoint(x: rect.maxX, y: rect.minY + tickLength))
        tick.move(to: CGPoint(x: rect.minX, y: rect.maxY - tickLength))
        tick.line(to: CGPoint(x: rect.minX, y: rect.maxY))
        tick.line(to: CGPoint(x: rect.minX + tickLength, y: rect.maxY))
        tick.move(to: CGPoint(x: rect.maxX - tickLength, y: rect.maxY))
        tick.line(to: CGPoint(x: rect.maxX, y: rect.maxY))
        tick.line(to: CGPoint(x: rect.maxX, y: rect.maxY - tickLength))
        tick.lineWidth = 2.0
        if paused {
            WorkRecorderTheme.warning.withAlphaComponent(0.90).setStroke()
        } else {
            NSColor(calibratedRed: 0.90, green: 0.18, blue: 0.15, alpha: 0.86).setStroke()
        }
        tick.stroke()
    }

    private func drawStatusBadge(in rect: CGRect) {
        let text = WorkRecorderLocalization.text(paused ? "已暂停" : "录制区域")
        let tint = paused ? WorkRecorderTheme.warning : NSColor(calibratedRed: 0.86, green: 0.14, blue: 0.12, alpha: 1)
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 12.0, weight: .semibold),
            .foregroundColor: tint.withAlphaComponent(0.94),
        ]
        let size = (text as NSString).size(withAttributes: attributes)
        let badgeRect = CGRect(
            x: rect.minX + 12,
            y: max(8, rect.minY - 31),
            width: size.width + 20,
            height: 24
        )
        let path = WorkRecorderTheme.roundedRectPath(badgeRect, radius: 12)
        NSColor.white.withAlphaComponent(0.90).setFill()
        path.fill()
        tint.withAlphaComponent(0.30).setStroke()
        path.lineWidth = 0.9
        path.stroke()
        (text as NSString).draw(
            in: CGRect(x: badgeRect.minX + 10, y: badgeRect.minY + 4.0, width: size.width, height: 17),
            withAttributes: attributes
        )
    }
}

@MainActor
final class RecordingCountdownWindow: NSPanel {
    private let countdownView = RecordingCountdownView()
    private let onCancel: () -> Void

    init(anchor: CGRect, screen: NSScreen, onCancel: @escaping () -> Void = {}) {
        self.onCancel = onCancel
        let size = CGSize(width: 120, height: 92)
        let frame = CGRect(
            x: min(max(anchor.midX - size.width / 2, screen.visibleFrame.minX + 12), screen.visibleFrame.maxX - size.width - 12),
            y: min(max(anchor.midY - size.height / 2, screen.visibleFrame.minY + 12), screen.visibleFrame.maxY - size.height - 12),
            width: size.width,
            height: size.height
        )
        super.init(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isOpaque = false
        backgroundColor = .clear
        level = .screenSaver
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        ignoresMouseEvents = false
        contentView = countdownView
    }

    override var canBecomeKey: Bool {
        true
    }

    override func keyDown(with event: NSEvent) {
        if event.keyCode == CaptureKeyCode.escape {
            onCancel()
            return
        }
        super.keyDown(with: event)
    }

    func setValue(_ value: String) {
        countdownView.value = value
    }
}

@MainActor
private final class RecordingCountdownView: NSView {
    var value = "3" {
        didSet { needsDisplay = true }
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let panel = bounds.insetBy(dx: 1, dy: 1)
        let path = WorkRecorderTheme.roundedRectPath(panel, radius: 24)
        WorkRecorderTheme.Material.panelGlassTop.withAlphaComponent(0.86).setFill()
        path.fill()
        WorkRecorderTheme.Prism.tiffanyBlue.withAlphaComponent(0.20).setStroke()
        path.lineWidth = 1
        path.stroke()
        let fontSize: CGFloat = value.count > 1 ? 20 : 42
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: fontSize, weight: .semibold),
            .foregroundColor: WorkRecorderTheme.primaryText,
        ]
        let size = (value as NSString).size(withAttributes: attributes)
        value.draw(
            at: CGPoint(x: bounds.midX - size.width / 2, y: bounds.midY - size.height / 2),
            withAttributes: attributes
        )
        guard value != "Recording" else { return }
        let hint = WorkRecorderLocalization.text("Esc 取消") as NSString
        let hintAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 10.5, weight: .medium),
            .foregroundColor: WorkRecorderTheme.secondaryText,
        ]
        let hintSize = hint.size(withAttributes: hintAttributes)
        hint.draw(
            at: CGPoint(x: bounds.midX - hintSize.width / 2, y: 14),
            withAttributes: hintAttributes
        )
    }
}
