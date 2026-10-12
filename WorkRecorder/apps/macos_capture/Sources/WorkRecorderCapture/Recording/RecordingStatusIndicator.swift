import AppKit

@MainActor
final class RecordingStatusIndicator: NSView {
    var mode: RecordingHUDMode = .preparing {
        didSet { needsDisplay = true }
    }
    var traceDegraded = false {
        didSet { needsDisplay = true }
    }
    var scopeNeedsReview = false {
        didSet { needsDisplay = true }
    }

    override var intrinsicContentSize: NSSize { NSSize(width: 13, height: 13) }

    override func draw(_ dirtyRect: NSRect) {
        let tint = statusTint
        let rect = bounds.insetBy(dx: 1.5, dy: 1.5)
        tint.withAlphaComponent(0.16).setFill()
        NSBezierPath(ovalIn: bounds).fill()
        tint.withAlphaComponent(0.92).setFill()
        drawGlyph(in: rect)
    }

    private var statusTint: NSColor {
        if traceDegraded || scopeNeedsReview {
            return WorkRecorderTheme.warning
        }
        if mode == .recording {
            return NSColor(calibratedRed: 0.84, green: 0.10, blue: 0.08, alpha: 1)
        }
        return WorkRecorderTheme.Prism.tiffanyBlue
    }

    private func drawGlyph(in rect: NSRect) {
        switch mode {
        case .paused, .stopping:
            drawPauseGlyph(in: rect)
        case .preparing:
            NSBezierPath(ovalIn: rect.insetBy(dx: 1.6, dy: 1.6)).fill()
        case .recording:
            NSBezierPath(ovalIn: rect).fill()
        }
    }

    private func drawPauseGlyph(in rect: NSRect) {
        let left = NSRect(x: rect.minX + 2.1, y: rect.minY + 1.8, width: 2.4, height: rect.height - 3.6)
        let right = NSRect(x: rect.maxX - 4.5, y: rect.minY + 1.8, width: 2.4, height: rect.height - 3.6)
        WorkRecorderTheme.roundedRectPath(left, radius: 1.1).fill()
        WorkRecorderTheme.roundedRectPath(right, radius: 1.1).fill()
    }
}
