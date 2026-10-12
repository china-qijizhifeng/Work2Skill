import AppKit

@MainActor
final class RecordingDiscardConfirmationWindow: NSPanel {
    private let confirmationView: RecordingDiscardConfirmationView

    init(
        anchor: CGRect,
        screen: NSScreen,
        onConfirm: @escaping () -> Void,
        onCancel: @escaping () -> Void
    ) {
        let size = CGSize(width: min(470, max(410, screen.visibleFrame.width - 36)), height: 176)
        let frame = Geometry.recordingOverlayFrame(anchor: anchor, panelSize: size, visibleFrame: screen.visibleFrame)
        confirmationView = RecordingDiscardConfirmationView(onConfirm: onConfirm, onCancel: onCancel)
        super.init(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isOpaque = false
        backgroundColor = .clear
        level = .floating
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        contentView = confirmationView
    }

    override var canBecomeKey: Bool { true }

    override func keyDown(with event: NSEvent) {
        switch event.keyCode {
        case CaptureKeyCode.escape:
            confirmationView.cancel()
        case 36, 76:
            confirmationView.cancel()
        default:
            super.keyDown(with: event)
        }
    }
}

@MainActor
private final class RecordingDiscardConfirmationView: NSView {
    private let onConfirm: () -> Void
    private let onCancel: () -> Void

    init(onConfirm: @escaping () -> Void, onCancel: @escaping () -> Void) {
        self.onConfirm = onConfirm
        self.onCancel = onCancel
        super.init(frame: .zero)
        wantsLayer = true
        setup()
    }

    required init?(coder: NSCoder) {
        nil
    }

    private func setup() {
        let title = NSTextField(labelWithString: "丢弃这段录制？")
        title.font = NSFont.systemFont(ofSize: 15.0, weight: .semibold)
        title.textColor = WorkRecorderTheme.primaryText

        let detail = NSTextField(labelWithString: "临时视频、关键帧和未保存的时间线会被删除；不会进入录制库。")
        detail.font = WorkRecorderTheme.Font.hint
        detail.textColor = WorkRecorderTheme.secondaryText
        detail.maximumNumberOfLines = 2

        let cancel = WorkRecorderPillButton(title: "返回", variant: .primary, target: self, action: #selector(cancelPressed))
        cancel.setAccessibilityLabel("返回录制完成面板")
        cancel.setAccessibilityHelp("回到录制完成面板，不删除任何本地材料。")
        let confirm = WorkRecorderPillButton(title: "丢弃录制", variant: .destructive, target: self, action: #selector(confirmPressed))
        confirm.setAccessibilityLabel("确认丢弃录制")
        confirm.setAccessibilityHelp("取消本次录制并删除本地临时视频。")

        let buttons = NSStackView(views: [cancel, confirm])
        buttons.orientation = .horizontal
        buttons.spacing = 9
        buttons.alignment = .centerY

        let root = NSStackView(views: [title, detail, buttons])
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 13
        root.translatesAutoresizingMaskIntoConstraints = false
        addSubview(root)
        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 22),
            root.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor, constant: -22),
            root.centerYAnchor.constraint(equalTo: centerYAnchor),
        ])
    }

    @objc private func confirmPressed() { confirm() }
    @objc private func cancelPressed() { cancel() }

    func confirm() { onConfirm() }

    func cancel() { onCancel() }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let panel = bounds.insetBy(dx: 1, dy: 1)
        let path = WorkRecorderTheme.roundedRectPath(panel, radius: 24)
        NSGradient(colors: [
            WorkRecorderTheme.Material.panelGlassTop.withAlphaComponent(0.97),
            WorkRecorderTheme.Material.panelGlassBottom.withAlphaComponent(0.94),
        ])?.draw(in: path, angle: 92)
        WorkRecorderTheme.warning.withAlphaComponent(0.22).setStroke()
        path.lineWidth = 1.2
        path.stroke()
    }
}
