import AppKit
import WorkRecorderCaptureDesign

enum RecordingOverlayPlacementEdge {
    case above
    case below
    case left
    case right
    case bottomHud
}

struct RecordingOverlayPlacement {
    let frame: CGRect
    let edge: RecordingOverlayPlacementEdge
    let associationPoint: CGPoint
}

enum Geometry {
    @MainActor
    static func screenContainingMouse() -> NSScreen? {
        let mouseLocation = NSEvent.mouseLocation
        return NSScreen.screens.first { screen in
            NSPointInRect(mouseLocation, screen.frame)
        } ?? NSScreen.main ?? NSScreen.screens.first
    }

    @MainActor
    static func previewScreen(preference: String?) -> NSScreen? {
        let normalized = preference?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        switch normalized {
        case "mouse":
            return screenContainingMouse()
        case "key":
            return NSScreen.main ?? NSScreen.screens.first
        case "main", nil, "":
            return NSScreen.screens.first ?? NSScreen.main
        default:
            if let normalized, let index = Int(normalized), NSScreen.screens.indices.contains(index) {
                return NSScreen.screens[index]
            }
            return NSScreen.screens.first ?? NSScreen.main
        }
    }

    static func normalizedRect(from start: CGPoint, to end: CGPoint) -> CGRect {
        CGRect(
            x: min(start.x, end.x),
            y: min(start.y, end.y),
            width: abs(end.x - start.x),
            height: abs(end.y - start.y)
        )
    }

    @MainActor
    static func appKitScreenRect(for viewRect: CGRect, in window: NSWindow) -> CGRect {
        CGRect(
            x: window.frame.minX + viewRect.minX,
            y: window.frame.maxY - viewRect.maxY,
            width: viewRect.width,
            height: viewRect.height
        )
    }

    static func screencaptureRect(from appKitScreenRect: CGRect, on screen: NSScreen) -> CGRect {
        displayPixelRect(from: appKitScreenRect, on: screen)
    }

    static func displayPixelRect(from appKitScreenRect: CGRect, on screen: NSScreen) -> CGRect {
        displayPixelRect(
            from: appKitScreenRect,
            screenFrame: screen.frame,
            backingScaleFactor: screen.backingScaleFactor
        )
    }

    static func displayPixelRect(
        from appKitScreenRect: CGRect,
        screenFrame: CGRect,
        backingScaleFactor: CGFloat
    ) -> CGRect {
        let boundedRect = clippedScreenRect(appKitScreenRect, to: screenFrame)
        let localPointRect = CGRect(
            x: boundedRect.minX - screenFrame.minX,
            y: screenFrame.maxY - boundedRect.maxY,
            width: boundedRect.width,
            height: boundedRect.height
        )
        return CGRect(
            x: (localPointRect.minX * backingScaleFactor).rounded(.down),
            y: (localPointRect.minY * backingScaleFactor).rounded(.down),
            width: max(1, (localPointRect.width * backingScaleFactor).rounded()),
            height: max(1, (localPointRect.height * backingScaleFactor).rounded())
        )
    }

    private static func clippedScreenRect(_ rect: CGRect, to screenFrame: CGRect) -> CGRect {
        let clipped = rect.intersection(screenFrame)
        if !clipped.isNull, clipped.width > 0, clipped.height > 0 {
            return clipped
        }

        let maxX = max(screenFrame.minX, screenFrame.maxX - 1)
        let maxY = max(screenFrame.minY, screenFrame.maxY - 1)
        let x = min(max(rect.minX, screenFrame.minX), maxX)
        let y = min(max(rect.minY, screenFrame.minY), maxY)
        return CGRect(x: x, y: y, width: 1, height: 1)
    }

    static func intBox(from rect: CGRect, coordinateSpace: String) -> BoundingBox {
        BoundingBox(
            x: Int(rect.origin.x.rounded(.down)),
            y: Int(rect.origin.y.rounded(.down)),
            width: max(1, Int(rect.width.rounded())),
            height: max(1, Int(rect.height.rounded())),
            coordinateSpace: coordinateSpace
        )
    }

    static func overlayRect(for screenRect: CGRect, on screen: NSScreen) -> CGRect {
        overlayRect(for: screenRect, screenFrame: screen.frame)
    }

    static func overlayRect(for screenRect: CGRect, screenFrame: CGRect) -> CGRect {
        CGRect(
            x: screenRect.minX - screenFrame.minX,
            y: screenFrame.maxY - screenRect.maxY,
            width: screenRect.width,
            height: screenRect.height
        )
    }

