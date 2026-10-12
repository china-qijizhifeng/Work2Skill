import AppKit

@MainActor
final class RecordingTimelineStepChipView: NSControl {
    private enum Metric {
        static let horizontalInset: CGFloat = 12
        static let iconSize: CGFloat = 14
        static let iconTextGap: CGFloat = 8
        static let topTextY: CGFloat = 12
        static let titleY: CGFloat = 39
        static let captionY: CGFloat = 65
    }

    private let title: String
    private let timeText: String
    private let caption: String
    private let symbolName: String
    private let selected: Bool
    private let needsReview: Bool
    private var hovering = false {
        didSet { needsDisplay = true }
    }
    private var pressed = false {
        didSet { needsDisplay = true }
    }
    private var trackingArea: NSTrackingArea?

    init(
        stepId: String,
        title: String,
        timeText: String,
        caption: String,
        symbolName: String,
        selected: Bool,
        needsReview: Bool,
        target: AnyObject?,
        action: Selector?
    ) {
        self.title = WorkRecorderLocalization.text(title)
        self.timeText = timeText
        self.caption = WorkRecorderLocalization.text(caption)
        self.symbolName = symbolName
        self.selected = selected
        self.needsReview = needsReview
        super.init(frame: .zero)
        self.identifier = NSUserInterfaceItemIdentifier(stepId)
        self.target = target
        self.action = action
        wantsLayer = true
        setAccessibilityRole(.button)
        setAccessibilityLabel("\(timeText) \(WorkRecorderLocalization.text(title))")
        setAccessibilityValue(selected ? "已选中" : (needsReview ? "需要复核" : "可选择"))
    }

    required init?(coder: NSCoder) {
        nil
    }

    override var intrinsicContentSize: NSSize {
        NSSize(width: 124, height: 92)
    }

    override var isFlipped: Bool {
        true
    }

    override var acceptsFirstResponder: Bool {
        true
    }

    override func updateTrackingAreas() {
        super.updateTrackingAreas()
        if let trackingArea {
            removeTrackingArea(trackingArea)
        }
        let area = NSTrackingArea(
            rect: bounds,
            options: [.activeInKeyWindow, .mouseEnteredAndExited, .inVisibleRect],
            owner: self
        )
        addTrackingArea(area)
        trackingArea = area
    }

    override func mouseEntered(with event: NSEvent) {
        hovering = true
    }

    override func mouseExited(with event: NSEvent) {
        hovering = false
    }

    override func mouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self)
        pressed = true
    }

    override func mouseUp(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        defer { pressed = false }
        guard bounds.contains(point) else { return }
        sendAction(action, to: target)
    }

    override func keyDown(with event: NSEvent) {
        if event.keyCode == 36 || event.keyCode == 49 {
            sendAction(action, to: target)
            return
        }
        super.keyDown(with: event)
    }

    override func draw(_ dirtyRect: NSRect) {
        let rect = bounds.insetBy(dx: 0.5, dy: 0.5)
        let path = NSBezierPath(roundedRect: rect, xRadius: 14, yRadius: 14)
        let fill = selected
            ? NSColor(calibratedRed: 0.906, green: 0.985, blue: 0.980, alpha: 0.98)
            : NSColor.white.withAlphaComponent(pressed ? 0.94 : (hovering ? 0.86 : 0.74))
        fill.setFill()
        path.fill()
        (selected ? WorkbenchDesignTokens.Color.tiffanyStrong : WorkbenchDesignTokens.Color.neutralHairline)
            .withAlphaComponent(selected ? 0.42 : 0.38)
            .setStroke()
        path.lineWidth = selected ? 1.15 : 0.8
        path.stroke()

        drawSymbol()
        drawText()
        if needsReview {
            drawReviewDot(in: rect)
        }
        if window?.firstResponder === self {
            NSColor.keyboardFocusIndicatorColor.withAlphaComponent(0.55).setStroke()
            let focus = NSBezierPath(roundedRect: rect.insetBy(dx: 2, dy: 2), xRadius: 12, yRadius: 12)
            focus.lineWidth = 1.2
            focus.stroke()
        }
    }

    private func drawSymbol() {
        guard let symbol = NSImage(systemSymbolName: symbolName, accessibilityDescription: nil),
              let context = NSGraphicsContext.current?.cgContext
        else { return }
        let rect = NSRect(x: Metric.horizontalInset, y: 12, width: Metric.iconSize, height: Metric.iconSize)
        var drawRect = rect
        guard let cgImage = symbol.cgImage(forProposedRect: &drawRect, context: nil, hints: nil) else { return }
        NSGraphicsContext.saveGraphicsState()
        context.clip(to: rect, mask: cgImage)
        (needsReview ? WorkbenchDesignTokens.Color.warning : WorkbenchDesignTokens.Color.tiffanyStrong)
            .withAlphaComponent(0.94)
            .setFill()
        rect.fill()
        NSGraphicsContext.restoreGraphicsState()
    }

    private func drawText() {
        let paragraph = NSMutableParagraphStyle()
        paragraph.lineBreakMode = .byTruncatingTail
        paragraph.alignment = .left
        let textX = Metric.horizontalInset + Metric.iconSize + Metric.iconTextGap
        let textWidth = bounds.width - textX - Metric.horizontalInset
        let timeAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 10.0, weight: .semibold),
            .foregroundColor: WorkbenchDesignTokens.Color.muted,
            .paragraphStyle: paragraph,
        ]
        timeText.draw(in: NSRect(x: textX, y: Metric.topTextY, width: textWidth, height: 15), withAttributes: timeAttributes)

        let titleAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 11.7, weight: .semibold),
            .foregroundColor: WorkbenchDesignTokens.Color.primaryText,
            .paragraphStyle: paragraph,
        ]
        title.draw(in: NSRect(x: textX, y: Metric.titleY, width: textWidth, height: 17), withAttributes: titleAttributes)

        let captionAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 10.1, weight: .regular),
            .foregroundColor: WorkbenchDesignTokens.Color.secondaryText,
            .paragraphStyle: paragraph,
        ]
        caption.draw(in: NSRect(x: textX, y: Metric.captionY, width: textWidth, height: 17), withAttributes: captionAttributes)
    }

    private func drawReviewDot(in rect: NSRect) {
        let dot = NSRect(x: rect.maxX - 15, y: 8, width: 7, height: 7)
        WorkbenchDesignTokens.Color.warning.withAlphaComponent(0.88).setFill()
        NSBezierPath(ovalIn: dot).fill()
    }
}
