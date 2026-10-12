import AppKit

@MainActor
final class RecordingCompletionWindow: NSPanel {
    private let completionView: RecordingCompletionView

    init(
        draft: RecordingCompletionDraft,
        screen: NSScreen,
        onSave: @escaping (String) -> Void,
        onDiscard: @escaping () -> Void,
        onPreview: @escaping () -> Void
    ) {
        let availableWidth = max(390, screen.visibleFrame.width - 36)
        let layout = RecordingCompletionLayout.make(availableWidth: availableWidth)
        let size = CGSize(width: layout.windowWidth, height: layout.windowHeight)
        let frame = Geometry.recordingOverlayFrame(
            anchor: draft.selection.screenRect,
            panelSize: size,
            visibleFrame: screen.visibleFrame
        )
        let view = RecordingCompletionView(
            draft: draft,
            layout: layout,
            onSave: onSave,
            onDiscard: onDiscard,
            onPreview: onPreview
        )
        completionView = view
        super.init(contentRect: frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isOpaque = false
        backgroundColor = .clear
        level = .floating
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        contentView = view
    }

    override var canBecomeKey: Bool { true }

    override func keyDown(with event: NSEvent) {
        if completionView.performTextEditingKeyEquivalent(event) {
            return
        }
        switch event.keyCode {
        case CaptureKeyCode.escape:
            completionView.confirmDiscard()
        case 36, 76:
            completionView.save()
        default:
            super.keyDown(with: event)
        }
    }

    override func performKeyEquivalent(with event: NSEvent) -> Bool {
        if completionView.performTextEditingKeyEquivalent(event) {
            return true
        }
        return super.performKeyEquivalent(with: event)
    }

    func focusNote() {
        makeKey()
        completionView.focusNote()
    }

    func setSubmitting(_ submitting: Bool) {
        completionView.setSubmitting(submitting)
    }

    func setErrorMessage(_ message: String?) {
        completionView.setErrorMessage(message)
    }
}

@MainActor
private final class RecordingCompletionView: NSView {
    private let onSave: (String) -> Void
    private let onDiscard: () -> Void
    private let onPreview: () -> Void
    private let layout: RecordingCompletionLayout
    private let noteField = NSTextField()
    private let noteShell = WorkRecorderInputShell()
    private let errorLabel = NSTextField(labelWithString: "")
    private var actionButtons: [NSButton] = []
    private var previewButton: WorkRecorderPillButton?
    private var previewAvailable = false

    init(
        draft: RecordingCompletionDraft,
        layout: RecordingCompletionLayout,
        onSave: @escaping (String) -> Void,
        onDiscard: @escaping () -> Void,
        onPreview: @escaping () -> Void
    ) {
        self.onSave = onSave
        self.onDiscard = onDiscard
        self.onPreview = onPreview
        self.layout = layout
        super.init(frame: .zero)
        wantsLayer = true
        setup(draft: draft)
    }

    required init?(coder: NSCoder) {
        nil
    }

