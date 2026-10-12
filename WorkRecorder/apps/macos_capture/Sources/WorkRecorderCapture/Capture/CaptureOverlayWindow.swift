import AppKit

@MainActor
final class CaptureOverlayWindow: NSPanel {
    init(
        screen: NSScreen,
        prompt: String = "WorkRecorder · 拖拽选择录制区域      Esc 取消",
        completion: @escaping (SelectionResult) -> Void,
        cancel: @escaping () -> Void
    ) {
        let view = CaptureOverlayView(screen: screen, prompt: prompt, completion: completion, cancel: cancel)
        super.init(contentRect: screen.frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isOpaque = false
        backgroundColor = .clear
        level = .screenSaver
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary]
        ignoresMouseEvents = false
        acceptsMouseMovedEvents = true
        contentView = view
        orderFrontRegardless()
    }

    override var canBecomeKey: Bool {
        true
    }

    override func keyDown(with event: NSEvent) {
        if event.keyCode == 53 {
            (contentView as? CaptureOverlayView)?.cancelCapture()
            return
        }
        super.keyDown(with: event)
    }

}

@MainActor
final class CaptureAnchorOverlayWindow: NSPanel {
    init(screen: NSScreen, selection: CGRect, associationEdge: RecordingOverlayPlacementEdge) {
        let localSelection = Geometry.overlayRect(for: selection, on: screen)
        let view = CaptureAnchorOverlayView(selection: localSelection, associationEdge: associationEdge)
        super.init(contentRect: screen.frame, styleMask: [.borderless, .nonactivatingPanel], backing: .buffered, defer: false)
        isOpaque = false
        backgroundColor = .clear
        level = .screenSaver
        collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        ignoresMouseEvents = true
        contentView = view
        orderFrontRegardless()
    }
}

@MainActor
final class CaptureOverlayView: NSView {
    override var isFlipped: Bool { true }

    private let owningScreen: NSScreen
    private let prompt: String
    private let completion: (SelectionResult) -> Void
    private let cancel: () -> Void
    private var dragStart: CGPoint?
    private var selection: CGRect?
    private var hasFinished = false

    init(
        screen: NSScreen,
        prompt: String = "WorkRecorder · 拖拽选择录制区域      Esc 取消",
        completion: @escaping (SelectionResult) -> Void,
        cancel: @escaping () -> Void
    ) {
        self.owningScreen = screen
        self.prompt = WorkRecorderLocalization.text(prompt)
        self.completion = completion
        self.cancel = cancel
        super.init(frame: CGRect(origin: .zero, size: screen.frame.size))
        wantsLayer = true
    }

    required init?(coder: NSCoder) {
        nil
    }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool {
        true
    }

    override var acceptsFirstResponder: Bool {
        true
    }

    func cancelCapture() {
        finishWithCancel()
    }

    override func keyDown(with event: NSEvent) {
        if event.keyCode == 53 {
            finishWithCancel()
        }
    }

    override func mouseDown(with event: NSEvent) {
        dragStart = convert(event.locationInWindow, from: nil)
        selection = nil
        needsDisplay = true
    }

    override func mouseDragged(with event: NSEvent) {
        guard let dragStart else { return }
        selection = Geometry.normalizedRect(from: dragStart, to: convert(event.locationInWindow, from: nil))
        needsDisplay = true
    }

    override func mouseUp(with event: NSEvent) {
        guard let window, let dragStart else {
            finishWithCancel()
            return
        }
        let finalSelection = Geometry.normalizedRect(from: dragStart, to: convert(event.locationInWindow, from: nil))
        guard finalSelection.width >= 12, finalSelection.height >= 12 else {
            finishWithCancel()
            return
        }
        let screenRect = Geometry.appKitScreenRect(for: finalSelection, in: window)
        let captureRect = Geometry.screencaptureRect(from: screenRect, on: owningScreen)
        finishWithSelection(SelectionResult(screen: owningScreen, screenRect: screenRect, captureRect: captureRect))
    }

    private func finishWithSelection(_ result: SelectionResult) {
        guard !hasFinished else { return }
        hasFinished = true
        // Defer the coordinator callback so this overlay window is not closed while AppKit
        // is still unwinding the mouse event that belongs to the same window/view.
        DispatchQueue.main.async { [completion] in
            completion(result)
        }
    }

    private func finishWithCancel() {
        guard !hasFinished else { return }
        hasFinished = true
        DispatchQueue.main.async { [cancel] in
            cancel()
        }
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        drawOverlay(selection: selection)
        drawTopBar()
        if let selection {
            CaptureOverlayStyle.drawSelection(selection, in: bounds, showBadge: true)
        }
    }

