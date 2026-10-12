import AppKit

@MainActor
final class RecordingVideoPreviewView: NSControl {
    enum ContentMode {
        case fill
        case fit
    }

    private let image: NSImage?
    private let title: String
    private let subtitle: String
    private let durationText: String?
    private let ctaText: String
    private let affordanceSymbolName: String
    private let showsPlaybackChrome: Bool
    private let compact: Bool
    private let contentMode: ContentMode
    private let actionable: Bool

    init(
        image: NSImage?,
        title: String,
        subtitle: String,
        durationText: String?,
        ctaText: String,
        affordanceSymbolName: String = "play.fill",
        showsPlaybackChrome: Bool = true,
        compact: Bool = false,
        contentMode: ContentMode = .fill,
        target: AnyObject? = nil,
        action: Selector? = nil
    ) {
        self.image = image
        self.title = WorkRecorderLocalization.text(title)
        self.subtitle = WorkRecorderLocalization.text(subtitle)
        self.durationText = durationText
        self.ctaText = WorkRecorderLocalization.text(ctaText)
        self.affordanceSymbolName = affordanceSymbolName
        self.showsPlaybackChrome = showsPlaybackChrome
        self.compact = compact
        self.contentMode = contentMode
        self.actionable = action != nil
        super.init(frame: .zero)
        self.target = target
        self.action = action
        wantsLayer = true
        layer?.cornerRadius = compact ? 18 : 22
        layer?.masksToBounds = true
        setAccessibilityRole(action == nil ? .group : .button)
        setAccessibilityLabel(WorkRecorderLocalization.text(ctaText))
    }

    required init?(coder: NSCoder) {
        nil
    }

    override var acceptsFirstResponder: Bool {
        actionable
    }

    override func resetCursorRects() {
        super.resetCursorRects()
        if actionable {
            addCursorRect(bounds, cursor: .pointingHand)
        }
    }

    override func becomeFirstResponder() -> Bool {
        needsDisplay = true
        return actionable
    }

