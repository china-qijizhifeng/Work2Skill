import AppKit

@MainActor
final class RecordingKeyframeStoryboardView: NSView {
    private let thumbnail: NSImage?
    private let title: String
    private let subtitle: String
    private let durationText: String?
    private let stepCount: Int

    init(
        thumbnail: NSImage?,
        title: String,
        subtitle: String,
        durationText: String?,
        stepCount: Int
    ) {
        self.thumbnail = thumbnail
        self.title = WorkRecorderLocalization.text(title)
        self.subtitle = WorkRecorderLocalization.text(subtitle)
        self.durationText = durationText
        self.stepCount = stepCount
        super.init(frame: .zero)
        wantsLayer = true
        layer?.cornerRadius = 22
        layer?.masksToBounds = true
        setAccessibilityRole(.group)
        setAccessibilityLabel("关键帧复盘")
    }

    required init?(coder: NSCoder) {
        nil
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let rect = bounds
        let path = NSBezierPath(roundedRect: rect, xRadius: 22, yRadius: 22)
        NSGraphicsContext.saveGraphicsState()
        path.addClip()
        NSGradient(colors: [
            NSColor(calibratedRed: 0.90, green: 0.985, blue: 0.990, alpha: 1),
            NSColor(calibratedRed: 1.00, green: 0.965, blue: 0.940, alpha: 1),
            NSColor(calibratedRed: 0.955, green: 0.985, blue: 0.968, alpha: 1),
        ])?.draw(in: rect, angle: 22)
        drawTopCopy(in: rect)
        if let thumbnail {
            drawThumbnailStage(thumbnail, in: rect)
        } else {
            drawStoryboardFrames(in: rect)
        }
        drawStatusPill(in: rect)
        NSGraphicsContext.restoreGraphicsState()
        WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.18).setStroke()
        path.lineWidth = 1
        path.stroke()
    }

    private func drawTopCopy(in rect: NSRect) {
        let titleAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 18, weight: .semibold),
            .foregroundColor: WorkbenchDesignTokens.Color.primaryText.withAlphaComponent(0.84),
        ]
        let subtitleAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 12, weight: .medium),
            .foregroundColor: WorkbenchDesignTokens.Color.secondaryText.withAlphaComponent(0.78),
        ]
        let titleRect = NSRect(x: rect.minX + 30, y: rect.maxY - 62, width: rect.width - 60, height: 24)
        title.draw(in: titleRect, withAttributes: titleAttrs)
        subtitle.draw(
            in: NSRect(x: titleRect.minX, y: titleRect.minY - 24, width: titleRect.width, height: 18),
            withAttributes: subtitleAttrs
        )
    }

    private func drawThumbnailStage(_ thumbnail: NSImage, in rect: NSRect) {
        let stage = rect.insetBy(dx: 30, dy: 94)
        let path = NSBezierPath(roundedRect: stage, xRadius: 18, yRadius: 18)
        NSColor.white.withAlphaComponent(0.82).setFill()
        path.fill()
        WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.20).setStroke()
        path.lineWidth = 0.9
        path.stroke()

        NSGraphicsContext.saveGraphicsState()
        path.addClip()
        thumbnail.drawWorkbenchAspectFit(in: stage.insetBy(dx: 10, dy: 10))
        NSGraphicsContext.restoreGraphicsState()

        drawStoryboardBadges(in: stage)
    }

    private func drawStoryboardBadges(in stage: NSRect) {
        let labels = ["开始帧", "关键帧", "结束帧"].map(WorkRecorderLocalization.text)
        let badgeWidth = min(94, max(70, (stage.width - 44) / 3))
        let startX = stage.minX + 14
        for (index, label) in labels.enumerated() {
            let badge = NSRect(
                x: startX + CGFloat(index) * (badgeWidth + 8),
                y: stage.minY + 14,
                width: badgeWidth,
                height: 25
            )
            let path = NSBezierPath(roundedRect: badge, xRadius: 12.5, yRadius: 12.5)
            NSColor.white.withAlphaComponent(index == 1 ? 0.86 : 0.70).setFill()
            path.fill()
            WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(index == 1 ? 0.34 : 0.18).setStroke()
            path.lineWidth = 0.7
            path.stroke()
            let attrs: [NSAttributedString.Key: Any] = [
                .font: NSFont.systemFont(ofSize: 10.5, weight: .semibold),
                .foregroundColor: WorkbenchDesignTokens.Color.primaryText.withAlphaComponent(0.76),
            ]
            let textWidth = (label as NSString).size(withAttributes: attrs).width
            label.draw(
                in: NSRect(x: badge.midX - textWidth / 2, y: badge.midY - 6.5, width: textWidth + 1, height: 14),
                withAttributes: attrs
            )
        }
    }

    private func drawStoryboardFrames(in rect: NSRect) {
        let frameWidth = min(210, max(144, (rect.width - 108) / 3))
        let frameHeight = min(118, frameWidth * 0.58)
        let totalWidth = frameWidth * 3 + 24
        let startX = rect.midX - totalWidth / 2
        let y = rect.midY - frameHeight / 2 - 8
        for index in 0..<3 {
            let frame = NSRect(x: startX + CGFloat(index) * (frameWidth + 12), y: y, width: frameWidth, height: frameHeight)
            drawStoryboardFrame(frame, index: index)
        }
    }

    private func drawStoryboardFrame(_ rect: NSRect, index: Int) {
        let path = NSBezierPath(roundedRect: rect, xRadius: 13, yRadius: 13)
        NSColor.white.withAlphaComponent(0.64).setFill()
        path.fill()
        WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(index == 1 ? 0.32 : 0.18).setStroke()
        path.lineWidth = index == 1 ? 1.2 : 0.8
        path.stroke()

        let rail = NSBezierPath()
        rail.move(to: CGPoint(x: rect.minX + 18, y: rect.midY + 4))
        rail.line(to: CGPoint(x: rect.maxX - 18, y: rect.midY + 4))
        WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.18).setStroke()
        rail.lineWidth = 1.6
        rail.stroke()
        let progress = NSBezierPath()
        progress.move(to: CGPoint(x: rect.minX + 18, y: rect.midY + 4))
        progress.line(to: CGPoint(x: rect.minX + 18 + (rect.width - 36) * CGFloat(index + 1) / 3.0, y: rect.midY + 4))
        WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.70).setStroke()
        progress.lineWidth = 2.0
        progress.stroke()

        let labelAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 11.5, weight: .semibold),
            .foregroundColor: WorkbenchDesignTokens.Color.primaryText.withAlphaComponent(0.74),
        ]
        ["开始", "关键帧", "结束"].map(WorkRecorderLocalization.text)[index].draw(
            in: NSRect(x: rect.minX + 16, y: rect.minY + 17, width: rect.width - 32, height: 16),
            withAttributes: labelAttrs
        )
    }

    private func drawStatusPill(in rect: NSRect) {
        let duration = durationText ?? "--:--"
        let text = WorkRecorderLocalization.text("视频不可用，已保留 \(stepCount) 个步骤 · \(duration)")
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 12.4, weight: .semibold),
            .foregroundColor: WorkbenchDesignTokens.Color.primaryText.withAlphaComponent(0.78),
        ]
        let textWidth = (text as NSString).size(withAttributes: attrs).width
        let pill = NSRect(x: rect.midX - (textWidth + 46) / 2, y: rect.minY + 44, width: textWidth + 46, height: 38)
        NSColor.white.withAlphaComponent(0.68).setFill()
        NSBezierPath(roundedRect: pill, xRadius: 19, yRadius: 19).fill()
        WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.22).setStroke()
        NSBezierPath(roundedRect: pill, xRadius: 19, yRadius: 19).stroke()
        text.draw(in: NSRect(x: pill.minX + 23, y: pill.midY - 8, width: textWidth + 2, height: 17), withAttributes: attrs)
    }
}
