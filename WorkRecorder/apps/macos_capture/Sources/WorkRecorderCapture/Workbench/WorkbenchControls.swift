import AppKit
import WorkRecorderCaptureDesign

enum WorkbenchControlMetric {
    static let actionHeight: CGFloat = 34
    static let actionRadius: CGFloat = 11
    static let actionHorizontalPadding: CGFloat = 16
    static let actionIconSize: CGFloat = 12
    static let actionIconTextGap: CGFloat = 6
    static let compactActionHeight: CGFloat = 30

    static let statusPillHeight: CGFloat = 28
    static let statusPillHorizontalPadding: CGFloat = 13

    static let evidenceTokenHeight: CGFloat = 26
    static let evidenceTokenRadius: CGFloat = 10
    static let evidenceTokenHorizontalPadding: CGFloat = 12
    static let evidenceTokenDotSize: CGFloat = 6
    static let evidenceTokenDotGap: CGFloat = 8

    static let filterChipHeight: CGFloat = 28
    static let filterChipHorizontalPadding: CGFloat = 11
    static let filterChipRadius: CGFloat = 14
}

@MainActor
final class WorkbenchSearchField: NSTextField {
    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        cell = WorkbenchCenteredTextFieldCell(textCell: "")
        configure()
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        cell = WorkbenchCenteredTextFieldCell(textCell: stringValue)
        configure()
    }

    private func configure() {
        isEditable = true
        isSelectable = true
        isBordered = false
        isBezeled = false
        drawsBackground = false
        focusRingType = .none
    }

    override func textDidChange(_ notification: Notification) {
        super.textDidChange(notification)
        _ = sendAction(action, to: target)
    }
}

private final class WorkbenchCenteredTextFieldCell: NSTextFieldCell {
    private func centeredRect(forBounds rect: NSRect) -> NSRect {
        let textSize = cellSize(forBounds: rect)
        var centered = rect
        centered.origin.y += floor((rect.height - textSize.height) / 2) + 1
        centered.size.height = textSize.height
        return centered
    }

    override func drawingRect(forBounds rect: NSRect) -> NSRect {
        centeredRect(forBounds: rect)
    }

    override func edit(
        withFrame rect: NSRect,
        in controlView: NSView,
        editor textObj: NSText,
        delegate: Any?,
        event: NSEvent?
    ) {
        super.edit(withFrame: centeredRect(forBounds: rect), in: controlView, editor: textObj, delegate: delegate, event: event)
    }

    override func select(
        withFrame rect: NSRect,
        in controlView: NSView,
        editor textObj: NSText,
        delegate: Any?,
        start selStart: Int,
        length selLength: Int
    ) {
        super.select(
            withFrame: centeredRect(forBounds: rect),
            in: controlView,
            editor: textObj,
            delegate: delegate,
            start: selStart,
            length: selLength
        )
    }
}

@MainActor
final class WorkbenchSearchBox: NSView {
    let searchField: NSTextField

    init(searchField: NSTextField) {
        self.searchField = searchField
        super.init(frame: .zero)
        wantsLayer = true
        layer?.backgroundColor = WorkbenchDesignTokens.Color.panelElevated.cgColor
        layer?.borderColor = WorkbenchDesignTokens.Color.brandSky.withAlphaComponent(0.92).cgColor
        layer?.borderWidth = 1.2
        layer?.cornerRadius = 18
        layer?.shadowColor = WorkbenchDesignTokens.Color.brandBlueStrong.withAlphaComponent(0.10).cgColor
        layer?.shadowOpacity = 1
        layer?.shadowRadius = 16
        layer?.shadowOffset = CGSize(width: 0, height: -6)

        searchField.font = NSFont.systemFont(ofSize: 13.2, weight: .medium)
        searchField.cell?.font = searchField.font
        searchField.cell?.usesSingleLineMode = true
        searchField.cell?.wraps = false
        searchField.cell?.lineBreakMode = .byTruncatingTail
        searchField.translatesAutoresizingMaskIntoConstraints = false
        addSubview(searchField)

        let icon = NSImageView(image: NSImage(systemSymbolName: "magnifyingglass", accessibilityDescription: "搜索") ?? NSImage())
        icon.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 13, weight: .medium)
        icon.contentTintColor = WorkbenchDesignTokens.Color.muted.withAlphaComponent(0.82)
        icon.translatesAutoresizingMaskIntoConstraints = false
        addSubview(icon)