    static func recordingOverlayFrame(anchor: CGRect, panelSize: CGSize, visibleFrame: CGRect) -> CGRect {
        recordingOverlayPlacement(anchor: anchor, panelSize: panelSize, visibleFrame: visibleFrame).frame
    }

    static func recordingOverlayPlacement(anchor: CGRect, panelSize: CGSize, visibleFrame: CGRect) -> RecordingOverlayPlacement {
        let margin: CGFloat = 12
        let bottomHud = CGRect(
            x: visibleFrame.midX - panelSize.width / 2,
            y: visibleFrame.minY + 14,
            width: panelSize.width,
            height: panelSize.height
        )
        if visibleFrame.width < HUDDesignTokens.Layout.compactBreakpoint || panelSize.width >= visibleFrame.width - 36 {
            let frame = clamp(bottomHud, inside: visibleFrame, margin: margin)
            return RecordingOverlayPlacement(
                frame: frame,
                edge: .bottomHud,
                associationPoint: CGPoint(x: frame.midX, y: frame.maxY)
            )
        }

        let candidates: [(edge: RecordingOverlayPlacementEdge, frame: CGRect)] = [
            (.below, CGRect(x: anchor.minX, y: anchor.minY - panelSize.height - margin, width: panelSize.width, height: panelSize.height)),
            (.above, CGRect(x: anchor.minX, y: anchor.maxY + margin, width: panelSize.width, height: panelSize.height)),
            (.right, CGRect(x: anchor.maxX + margin, y: anchor.midY - panelSize.height / 2, width: panelSize.width, height: panelSize.height)),
            (.left, CGRect(x: anchor.minX - panelSize.width - margin, y: anchor.midY - panelSize.height / 2, width: panelSize.width, height: panelSize.height)),
            (.bottomHud, bottomHud),
        ]

        let scored = candidates.enumerated().map { index, candidate -> (RecordingOverlayPlacement, CGFloat) in
            let clamped = clamp(candidate.frame, inside: visibleFrame, margin: margin)
            let overlap = clamped.intersection(anchor)
            let overlapPenalty = overlap.isNull ? 0 : overlap.width * overlap.height * 18
            let distance = hypot(clamped.midX - anchor.midX, clamped.midY - anchor.midY)
            let displacement = hypot(clamped.midX - candidate.frame.midX, clamped.midY - candidate.frame.midY)
            let orderBias = CGFloat(index) * 18
            let placement = RecordingOverlayPlacement(
                frame: clamped,
                edge: candidate.edge,
                associationPoint: associationPoint(for: candidate.edge, anchor: anchor, frame: clamped)
            )
            return (placement, overlapPenalty + distance + displacement * 1.8 + orderBias)
        }
        if let best = scored.min(by: { $0.1 < $1.1 })?.0 {
            return best
        }
        let frame = clamp(bottomHud, inside: visibleFrame, margin: margin)
        return RecordingOverlayPlacement(
            frame: frame,
            edge: .bottomHud,
            associationPoint: CGPoint(x: frame.midX, y: frame.maxY)
        )
    }

    private static func clamp(_ rect: CGRect, inside visibleFrame: CGRect, margin: CGFloat) -> CGRect {
        let maxX = max(visibleFrame.minX + margin, visibleFrame.maxX - rect.width - margin)
        let maxY = max(visibleFrame.minY + margin, visibleFrame.maxY - rect.height - margin)
        return CGRect(
            x: min(max(rect.minX, visibleFrame.minX + margin), maxX),
            y: min(max(rect.minY, visibleFrame.minY + margin), maxY),
            width: rect.width,
            height: rect.height
        )
    }

    private static func associationPoint(for edge: RecordingOverlayPlacementEdge, anchor: CGRect, frame: CGRect) -> CGPoint {
        switch edge {
        case .below:
            return CGPoint(x: min(max(anchor.midX, frame.minX), frame.maxX), y: frame.maxY)
        case .above:
            return CGPoint(x: min(max(anchor.midX, frame.minX), frame.maxX), y: frame.minY)
        case .right:
            return CGPoint(x: frame.minX, y: min(max(anchor.midY, frame.minY), frame.maxY))
        case .left:
            return CGPoint(x: frame.maxX, y: min(max(anchor.midY, frame.minY), frame.maxY))
        case .bottomHud:
            return CGPoint(x: frame.midX, y: frame.maxY)
        }
    }
}
