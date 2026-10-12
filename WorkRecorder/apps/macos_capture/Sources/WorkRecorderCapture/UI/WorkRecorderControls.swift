import AppKit

@MainActor
final class StatusDot: NSView {
    var color: NSColor = WorkRecorderTheme.accent {
        didSet { needsDisplay = true }
    }

    override var intrinsicContentSize: NSSize {
        NSSize(width: 10, height: 10)
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let center = CGPoint(x: bounds.midX, y: bounds.midY)
        let outer: CGFloat = min(bounds.width, bounds.height) * 0.48
        let inner: CGFloat = outer * 0.32
        let star = NSBezierPath()
        for index in 0..<8 {
            let radius = index.isMultiple(of: 2) ? outer : inner
            let angle = CGFloat(index) * .pi / 4 - .pi / 2
            let point = CGPoint(
                x: center.x + cos(angle) * radius,
                y: center.y + sin(angle) * radius
            )
            if index == 0 {
                star.move(to: point)
            } else {
                star.line(to: point)
            }
        }
        star.close()
        color.withAlphaComponent(0.11).setFill()
        NSBezierPath(ovalIn: bounds.insetBy(dx: 0.2, dy: 0.2)).fill()
        WorkRecorderTheme.Satin.silverHighlight.withAlphaComponent(WorkRecorderTheme.Satin.statusCoreAlpha).setFill()
        star.fill()
        color.withAlphaComponent(0.62).setStroke()
        star.lineWidth = 0.7
        star.stroke()

        let glint = NSBezierPath()
        glint.move(to: CGPoint(x: center.x - outer * 0.30, y: center.y - outer * 0.30))
        glint.line(to: CGPoint(x: center.x + outer * 0.32, y: center.y + outer * 0.32))
        glint.lineWidth = 0.55
        WorkRecorderTheme.Satin.coatingBlue.withAlphaComponent(0.46).setStroke()
        glint.stroke()
    }
}

@MainActor
final class KeyboardHintToken: NSView {
    private let text: String

    init(_ text: String) {
        self.text = WorkRecorderLocalization.text(text)
        super.init(frame: .zero)
        setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
    }

    required init?(coder: NSCoder) {
        nil
    }

    override var intrinsicContentSize: NSSize {
        let width = (text as NSString).size(withAttributes: [.font: WorkRecorderTheme.Font.hint]).width
        return NSSize(width: width + 14, height: 18)
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let rect = bounds.insetBy(dx: 0.5, dy: 0.5)
        let path = WorkRecorderTheme.roundedRectPath(rect, radius: 6)
        WorkRecorderTheme.fieldBackground.withAlphaComponent(0.78).setFill()
        path.fill()
        WorkRecorderTheme.hairline.withAlphaComponent(0.42).setStroke()
        path.lineWidth = 1
        path.stroke()
        let attributes: [NSAttributedString.Key: Any] = [
            .font: WorkRecorderTheme.Font.hint,
            .foregroundColor: WorkRecorderTheme.mutedText,
        ]
        text.draw(in: bounds.insetBy(dx: 7, dy: 3), withAttributes: attributes)
    }
}

@MainActor
final class WorkRecorderPillButton: NSButton {
    enum Variant {
        case primary
        case secondary
        case destructive
        case quiet
        case workspace
    }

    private let variant: Variant

    init(title: String, variant: Variant, target: AnyObject?, action: Selector?) {
        self.variant = variant
        super.init(frame: .zero)
        self.title = WorkRecorderLocalization.text(title)
        self.target = target
        self.action = action
        isBordered = false
        setButtonType(.momentaryPushIn)
        focusRingType = .none
        font = WorkRecorderTheme.Font.action
        bezelStyle = .regularSquare
    }

    required init?(coder: NSCoder) {
        nil
    }

    override var intrinsicContentSize: NSSize {
        let width = (title as NSString).size(withAttributes: [.font: font ?? WorkRecorderTheme.Font.action]).width
        return NSSize(width: width + horizontalPadding * 2, height: 31)
    }

