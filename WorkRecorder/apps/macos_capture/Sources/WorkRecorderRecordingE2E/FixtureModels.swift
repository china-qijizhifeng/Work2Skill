import AppKit
import AVFoundation
import Foundation

enum FixtureConstants {
    static let targetTitlePrefix = "WorkRecorder Recording E2E Target"
    static let sentinelTitlePrefix = "WorkRecorder Recording E2E Sentinel"
    static let bundleIdentifier = "workrecorder.recording.e2e"
}

enum FixtureStatus: String, Codable {
    case ok
}

enum RecordingBackend: String, Codable {
    case screenCaptureKit = "ScreenCaptureKit"
}

enum RecordingContentFilter: String, Codable {
    case desktopIndependentWindow
}

struct RecordingFrameMetrics {
    let durationMilliseconds: Int
    let frameCount: Int
    let videoWidth: Int
    let videoHeight: Int
    let firstFrameMonotonicMilliseconds: Int?
    let finalFrameMonotonicMilliseconds: Int?
}

struct RecordingCaptureMetadata {
    let videoURL: URL
    let startFrameURL: URL
    let finalFrameURL: URL
    let durationMilliseconds: Int
    let containerDurationMilliseconds: Int
    let frameCount: Int
    let videoWidth: Int
    let videoHeight: Int
    let startedMonotonicMilliseconds: Int
    let firstFrameMonotonicMilliseconds: Int?
    let finalFrameMonotonicMilliseconds: Int?
    let endedMonotonicMilliseconds: Int
}

struct PreparedFixtureMetadata {
    let targetTitle: String
    let sentinelTitle: String
    let targetContentSize: SizeValue
    let sentinelContentSize: SizeValue
    let sentinelWindowNumber: Int?
    let sentinelFrame: IntRect
    let sentinelOverlap: SentinelOcclusionMetadata
    let display: DisplayFixtureMetadata
}

struct RecordingFixtureResult: Codable {
    let status: FixtureStatus
    let recordingBackend: RecordingBackend
    let contentFilter: RecordingContentFilter
    let videoPath: String
    let startKeyframePath: String
    let finalKeyframePath: String
    let requestedDurationMs: Int
    let durationMs: Int
    let containerDurationMs: Int
    let frameCount: Int
    let videoWidth: Int
    let videoHeight: Int
    let display: DisplayFixtureMetadata
    let targetWindow: WindowFixtureMetadata
    let sentinelWindow: WindowFixtureMetadata
    let sentinelOcclusion: SentinelOcclusionMetadata
    let timing: RecordingTimingMetadata
    let producerEvents: [RecordingProducerEventFixture]

    enum CodingKeys: String, CodingKey {
        case status
        case recordingBackend = "recording_backend"
        case contentFilter = "content_filter"
        case videoPath = "video_path"
        case startKeyframePath = "start_keyframe_path"
        case finalKeyframePath = "final_keyframe_path"
        case requestedDurationMs = "requested_duration_ms"
        case durationMs = "duration_ms"
        case containerDurationMs = "container_duration_ms"
        case frameCount = "frame_count"
        case videoWidth = "video_width"
        case videoHeight = "video_height"
        case display
        case targetWindow = "target_window"
        case sentinelWindow = "sentinel_window"
        case sentinelOcclusion = "sentinel_occlusion"
        case timing
        case producerEvents = "producer_events"
    }
}

struct RecordingProducerEventFixture: Codable {
    let kind: String
    let occurredAtMonotonicMs: Int
    let x: Double?
    let y: Double?
    let deltaX: Double?
    let deltaY: Double?
    let keyCode: Int?
    let keyLabel: String?
    let modifiers: [String]
    let semantic: String?
    let typingEventCount: Int?
    let typingCharacterCount: Int?

    enum CodingKeys: String, CodingKey {
        case kind
        case occurredAtMonotonicMs = "occurred_at_monotonic_ms"
        case x
        case y
        case deltaX = "delta_x"
        case deltaY = "delta_y"
        case keyCode = "key_code"
        case keyLabel = "key_label"
        case modifiers
        case semantic
        case typingEventCount = "typing_event_count"
        case typingCharacterCount = "typing_character_count"
    }
}