        let shortcut = NSTextField(labelWithString: "⌘ K")
        shortcut.font = NSFont.systemFont(ofSize: 10.4, weight: .medium)
        shortcut.textColor = WorkbenchDesignTokens.Color.muted.withAlphaComponent(0.90)
        shortcut.alignment = .center
        shortcut.wantsLayer = true
        shortcut.layer?.backgroundColor = WorkbenchDesignTokens.Color.panelSoft.withAlphaComponent(0.74).cgColor
        shortcut.layer?.borderColor = WorkbenchDesignTokens.Color.brandSky.withAlphaComponent(0.70).cgColor
        shortcut.layer?.borderWidth = 0.8
        shortcut.layer?.cornerRadius = 6
        shortcut.translatesAutoresizingMaskIntoConstraints = false
        addSubview(shortcut)

        NSLayoutConstraint.activate([
            icon.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 16),
            icon.centerYAnchor.constraint(equalTo: centerYAnchor),
            icon.widthAnchor.constraint(equalToConstant: 15),
            icon.heightAnchor.constraint(equalToConstant: 15),

            searchField.leadingAnchor.constraint(equalTo: icon.trailingAnchor, constant: 10),
            searchField.trailingAnchor.constraint(equalTo: shortcut.leadingAnchor, constant: -10),
            searchField.centerYAnchor.constraint(equalTo: centerYAnchor),
            searchField.heightAnchor.constraint(equalToConstant: 26),

            shortcut.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -12),
            shortcut.centerYAnchor.constraint(equalTo: centerYAnchor),
            shortcut.widthAnchor.constraint(equalToConstant: 30),
            shortcut.heightAnchor.constraint(equalToConstant: 18),
        ])
    }

    required init?(coder: NSCoder) {
        nil
    }

    override var intrinsicContentSize: NSSize {
        NSSize(width: 430, height: 42)
    }
}

@MainActor
final class WorkbenchDropdownButton: NSControl {
    private let text: String
    private let active: Bool
    private let symbolName: String?
    private let buttonFont = NSFont.systemFont(ofSize: 11.0, weight: .semibold)
    private var hovering = false {
        didSet { needsDisplay = true }
    }
    private var trackingArea: NSTrackingArea?

    init(text: String, symbolName: String? = "chevron.down", active: Bool = false) {
        self.text = WorkRecorderLocalization.text(text)
        self.symbolName = symbolName
        self.active = active
        super.init(frame: .zero)
        wantsLayer = true
        setAccessibilityRole(.button)
        setAccessibilityLabel(self.text)
    }

    required init?(coder: NSCoder) {
        nil
    }

    override var intrinsicContentSize: NSSize {
        let textWidth = (text as NSString).size(withAttributes: [.font: buttonFont]).width
        let iconWidth: CGFloat = symbolName == nil ? 0 : 15
        return NSSize(width: ceil(textWidth + iconWidth + 24), height: 28)
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
        sendAction(action, to: target)
    }