    override func draw(_ dirtyRect: NSRect) {
        let rect = bounds.insetBy(dx: 0.5, dy: 0.5)
        let highlighted = cell?.isHighlighted == true
        let colors = palette(highlighted: highlighted, enabled: isEnabled)
        let path = WorkRecorderTheme.roundedRectPath(rect, radius: 12)
        drawButtonShadow(path: path, highlighted: highlighted)
        drawButtonFill(path: path, colors: colors, highlighted: highlighted)
        drawButtonSurfaceDetails(rect: rect, highlighted: highlighted)
        drawButtonBorderAndTitle(path: path, colors: colors)
    }

    private func drawButtonShadow(path: NSBezierPath, highlighted: Bool) {
        NSGraphicsContext.saveGraphicsState()
        let shadow = NSShadow()
        switch variant {
        case .primary:
            shadow.shadowColor = WorkRecorderTheme.accent.withAlphaComponent(isEnabled ? 0.105 : 0.036)
            shadow.shadowBlurRadius = highlighted ? 6 : 13
            shadow.shadowOffset = CGSize(width: 0, height: highlighted ? -0.8 : -3.0)
        case .quiet, .secondary, .destructive, .workspace:
            shadow.shadowColor = NSColor(calibratedRed: 0.28, green: 0.42, blue: 0.46, alpha: highlighted ? 0.050 : 0.030)
            shadow.shadowBlurRadius = highlighted ? 4 : 7
            shadow.shadowOffset = CGSize(width: 0, height: highlighted ? -0.4 : -1.2)
        }
        shadow.set()
        NSColor(calibratedWhite: 1.0, alpha: shadowFillAlpha).setFill()
        path.fill()
        NSGraphicsContext.restoreGraphicsState()
    }

    private var shadowFillAlpha: CGFloat {
        switch variant {
        case .primary:
            return 0.30
        case .quiet:
            return 0.15
        case .secondary, .destructive, .workspace:
            return 0.22
        }
    }

    private func drawButtonFill(path: NSBezierPath, colors: (fill: NSColor, stroke: NSColor, text: NSColor), highlighted: Bool) {
        if variant == .primary {
            NSGradient(colors: [
                NSColor(calibratedRed: 0.88, green: 0.976, blue: 0.968, alpha: highlighted ? 0.82 : 0.86),
                NSColor(calibratedRed: 0.80, green: 0.938, blue: 0.922, alpha: isEnabled ? 0.82 : 0.30),
                NSColor(calibratedRed: 0.74, green: 0.908, blue: 0.890, alpha: isEnabled ? 0.80 : 0.26),
            ])?.draw(in: path, angle: 96)
        } else {
            NSGradient(colors: [
                NSColor(calibratedWhite: 1.0, alpha: highlighted ? 0.54 : 0.34),
                colors.fill,
                NSColor(calibratedRed: 0.84, green: 0.92, blue: 0.93, alpha: highlighted ? 0.24 : 0.16),
            ])?.draw(in: path, angle: 92)
        }
    }

    private func drawButtonSurfaceDetails(rect: NSRect, highlighted: Bool) {
        drawTopHighlight(rect: rect)
        switch variant {
        case .primary:
            drawPrimaryButtonDetails(rect: rect, highlighted: highlighted)
        case .quiet:
            drawQuietButtonDetails(rect: rect)
        case .secondary, .destructive, .workspace:
            break
        }
    }

    private func drawTopHighlight(rect: NSRect) {
        let topHighlight = NSBezierPath()
        topHighlight.move(to: CGPoint(x: rect.minX + 11, y: rect.minY + 2.0))
        topHighlight.line(to: CGPoint(x: rect.maxX - 11, y: rect.minY + 2.0))
        topHighlight.lineWidth = 0.8
        NSColor(calibratedWhite: 1.0, alpha: variant == .primary ? 0.78 : 0.46).setStroke()
        topHighlight.stroke()
    }