struct DisplayFixtureMetadata: Codable {
    let displayId: String
    let frame: IntRect
    let scaleFactor: Double

    enum CodingKeys: String, CodingKey {
        case displayId = "display_id"
        case frame
        case scaleFactor = "scale_factor"
    }
}

struct WindowFixtureMetadata: Codable {
    let title: String
    let appName: String
    let bundleId: String
    let processId: Int
    let windowId: String?
    let frame: IntRect
    let expectedContentWidth: Int
    let expectedContentHeight: Int

    enum CodingKeys: String, CodingKey {
        case title
        case appName = "app_name"
        case bundleId = "bundle_id"
        case processId = "process_id"
        case windowId = "window_id"
        case frame
        case expectedContentWidth = "expected_content_width"
        case expectedContentHeight = "expected_content_height"
    }
}

struct SentinelOcclusionMetadata: Codable {
    let overlapsTarget: Bool
    let overlapArea: Int
    let overlapFrame: IntRect?

    enum CodingKeys: String, CodingKey {
        case overlapsTarget = "overlaps_target"
        case overlapArea = "overlap_area"
        case overlapFrame = "overlap_frame"
    }
}

struct RecordingTimingMetadata: Codable {
    let startedMonotonicMs: Int
    let firstFrameMonotonicMs: Int?
    let finalFrameMonotonicMs: Int?
    let endedMonotonicMs: Int

    enum CodingKeys: String, CodingKey {
        case startedMonotonicMs = "started_monotonic_ms"
        case firstFrameMonotonicMs = "first_frame_monotonic_ms"
        case finalFrameMonotonicMs = "final_frame_monotonic_ms"
        case endedMonotonicMs = "ended_monotonic_ms"
    }
}

struct SizeValue: Codable {
    let width: Int
    let height: Int

    var cgSize: CGSize {
        CGSize(width: width, height: height)
    }
}

struct IntRect: Codable {
    let x: Int
    let y: Int
    let width: Int
    let height: Int
    let coordinateSpace: String

    init(_ rect: CGRect, coordinateSpace: String = "macos_global") {
        x = Int(rect.minX.rounded())
        y = Int(rect.minY.rounded())
        width = max(1, Int(rect.width.rounded()))
        height = max(1, Int(rect.height.rounded()))
        self.coordinateSpace = coordinateSpace
    }

    enum CodingKeys: String, CodingKey {
        case x
        case y
        case width
        case height
        case coordinateSpace = "coordinate_space"
    }
}

enum FixtureError: Error, CustomStringConvertible {
    case invalidArguments(String)
    case noMainScreen
    case targetWindowUnavailable(String)
    case noFramesWritten
    case writerTimedOut
    case writerFailed(String)
    case frameProcessingFailed(String)
    case pngWriteFailed(String)
    case assetDurationUnavailable(String)

    var description: String {
        switch self {
        case .invalidArguments(let message):
            return message
        case .noMainScreen:
            return "main screen is unavailable"
        case .targetWindowUnavailable(let title):
            return "target window not visible to ScreenCaptureKit: \(title)"
        case .noFramesWritten:
            return "ScreenCaptureKit produced no complete frames"
        case .writerTimedOut:
            return "AVAssetWriter did not finish within timeout"
        case .writerFailed(let message):
            return "AVAssetWriter failed: \(message)"
        case .frameProcessingFailed(let message):
            return "ScreenCaptureKit frame processing failed: \(message)"
        case .pngWriteFailed(let message):
            return "failed to write keyframe PNG: \(message)"
        case .assetDurationUnavailable(let message):
            return "failed to read MP4 container duration: \(message)"
        }
    }
}

func monotonicMilliseconds() -> Int {
    Int((ProcessInfo.processInfo.systemUptime * 1000).rounded())
}

func mp4ContainerDurationMilliseconds(videoURL: URL) async throws -> Int {
    let asset = AVURLAsset(url: videoURL)
    let duration = try await asset.load(.duration)
    let seconds = CMTimeGetSeconds(duration)
    guard seconds.isFinite, seconds > 0 else {
        throw FixtureError.assetDurationUnavailable("duration=\(seconds)")
    }
    return Int((seconds * 1000).rounded())
}
