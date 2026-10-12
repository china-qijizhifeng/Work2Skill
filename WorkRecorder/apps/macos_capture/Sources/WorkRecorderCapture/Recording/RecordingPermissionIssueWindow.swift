import AppKit

@MainActor
final class RecordingPermissionIssueWindow: NSPanel {
    private let issueView: RecordingPermissionIssueView

    init(
        anchor: CGRect,
        screen: NSScreen,
        issue: RecordingPermissionIssue,
        onPrimaryAction: @escaping () -> Void,
        onDismiss: @escaping () -> Void
    ) {
        let size = CGSize(width: min(548, max(476, screen.visibleFrame.width - 36)), height: 306)
        let frame = Geometry.recordingOverlayFrame(anchor: anchor, panelSize: size, visibleFrame: screen.visibleFrame)
        issueView = RecordingPermissionIssueView(
            issue: issue,
            onPrimaryAction: onPrimaryAction,
            onDismiss: onDismiss
        )
        super.init(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isOpaque = false
        backgroundColor = .clear
        level = .floating
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        contentView = issueView
    }

    override var canBecomeKey: Bool { true }

    override func keyDown(with event: NSEvent) {
        switch event.keyCode {
        case CaptureKeyCode.escape:
            issueView.dismiss()
        case CaptureKeyCode.return, CaptureKeyCode.keypadEnter:
            issueView.primaryAction()
        default:
            super.keyDown(with: event)
        }
    }
}

private final class RecordingPermissionIssueView: NSView {
    private let issue: RecordingPermissionIssue
    private let onPrimaryAction: () -> Void
    private let onDismiss: () -> Void

    init(
        issue: RecordingPermissionIssue,
        onPrimaryAction: @escaping () -> Void,
        onDismiss: @escaping () -> Void
    ) {
        self.issue = issue
        self.onPrimaryAction = onPrimaryAction
        self.onDismiss = onDismiss
        super.init(frame: .zero)
        wantsLayer = true
        setup()
    }

    required init?(coder: NSCoder) {
        nil
    }