    override func draw(_ dirtyRect: NSRect) {
        let rect = bounds.insetBy(dx: 0.5, dy: 0.5)
        let path = NSBezierPath(roundedRect: rect, xRadius: rect.height / 2, yRadius: rect.height / 2)
        let top = active
            ? WorkbenchDesignTokens.Color.panelElevated
            : NSColor.white.withAlphaComponent(hovering ? 0.86 : 0.72)
        let bottom = active
            ? WorkbenchDesignTokens.Color.brandSky.withAlphaComponent(0.44)
            : WorkbenchDesignTokens.Color.panelSoft.withAlphaComponent(hovering ? 0.62 : 0.40)
        NSGradient(colors: [top, bottom])?.draw(in: path, angle: 92)
        (active ? WorkbenchDesignTokens.Color.tiffany : WorkbenchDesignTokens.Color.neutralHairline)
            .withAlphaComponent(active ? 0.36 : 0.16)
            .setStroke()
        path.lineWidth = 1
        path.stroke()

        let textColor = active ? WorkbenchDesignTokens.Color.tiffanyStrong : WorkbenchDesignTokens.Color.secondaryText
        let attributes: [NSAttributedString.Key: Any] = [
            .font: buttonFont,
            .foregroundColor: textColor,
        ]
        let textSize = (text as NSString).size(withAttributes: attributes)
        let iconSize: CGFloat = symbolName == nil ? 0 : 9.5
        let gap: CGFloat = symbolName == nil ? 0 : 6
        let groupWidth = textSize.width + iconSize + gap
        let startX = floor(bounds.midX - groupWidth / 2)
        text.draw(
            in: NSRect(
                x: startX,
                y: floor(bounds.midY - textSize.height / 2),
                width: ceil(textSize.width) + 1,
                height: ceil(textSize.height) + 2
            ),
            withAttributes: attributes
        )
        if let symbolName,
           let symbol = NSImage(systemSymbolName: symbolName, accessibilityDescription: text),
           let context = NSGraphicsContext.current?.cgContext {
            var imageRect = NSRect(
                x: startX + textSize.width + gap,
                y: floor(bounds.midY - iconSize / 2) - 0.25,
                width: iconSize,
                height: iconSize
            )
            if let cgImage = symbol.cgImage(forProposedRect: &imageRect, context: nil, hints: nil) {
                NSGraphicsContext.saveGraphicsState()
                context.clip(to: imageRect, mask: cgImage)
                textColor.withAlphaComponent(0.76).setFill()
                imageRect.fill()
                NSGraphicsContext.restoreGraphicsState()
            }
        }
    }
}

@MainActor
final class WorkbenchButton: NSButton {
    enum Variant {
        case primary
        case secondary
        case quiet
    }

    private let variant: Variant
    private let symbolName: String?
    private var minimumWidth: CGFloat = 0
    private var trackingArea: NSTrackingArea?
    private var hovering = false

    init(title: String, variant: Variant, symbolName: String? = nil, target: AnyObject?, action: Selector?) {
        self.variant = variant
        self.symbolName = symbolName
        super.init(frame: .zero)
        self.title = WorkRecorderLocalization.text(title)
        self.target = target
        self.action = action
        isBordered = false
        setButtonType(.momentaryPushIn)
        focusRingType = .default
        font = NSFont.systemFont(ofSize: 12.4, weight: .semibold)
        setAccessibilityLabel(self.title)
    }

    override var isEnabled: Bool {
        didSet { needsDisplay = true }
    }

    required init?(coder: NSCoder) {
        nil
    }

    override var intrinsicContentSize: NSSize {
        let textWidth = (title as NSString).size(withAttributes: [.font: font ?? NSFont.systemFont(ofSize: 13)]).width
        let iconWidth = symbolName == nil ? 0 : WorkbenchControlMetric.actionIconSize + WorkbenchControlMetric.actionIconTextGap
        let width = textWidth + iconWidth + WorkbenchControlMetric.actionHorizontalPadding * 2
        return NSSize(width: ceil(max(width, minimumWidth)), height: WorkbenchControlMetric.actionHeight)
    }

    func applyActionRowMinimumWidth() {
        switch variant {
        case .primary:
            minimumWidth = max(minimumWidth, 122)
        case .secondary:
            minimumWidth = max(minimumWidth, 104)
        case .quiet:
            minimumWidth = max(minimumWidth, 100)
        }
        invalidateIntrinsicContentSize()
    }

    func applyCompactMinimumWidth() {
        minimumWidth = max(minimumWidth, 58)
        invalidateIntrinsicContentSize()
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
        needsDisplay = true
    }

    override func mouseExited(with event: NSEvent) {
        hovering = false
        needsDisplay = true
    }