    private func setup(draft: RecordingCompletionDraft) {
        let previewAsset = RecordingCompletionPreviewAsset(draft: draft)
        let preview = RecordingCompletionPreviewView(asset: previewAsset)
        preview.translatesAutoresizingMaskIntoConstraints = false
        preview.widthAnchor.constraint(equalToConstant: layout.previewSize.width).isActive = true
        preview.heightAnchor.constraint(equalToConstant: layout.previewSize.height).isActive = true

        let title = NSTextField(labelWithString: "录制完成")
        title.font = NSFont.systemFont(ofSize: 15.0, weight: .semibold)
        title.textColor = WorkRecorderTheme.primaryText
        let warningSuffix = Self.warningSuffix(for: draft)
        let detail = NSTextField(labelWithString: "\(Self.formatted(milliseconds: draft.totalDurationMilliseconds)) · \(draft.segments.count) 段 · \(draft.totalFrameCount) 帧\(warningSuffix)")
        detail.font = WorkRecorderTheme.Font.metadata
        detail.textColor = draft.inputTraceDegraded || draft.scopeNeedsReview
            ? WorkRecorderTheme.warning
            : WorkRecorderTheme.secondaryText
        let hintText = Self.hintText(for: draft)
        let hint = NSTextField(labelWithString: hintText)
        hint.font = WorkRecorderTheme.Font.hint
        hint.textColor = WorkRecorderTheme.mutedText
        hint.maximumNumberOfLines = 2
        errorLabel.font = WorkRecorderTheme.Font.hint
        errorLabel.textColor = WorkRecorderTheme.warning
        errorLabel.maximumNumberOfLines = 2
        errorLabel.isHidden = true

        let noteLabel = NSTextField(labelWithString: "给这段录制一句备注")
        noteLabel.font = WorkRecorderTheme.Font.label
        noteLabel.textColor = WorkRecorderTheme.secondaryText
        noteField.font = WorkRecorderTheme.Font.input
        noteField.backgroundColor = .clear
        noteField.isBordered = false
        noteField.focusRingType = .none
        noteField.placeholderString = "例如：API key 轮换步骤、失败原因、注意事项"
        noteField.target = self
        noteField.action = #selector(savePressed)
        noteField.delegate = self
        noteField.setAccessibilityLabel("录制备注")
        noteField.setAccessibilityHelp("可选。保存后可在录制中心搜索、复盘并继续整理。")
        noteField.translatesAutoresizingMaskIntoConstraints = false
        noteShell.translatesAutoresizingMaskIntoConstraints = false
        noteShell.addSubview(noteField)
        NSLayoutConstraint.activate([
            noteShell.heightAnchor.constraint(equalToConstant: 40),
            noteField.leadingAnchor.constraint(equalTo: noteShell.leadingAnchor, constant: 13),
            noteField.trailingAnchor.constraint(equalTo: noteShell.trailingAnchor, constant: -13),
            noteField.centerYAnchor.constraint(equalTo: noteShell.centerYAnchor),
        ])

        let save = WorkRecorderPillButton(title: "保存", variant: .primary, target: self, action: #selector(savePressed))
        save.setAccessibilityLabel("保存录制")
        save.setAccessibilityHelp("提交录制视频和关键帧，并完成本次录制。")
        let discard = WorkRecorderPillButton(title: "丢弃", variant: .quiet, target: self, action: #selector(discardPressed))
        discard.setAccessibilityLabel("丢弃录制")
        discard.setAccessibilityHelp("先确认，再取消本次录制并移除本地临时视频。")
        previewAvailable = previewAsset.videoURL != nil
        let previewButton = WorkRecorderPillButton(
            title: previewAsset.videoURL == nil ? "视频暂不可用" : "打开本地预览",
            variant: previewAsset.videoURL == nil ? .quiet : .secondary,
            target: self,
            action: #selector(previewPressed)
        )
        previewButton.isEnabled = previewAsset.videoURL != nil
        previewButton.setAccessibilityLabel("本地预览录制")
        previewButton.setAccessibilityHelp(previewAsset.videoURL == nil ? "本地视频文件暂不可用。" : "在保存前打开本地临时视频预览。")
        self.previewButton = previewButton
        actionButtons = [save, previewButton, discard]
        let buttons = NSStackView(views: [save, previewButton, discard])
        buttons.orientation = .horizontal
        buttons.spacing = 9
        buttons.alignment = .centerY

        let copy = NSStackView(views: [title, detail, hint, errorLabel, noteLabel, noteShell, buttons])
        copy.orientation = .vertical
        copy.alignment = .leading
        copy.spacing = 8
        noteShell.widthAnchor.constraint(equalToConstant: layout.noteWidth).isActive = true
        let root = NSStackView(views: [preview, copy])
        root.orientation = layout.rootOrientation
        root.alignment = layout.rootAlignment
        root.spacing = layout.rootSpacing
        root.translatesAutoresizingMaskIntoConstraints = false
        addSubview(root)
        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 22),
            root.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor, constant: -22),
            root.centerYAnchor.constraint(equalTo: centerYAnchor),
        ])
    }

    @objc private func savePressed() { save() }
    @objc private func discardPressed() { confirmDiscard() }
    @objc private func previewPressed() { onPreview() }

    func save() { onSave(Self.sanitizedNote(noteField.stringValue)) }

    func focusNote() {
        window?.makeFirstResponder(noteField)
    }

    func performTextEditingKeyEquivalent(_ event: NSEvent) -> Bool {
        guard noteField.isEnabled,
              event.modifierFlags.intersection(.deviceIndependentFlagsMask).contains(.command),
              event.charactersIgnoringModifiers?.lowercased() == "v",
              let window,
              let editor = window.fieldEditor(false, for: noteField) as? NSTextView,
              window.firstResponder === editor
        else {
            return false
        }
        editor.paste(nil)
        return true
    }

    func confirmDiscard() { onDiscard() }

    func setSubmitting(_ submitting: Bool) {
        actionButtons.forEach { $0.isEnabled = !submitting }
        previewButton?.isEnabled = !submitting && previewAvailable
        noteField.isEnabled = !submitting
        if submitting {
            setErrorMessage(nil)
        }
    }

    func setErrorMessage(_ message: String?) {
        let trimmed = message?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        errorLabel.stringValue = trimmed
        errorLabel.isHidden = trimmed.isEmpty
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let panel = bounds.insetBy(dx: 1, dy: 1)
        let path = WorkRecorderTheme.roundedRectPath(panel, radius: 24)
        NSGradient(colors: [
            WorkRecorderTheme.Material.panelGlassTop.withAlphaComponent(0.96),
            WorkRecorderTheme.Material.panelGlassBottom.withAlphaComponent(0.94),
        ])?.draw(in: path, angle: 92)
        WorkRecorderTheme.Prism.tiffanyBlue.withAlphaComponent(0.16).setStroke()
        path.lineWidth = 1.2
        path.stroke()
    }

    private static func formatted(milliseconds: Int) -> String {
        let totalSeconds = max(0, milliseconds / 1000)
        return String(format: "%02d:%02d", totalSeconds / 60, totalSeconds % 60)
    }

    private static func warningSuffix(for draft: RecordingCompletionDraft) -> String {
        let parts = [
            draft.inputTraceDegraded ? "输入监听受限" : nil,
            draft.scopeNeedsReview ? "范围需复核" : nil,
        ].compactMap(\.self)
        return parts.isEmpty ? "" : " · \(parts.joined(separator: " · "))"
    }

    private static func hintText(for draft: RecordingCompletionDraft) -> String {
        if draft.inputTraceDegraded && draft.scopeNeedsReview {
            return "操作线索和窗口范围都需要复核；视频仍按固定区域保存，复盘中会标记需要确认。"
        }
        if draft.inputTraceDegraded {
            return "输入监听受限；仍可保存视频和关键帧，复盘中会标记需要确认。可在设置里开启辅助功能后重试。"
        }
        if draft.scopeNeedsReview {
            return "窗口线索发生变化；视频仍按你框选的固定区域保存，复盘时请确认范围和目标。"
        }
        return "可打开本地预览确认内容；保存前不会上传原始视频，丢弃会移除本地临时视频。"
    }

    private static func sanitizedNote(_ value: String) -> String {
        String(value.trimmingCharacters(in: .whitespacesAndNewlines).prefix(1000))
    }
}