    private func setup() {
        let eyebrow = NSTextField(labelWithString: "区域录制权限")
        eyebrow.font = NSFont.systemFont(ofSize: 11.2, weight: .semibold)
        eyebrow.textColor = WorkRecorderTheme.Prism.tiffanyBlue

        let title = NSTextField(labelWithString: issue.kind.title)
        title.font = NSFont.systemFont(ofSize: 16.0, weight: .semibold)
        title.textColor = WorkRecorderTheme.primaryText

        let detail = NSTextField(labelWithString: issue.kind.detail)
        detail.font = NSFont.systemFont(ofSize: 12.0, weight: .regular)
        detail.textColor = WorkRecorderTheme.secondaryText
        detail.maximumNumberOfLines = 3
        detail.lineBreakMode = .byWordWrapping
        detail.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        detail.preferredMaxLayoutWidth = 468

        let summary = Self.summaryPanel(issue)
        let primary = WorkRecorderPillButton(
            title: issue.kind.primaryActionTitle,
            variant: .primary,
            target: self,
            action: #selector(primaryPressed)
        )
        primary.setAccessibilityLabel(issue.kind.primaryActionTitle)
        let dismiss = WorkRecorderPillButton(title: "知道了", variant: .secondary, target: self, action: #selector(dismissPressed))
        dismiss.setAccessibilityLabel("关闭录制权限提示")
        let actions = NSStackView(views: [primary, dismiss])
        actions.orientation = .horizontal
        actions.spacing = 9
        actions.alignment = .centerY

        let copy = NSStackView(views: [eyebrow, title, detail, summary])
        copy.orientation = .vertical
        copy.alignment = .leading
        copy.spacing = 12
        let root = NSStackView(views: [copy, actions])
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 22
        root.translatesAutoresizingMaskIntoConstraints = false
        addSubview(root)
        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 26),
            root.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -26),
            root.topAnchor.constraint(greaterThanOrEqualTo: topAnchor, constant: 24),
            root.bottomAnchor.constraint(lessThanOrEqualTo: bottomAnchor, constant: -24),
            root.centerYAnchor.constraint(equalTo: centerYAnchor, constant: 2),
            detail.widthAnchor.constraint(lessThanOrEqualToConstant: 468),
        ])
        setAccessibilityLabel("\(issue.kind.title)。\(issue.kind.detail)")
    }

    private static func summaryPanel(_ issue: RecordingPermissionIssue) -> NSView {
        var rows: [NSView] = [
            factRow(title: "区域", detail: issue.selectedRegionDescription, tint: WorkRecorderTheme.Prism.tiffanyBlue),
            factRow(title: "来源", detail: issue.sourceDescription ?? "未识别窗口", tint: WorkRecorderTheme.secondaryText),
        ]
        if let diagnostic = issue.diagnostic?.trimmingCharacters(in: .whitespacesAndNewlines), !diagnostic.isEmpty {
            rows.append(factRow(title: "系统", detail: Self.truncated(diagnostic), tint: WorkRecorderTheme.warning))
        }
        let stack = NSStackView(views: rows)
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 9
        stack.translatesAutoresizingMaskIntoConstraints = false

        let panel = NSView()
        panel.wantsLayer = true
        panel.layer?.cornerRadius = 14
        panel.layer?.backgroundColor = WorkRecorderTheme.Prism.mintGlass.withAlphaComponent(0.12).cgColor
        panel.layer?.borderColor = WorkRecorderTheme.Prism.tiffanyBlue.withAlphaComponent(0.18).cgColor
        panel.layer?.borderWidth = 0.8
        panel.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: panel.leadingAnchor, constant: 14),
            stack.trailingAnchor.constraint(equalTo: panel.trailingAnchor, constant: -14),
            stack.topAnchor.constraint(equalTo: panel.topAnchor, constant: 12),
            stack.bottomAnchor.constraint(equalTo: panel.bottomAnchor, constant: -12),
            panel.widthAnchor.constraint(lessThanOrEqualToConstant: 472),
        ])
        return panel
    }

    private static func factRow(title: String, detail: String, tint: NSColor) -> NSView {
        let titleLabel = NSTextField(labelWithString: title)
        titleLabel.font = NSFont.systemFont(ofSize: 11.0, weight: .semibold)
        titleLabel.textColor = tint
        titleLabel.alignment = .right
        titleLabel.translatesAutoresizingMaskIntoConstraints = false
        let detailLabel = NSTextField(labelWithString: detail)
        detailLabel.font = WorkRecorderTheme.Font.metadata
        detailLabel.textColor = WorkRecorderTheme.secondaryText
        detailLabel.maximumNumberOfLines = 1
        detailLabel.lineBreakMode = .byTruncatingTail
        detailLabel.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        let row = NSStackView(views: [titleLabel, detailLabel])
        row.orientation = .horizontal
        row.alignment = .firstBaseline
        row.spacing = 10
        NSLayoutConstraint.activate([
            titleLabel.widthAnchor.constraint(equalToConstant: 40),
            detailLabel.widthAnchor.constraint(lessThanOrEqualToConstant: 384),
        ])
        row.setAccessibilityLabel("\(title)：\(detail)")
        return row
    }

    private static func truncated(_ value: String) -> String {
        guard value.count > 34 else { return value }
        return "\(value.prefix(31))..."
    }

    @objc private func primaryPressed() { primaryAction() }
    @objc private func dismissPressed() { dismiss() }

    func primaryAction() { onPrimaryAction() }

    func dismiss() { onDismiss() }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let panel = bounds.insetBy(dx: 1, dy: 1)
        let path = WorkRecorderTheme.roundedRectPath(panel, radius: 24)
        NSGradient(colors: [
            WorkRecorderTheme.Material.panelGlassTop.withAlphaComponent(0.98),
            WorkRecorderTheme.Material.panelGlassBottom.withAlphaComponent(0.94),
        ])?.draw(in: path, angle: 92)

        let glow = NSBezierPath(roundedRect: panel.insetBy(dx: 8, dy: 8), xRadius: 20, yRadius: 20)
        WorkRecorderTheme.warning.withAlphaComponent(0.035).setFill()
        glow.fill()
        WorkRecorderTheme.warning.withAlphaComponent(0.22).setStroke()
        path.lineWidth = 1.05
        path.stroke()
        WorkRecorderTheme.Prism.tiffanyBlue.withAlphaComponent(0.10).setStroke()
        let accent = NSBezierPath()
        accent.move(to: CGPoint(x: panel.minX + 24, y: panel.maxY - 24))
        accent.line(to: CGPoint(x: panel.maxX - 24, y: panel.maxY - 24))
        accent.lineWidth = 0.8
        accent.stroke()
    }
}