    override func draw(_ dirtyRect: NSRect) {
        let highlighted = cell?.isHighlighted == true
        let rect = bounds.insetBy(dx: 0.5, dy: 0.5)
        let radius = min(WorkbenchControlMetric.actionRadius, rect.height / 2)
        let path = NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
        let palette = colors(highlighted: highlighted)
        NSGraphicsContext.saveGraphicsState()
        let shadow = NSShadow()
        shadow.shadowColor = variant == .primary
            ? WorkbenchDesignTokens.Color.brandBlue.withAlphaComponent(hovering || highlighted ? 0.30 : 0.22)
            : WorkbenchDesignTokens.Color.brandBlueStrong.withAlphaComponent(hovering || highlighted ? 0.11 : 0.07)
        shadow.shadowBlurRadius = variant == .primary ? 16 : 10
        shadow.shadowOffset = CGSize(width: 0, height: variant == .primary ? -4 : -2)
        shadow.set()
        NSColor.white.withAlphaComponent(variant == .primary ? 0.26 : 0.18).setFill()
        path.fill()
        NSGraphicsContext.restoreGraphicsState()
        if variant == .primary {
            NSGradient(colors: [
                WorkbenchDesignTokens.Color.brandSky.withAlphaComponent(highlighted ? 0.76 : 0.92),
                palette.fill,
                WorkbenchDesignTokens.Color.brandBlueStrong,
            ])?.draw(in: path, angle: 92)
        } else {
            NSGradient(colors: [
                NSColor.white.withAlphaComponent(highlighted ? 0.92 : 0.82),
                palette.fill,
                WorkbenchDesignTokens.Color.panelSoft.withAlphaComponent(highlighted ? 0.74 : 0.58),
            ])?.draw(in: path, angle: 92)
        }
        let innerHighlight = NSBezierPath(roundedRect: rect.insetBy(dx: 1, dy: 1), xRadius: radius - 1, yRadius: radius - 1)
        NSColor.white.withAlphaComponent(variant == .primary ? 0.28 : 0.52).setStroke()
        innerHighlight.lineWidth = 0.75
        innerHighlight.stroke()
        if variant == .primary {
            let sheen = NSBezierPath(roundedRect: rect.insetBy(dx: 4, dy: 4), xRadius: max(1, radius - 4), yRadius: max(1, radius - 4))
            NSColor.white.withAlphaComponent(0.08).setStroke()
            sheen.lineWidth = 0.8
            sheen.stroke()
        }
        palette.stroke.setStroke()
        path.lineWidth = 1
        path.stroke()

        let paragraph = NSMutableParagraphStyle()
        paragraph.alignment = .center
        paragraph.lineBreakMode = .byTruncatingTail
        let attributes: [NSAttributedString.Key: Any] = [
            .font: font ?? WorkbenchDesignTokens.Font.action,
            .foregroundColor: palette.text,
            .paragraphStyle: paragraph,
        ]
        let textSize = (title as NSString).size(withAttributes: attributes)
        let iconSize = WorkbenchControlMetric.actionIconSize
        let iconGap = symbolName == nil ? 0 : WorkbenchControlMetric.actionIconTextGap
        let symbolWidth = symbolName == nil ? 0 : iconSize
        let groupWidth = textSize.width + symbolWidth + iconGap
        let groupMinX = floor(bounds.midX - groupWidth / 2)
        if let symbolName,
           let symbol = NSImage(systemSymbolName: symbolName, accessibilityDescription: title) {
            let imageRect = NSRect(
                x: groupMinX,
                y: floor(bounds.midY - iconSize / 2),
                width: iconSize,
                height: iconSize
            )
            let configuration = NSImage.SymbolConfiguration(paletteColors: [palette.text])
            let tintedSymbol = symbol.withSymbolConfiguration(configuration) ?? symbol
            tintedSymbol.draw(
                in: imageRect,
                from: .zero,
                operation: .sourceOver,
                fraction: isEnabled ? 1.0 : 0.62,
                respectFlipped: true,
                hints: nil
            )
        }
        let textRect = NSRect(
            x: groupMinX + symbolWidth + iconGap,
            y: floor(bounds.midY - textSize.height / 2) - 0.10,
            width: textSize.width + 2,
            height: ceil(textSize.height) + 2
        )
        title.draw(in: textRect, withAttributes: attributes)
    }

