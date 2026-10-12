import AppKit

extension NSImage {
    func drawWorkbenchAspectFit(in rect: NSRect) {
        guard size.width > 0, size.height > 0, rect.width > 0, rect.height > 0 else { return }
        let scale = min(rect.width / size.width, rect.height / size.height)
        let drawSize = NSSize(width: size.width * scale, height: size.height * scale)
        let drawRect = NSRect(
            x: rect.midX - drawSize.width / 2,
            y: rect.midY - drawSize.height / 2,
            width: drawSize.width,
            height: drawSize.height
        )
        draw(in: drawRect, from: NSRect(origin: .zero, size: size), operation: .sourceOver, fraction: 1)
    }

    func drawAspectFill(in rect: NSRect) {
        guard size.width > 0, size.height > 0, rect.width > 0, rect.height > 0 else { return }
        let scale = max(rect.width / size.width, rect.height / size.height)
        let sourceSize = NSSize(width: rect.width / scale, height: rect.height / scale)
        let sourceRect = NSRect(
            x: (size.width - sourceSize.width) / 2,
            y: (size.height - sourceSize.height) / 2,
            width: sourceSize.width,
            height: sourceSize.height
        )
        draw(in: rect, from: sourceRect, operation: .sourceOver, fraction: 1)
    }

    func drawWorkbenchThumbnailPreview(in rect: NSRect) {
        guard size.width > 0, size.height > 0, rect.width > 0, rect.height > 0 else { return }
        let stage = rect.insetBy(dx: 4, dy: 4)
        let stagePath = NSBezierPath(roundedRect: stage, xRadius: 13, yRadius: 13)
        NSColor.white.withAlphaComponent(0.90).setFill()
        stagePath.fill()

        let scale = min(stage.width / size.width, stage.height / size.height)
        let drawSize = NSSize(width: floor(size.width * scale), height: floor(size.height * scale))
        let drawRect = NSRect(
            x: stage.midX - drawSize.width / 2,
            y: stage.midY - drawSize.height / 2,
            width: drawSize.width,
            height: drawSize.height
        )
        NSGraphicsContext.current?.imageInterpolation = .high
        draw(in: drawRect, from: NSRect(origin: .zero, size: size), operation: .copy, fraction: 1)
        WorkbenchDesignTokens.Color.neutralHairline.withAlphaComponent(0.24).setStroke()
        stagePath.lineWidth = 0.7
        stagePath.stroke()
    }
}