    private func drawPrimaryButtonDetails(rect: NSRect, highlighted: Bool) {
        drawPrimaryInsetStrokes(rect: rect, highlighted: highlighted)
        drawPrimarySatinRim(rect: rect, highlighted: highlighted)
        drawPrimaryPrismSheen(rect: rect, highlighted: highlighted)
    }

    private func drawPrimaryInsetStrokes(rect: NSRect, highlighted: Bool) {
        let innerStroke = WorkRecorderTheme.roundedRectPath(rect.insetBy(dx: 1.0, dy: 1.0), radius: 11.2)
        NSColor(calibratedWhite: 1.0, alpha: highlighted ? 0.34 : 0.52).setStroke()
        innerStroke.lineWidth = 0.9
        innerStroke.stroke()
        let aquaInset = WorkRecorderTheme.roundedRectPath(rect.insetBy(dx: 1.7, dy: 1.7), radius: 10.8)
        WorkRecorderTheme.accent.withAlphaComponent(highlighted ? 0.20 : 0.14).setStroke()
        aquaInset.lineWidth = 0.6
        aquaInset.stroke()
    }

    private func drawPrimarySatinRim(rect: NSRect, highlighted: Bool) {
        let satinRim = NSBezierPath()
        satinRim.move(to: CGPoint(x: rect.minX + 12, y: rect.minY + 1.1))
        satinRim.curve(
            to: CGPoint(x: rect.maxX - 16, y: rect.minY + 1.0),
            controlPoint1: CGPoint(x: rect.minX + rect.width * 0.36, y: rect.minY - 0.6),
            controlPoint2: CGPoint(x: rect.minX + rect.width * 0.70, y: rect.minY + 3.2)
        )
        satinRim.lineWidth = 0.75
        WorkRecorderTheme.Satin.silverHighlight.withAlphaComponent(highlighted ? 0.76 : 0.64).setStroke()
        satinRim.stroke()
        let coatingRim = NSBezierPath()
        coatingRim.move(to: CGPoint(x: rect.maxX - 5.2, y: rect.minY + 8.5))
        coatingRim.curve(
            to: CGPoint(x: rect.maxX - 11.5, y: rect.maxY - 5.0),
            controlPoint1: CGPoint(x: rect.maxX - 1.2, y: rect.minY + rect.height * 0.38),
            controlPoint2: CGPoint(x: rect.maxX - 2.2, y: rect.maxY - rect.height * 0.28)
        )
        coatingRim.lineWidth = 0.65
        WorkRecorderTheme.Satin.coatingBlue.withAlphaComponent(highlighted ? 0.18 : 0.12).setStroke()
        coatingRim.stroke()
    }

    private func drawPrimaryPrismSheen(rect: NSRect, highlighted: Bool) {
        let prismSheen = NSBezierPath()
        prismSheen.move(to: CGPoint(x: rect.maxX - 42, y: rect.minY + 4.2))
        prismSheen.curve(
            to: CGPoint(x: rect.maxX - 8, y: rect.minY + 8.0),
            controlPoint1: CGPoint(x: rect.maxX - 30, y: rect.minY - 1.4),
            controlPoint2: CGPoint(x: rect.maxX - 17, y: rect.minY + 3.0)
        )
        prismSheen.lineWidth = 1
        WorkRecorderTheme.Prism.softLavender
            .withAlphaComponent(highlighted ? WorkRecorderTheme.Prism.Alpha.buttonSheenActive : WorkRecorderTheme.Prism.Alpha.buttonSheen)
            .setStroke()
        prismSheen.stroke()
        let contact = NSBezierPath()
        contact.move(to: CGPoint(x: rect.minX + 13, y: rect.maxY - 2.0))
        contact.curve(
            to: CGPoint(x: rect.maxX - 13, y: rect.maxY - 2.4),
            controlPoint1: CGPoint(x: rect.minX + rect.width * 0.35, y: rect.maxY - 0.6),
            controlPoint2: CGPoint(x: rect.minX + rect.width * 0.66, y: rect.maxY - 4.2)
        )
        contact.lineWidth = 0.8
        NSColor(calibratedRed: 0.18, green: 0.58, blue: 0.61, alpha: highlighted ? 0.10 : 0.060).setStroke()
        contact.stroke()
    }

