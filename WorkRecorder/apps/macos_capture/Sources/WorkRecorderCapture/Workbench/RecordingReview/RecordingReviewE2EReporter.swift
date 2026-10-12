import AppKit
import Foundation

enum RecordingReviewE2EReporter {
    private static let reportPathKey = "WORKRECORDER_E2E_RECORDING_LARGE_REVIEW_REPORT"

    @MainActor
    static func writeReportIfRequested(
        request: RecordingReviewOpenRequest,
        recording: WorkbenchActiveCaptureInspectView,
        window: NSWindow?,
        playbackSession: RecordingPlaybackSession
    ) -> Bool {
        guard let rawPath = ProcessInfo.processInfo.environment[reportPathKey],
              !rawPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        else { return false }
        let reportURL = URL(fileURLWithPath: rawPath)
        let playbackFileExists = FileManager.default.fileExists(atPath: playbackSession.fileURL.path)
        let playbackByteSize = (try? FileManager.default
            .attributesOfItem(atPath: playbackSession.fileURL.path)[.size] as? NSNumber)?.intValue
        let payload = RecordingReviewE2EReport(
            generatedAt: Date(),
            eventId: request.inspect.eventId,
            sessionId: recording.sessionId,
            recordingTitle: request.inspect.source.title.isEmpty ? "录制复盘" : request.inspect.source.title,
            videoArtifactId: recording.videoRef?.artifactId,
            videoState: recording.videoRef?.state.e2eValue,
            durationMs: recording.timeline?.durationMs,
            stepCount: recording.timeline?.steps.count ?? 0,
            selectedStepId: request.selectedStepId,
            windowVisible: window?.isVisible == true,
            windowFrame: window.map { RecordingReviewE2EWindowFrame($0.frame) },
            playbackPurpose: "workbench_large_recording_review",
            playbackLoaded: true,
            playbackFileExists: playbackFileExists,
            playbackByteSize: playbackByteSize,
            playbackFileName: playbackSession.fileURL.lastPathComponent
        )
        do {
            try FileManager.default.createDirectory(
                at: reportURL.deletingLastPathComponent(),
                withIntermediateDirectories: true
            )
            let encoder = JSONEncoder()
            encoder.dateEncodingStrategy = .iso8601
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try encoder.encode(payload).write(to: reportURL, options: .atomic)
            return true
        } catch {
            NSLog("WorkRecorder E2E large review report failed: \(error.localizedDescription)")
            return false
        }
    }
}

private extension WorkbenchRecordingVideoState {
    var e2eValue: String {
        switch self {
        case .notRecorded:
            return "not_recorded"
        case .recording:
            return "recording"
        case .staged:
            return "staged"
        case .available:
            return "available"
        case .failed:
            return "failed"
        case .deleted:
            return "deleted"
        case .unknown(let value):
            return value
        }
    }
}

private struct RecordingReviewE2EReport: Encodable {
    let generatedAt: Date
    let eventId: String
    let sessionId: String
    let recordingTitle: String
    let videoArtifactId: String?
    let videoState: String?
    let durationMs: Int?
    let stepCount: Int
    let selectedStepId: String?
    let windowVisible: Bool
    let windowFrame: RecordingReviewE2EWindowFrame?
    let playbackPurpose: String
    let playbackLoaded: Bool
    let playbackFileExists: Bool
    let playbackByteSize: Int?
    let playbackFileName: String

    enum CodingKeys: String, CodingKey {
        case generatedAt = "generated_at"
        case eventId = "event_id"
        case sessionId = "session_id"
        case recordingTitle = "recording_title"
        case videoArtifactId = "video_artifact_id"
        case videoState = "video_state"
        case durationMs = "duration_ms"
        case stepCount = "step_count"
        case selectedStepId = "selected_step_id"
        case windowVisible = "window_visible"
        case windowFrame = "window_frame"
        case playbackPurpose = "playback_purpose"
        case playbackLoaded = "playback_loaded"
        case playbackFileExists = "playback_file_exists"
        case playbackByteSize = "playback_byte_size"
        case playbackFileName = "playback_file_name"
    }
}

private struct RecordingReviewE2EWindowFrame: Encodable {
    let x: Double
    let y: Double
    let width: Double
    let height: Double

    init(_ frame: NSRect) {
        x = frame.origin.x
        y = frame.origin.y
        width = frame.size.width
        height = frame.size.height
    }
}
