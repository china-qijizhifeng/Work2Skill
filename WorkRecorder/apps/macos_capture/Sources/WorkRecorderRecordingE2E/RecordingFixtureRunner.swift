import Foundation
import ScreenCaptureKit

final class RecordingFixtureRunner {
    private let arguments: RunnerArguments

    init(arguments: RunnerArguments) {
        self.arguments = arguments
    }

    func run() async throws -> RecordingFixtureResult {
        let outputDirectory = arguments.outputDirectory
        let durationMilliseconds = arguments.durationMilliseconds
        try FileManager.default.createDirectory(at: outputDirectory, withIntermediateDirectories: true)
        let fixture = try await MainActor.run {
            try FixtureWindowHost(outputDirectory: outputDirectory)
        }
        defer {
            Task { @MainActor in
                fixture.close()
            }
        }
        try await Task.sleep(nanoseconds: 700_000_000)
        let shareableContent = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard
            let targetWindow = shareableContent.windows.first(where: {
                $0.title == fixture.targetTitle
                    && $0.owningApplication?.processID == ProcessInfo.processInfo.processIdentifier
            })
        else {
            throw FixtureError.targetWindowUnavailable(fixture.targetTitle)
        }
        let recorder = WindowRecordingSession(
            outputDirectory: outputDirectory,
            targetWindow: targetWindow,
            durationMilliseconds: durationMilliseconds
        )
        let recording = try await recorder.record()
        let fixtureMetadata = await MainActor.run {
            PreparedFixtureMetadata(
                targetTitle: fixture.targetTitle,
                sentinelTitle: fixture.sentinelTitle,
                targetContentSize: fixture.targetContentSize,
                sentinelContentSize: fixture.sentinelContentSize,
                sentinelWindowNumber: fixture.sentinelWindowNumber,
                sentinelFrame: fixture.sentinelFrame,
                sentinelOverlap: fixture.sentinelOcclusion,
                display: fixture.display
            )
        }
        return RecordingFixtureResult(
            status: .ok,
            recordingBackend: .screenCaptureKit,
            contentFilter: .desktopIndependentWindow,
            videoPath: recording.videoURL.path,
            startKeyframePath: recording.startFrameURL.path,
            finalKeyframePath: recording.finalFrameURL.path,
            requestedDurationMs: durationMilliseconds,
            durationMs: recording.durationMilliseconds,
            containerDurationMs: recording.containerDurationMilliseconds,
            frameCount: recording.frameCount,
            videoWidth: recording.videoWidth,
            videoHeight: recording.videoHeight,
            display: fixtureMetadata.display,
            targetWindow: WindowFixtureMetadata(
                title: fixtureMetadata.targetTitle,
                appName: ProcessInfo.processInfo.processName,
                bundleId: Bundle.main.bundleIdentifier ?? FixtureConstants.bundleIdentifier,
                processId: Int(ProcessInfo.processInfo.processIdentifier),
                windowId: "\(targetWindow.windowID)",
                frame: IntRect(targetWindow.frame),
                expectedContentWidth: fixtureMetadata.targetContentSize.width,
                expectedContentHeight: fixtureMetadata.targetContentSize.height
            ),
            sentinelWindow: WindowFixtureMetadata(
                title: fixtureMetadata.sentinelTitle,
                appName: ProcessInfo.processInfo.processName,
                bundleId: Bundle.main.bundleIdentifier ?? FixtureConstants.bundleIdentifier,
                processId: Int(ProcessInfo.processInfo.processIdentifier),
                windowId: fixtureMetadata.sentinelWindowNumber.map(String.init),
                frame: fixtureMetadata.sentinelFrame,
                expectedContentWidth: fixtureMetadata.sentinelContentSize.width,
                expectedContentHeight: fixtureMetadata.sentinelContentSize.height
            ),
            sentinelOcclusion: fixtureMetadata.sentinelOverlap,
            timing: RecordingTimingMetadata(
                startedMonotonicMs: recording.startedMonotonicMilliseconds,
                firstFrameMonotonicMs: recording.firstFrameMonotonicMilliseconds,
                finalFrameMonotonicMs: recording.finalFrameMonotonicMilliseconds,
                endedMonotonicMs: recording.endedMonotonicMilliseconds
            ),
            producerEvents: Self.fixtureProducerEvents(
                timing: recording,
                targetFrame: IntRect(targetWindow.frame)
            )
        )
    }

    private static func fixtureProducerEvents(
        timing: RecordingCaptureMetadata,
        targetFrame: IntRect
    ) -> [RecordingProducerEventFixture] {
        let base = timing.firstFrameMonotonicMilliseconds ?? timing.startedMonotonicMilliseconds
        let centerX = Double(targetFrame.x + targetFrame.width / 2)
        let centerY = Double(targetFrame.y + targetFrame.height / 2)
        return [
            RecordingProducerEventFixture(
                kind: "pointer_click",
                occurredAtMonotonicMs: base + 350,
                x: centerX,
                y: centerY,
                deltaX: nil,
                deltaY: nil,
                keyCode: nil,
                keyLabel: nil,
                modifiers: [],
                semantic: nil,
                typingEventCount: nil,
                typingCharacterCount: nil
            ),
            RecordingProducerEventFixture(
                kind: "scroll",
                occurredAtMonotonicMs: base + 700,
                x: nil,
                y: nil,
                deltaX: 0,
                deltaY: -42,
                keyCode: nil,
                keyLabel: nil,
                modifiers: [],
                semantic: nil,
                typingEventCount: nil,
                typingCharacterCount: nil
            ),
            RecordingProducerEventFixture(
                kind: "hotkey",
                occurredAtMonotonicMs: base + 1_000,
                x: nil,
                y: nil,
                deltaX: nil,
                deltaY: nil,
                keyCode: 40,
                keyLabel: "k",
                modifiers: ["command"],
                semantic: "open_command",
                typingEventCount: nil,
                typingCharacterCount: nil
            ),
            RecordingProducerEventFixture(
                kind: "typing_pause",
                occurredAtMonotonicMs: base + 1_350,
                x: nil,
                y: nil,
                deltaX: nil,
                deltaY: nil,
                keyCode: nil,
                keyLabel: nil,
                modifiers: [],
                semantic: nil,
                typingEventCount: 5,
                typingCharacterCount: 5
            ),
            RecordingProducerEventFixture(
                kind: "hotkey",
                occurredAtMonotonicMs: base + 1_650,
                x: nil,
                y: nil,
                deltaX: nil,
                deltaY: nil,
                keyCode: 36,
                keyLabel: "enter",
                modifiers: [],
                semantic: "submit",
                typingEventCount: nil,
                typingCharacterCount: nil
            ),
        ]
    }
}