    private func drawQuietButtonDetails(rect: NSRect) {
        let innerStroke = WorkRecorderTheme.roundedRectPath(rect.insetBy(dx: 1.1, dy: 1.1), radius: 11.2)
        NSColor(calibratedWhite: 1.0, alpha: 0.32).setStroke()
        innerStroke.lineWidth = 0.8
        innerStroke.stroke()
        let topSatin = NSBezierPath()
        topSatin.move(to: CGPoint(x: rect.minX + 12, y: rect.minY + 1.6))
        topSatin.line(to: CGPoint(x: rect.maxX - 12, y: rect.minY + 1.5))
        topSatin.lineWidth = 0.55
        WorkRecorderTheme.Satin.silverHighlight.withAlphaComponent(0.36).setStroke()
        topSatin.stroke()
    }

    private func drawButtonBorderAndTitle(path: NSBezierPath, colors: (fill: NSColor, stroke: NSColor, text: NSColor)) {
        colors.stroke.setStroke()
        path.lineWidth = 1
        path.stroke()
        let paragraph = NSMutableParagraphStyle()
        paragraph.alignment = .center
        paragraph.lineBreakMode = .byTruncatingTail
        let attributes: [NSAttributedString.Key: Any] = [
            .font: font ?? WorkRecorderTheme.Font.action,
            .foregroundColor: colors.text,
            .paragraphStyle: paragraph,
        ]
        let textSize = (title as NSString).size(withAttributes: attributes)
        let textRect = CGRect(
            x: bounds.minX + 8,
            y: bounds.midY - textSize.height / 2 - 0.4,
            width: bounds.width - 16,
            height: textSize.height + 1.2
        )
        title.draw(in: textRect, withAttributes: attributes)
    }

    private var horizontalPadding: CGFloat {
        switch variant {
        case .workspace:
            return 12
        case .quiet:
            return 15
        case .primary, .secondary, .destructive:
            return 19
        }
    }

    private func palette(highlighted: Bool, enabled: Bool) -> (fill: NSColor, stroke: NSColor, text: NSColor) {
        let disabledAlpha: CGFloat = enabled ? 1.0 : 0.42
        let primaryText = WorkRecorderTheme.primaryTextColor(for: effectiveAppearance)
        let stroke = WorkRecorderTheme.strokeColor(for: effectiveAppearance)
        let elevated = WorkRecorderTheme.elevatedColor(for: effectiveAppearance)
        switch variant {
        case .primary:
            return (
                fill: NSColor(calibratedRed: 0.74, green: 0.91, blue: 0.895, alpha: highlighted ? 0.86 : 0.76 * disabledAlpha),
                stroke: WorkRecorderTheme.accent.withAlphaComponent(highlighted ? 0.22 : 0.18 * disabledAlpha),
                text: NSColor(calibratedRed: 0.13, green: 0.33, blue: 0.36, alpha: disabledAlpha)
            )
        case .secondary:
            return (
                fill: elevated.withAlphaComponent(highlighted ? 0.92 : 0.66 * disabledAlpha),
                stroke: stroke.withAlphaComponent(highlighted ? 0.72 : 0.40 * disabledAlpha),
                text: primaryText.withAlphaComponent(disabledAlpha)
            )
        case .destructive:
            return (
                fill: NSColor(calibratedRed: 1.0, green: 0.946, blue: 0.908, alpha: highlighted ? 0.88 : 0.70 * disabledAlpha),
                stroke: WorkRecorderTheme.warning.withAlphaComponent(highlighted ? 0.56 : 0.40 * disabledAlpha),
                text: NSColor(calibratedRed: 0.54, green: 0.25, blue: 0.09, alpha: 0.98 * disabledAlpha)
            )
        case .quiet:
            return (
                fill: highlighted
                    ? NSColor(calibratedRed: 0.89, green: 0.956, blue: 0.964, alpha: 0.56)
                    : NSColor(calibratedRed: 0.905, green: 0.962, blue: 0.970, alpha: 0.44),
                stroke: NSColor(calibratedRed: 0.36, green: 0.52, blue: 0.55, alpha: highlighted ? 0.20 : 0.145),
                text: NSColor(calibratedRed: 0.33, green: 0.43, blue: 0.45, alpha: 0.92 * disabledAlpha)
            )
        case .workspace:
            return (
                fill: WorkRecorderTheme.fieldColor(for: effectiveAppearance).withAlphaComponent(highlighted ? 0.92 : 0.70 * disabledAlpha),
                stroke: stroke.withAlphaComponent(highlighted ? 0.52 : 0.32 * disabledAlpha),
                text: primaryText.withAlphaComponent(disabledAlpha)
            )
        }
    }
}

