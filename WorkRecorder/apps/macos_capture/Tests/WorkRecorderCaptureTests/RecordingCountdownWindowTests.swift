import AppKit
import Testing
@testable import WorkRecorderCapture

@MainActor
@Suite(.serialized)
struct RecordingCountdownWindowTests {
    @Test func countdownEscapeCancelsBeforeRecordingStarts() throws {
        let screen = try #require(NSScreen.main)
        var cancelled = false
        let window = RecordingCountdownWindow(
            anchor: screen.visibleFrame.insetBy(dx: 120, dy: 120),
            screen: screen,
            onCancel: { cancelled = true }
        )

        window.keyDown(
            with: try Self.keyEvent(
                keyCode: CaptureKeyCode.escape,
                characters: "\u{1b}",
                windowNumber: window.windowNumber
            )
        )

        #expect(cancelled)
    }

    private static func keyEvent(keyCode: UInt16, characters: String, windowNumber: Int) throws -> NSEvent {
        try #require(NSEvent.keyEvent(
            with: .keyDown,
            location: .zero,
            modifierFlags: [],
            timestamp: 0,
            windowNumber: windowNumber,
            context: nil,
            characters: characters,
            charactersIgnoringModifiers: characters,
            isARepeat: false,
            keyCode: keyCode
        ))
    }
}
