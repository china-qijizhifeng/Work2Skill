import AppKit
import Foundation

struct RecordingReviewCommit {
    let eventId: String
    let sessionId: String
    let selectedStepId: String?
    let currentMediaTimeMs: Int?
}

struct RecordingReviewOpenRequest {
    let inspect: WorkbenchEventInspectView
    let thumbnail: NSImage?
    let selectedStepId: String?
    let currentMediaTimeMs: Int?
    let sourceWindowFrame: NSRect?
    let sourceScreenVisibleFrame: NSRect?
    let onCommit: @MainActor (RecordingReviewCommit) -> Void

    var recording: WorkbenchActiveCaptureInspectView? {
        inspect.activeCapture
    }

    init(
        inspect: WorkbenchEventInspectView,
        thumbnail: NSImage?,
        selectedStepId: String?,
        currentMediaTimeMs: Int?,
        sourceWindowFrame: NSRect? = nil,
        sourceScreenVisibleFrame: NSRect? = nil,
        onCommit: @escaping @MainActor (RecordingReviewCommit) -> Void
    ) {
        self.inspect = inspect
        self.thumbnail = thumbnail
        self.selectedStepId = selectedStepId
        self.currentMediaTimeMs = currentMediaTimeMs
        self.sourceWindowFrame = sourceWindowFrame
        self.sourceScreenVisibleFrame = sourceScreenVisibleFrame
        self.onCommit = onCommit
    }
}

struct RecordingReviewState {
    var selectedStepId: String?
    var currentMediaTimeMs: Int?
    var selectionMode: RecordingReviewSelectionMode
    var timelineFilter: RecordingReviewTimelineFilter
    var showsAllKeyframes: Bool
    var showsMaterialsPanel: Bool
    var playbackRate: Float

    static func initial(selectedStepId: String?, currentMediaTimeMs: Int?) -> RecordingReviewState {
        RecordingReviewState(
            selectedStepId: selectedStepId,
            currentMediaTimeMs: currentMediaTimeMs,
            selectionMode: .follow,
            timelineFilter: .all,
            showsAllKeyframes: false,
            showsMaterialsPanel: false,
            playbackRate: 1.0
        )
    }
}

enum RecordingReviewWindowPlacementPolicy {
    private static let screenMargin: CGFloat = 18

    static func preferredFrame(
        defaultSize: NSSize,
        minSize: NSSize,
        sourceWindowFrame: NSRect?,
        sourceScreenVisibleFrame: NSRect?
    ) -> NSRect {
        let visibleFrame = sourceScreenVisibleFrame ?? NSScreen.main?.visibleFrame ?? NSRect(origin: .zero, size: defaultSize)
        let availableWidth = max(1, visibleFrame.width - screenMargin * 2)
        let availableHeight = max(1, visibleFrame.height - screenMargin * 2)
        let width = min(defaultSize.width, max(minSize.width, availableWidth))
        let height = min(defaultSize.height, max(minSize.height, availableHeight))
        let size = NSSize(width: width, height: height)
        let anchor = sourceWindowFrame ?? visibleFrame
        let proposedOrigin = NSPoint(
            x: anchor.midX - size.width / 2,
            y: anchor.midY - size.height / 2
        )
        return NSRect(
            origin: clampedOrigin(proposedOrigin, size: size, visibleFrame: visibleFrame),
            size: size
        )
    }

    private static func clampedOrigin(_ origin: NSPoint, size: NSSize, visibleFrame: NSRect) -> NSPoint {
        let minX = visibleFrame.minX + screenMargin
        let maxX = max(minX, visibleFrame.maxX - size.width - screenMargin)
        let minY = visibleFrame.minY + screenMargin
        let maxY = max(minY, visibleFrame.maxY - size.height - screenMargin)
        return NSPoint(
            x: min(max(origin.x, minX), maxX),
            y: min(max(origin.y, minY), maxY)
        )
    }
}