    private func drawOverlay(selection: CGRect?) {
        guard let selection else {
            CaptureOverlayStyle.drawVeil(bounds, active: true)
            return
        }
        CaptureOverlayStyle.drawVeil(CGRect(x: bounds.minX, y: bounds.minY, width: bounds.width, height: max(0, selection.minY - bounds.minY)), active: true)
        CaptureOverlayStyle.drawVeil(CGRect(x: bounds.minX, y: selection.maxY, width: bounds.width, height: max(0, bounds.maxY - selection.maxY)), active: true)
        CaptureOverlayStyle.drawVeil(CGRect(x: bounds.minX, y: selection.minY, width: max(0, selection.minX - bounds.minX), height: selection.height), active: true)
        CaptureOverlayStyle.drawVeil(CGRect(x: selection.maxX, y: selection.minY, width: max(0, bounds.maxX - selection.maxX), height: selection.height), active: true)
    }

    private func drawTopBar() {
        let textWidth = (prompt as NSString).size(withAttributes: [.font: NSFont.systemFont(ofSize: 11.5, weight: .medium)]).width
        let barWidth = min(bounds.width - 28, max(344, textWidth + 28))
        let bar = CGRect(x: bounds.midX - barWidth / 2, y: 18, width: barWidth, height: 32)
        WorkRecorderTheme.panelColor(for: effectiveAppearance).withAlphaComponent(0.82).setFill()
        WorkRecorderTheme.roundedRectPath(bar, radius: 16).fill()
        WorkRecorderTheme.strokeColor(for: effectiveAppearance).withAlphaComponent(0.72).setStroke()
        let border = WorkRecorderTheme.roundedRectPath(bar.insetBy(dx: 0.5, dy: 0.5), radius: 16)
        border.lineWidth = 1
        border.stroke()
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 11.5, weight: .medium),
            .foregroundColor: WorkRecorderTheme.primaryTextColor(for: effectiveAppearance),
        ]
        prompt.draw(in: bar.insetBy(dx: 14, dy: 8), withAttributes: attributes)
    }
}

@MainActor
final class CaptureAnchorOverlayView: NSView {
    override var isFlipped: Bool { true }

    private let selection: CGRect
    private let associationEdge: RecordingOverlayPlacementEdge

    init(selection: CGRect, associationEdge: RecordingOverlayPlacementEdge) {
        self.selection = selection
        self.associationEdge = associationEdge
        super.init(frame: .zero)
        wantsLayer = true
    }

    required init?(coder: NSCoder) {
        nil
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        drawOverlay(selection: selection)
        CaptureOverlayStyle.drawSelection(selection, in: bounds, showBadge: false)
        CaptureOverlayStyle.drawAssociationBloom(on: selection, edge: associationEdge)
    }

    private func drawOverlay(selection: CGRect) {
        CaptureOverlayStyle.drawVeil(CGRect(x: bounds.minX, y: bounds.minY, width: bounds.width, height: max(0, selection.minY - bounds.minY)), active: false)
        CaptureOverlayStyle.drawVeil(CGRect(x: bounds.minX, y: selection.maxY, width: bounds.width, height: max(0, bounds.maxY - selection.maxY)), active: false)
        CaptureOverlayStyle.drawVeil(CGRect(x: bounds.minX, y: selection.minY, width: max(0, selection.minX - bounds.minX), height: selection.height), active: false)
        CaptureOverlayStyle.drawVeil(CGRect(x: selection.maxX, y: selection.minY, width: max(0, bounds.maxX - selection.maxX), height: selection.height), active: false)
    }
}

enum CaptureOverlayStyle {
    @MainActor
    static func drawVeil(_ rect: CGRect, active: Bool) {
        guard !rect.isEmpty else { return }
        NSColor(calibratedRed: 0.46, green: 0.52, blue: 0.55, alpha: active ? 0.34 : 0.31).setFill()
        rect.fill()

        let sheen = NSGradient(colors: [
            NSColor(calibratedWhite: 1.0, alpha: active ? 0.015 : 0.010),
            WorkRecorderTheme.Prism.iceBlue.withAlphaComponent(active ? 0.013 : 0.009),
            WorkRecorderTheme.Prism.tiffanyBlue.withAlphaComponent(active ? 0.004 : 0.003),
            NSColor(calibratedWhite: 1.0, alpha: 0.0),
        ])
        sheen?.draw(in: rect, angle: -14)

        let texture = NSBezierPath()
        var x = rect.minX - rect.height
        while x < rect.maxX + rect.height {
            texture.move(to: CGPoint(x: x, y: rect.maxY))
            texture.line(to: CGPoint(x: x + rect.height * 0.45, y: rect.minY))
            x += 34
        }
        texture.lineWidth = 0.36
        WorkRecorderTheme.Prism.softLavender.withAlphaComponent(active ? 0.006 : 0.004).setStroke()
        texture.stroke()
    }

