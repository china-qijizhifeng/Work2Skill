import AppKit
import Foundation

@MainActor
final class FixtureWindowHost {
    let targetTitle: String
    let sentinelTitle: String
    let targetContentSize = SizeValue(width: 520, height: 320)
    let sentinelContentSize = SizeValue(width: 180, height: 180)
    let display: DisplayFixtureMetadata

    private let targetWindow: NSWindow
    private let sentinelWindow: NSWindow

    init(outputDirectory: URL) throws {
        _ = outputDirectory
        guard let screen = NSScreen.main else {
            throw FixtureError.noMainScreen
        }
        NSApplication.shared.setActivationPolicy(.regular)
        let runId = UUID().uuidString
        targetTitle = "\(FixtureConstants.targetTitlePrefix) \(runId)"
        sentinelTitle = "\(FixtureConstants.sentinelTitlePrefix) \(runId)"

        let visibleFrame = screen.visibleFrame
        let targetFrame = CGRect(
            x: visibleFrame.minX + 80,
            y: visibleFrame.midY - 190,
            width: CGFloat(targetContentSize.width),
            height: CGFloat(targetContentSize.height + 28)
        )
        let sentinelFrame = CGRect(
            x: targetFrame.minX + targetFrame.width - CGFloat(sentinelContentSize.width) - 44,
            y: targetFrame.minY + 96,
            width: CGFloat(sentinelContentSize.width),
            height: CGFloat(sentinelContentSize.height + 28)
        )

        targetWindow = NSWindow(contentRect: targetFrame, styleMask: [.titled], backing: .buffered, defer: false)
        targetWindow.title = targetTitle
        targetWindow.contentView = AnimatedTargetView(frame: CGRect(origin: .zero, size: targetContentSize.cgSize))
        targetWindow.isReleasedWhenClosed = false
        targetWindow.level = .normal
        targetWindow.backgroundColor = .black
        targetWindow.setContentSize(targetContentSize.cgSize)
        targetWindow.setFrameOrigin(targetFrame.origin)

        sentinelWindow = NSWindow(contentRect: sentinelFrame, styleMask: [.titled], backing: .buffered, defer: false)
        sentinelWindow.title = sentinelTitle
        sentinelWindow.contentView = SentinelView(frame: CGRect(origin: .zero, size: sentinelContentSize.cgSize))
        sentinelWindow.isReleasedWhenClosed = false
        sentinelWindow.level = .floating
        sentinelWindow.setContentSize(sentinelContentSize.cgSize)
        sentinelWindow.setFrameOrigin(sentinelFrame.origin)

        targetWindow.orderFrontRegardless()
        targetWindow.makeKeyAndOrderFront(nil)
        sentinelWindow.orderFrontRegardless()
        NSApplication.shared.activate(ignoringOtherApps: true)

        display = DisplayFixtureMetadata(
            displayId: Self.displayId(for: screen),
            frame: IntRect(screen.frame),
            scaleFactor: Double(screen.backingScaleFactor)
        )
    }

    var sentinelWindowNumber: Int? {
        sentinelWindow.windowNumber
    }

    var sentinelFrame: IntRect {
        IntRect(sentinelWindow.frame)
    }

    var sentinelOcclusion: SentinelOcclusionMetadata {
        let intersection = targetWindow.frame.intersection(sentinelWindow.frame)
        let overlaps = !intersection.isNull && intersection.width > 0 && intersection.height > 0
        return SentinelOcclusionMetadata(
            overlapsTarget: overlaps,
            overlapArea: overlaps ? Int((intersection.width * intersection.height).rounded()) : 0,
            overlapFrame: overlaps ? IntRect(intersection) : nil
        )
    }

    func close() {
        targetWindow.close()
        sentinelWindow.close()
    }

    private static func displayId(for screen: NSScreen) -> String {
        if let screenNumber = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber {
            return String(screenNumber.uint32Value)
        }
        return "main"
    }
}

private final class AnimatedTargetView: NSView {
    private var displayLink: Timer?
    private var phase: CGFloat = 0

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        displayLink = Timer.scheduledTimer(withTimeInterval: 1.0 / 24.0, repeats: true) { [weak self] _ in
            Task { @MainActor in
                guard let self else { return }
                self.phase = (self.phase + 0.035).truncatingRemainder(dividingBy: 1)
                self.needsDisplay = true
            }
        }
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override var isFlipped: Bool { true }

    override func draw(_ dirtyRect: NSRect) {
        NSColor(calibratedRed: 0.02, green: 0.06, blue: 0.13, alpha: 1).setFill()
        bounds.fill()
        NSColor(calibratedRed: 0.0, green: 0.86, blue: 0.92, alpha: 1).setStroke()
        let border = bounds.insetBy(dx: 8, dy: 8)
        let borderPath = NSBezierPath(roundedRect: border, xRadius: 12, yRadius: 12)
        borderPath.lineWidth = 6
        borderPath.stroke()

        NSColor(calibratedRed: 0.1, green: 0.23, blue: 0.34, alpha: 1).setFill()
        NSBezierPath(roundedRect: CGRect(x: 34, y: 54, width: bounds.width - 68, height: 82), xRadius: 10, yRadius: 10)
            .fill()

        let movingX = 54 + (bounds.width - 168) * phase
        NSColor(calibratedRed: 1.0, green: 0.82, blue: 0.14, alpha: 1).setFill()
        NSBezierPath(roundedRect: CGRect(x: movingX, y: 178, width: 96, height: 54), xRadius: 8, yRadius: 8).fill()

        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedSystemFont(ofSize: 28, weight: .bold),
            .foregroundColor: NSColor.white,
        ]
        "WORKRECORDER WINDOW ONLY TARGET".draw(at: CGPoint(x: 52, y: 80), withAttributes: attributes)
    }
}

private final class SentinelView: NSView {
    override var isFlipped: Bool { true }

    override func draw(_ dirtyRect: NSRect) {
        NSColor(calibratedRed: 1.0, green: 0.0, blue: 1.0, alpha: 1).setFill()
        bounds.fill()
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.monospacedSystemFont(ofSize: 22, weight: .bold),
            .foregroundColor: NSColor.black,
        ]
        "SENTINEL".draw(at: CGPoint(x: 24, y: 70), withAttributes: attributes)
    }
}