    private func colors(highlighted: Bool) -> (fill: NSColor, stroke: NSColor, text: NSColor) {
        guard isEnabled else {
            return (
                WorkbenchDesignTokens.Color.panelSoft.withAlphaComponent(0.70),
                WorkbenchDesignTokens.Color.brandSky.withAlphaComponent(0.45),
                WorkbenchDesignTokens.Color.muted.withAlphaComponent(0.76)
            )
        }
        let active = highlighted || hovering
        switch variant {
        case .primary:
            return (
                active ? WorkbenchDesignTokens.Color.brandBlueStrong : WorkbenchDesignTokens.Color.brandBlue,
                WorkbenchDesignTokens.Color.brandBlueStrong.withAlphaComponent(active ? 0.72 : 0.54),
                NSColor.white
            )
        case .secondary:
            return (
                active ? WorkbenchDesignTokens.Color.panelSoft : WorkbenchDesignTokens.Color.panelElevated,
                WorkbenchDesignTokens.Color.brandBlue.withAlphaComponent(active ? 0.70 : 0.46),
                WorkbenchDesignTokens.Color.brandBlueStrong
            )
        case .quiet:
            return (
                WorkbenchDesignTokens.Color.panelSoft.withAlphaComponent(active ? 0.82 : 0.45),
                WorkbenchDesignTokens.Color.neutralHairline.withAlphaComponent(active ? 0.72 : 0.44),
                WorkbenchDesignTokens.Color.secondaryText
            )
        }
    }
}

@MainActor
final class WorkbenchStatusPill: NSView {
    private let text: String
    private let state: WorkbenchPermissionState
    private let font = NSFont.systemFont(ofSize: 11.6, weight: .semibold)

    init(text: String, state: WorkbenchPermissionState) {
        self.text = WorkRecorderLocalization.text(text)
        self.state = state
        super.init(frame: .zero)
        wantsLayer = true
        setAccessibilityLabel(self.text)
    }

    required init?(coder: NSCoder) {
        nil
    }

    override var intrinsicContentSize: NSSize {
        let width = (text as NSString).size(withAttributes: [.font: font]).width
            + WorkbenchControlMetric.statusPillHorizontalPadding * 2
        return NSSize(width: ceil(max(width, 76)), height: WorkbenchControlMetric.statusPillHeight)
    }

    override func draw(_ dirtyRect: NSRect) {
        let rect = bounds.insetBy(dx: 0.5, dy: 0.5)
        let path = NSBezierPath(roundedRect: rect, xRadius: rect.height / 2, yRadius: rect.height / 2)
        fillColor.setFill()
        path.fill()
        strokeColor.setStroke()
        path.lineWidth = 1
        path.stroke()

        let attributes: [NSAttributedString.Key: Any] = [
            .font: font,
            .foregroundColor: textColor,
        ]
        let textSize = (text as NSString).size(withAttributes: attributes)
        let textRect = NSRect(
            x: floor(bounds.midX - textSize.width / 2),
            y: floor(bounds.midY - textSize.height / 2) - 0.10,
            width: textSize.width + 1,
            height: ceil(textSize.height) + 2
        )
        text.draw(in: textRect, withAttributes: attributes)
    }

    private var fillColor: NSColor {
        switch state {
        case .granted:
            return WorkbenchDesignTokens.Color.panelSoft.withAlphaComponent(0.82)
        case .denied:
            return WorkbenchDesignTokens.Color.recordingRed.withAlphaComponent(0.12)
        case .unknown:
            return WorkbenchDesignTokens.Color.panel.withAlphaComponent(0.82)
        }
    }

    private var strokeColor: NSColor {
        switch state {
        case .granted:
            return WorkbenchDesignTokens.Color.brandBlue.withAlphaComponent(0.30)
        case .denied:
            return WorkbenchDesignTokens.Color.recordingRed.withAlphaComponent(0.30)
        case .unknown:
            return WorkbenchDesignTokens.Color.brandSky.withAlphaComponent(0.38)
        }
    }

    private var textColor: NSColor {
        switch state {
        case .granted:
            return WorkbenchDesignTokens.Color.brandBlueStrong
        case .denied:
            return WorkbenchDesignTokens.Color.recordingRedStrong
        case .unknown:
            return WorkbenchDesignTokens.Color.secondaryText
        }
    }
}