    @MainActor
    static func drawSelection(_ rect: CGRect, in bounds: CGRect, showBadge: Bool) {
        drawGlow(rect, active: showBadge)
        drawLensFill(rect, active: showBadge)
        let precisionKeyline = NSBezierPath(rect: rect.insetBy(dx: -0.6, dy: -0.6))
        precisionKeyline.lineWidth = showBadge ? 2.48 : 2.32
        NSColor(calibratedRed: 0.012, green: 0.072, blue: 0.084, alpha: showBadge ? 0.50 : 0.45).setStroke()
        precisionKeyline.stroke()

        let outline = NSBezierPath(rect: rect.insetBy(dx: 0.45, dy: 0.45))
        outline.lineWidth = showBadge ? WorkRecorderTheme.Prism.Alpha.selectionLineActive : WorkRecorderTheme.Prism.Alpha.selectionLine
        WorkRecorderTheme.Prism.tiffanyBlue
            .withAlphaComponent(showBadge ? 0.98 : 0.94)
            .setStroke()
        outline.stroke()
        drawPrismEdge(rect, active: showBadge)
        drawCornerBloom(rect, active: showBadge)

        drawHandles(rect, active: showBadge)
        if showBadge {
            drawSizeBadge(rect, in: bounds)
        }
    }

    @MainActor
    private static func drawLensFill(_ rect: CGRect, active: Bool) {
        NSGraphicsContext.saveGraphicsState()
        NSBezierPath(rect: rect).addClip()
        let lens = NSGradient(colors: [
            NSColor(calibratedWhite: 1.0, alpha: 0.0),
            WorkRecorderTheme.Prism.iceBlue.withAlphaComponent(active ? 0.010 : 0.006),
            WorkRecorderTheme.Prism.tiffanyBlue.withAlphaComponent(active ? 0.012 : 0.007),
            NSColor(calibratedWhite: 1.0, alpha: 0.0),
        ])
        lens?.draw(in: rect, angle: -18)

        let refraction = NSBezierPath()
        var x = rect.minX - rect.height
        while x < rect.maxX + rect.height {
            refraction.move(to: CGPoint(x: x, y: rect.maxY))
            refraction.line(to: CGPoint(x: x + rect.height * 0.36, y: rect.minY))
            x += 42
        }
        refraction.lineWidth = 0.32
        WorkRecorderTheme.Prism.softAqua
            .withAlphaComponent(active ? 0.006 : 0.003)
            .setStroke()
        refraction.stroke()
        NSGraphicsContext.restoreGraphicsState()
    }

    @MainActor
    static func drawAssociationBloom(on rect: CGRect, edge: RecordingOverlayPlacementEdge) {
        guard edge != .bottomHud else { return }
        let path = NSBezierPath()
        let length = min(edge == .left || edge == .right ? rect.height * 0.42 : rect.width * 0.42, 90)
        switch edge {
        case .below:
            path.move(to: CGPoint(x: rect.midX - length / 2, y: rect.maxY))
            path.curve(
                to: CGPoint(x: rect.midX + length / 2, y: rect.maxY),
                controlPoint1: CGPoint(x: rect.midX - length * 0.18, y: rect.maxY + 2),
                controlPoint2: CGPoint(x: rect.midX + length * 0.18, y: rect.maxY - 2)
            )
        case .above:
            path.move(to: CGPoint(x: rect.midX - length / 2, y: rect.minY))
            path.curve(
                to: CGPoint(x: rect.midX + length / 2, y: rect.minY),
                controlPoint1: CGPoint(x: rect.midX - length * 0.18, y: rect.minY - 2),
                controlPoint2: CGPoint(x: rect.midX + length * 0.18, y: rect.minY + 2)
            )
        case .right:
            path.move(to: CGPoint(x: rect.maxX, y: rect.midY - length / 2))
            path.curve(
                to: CGPoint(x: rect.maxX, y: rect.midY + length / 2),
                controlPoint1: CGPoint(x: rect.maxX + 2, y: rect.midY - length * 0.18),
                controlPoint2: CGPoint(x: rect.maxX - 2, y: rect.midY + length * 0.18)
            )
        case .left:
            path.move(to: CGPoint(x: rect.minX, y: rect.midY - length / 2))
            path.curve(
                to: CGPoint(x: rect.minX, y: rect.midY + length / 2),
                controlPoint1: CGPoint(x: rect.minX - 2, y: rect.midY - length * 0.18),
                controlPoint2: CGPoint(x: rect.minX + 2, y: rect.midY + length * 0.18)
            )
        case .bottomHud:
            return
        }
        path.lineCapStyle = .round
        path.lineWidth = 8
        WorkRecorderTheme.accent.withAlphaComponent(0.045).setStroke()
        path.stroke()
        path.lineWidth = 2
        WorkRecorderTheme.accentSoft.withAlphaComponent(0.24).setStroke()
        path.stroke()
        path.lineWidth = 0.8
        NSColor(calibratedWhite: 1.0, alpha: 0.52).setStroke()
        path.stroke()
    }