@MainActor
private struct RecordingCompletionPreviewAsset {
    let image: NSImage?
    let imageURL: URL?
    let videoURL: URL?
    let title: String
    let subtitle: String

    init(draft: RecordingCompletionDraft, fileManager: FileManager = .default) {
        let resolvedImage = draft.previewImageCandidates.lazy.compactMap { url -> (URL, NSImage)? in
            guard fileManager.fileExists(atPath: url.path), let image = NSImage(contentsOf: url), image.isValid else {
                return nil
            }
            return (url, image)
        }.first
        imageURL = resolvedImage?.0
        image = resolvedImage?.1

        videoURL = draft.videoCandidates.first { fileManager.fileExists(atPath: $0.path) }
        if image != nil {
            title = "保存前预览"
            subtitle = "\(draft.segments.count) 段 · \(draft.totalFrameCount) 帧"
        } else if videoURL != nil {
            title = "预览帧暂不可用"
            subtitle = "视频已生成，可打开本地预览"
        } else {
            title = "视频预览暂不可用"
            subtitle = "保存会保留关键帧和诊断信息"
        }
    }
}

@MainActor
private final class RecordingCompletionPreviewView: NSView {
    private let asset: RecordingCompletionPreviewAsset

    init(asset: RecordingCompletionPreviewAsset) {
        self.asset = asset
        super.init(frame: .zero)
        wantsLayer = true
        layer?.masksToBounds = true
        setAccessibilityLabel(asset.image == nil ? asset.title : "录制完成预览图")
        setAccessibilityHelp(asset.subtitle)
    }

