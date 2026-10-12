import AppKit

final class RecordingReviewContentWindow: NSWindow {
    var onEscape: (() -> Void)?
    var onTogglePlayback: (() -> Void)?
    var onMoveStep: ((Int) -> Void)?
    var onSeekRelative: ((Int) -> Void)?

    override func sendEvent(_ event: NSEvent) {
        if event.type == .keyDown, handleReviewKey(event) {
            return
        }
        super.sendEvent(event)
    }

    override func keyDown(with event: NSEvent) {
        if handleReviewKey(event) {
            return
        }
        super.keyDown(with: event)
    }

    @discardableResult
    private func handleReviewKey(_ event: NSEvent) -> Bool {
        if event.keyCode == 53 {
            onEscape?()
            return true
        }
        if event.keyCode == 49 {
            onTogglePlayback?()
            return true
        }
        if event.keyCode == 123 {
            if event.modifierFlags.contains(.shift) {
                onSeekRelative?(-5_000)
            } else {
                onMoveStep?(-1)
            }
            return true
        }
        if event.keyCode == 124 {
            if event.modifierFlags.contains(.shift) {
                onSeekRelative?(5_000)
            } else {
                onMoveStep?(1)
            }
            return true
        }
        return false
    }

    override func cancelOperation(_ sender: Any?) {
        onEscape?()
    }
}
