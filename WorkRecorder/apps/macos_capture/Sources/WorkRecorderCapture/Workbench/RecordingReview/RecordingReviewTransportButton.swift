import AppKit

@MainActor
final class RecordingReviewTransportButton: NSButton {
    enum Style {
        case primary
        case secondary
    }

    private let style: Style
    private let symbolName: String?

    init(title: String, style: Style, symbolName: String?, target: AnyObject?, action: Selector?) {
        self.style = style
        self.symbolName = symbolName
        super.init(frame: .zero)
        self.title = WorkRecorderLocalization.text(title)
        self.target = target
        self.action = action
        isBordered = false
        setButtonType(.momentaryPushIn)
        focusRingType = .default
        font = NSFont.systemFont(ofSize: 12.2, weight: .semibold)
        setAccessibilityLabel(self.title)
    }

    required init?(coder: NSCoder) {
        nil
    }

    override var intrinsicContentSize: NSSize {
        let textWidth = (title as NSString).size(withAttributes: [.font: font ?? NSFont.systemFont(ofSize: 12)]).width
        let iconWidth: CGFloat = symbolName == nil ? 0 : 19
        return NSSize(width: max(82, ceil(textWidth + iconWidth + 28)), height: 34)
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let rect = bounds.insetBy(dx: 0.5, dy: 0.5)
        let path = NSBezierPath(roundedRect: rect, xRadius: 17, yRadius: 17)
        let pressed = isHighlighted
        switch style {
        case .primary:
            NSColor(calibratedRed: 0.80, green: 0.990, blue: 0.992, alpha: pressed ? 0.82 : 0.94).setFill()
            path.fill()
            WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.28).setStroke()
        case .secondary:
            NSColor.white.withAlphaComponent(pressed ? 0.20 : 0.13).setFill()
            path.fill()
            NSColor.white.withAlphaComponent(0.18).setStroke()
        }
        path.lineWidth = 0.8
        path.stroke()

        let textColor: NSColor = style == .primary
            ? WorkbenchDesignTokens.Color.primaryText
            : NSColor.white.withAlphaComponent(0.84)
        let attrs: [NSAttributedString.Key: Any] = [
            .font: font ?? NSFont.systemFont(ofSize: 12.2, weight: .semibold),
            .foregroundColor: textColor,
        ]
        let textSize = (title as NSString).size(withAttributes: attrs)
        let iconSize: CGFloat = symbolName == nil ? 0 : 13
        let gap: CGFloat = symbolName == nil ? 0 : 6
        let contentWidth = iconSize + gap + textSize.width
        let startX = rect.midX - contentWidth / 2
        if let symbolName,
           let symbol = NSImage(systemSymbolName: symbolName, accessibilityDescription: title),
           let context = NSGraphicsContext.current?.cgContext {
            let iconRect = NSRect(x: startX, y: rect.midY - iconSize / 2, width: iconSize, height: iconSize)
            if let cgImage = symbol.cgImage(forProposedRect: nil, context: nil, hints: nil) {
                NSGraphicsContext.saveGraphicsState()
                context.clip(to: iconRect, mask: cgImage)
                textColor.withAlphaComponent(0.82).setFill()
                iconRect.fill()
                NSGraphicsContext.restoreGraphicsState()
            }
        }
        title.draw(
            in: NSRect(x: startX + iconSize + gap, y: rect.midY - textSize.height / 2 - 0.5, width: textSize.width + 1, height: textSize.height + 1),
            withAttributes: attrs
        )
    }
}