    override func resignFirstResponder() -> Bool {
        needsDisplay = true
        return true
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let radius: CGFloat = compact ? 18 : 22
        let rect = bounds
        let path = NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius)
        NSGraphicsContext.saveGraphicsState()
        path.addClip()
        drawBackdrop(in: rect)
        drawVignette(in: rect)
        drawPlaybackAffordance(in: rect)
        if compact {
            if showsPlaybackChrome {
                drawCompactPlaybackRail(in: rect.insetBy(dx: 18, dy: 14))
            } else {
                drawTimeline(in: rect.insetBy(dx: 18, dy: 14))
            }
        } else if showsPlaybackChrome {
            drawPlaybackControlBar(in: rect.insetBy(dx: 20, dy: 18))
        }
        drawTitleBlock(in: rect.insetBy(dx: compact ? 18 : 22, dy: compact ? 14 : 18))
        if let durationText {
            drawDurationBadge(durationText, in: rect)
        }
        NSGraphicsContext.restoreGraphicsState()
        WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.18).setStroke()
        path.lineWidth = 1
        path.stroke()
        drawFocusRingIfNeeded(in: rect, radius: radius)
    }

    override func mouseDown(with event: NSEvent) {
        if actionable {
            window?.makeFirstResponder(self)
            performPrimaryAction()
        } else {
            super.mouseDown(with: event)
        }
    }

    override func keyDown(with event: NSEvent) {
        if actionable, event.keyCode == 36 || event.keyCode == 49 {
            performPrimaryAction()
            return
        }
        super.keyDown(with: event)
    }

    override func accessibilityPerformPress() -> Bool {
        guard actionable else { return false }
        performPrimaryAction()
        return true
    }

    private func drawBackdrop(in rect: NSRect) {
        if let image {
            switch contentMode {
            case .fill:
                image.drawAspectFill(in: rect)
                NSColor.black.withAlphaComponent(0.13).setFill()
                rect.fill()
            case .fit:
                NSColor(calibratedRed: 0.030, green: 0.043, blue: 0.050, alpha: 1).setFill()
                rect.fill()
                let stage = rect.insetBy(dx: compact ? 12 : 18, dy: compact ? 12 : 18)
                let stagePath = NSBezierPath(roundedRect: stage, xRadius: compact ? 14 : 18, yRadius: compact ? 14 : 18)
                NSColor.white.withAlphaComponent(0.94).setFill()
                stagePath.fill()
                NSGraphicsContext.saveGraphicsState()
                stagePath.addClip()
                image.drawWorkbenchAspectFit(in: stage.insetBy(dx: 8, dy: 8))
                NSGraphicsContext.restoreGraphicsState()
                WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.20).setStroke()
                stagePath.lineWidth = 0.8
                stagePath.stroke()
                NSColor.black.withAlphaComponent(0.05).setFill()
                rect.fill()
            }
            return
        }
        NSGradient(colors: [
            NSColor(calibratedRed: 0.045, green: 0.052, blue: 0.068, alpha: 1),
            NSColor(calibratedRed: 0.105, green: 0.082, blue: 0.082, alpha: 1),
            NSColor(calibratedRed: 0.205, green: 0.105, blue: 0.090, alpha: 1),
        ])?.draw(in: rect, angle: 18)
    }

    private func drawVignette(in rect: NSRect) {
        NSGradient(colors: [
            NSColor.black.withAlphaComponent(0.04),
            NSColor.black.withAlphaComponent(0.00),
            NSColor.black.withAlphaComponent(0.22),
        ])?.draw(in: rect, angle: 90)
    }

    private func drawPlaybackAffordance(in rect: NSRect) {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: compact ? 12.0 : 12.8, weight: .semibold),
            .foregroundColor: WorkbenchDesignTokens.Color.primaryText.withAlphaComponent(actionable ? 1.0 : 0.68),
        ]
        let textWidth = (ctaText as NSString).size(withAttributes: attributes).width
        let pillWidth = min(rect.width - 36, max(compact ? 116 : 136, textWidth + 58))
        let pillSize = CGSize(width: pillWidth, height: compact ? 36 : 40)
        let pill = NSRect(
            x: rect.midX - pillSize.width / 2,
            y: rect.midY - pillSize.height / 2 + (compact ? 4 : 8),
            width: pillSize.width,
            height: pillSize.height
        )
        let path = NSBezierPath(roundedRect: pill, xRadius: pill.height / 2, yRadius: pill.height / 2)
        NSColor.white.withAlphaComponent(actionable ? 0.82 : 0.58).setFill()
        path.fill()
        WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(actionable ? 0.38 : 0.16).setStroke()
        path.lineWidth = 0.8
        path.stroke()

        let iconRect = NSRect(x: pill.minX + 15, y: pill.midY - 7.5, width: 15, height: 15)
        drawSymbol(
            affordanceSymbolName,
            in: iconRect,
            color: WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(actionable ? 1.0 : 0.62)
        )
        ctaText.draw(
            in: NSRect(x: iconRect.maxX + 8, y: pill.midY - 9, width: pill.width - 48, height: 18),
            withAttributes: attributes
        )
    }

    private func drawTimeline(in rect: NSRect) {
        let lineY = rect.minY + (compact ? 20 : 24)
        let line = NSBezierPath()
        line.move(to: CGPoint(x: rect.minX, y: lineY))
        line.line(to: CGPoint(x: rect.maxX, y: lineY))
        WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.35).setStroke()
        line.lineWidth = 1.4
        line.stroke()
        let offsets: [CGFloat] = [0.02, 0.31, 0.56, 0.82, 0.98]
        for (index, offset) in offsets.enumerated() {
            let x = rect.minX + rect.width * offset
            let radius: CGFloat = index == 0 || index == offsets.count - 1 ? 5.0 : 3.4
            let dot = NSRect(x: x - radius, y: lineY - radius, width: radius * 2, height: radius * 2)
            (index == 0 || index == offsets.count - 1
                ? NSColor.white.withAlphaComponent(0.96)
                : NSColor(calibratedRed: 0.86, green: 0.26, blue: 0.22, alpha: 0.82)
            ).setFill()
            NSBezierPath(ovalIn: dot).fill()
        }
    }

    private func drawPlaybackControlBar(in rect: NSRect) {
        let bar = NSRect(x: rect.minX + 4, y: rect.minY + 2, width: rect.width - 8, height: 28)
        let barPath = NSBezierPath(roundedRect: bar, xRadius: 14, yRadius: 14)
        NSColor.white.withAlphaComponent(0.72).setFill()
        barPath.fill()
        WorkbenchDesignTokens.Color.neutralHairline.withAlphaComponent(0.42).setStroke()
        barPath.lineWidth = 0.7
        barPath.stroke()

        let playCircle = NSRect(x: bar.minX + 8, y: bar.midY - 8.5, width: 17, height: 17)
        WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.16).setFill()
        NSBezierPath(ovalIn: playCircle).fill()
        drawSymbol(
            "play.fill",
            in: playCircle.insetBy(dx: 5.2, dy: 4.4).offsetBy(dx: 0.8, dy: 0),
            color: WorkbenchDesignTokens.Color.tiffanyStrong
        )

        let timeAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 9.4, weight: .medium),
            .foregroundColor: WorkbenchDesignTokens.Color.secondaryText,
        ]
        "00:00".draw(
            in: NSRect(x: playCircle.maxX + 7, y: bar.midY - 6.5, width: 36, height: 13),
            withAttributes: timeAttributes
        )
        let duration = durationText ?? "--:--"
        let durationSize = (duration as NSString).size(withAttributes: timeAttributes)
        duration.draw(
            in: NSRect(x: bar.maxX - durationSize.width - 10, y: bar.midY - 6.5, width: durationSize.width + 1, height: 13),
            withAttributes: timeAttributes
        )

        let railStartX = playCircle.maxX + 47
        let railEndX = bar.maxX - durationSize.width - 18
        let railY = bar.midY
        let rail = NSBezierPath()
        rail.move(to: CGPoint(x: railStartX, y: railY))
        rail.line(to: CGPoint(x: railEndX, y: railY))
        WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.20).setStroke()
        rail.lineWidth = 1.7
        rail.stroke()
        let progress = NSBezierPath()
        progress.move(to: CGPoint(x: railStartX, y: railY))
        progress.line(to: CGPoint(x: railStartX + (railEndX - railStartX) * 0.38, y: railY))
        WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.82).setStroke()
        progress.lineWidth = 1.9
        progress.stroke()
        for offset in [0.0, 0.28, 0.52, 0.78, 1.0] {
            let x = railStartX + (railEndX - railStartX) * offset
            let dot = NSRect(x: x - 2.0, y: railY - 2.0, width: 4.0, height: 4.0)
            NSColor.white.withAlphaComponent(0.96).setFill()
            NSBezierPath(ovalIn: dot).fill()
            WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.52).setStroke()
            NSBezierPath(ovalIn: dot).stroke()
        }
    }

    private func drawCompactPlaybackRail(in rect: NSRect) {
        let play = NSRect(x: rect.minX, y: rect.minY + 10, width: 18, height: 18)
        WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.16).setFill()
        NSBezierPath(ovalIn: play).fill()
        drawSymbol("play.fill", in: play.insetBy(dx: 5.5, dy: 4.7).offsetBy(dx: 0.8, dy: 0), color: WorkbenchDesignTokens.Color.tiffanyStrong)
        let railStartX = play.maxX + 10
        let railEndX = rect.maxX
        let railY = play.midY
        let rail = NSBezierPath()
        rail.move(to: CGPoint(x: railStartX, y: railY))
        rail.line(to: CGPoint(x: railEndX, y: railY))
        WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.28).setStroke()
        rail.lineWidth = 1.6
        rail.stroke()
        let progress = NSBezierPath()
        progress.move(to: CGPoint(x: railStartX, y: railY))
        progress.line(to: CGPoint(x: railStartX + (railEndX - railStartX) * 0.34, y: railY))
        WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.74).setStroke()
        progress.lineWidth = 1.8
        progress.stroke()
        for offset in [0.0, 0.33, 0.62, 1.0] {
            let x = railStartX + (railEndX - railStartX) * offset
            let dot = NSRect(x: x - 3, y: railY - 3, width: 6, height: 6)
            NSColor.white.withAlphaComponent(0.96).setFill()
            NSBezierPath(ovalIn: dot).fill()
            WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.44).setStroke()
            NSBezierPath(ovalIn: dot).stroke()
        }
    }

    private func drawTitleBlock(in rect: NSRect) {
        guard !title.isEmpty || !subtitle.isEmpty else {
            return
        }
        let titleAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: compact ? 13.2 : 15.0, weight: .semibold),
            .foregroundColor: NSColor.white.withAlphaComponent(0.94),
        ]
        let subtitleAttributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: compact ? 10.8 : 11.6, weight: .medium),
            .foregroundColor: NSColor.white.withAlphaComponent(0.72),
        ]
        title.draw(
            in: NSRect(x: rect.minX, y: rect.maxY - (compact ? 28 : 32), width: rect.width - 82, height: 18),
            withAttributes: titleAttributes
        )
        if !subtitle.isEmpty {
            subtitle.draw(
                in: NSRect(x: rect.minX, y: rect.maxY - (compact ? 46 : 52), width: rect.width - 36, height: 16),
                withAttributes: subtitleAttributes
            )
        }
    }

    private func drawDurationBadge(_ text: String, in rect: NSRect) {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 11.0, weight: .semibold),
            .foregroundColor: WorkbenchDesignTokens.Color.primaryText,
        ]
        let size = (text as NSString).size(withAttributes: attributes)
        let badge = NSRect(
            x: rect.maxX - size.width - 28,
            y: rect.maxY - 32,
            width: size.width + 16,
            height: 22
        )
        let path = NSBezierPath(roundedRect: badge, xRadius: 11, yRadius: 11)
        NSColor.white.withAlphaComponent(0.82).setFill()
        path.fill()
        text.draw(
            in: NSRect(x: badge.minX + 8, y: badge.midY - 7, width: size.width + 1, height: 14),
            withAttributes: attributes
        )
    }

    private func drawSymbol(_ name: String, in rect: NSRect, color: NSColor) {
        guard let symbol = NSImage(systemSymbolName: name, accessibilityDescription: nil),
              let context = NSGraphicsContext.current?.cgContext else {
            return
        }
        var drawRect = rect
        guard let cgImage = symbol.cgImage(forProposedRect: &drawRect, context: nil, hints: nil) else {
            return
        }
        NSGraphicsContext.saveGraphicsState()
        context.clip(to: rect, mask: cgImage)
        color.setFill()
        rect.fill()
        NSGraphicsContext.restoreGraphicsState()
    }

    private func drawFocusRingIfNeeded(in rect: NSRect, radius: CGFloat) {
        guard actionable, window?.firstResponder === self else { return }
        NSColor.keyboardFocusIndicatorColor.withAlphaComponent(0.58).setStroke()
        let focus = NSBezierPath(
            roundedRect: rect.insetBy(dx: 3, dy: 3),
            xRadius: max(2, radius - 3),
            yRadius: max(2, radius - 3)
        )
        focus.lineWidth = 1.4
        focus.stroke()
    }

    private func performPrimaryAction() {
        guard let action else { return }
        sendAction(action, to: target)
    }
}
