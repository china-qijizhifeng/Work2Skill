import AppKit

@MainActor
final class RecordingTimelineMarkerBarView: NSControl {
    private let steps: [WorkbenchRecordingTimelineStepView]
    private let selectedStepId: String?
    private let durationMs: Int

    private struct MarkerLayout {
        let step: WorkbenchRecordingTimelineStepView
        let desiredX: CGFloat
        var x: CGFloat
        var yOffset: CGFloat
        let radius: CGFloat
        let selected: Bool
    }

    init(
        steps: [WorkbenchRecordingTimelineStepView],
        selectedStepId: String?,
        durationMs: Int?,
        target: AnyObject?,
        action: Selector?
    ) {
        self.steps = steps
        self.selectedStepId = selectedStepId
        self.durationMs = max(durationMs ?? steps.compactMap(\.mediaTimeMs).max() ?? 1, 1)
        super.init(frame: .zero)
        self.target = target
        self.action = action
        wantsLayer = true
        toolTip = "点击时间点跳转步骤，也可以用方向键切换。"
        setAccessibilityRole(.group)
        setAccessibilityLabel("录制时间标记，可点击跳到对应步骤")
        setAccessibilityValue(accessibilityValueText())
    }

    required init?(coder: NSCoder) {
        nil
    }

    override var intrinsicContentSize: NSSize {
        NSSize(width: 360, height: 44)
    }

    var representedStepIds: [String] {
        steps.map(\.stepId)
    }

    override var acceptsFirstResponder: Bool {
        true
    }

    override func resetCursorRects() {
        super.resetCursorRects()
        addCursorRect(bounds, cursor: .pointingHand)
    }

    override func becomeFirstResponder() -> Bool {
        needsDisplay = true
        return true
    }

    override func resignFirstResponder() -> Bool {
        needsDisplay = true
        return true
    }