    required init?(coder: NSCoder) {
        nil
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let rect = bounds.insetBy(dx: 0.5, dy: 0.5)
        let path = WorkRecorderTheme.roundedRectPath(rect, radius: 12)
        NSGraphicsContext.saveGraphicsState()
        path.addClip()
        drawBackground(in: rect)
        if let image = asset.image {
            drawPreviewImage(image, in: rect)
            drawImageOverlay(in: rect)
        } else {
            drawUnavailableState(in: rect)
        }
        NSGraphicsContext.restoreGraphicsState()
        WorkRecorderTheme.accent.withAlphaComponent(asset.image == nil ? 0.18 : 0.24).setStroke()
        path.lineWidth = 1
        path.stroke()
    }

    private func drawBackground(in rect: CGRect) {
        NSGradient(colors: [
            WorkRecorderTheme.Prism.pearlWhite.withAlphaComponent(0.88),
            WorkRecorderTheme.Prism.iceBlue.withAlphaComponent(0.36),
            WorkRecorderTheme.graphite.withAlphaComponent(0.10),
        ])?.draw(in: rect, angle: 92)
        WorkRecorderTheme.Prism.tiffanyBlue.withAlphaComponent(0.08).setFill()
        NSBezierPath(roundedRect: rect.insetBy(dx: 9, dy: 9), xRadius: 10, yRadius: 10).fill()
    }

    private func drawPreviewImage(_ image: NSImage, in rect: CGRect) {
        let imageSize = image.size
        guard imageSize.width > 0, imageSize.height > 0 else { return }
        let scale = max(rect.width / imageSize.width, rect.height / imageSize.height)
        let drawSize = CGSize(width: imageSize.width * scale, height: imageSize.height * scale)
        let drawRect = CGRect(
            x: rect.midX - drawSize.width / 2,
            y: rect.midY - drawSize.height / 2,
            width: drawSize.width,
            height: drawSize.height
        )
        image.draw(in: drawRect, from: .zero, operation: .sourceOver, fraction: 0.98)
    }

    private func drawImageOverlay(in rect: CGRect) {
        NSGradient(colors: [
            NSColor.clear,
            WorkRecorderTheme.graphite.withAlphaComponent(0.28),
        ])?.draw(in: CGRect(x: rect.minX, y: rect.minY, width: rect.width, height: rect.height * 0.42), angle: 90)
        drawPlayBadge(
            center: CGPoint(x: rect.maxX - 24, y: rect.minY + 23),
            fillAlpha: 0.78,
            strokeAlpha: 0.30
        )
        drawText(asset.title, subtitle: asset.subtitle, in: rect.insetBy(dx: 13, dy: 10), dark: false)
    }

