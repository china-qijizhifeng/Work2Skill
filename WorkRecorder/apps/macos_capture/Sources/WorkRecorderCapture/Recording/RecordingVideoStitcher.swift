@preconcurrency import AVFoundation
import Foundation

enum RecordingVideoStitchingError: LocalizedError {
    case noSegments
    case noVideoTrack(URL)
    case exportUnavailable
    case exportFailed(String)

    var errorDescription: String? {
        switch self {
        case .noSegments:
            return "没有可合成的录制片段。"
        case .noVideoTrack(let url):
            return "录制片段缺少视频轨道：\(url.lastPathComponent)"
        case .exportUnavailable:
            return "当前系统暂时无法合成多段录制视频。"
        case .exportFailed(let message):
            return "多段录制视频合成失败：\(message)"
        }
    }
}

struct RecordingVideoStitchingResult {
    let videoURL: URL
    let durationMilliseconds: Int
    let segmentCount: Int
}

final class RecordingVideoStitcher: @unchecked Sendable {
    func stitchedVideoIfNeeded(
        segments: [RecordingSegmentCaptureResult],
        outputDirectory: URL,
        sessionId: String
    ) async throws -> RecordingVideoStitchingResult? {
        let orderedSegments = segments.sorted { lhs, rhs in
            lhs.startedMonotonicMilliseconds < rhs.startedMonotonicMilliseconds
        }
        guard orderedSegments.count > 1 else { return nil }
        guard !orderedSegments.isEmpty else { throw RecordingVideoStitchingError.noSegments }

        try FileManager.default.createDirectory(at: outputDirectory, withIntermediateDirectories: true)
        let outputURL = outputDirectory.appendingPathComponent("recording-\(sessionId)-stitched-\(UUID().uuidString).mp4")
        let composition = AVMutableComposition()
        guard let compositionVideo = composition.addMutableTrack(
            withMediaType: .video,
            preferredTrackID: kCMPersistentTrackID_Invalid
        ) else {
            throw RecordingVideoStitchingError.exportUnavailable
        }

        var cursor = CMTime.zero
        for segment in orderedSegments {
            let asset = AVURLAsset(url: segment.videoURL)
            let videoTracks = try await asset.loadTracks(withMediaType: .video)
            guard let sourceVideo = videoTracks.first else {
                throw RecordingVideoStitchingError.noVideoTrack(segment.videoURL)
            }
            let duration = try await asset.load(.duration)
            try compositionVideo.insertTimeRange(
                CMTimeRange(start: .zero, duration: duration),
                of: sourceVideo,
                at: cursor
            )
            cursor = CMTimeAdd(cursor, duration)
        }

        guard let exporter = AVAssetExportSession(asset: composition, presetName: AVAssetExportPresetHighestQuality) else {
            throw RecordingVideoStitchingError.exportUnavailable
        }
        exporter.outputURL = outputURL
        exporter.outputFileType = .mp4
        exporter.shouldOptimizeForNetworkUse = false
        try await export(exporter)
        return RecordingVideoStitchingResult(
            videoURL: outputURL,
            durationMilliseconds: Int((CMTimeGetSeconds(cursor) * 1000).rounded()),
            segmentCount: orderedSegments.count
        )
    }

    private func export(_ exporter: AVAssetExportSession) async throws {
        let box = RecordingVideoExportSessionBox(exporter)
        try await withCheckedThrowingContinuation { continuation in
            box.exporter.exportAsynchronously {
                let exporter = box.exporter
                switch exporter.status {
                case .completed:
                    continuation.resume()
                case .cancelled:
                    continuation.resume(throwing: CancellationError())
                case .failed:
                    continuation.resume(
                        throwing: RecordingVideoStitchingError.exportFailed(
                            exporter.error?.localizedDescription ?? "unknown export failure"
                        )
                    )
                default:
                    continuation.resume(
                        throwing: RecordingVideoStitchingError.exportFailed("unexpected export status \(exporter.status.rawValue)")
                    )
                }
            }
        }
    }
}

private final class RecordingVideoExportSessionBox: @unchecked Sendable {
    let exporter: AVAssetExportSession

    init(_ exporter: AVAssetExportSession) {
        self.exporter = exporter
    }
}