    override func mouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self)
        let location = convert(event.locationInWindow, from: nil)
        guard let step = nearestStep(to: location.x) else { return }
        select(step)
    }

    override func keyDown(with event: NSEvent) {
        switch event.keyCode {
        case 123:
            selectStep(offset: -1)
        case 124:
            selectStep(offset: 1)
        case 36, 49:
            if let selectedStep = selectedStep() ?? steps.first {
                select(selectedStep)
            }
        default:
            super.keyDown(with: event)
        }
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let rect = bounds.insetBy(dx: 14, dy: 8)
        let railY = rect.midY + 2
        drawRail(in: rect, railY: railY)
        drawMarkers(in: rect, railY: railY)
        drawEndLabels(in: rect, railY: railY)
        drawFocusRingIfNeeded(in: rect)
    }

    private func drawRail(in rect: NSRect, railY: CGFloat) {
        let rail = NSBezierPath()
        rail.move(to: CGPoint(x: rect.minX, y: railY))
        rail.line(to: CGPoint(x: rect.maxX, y: railY))
        WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.18).setStroke()
        rail.lineWidth = 3.0
        rail.lineCapStyle = .round
        rail.stroke()
    }

    private func drawMarkers(in rect: NSRect, railY: CGFloat) {
        let layouts = markerLayouts(in: rect, railY: railY)
        let drawOrder = layouts.filter { !$0.selected } + layouts.filter(\.selected)
        for layout in drawOrder {
            let dot = NSRect(
                x: layout.x - layout.radius,
                y: railY + layout.yOffset - layout.radius,
                width: layout.radius * 2,
                height: layout.radius * 2
            )
            (layout.selected ? WorkbenchDesignTokens.Color.tiffanyStrong : markerFill(for: layout.step))
                .withAlphaComponent(layout.selected ? 0.95 : 0.84)
                .setFill()
            NSBezierPath(ovalIn: dot).fill()
            NSColor.white.withAlphaComponent(layout.selected ? 0.96 : 0.72).setStroke()
            let outline = NSBezierPath(ovalIn: dot.insetBy(dx: -0.8, dy: -0.8))
            outline.lineWidth = layout.selected ? 1.4 : 0.9
            outline.stroke()
        }
    }

    private func markerLayouts(in rect: NSRect, railY: CGFloat) -> [MarkerLayout] {
        guard !steps.isEmpty, rect.width > 0 else { return [] }
        let availableSpacing = rect.width / CGFloat(max(steps.count - 1, 1))
        let minSpacing = min(8, max(3, availableSpacing))
        var layouts = steps.map { step in
            let time = CGFloat(max(0, min(step.mediaTimeMs ?? 0, durationMs)))
            let x = rect.minX + rect.width * (time / CGFloat(durationMs))
            let selected = step.stepId == selectedStepId
            return MarkerLayout(
                step: step,
                desiredX: x,
                x: x,
                yOffset: 0,
                radius: selected ? 6.2 : (step.needsReview ? 4.9 : 3.7),
                selected: selected
            )
        }
        .sorted { lhs, rhs in
            if lhs.desiredX == rhs.desiredX {
                return (lhs.step.sequenceIndex ?? 0) < (rhs.step.sequenceIndex ?? 0)
            }
            return lhs.desiredX < rhs.desiredX
        }
        for index in layouts.indices.dropFirst() where layouts[index].x - layouts[index - 1].x < minSpacing {
            layouts[index].x = layouts[index - 1].x + minSpacing
        }
        if let last = layouts.last, last.x > rect.maxX {
            let overflow = last.x - rect.maxX
            for index in layouts.indices {
                layouts[index].x -= overflow
            }
        }
        if layouts.count > 1 {
            for index in stride(from: layouts.count - 2, through: 0, by: -1)
            where layouts[index + 1].x - layouts[index].x < minSpacing {
                layouts[index].x = layouts[index + 1].x - minSpacing
            }
        }
        if let first = layouts.first, first.x < rect.minX {
            let underflow = rect.minX - first.x
            for index in layouts.indices {
                layouts[index].x += underflow
            }
        }
        let offsets: [CGFloat] = [-4, 0, 4]
        for index in layouts.indices {
            let previousClose = index > 0 && abs(layouts[index].desiredX - layouts[index - 1].desiredX) < minSpacing * 1.2
            let nextClose = index < layouts.count - 1 && abs(layouts[index + 1].desiredX - layouts[index].desiredX) < minSpacing * 1.2
            if previousClose || nextClose {
                layouts[index].yOffset = offsets[index % offsets.count]
            }
        }
        return layouts
    }

    private func drawEndLabels(in rect: NSRect, railY: CGFloat) {
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedDigitSystemFont(ofSize: 10.2, weight: .medium),
            .foregroundColor: WorkbenchDesignTokens.Color.muted,
        ]
        "00:00".draw(in: NSRect(x: rect.minX, y: railY - 23, width: 44, height: 14), withAttributes: attributes)
        let end = format(milliseconds: durationMs)
        let size = (end as NSString).size(withAttributes: attributes)
        end.draw(
            in: NSRect(x: rect.maxX - size.width, y: railY - 23, width: size.width + 1, height: 14),
            withAttributes: attributes
        )
    }

    private func markerFill(for step: WorkbenchRecordingTimelineStepView) -> NSColor {
        if step.needsReview {
            return WorkbenchDesignTokens.Color.warning
        }
        switch step.kind {
        case .action:
            return NSColor(calibratedRed: 0.20, green: 0.38, blue: 0.78, alpha: 1)
        case .control:
            return WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.88)
        case .keyframe:
            return WorkbenchDesignTokens.Color.tiffanyStrong
        case .warning:
            return WorkbenchDesignTokens.Color.warning
        case .unknown:
            return WorkbenchDesignTokens.Color.muted
        }
    }

    private func format(milliseconds: Int) -> String {
        let totalSeconds = max(0, milliseconds / 1000)
        let minutes = totalSeconds / 60
        let seconds = totalSeconds % 60
        return String(format: "%02d:%02d", minutes, seconds)
    }

    private func nearestStep(to x: CGFloat) -> WorkbenchRecordingTimelineStepView? {
        guard !steps.isEmpty else { return nil }
        let rect = bounds.insetBy(dx: 14, dy: 8)
        guard rect.width > 0 else { return steps.first }
        let clampedX = max(rect.minX, min(x, rect.maxX))
        let layouts = markerLayouts(in: rect, railY: rect.midY + 2)
        return layouts.min { lhs, rhs in
            abs(lhs.x - clampedX) < abs(rhs.x - clampedX)
        }
        .map(\.step)
    }

    private func select(_ step: WorkbenchRecordingTimelineStepView) {
        identifier = NSUserInterfaceItemIdentifier(step.stepId)
        sendAction(action, to: target)
    }

    private func selectStep(offset: Int) {
        guard !steps.isEmpty else { return }
        let currentIndex = selectedIndex() ?? 0
        let targetIndex = max(0, min(steps.count - 1, currentIndex + offset))
        select(steps[targetIndex])
    }

    private func selectedStep() -> WorkbenchRecordingTimelineStepView? {
        guard let selectedStepId else { return nil }
        return steps.first { $0.stepId == selectedStepId }
    }

    private func selectedIndex() -> Int? {
        guard let selectedStepId else { return nil }
        return steps.firstIndex { $0.stepId == selectedStepId }
    }

    private func accessibilityValueText() -> String {
        guard let index = selectedIndex() else {
            return "\(steps.count) 个时间点"
        }
        return "第 \(index + 1) 个，共 \(steps.count) 个"
    }

    private func drawFocusRingIfNeeded(in rect: NSRect) {
        guard window?.firstResponder === self else { return }
        NSColor.keyboardFocusIndicatorColor.withAlphaComponent(0.58).setStroke()
        let focus = NSBezierPath(roundedRect: rect.insetBy(dx: -4, dy: -3), xRadius: 9, yRadius: 9)
        focus.lineWidth = 1.1
        focus.stroke()
    }
}