    private func drawUnavailableState(in rect: CGRect) {
        let center = CGPoint(x: rect.midX, y: rect.midY + 11)
        drawPlayBadge(center: center, fillAlpha: 0.18, strokeAlpha: 0.28)
        drawText(asset.title, subtitle: asset.subtitle, in: rect.insetBy(dx: 14, dy: 10), dark: true)
    }

    private func drawPlayBadge(center: CGPoint, fillAlpha: CGFloat, strokeAlpha: CGFloat) {
        let badge = CGRect(x: center.x - 18, y: center.y - 18, width: 36, height: 36)
        let path = NSBezierPath(ovalIn: badge)
        WorkRecorderTheme.Prism.pearlWhite.withAlphaComponent(fillAlpha).setFill()
        path.fill()
        WorkRecorderTheme.accent.withAlphaComponent(strokeAlpha).setStroke()
        path.lineWidth = 1
        path.stroke()
        let triangle = NSBezierPath()
        triangle.move(to: CGPoint(x: center.x - 4, y: center.y - 8))
        triangle.line(to: CGPoint(x: center.x - 4, y: center.y + 8))
        triangle.line(to: CGPoint(x: center.x + 9, y: center.y))
        triangle.close()
        (asset.videoURL == nil ? WorkRecorderTheme.mutedText : WorkRecorderTheme.accent).withAlphaComponent(0.86).setFill()
        triangle.fill()
    }

    private func drawText(_ title: String, subtitle: String, in rect: CGRect, dark: Bool) {
        let titleColor = dark ? WorkRecorderTheme.primaryText : NSColor.white.withAlphaComponent(0.92)
        let subtitleColor = dark ? WorkRecorderTheme.secondaryText : NSColor.white.withAlphaComponent(0.72)
        let titleAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 12.2, weight: .semibold),
            .foregroundColor: titleColor,
        ]
        let subtitleAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 10.5, weight: .medium),
            .foregroundColor: subtitleColor,
        ]
        title.draw(
            in: CGRect(x: rect.minX, y: rect.minY + 22, width: rect.width - 46, height: 16),
            withAttributes: titleAttributes
        )
        subtitle.draw(
            in: CGRect(x: rect.minX, y: rect.minY + 6, width: rect.width - 10, height: 14),
            withAttributes: subtitleAttributes
        )
    }
}

private struct RecordingCompletionLayout {
    let windowWidth: CGFloat
    let windowHeight: CGFloat
    let previewSize: CGSize
    let noteWidth: CGFloat
    let rootOrientation: NSUserInterfaceLayoutOrientation
    let rootAlignment: NSLayoutConstraint.Attribute
    let rootSpacing: CGFloat

    static func make(availableWidth: CGFloat) -> RecordingCompletionLayout {
        if availableWidth < 620 {
            return RecordingCompletionLayout(
                windowWidth: min(520, availableWidth),
                windowHeight: 388,
                previewSize: CGSize(width: min(224, availableWidth - 80), height: 126),
                noteWidth: min(430, availableWidth - 84),
                rootOrientation: .vertical,
                rootAlignment: .leading,
                rootSpacing: 15
            )
        }
        return RecordingCompletionLayout(
            windowWidth: min(680, availableWidth),
            windowHeight: 286,
            previewSize: CGSize(width: 166, height: 104),
            noteWidth: min(420, availableWidth - 260),
            rootOrientation: .horizontal,
            rootAlignment: .centerY,
            rootSpacing: 20
        )
    }
}

extension RecordingCompletionView: NSTextFieldDelegate {
    func controlTextDidBeginEditing(_ obj: Notification) {
        noteShell.active = true
    }

    func controlTextDidEndEditing(_ obj: Notification) {
        noteShell.active = false
    }
}