    @MainActor
    private static func drawGlow(_ rect: CGRect, active: Bool) {
        let outer = rect.insetBy(dx: -5, dy: -5)
        let glow = NSBezierPath(rect: outer)
        glow.lineWidth = active ? 6.2 : 3.8
        WorkRecorderTheme.Prism.tiffanyBlue.withAlphaComponent(active ? 0.090 : 0.056).setStroke()
        glow.stroke()

        let mid = rect.insetBy(dx: -2, dy: -2)
        let midPath = NSBezierPath(rect: mid)
        midPath.lineWidth = active ? 2.3 : 1.35
        WorkRecorderTheme.Prism.tiffanyBlue
            .withAlphaComponent(active ? 0.24 : 0.14)
            .setStroke()
        midPath.stroke()
    }

    @MainActor
    private static func drawPrismEdge(_ rect: CGRect, active: Bool) {
        let topLeft = NSBezierPath()
        topLeft.move(to: CGPoint(x: rect.minX + 8, y: rect.minY + 0.6))
        topLeft.line(to: CGPoint(x: rect.maxX - 8, y: rect.minY + 0.6))
        topLeft.move(to: CGPoint(x: rect.minX + 0.6, y: rect.minY + 8))
        topLeft.line(to: CGPoint(x: rect.minX + 0.6, y: rect.maxY - 8))
        topLeft.lineWidth = 0.7
        NSColor(calibratedWhite: 1.0, alpha: active ? 0.70 : 0.54).setStroke()
        topLeft.stroke()

        let lowerRight = NSBezierPath()
        lowerRight.move(to: CGPoint(x: rect.minX + 10, y: rect.maxY - 0.6))
        lowerRight.line(to: CGPoint(x: rect.maxX - 10, y: rect.maxY - 0.6))
        lowerRight.move(to: CGPoint(x: rect.maxX - 0.6, y: rect.minY + 10))
        lowerRight.line(to: CGPoint(x: rect.maxX - 0.6, y: rect.maxY - 10))
        lowerRight.lineWidth = 0.7
        WorkRecorderTheme.Prism.softLavender
            .withAlphaComponent(active ? WorkRecorderTheme.Prism.Alpha.selectionCornerActive : WorkRecorderTheme.Prism.Alpha.selectionCorner)
            .setStroke()
        lowerRight.stroke()
    }

    @MainActor
    private static func drawCornerBloom(_ rect: CGRect, active: Bool) {
        let length = min(rect.width, rect.height, 92) * 0.18
        let segments: [(CGPoint, CGPoint, CGPoint)] = [
            (
                CGPoint(x: rect.minX, y: rect.minY),
                CGPoint(x: rect.minX + length, y: rect.minY),
                CGPoint(x: rect.minX, y: rect.minY + length)
            ),
            (
                CGPoint(x: rect.maxX, y: rect.minY),
                CGPoint(x: rect.maxX - length, y: rect.minY),
                CGPoint(x: rect.maxX, y: rect.minY + length)
            ),
            (
                CGPoint(x: rect.maxX, y: rect.maxY),
                CGPoint(x: rect.maxX - length, y: rect.maxY),
                CGPoint(x: rect.maxX, y: rect.maxY - length)
            ),
            (
                CGPoint(x: rect.minX, y: rect.maxY),
                CGPoint(x: rect.minX + length, y: rect.maxY),
                CGPoint(x: rect.minX, y: rect.maxY - length)
            ),
        ]
        for (corner, horizontalEnd, verticalEnd) in segments {
            let bloom = NSBezierPath()
            bloom.move(to: corner)
            bloom.line(to: horizontalEnd)
            bloom.move(to: corner)
            bloom.line(to: verticalEnd)
            bloom.lineCapStyle = .round
            bloom.lineWidth = active ? 2.4 : 1.70
            WorkRecorderTheme.Prism.tiffanyBlue.withAlphaComponent(active ? 0.070 : 0.040).setStroke()
            bloom.stroke()
            bloom.lineWidth = 0.75
            NSColor(calibratedWhite: 1.0, alpha: active ? 0.64 : 0.46).setStroke()
            bloom.stroke()
        }
    }