@MainActor
final class WorkRecorderInputShell: NSView {
    var active = false {
        didSet { needsDisplay = true }
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let rect = bounds.insetBy(dx: 0.5, dy: 0.5)
        let path = WorkRecorderTheme.roundedRectPath(rect, radius: 13)
        WorkRecorderTheme.Material.inputFillTop.withAlphaComponent(1.0).setFill()
        path.fill()
        let gradient = NSGradient(colors: [
            WorkRecorderTheme.Material.inputFillTop,
            WorkRecorderTheme.Prism.mintGlass.withAlphaComponent(0.0015),
            WorkRecorderTheme.Material.inputFillBottom,
        ])
        gradient?.draw(in: path, angle: 92)
        let lowerSheen = NSGradient(colors: [
            WorkRecorderTheme.accentMist.withAlphaComponent(0.036),
            NSColor(calibratedWhite: 1.0, alpha: 0.0),
        ])
        lowerSheen?.draw(in: CGRect(x: rect.minX, y: rect.maxY - 14, width: rect.width, height: 14), angle: 90)

        let innerShadow = NSBezierPath()
        innerShadow.move(to: CGPoint(x: rect.minX + 14, y: rect.maxY - 1.8))
        innerShadow.line(to: CGPoint(x: rect.maxX - 14, y: rect.maxY - 1.8))
        innerShadow.lineWidth = 1
        NSColor(calibratedRed: 0.30, green: 0.54, blue: 0.58, alpha: 0.040).setStroke()
        innerShadow.stroke()

        let topHighlight = NSBezierPath()
        topHighlight.move(to: CGPoint(x: rect.minX + 14, y: rect.minY + 1.5))
        topHighlight.line(to: CGPoint(x: rect.maxX - 14, y: rect.minY + 1.5))
        topHighlight.lineWidth = 0.8
        NSColor(calibratedWhite: 1.0, alpha: 0.56).setStroke()
        topHighlight.stroke()

        NSColor(calibratedWhite: 1.0, alpha: 0.50).setStroke()
        let innerHighlight = WorkRecorderTheme.roundedRectPath(rect.insetBy(dx: 1, dy: 1), radius: 12)
        innerHighlight.lineWidth = 1
        innerHighlight.stroke()
        (active ? WorkRecorderTheme.Material.inputStrokeActive : WorkRecorderTheme.Material.inputStroke).setStroke()
        path.lineWidth = active ? 1.15 : 1.0
        path.stroke()

        guard active else { return }
        let focusPrism = NSBezierPath()
        focusPrism.move(to: CGPoint(x: rect.maxX - 56, y: rect.minY + 1.6))
        focusPrism.curve(
            to: CGPoint(x: rect.maxX - 13, y: rect.minY + 4.8),
            controlPoint1: CGPoint(x: rect.maxX - 42, y: rect.minY - 1.0),
            controlPoint2: CGPoint(x: rect.maxX - 24, y: rect.minY + 1.8)
        )
        focusPrism.lineWidth = 0.85
        WorkRecorderTheme.Prism.softLavender.withAlphaComponent(WorkRecorderTheme.Prism.Alpha.inputFocusActive).setStroke()
        focusPrism.stroke()
    }
}