    @MainActor
    private static func drawHandles(_ rect: CGRect, active: Bool) {
        let size: CGFloat = active ? 12.5 : 11.5
        let points = active ? [
            CGPoint(x: rect.minX, y: rect.minY),
            CGPoint(x: rect.maxX, y: rect.minY),
            CGPoint(x: rect.minX, y: rect.midY),
            CGPoint(x: rect.maxX, y: rect.midY),
            CGPoint(x: rect.minX, y: rect.maxY),
            CGPoint(x: rect.maxX, y: rect.maxY),
        ] : [
            CGPoint(x: rect.minX, y: rect.minY),
            CGPoint(x: rect.maxX, y: rect.minY),
            CGPoint(x: rect.minX, y: rect.maxY),
            CGPoint(x: rect.maxX, y: rect.maxY),
        ]
        for point in points {
            let handle = CGRect(x: point.x - size / 2, y: point.y - size / 2, width: size, height: size)
            let path = WorkRecorderTheme.roundedRectPath(handle, radius: 2.8)
            NSGraphicsContext.saveGraphicsState()
            let shadow = NSShadow()
            shadow.shadowColor = WorkRecorderTheme.accent.withAlphaComponent(active ? 0.11 : 0.070)
            shadow.shadowBlurRadius = active ? 8 : 5.5
            shadow.shadowOffset = CGSize(width: 0, height: -1.2)
            shadow.set()
            WorkRecorderTheme.Satin.silverHighlight.withAlphaComponent(active ? 0.70 : 0.58).setFill()
            path.fill()
            NSGraphicsContext.restoreGraphicsState()
            WorkRecorderTheme.Prism.iceBlue.withAlphaComponent(active ? 0.24 : 0.17).setFill()
            path.fill()

            let topHighlight = NSBezierPath()
            topHighlight.move(to: CGPoint(x: handle.minX + 2.6, y: handle.minY + 2.3))
            topHighlight.line(to: CGPoint(x: handle.maxX - 2.6, y: handle.minY + 2.3))
            topHighlight.lineWidth = 0.7
            WorkRecorderTheme.Satin.silverHighlight
                .withAlphaComponent(WorkRecorderTheme.Satin.handleHighlightAlpha)
                .setStroke()
            topHighlight.stroke()

            let bottomContact = NSBezierPath()
            bottomContact.move(to: CGPoint(x: handle.minX + 2.6, y: handle.maxY - 2.0))
            bottomContact.line(to: CGPoint(x: handle.maxX - 2.6, y: handle.maxY - 2.0))
            bottomContact.lineWidth = 0.7
            WorkRecorderTheme.Satin.coolGraphiteReflection.withAlphaComponent(0.055).setStroke()
            bottomContact.stroke()

        WorkRecorderTheme.accent.withAlphaComponent(active ? 0.88 : 0.76).setStroke()
            path.lineWidth = 1
            path.stroke()

            WorkRecorderTheme.Satin.coatingBlue.withAlphaComponent(active ? 0.46 : 0.34).setFill()
            NSBezierPath(roundedRect: handle.insetBy(dx: size * 0.42, dy: size * 0.42), xRadius: 1.2, yRadius: 1.2).fill()
        }
    }

    @MainActor
    private static func drawSizeBadge(_ rect: CGRect, in bounds: CGRect) {
        let label = "\(Int(rect.width)) × \(Int(rect.height))"
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 11, weight: .medium),
            .foregroundColor: WorkRecorderTheme.primaryText,
        ]
        let size = label.size(withAttributes: attributes)
        var y = rect.minY - 28
        if y < 58 {
            y = rect.maxY + 8
        }
        let badge = CGRect(x: min(rect.minX, bounds.maxX - size.width - 34), y: y, width: size.width + 18, height: 22)
        WorkRecorderTheme.panelColor(for: NSAppearance(named: .aqua)!).withAlphaComponent(0.90).setFill()
        WorkRecorderTheme.roundedRectPath(badge, radius: 8).fill()
        WorkRecorderTheme.panelStroke.withAlphaComponent(0.70).setStroke()
        let border = WorkRecorderTheme.roundedRectPath(badge.insetBy(dx: 0.5, dy: 0.5), radius: 8)
        border.lineWidth = 1
        border.stroke()
        label.draw(in: badge.insetBy(dx: 9, dy: 4), withAttributes: attributes)
    }
}
