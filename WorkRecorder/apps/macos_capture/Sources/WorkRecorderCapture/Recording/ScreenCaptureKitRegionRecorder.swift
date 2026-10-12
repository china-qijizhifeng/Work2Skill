import AppKit
@preconcurrency import AVFoundation
import Foundation
@preconcurrency import ScreenCaptureKit

@MainActor
final class ScreenCaptureKitRegionRecorder: @unchecked Sendable {
    func startSegment(
        segmentId: String,
        target: RegionRecordingTarget
    ) async throws -> ScreenCaptureKitRegionRecordingSegment {
        try FileManager.default.createDirectory(at: target.outputDirectory, withIntermediateDirectories: true)
        let content: SCShareableContent
        do {
            content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        } catch {
            throw RegionRecordingFailure.screenCapturePermissionDenied(error.localizedDescription)
        }
        guard let displayId = target.selection.screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber,
              let display = content.displays.first(where: { $0.displayID == CGDirectDisplayID(displayId.uint32Value) })
        else {
            throw RegionRecordingFailure.displayUnavailable
        }

        let excludedApplications = content.applications.filter { application in
            application.processID == ProcessInfo.processInfo.processIdentifier
        }
        let logicalRect = Self.displayLogicalRect(
            from: target.selection.screenRect,
            screen: target.selection.screen
        )
        let scale = target.selection.screen.backingScaleFactor
        let configuration = SCStreamConfiguration()
        configuration.width = max(64, Int((logicalRect.width * scale).rounded()))
        configuration.height = max(64, Int((logicalRect.height * scale).rounded()))
        configuration.sourceRect = logicalRect
        configuration.minimumFrameInterval = CMTime(value: 1, timescale: 24)
        configuration.queueDepth = 8
        configuration.showsCursor = true
        configuration.pixelFormat = kCVPixelFormatType_32BGRA

        let videoURL = target.outputDirectory.appendingPathComponent("recording-\(segmentId).mp4")
        let startFrameURL = target.outputDirectory.appendingPathComponent("recording-\(segmentId)-start.png")
        let finalFrameURL = target.outputDirectory.appendingPathComponent("recording-\(segmentId)-final.png")
        let sink = RegionRecordingFrameSink(
            videoURL: videoURL,
            startFrameURL: startFrameURL,
            finalFrameURL: finalFrameURL
        )
        let stream = SCStream(
            filter: SCContentFilter(display: display, excludingApplications: excludedApplications, exceptingWindows: []),
            configuration: configuration,
            delegate: nil
        )
        let queue = DispatchQueue(label: "workrecorder.recording.region.frames", qos: .userInitiated)
        try stream.addStreamOutput(sink, type: .screen, sampleHandlerQueue: queue)
        let started = monotonicMilliseconds()
        try await stream.startCapture()
        return ScreenCaptureKitRegionRecordingSegment(
            segmentId: segmentId,
            stream: stream,
            sink: sink,
            startedMonotonicMilliseconds: started
        )
    }

    private static func displayLogicalRect(from appKitScreenRect: CGRect, screen: NSScreen) -> CGRect {
        let clipped = appKitScreenRect.intersection(screen.frame)
        let bounded = clipped.isNull ? CGRect(x: screen.frame.minX, y: screen.frame.minY, width: 1, height: 1) : clipped
        return CGRect(
            x: bounded.minX - screen.frame.minX,
            y: screen.frame.maxY - bounded.maxY,
            width: max(1, bounded.width),
            height: max(1, bounded.height)
        )
    }
}

final class ScreenCaptureKitRegionRecordingSegment: @unchecked Sendable {
    let segmentId: String
    private let stream: SCStream
    private let sink: RegionRecordingFrameSink
    private let startedMonotonicMilliseconds: Int
    private var stopped = false

    fileprivate init(
        segmentId: String,
        stream: SCStream,
        sink: RegionRecordingFrameSink,
        startedMonotonicMilliseconds: Int
    ) {
        self.segmentId = segmentId
        self.stream = stream
        self.sink = sink
        self.startedMonotonicMilliseconds = startedMonotonicMilliseconds
    }

    func stop(closeReason: ActiveCaptureRecordingSegmentCloseReason = .stopped) async throws -> RecordingSegmentCaptureResult {
        guard !stopped else {
            return try await sink.finishedResult(
                segmentId: segmentId,
                startedMonotonicMilliseconds: startedMonotonicMilliseconds,
                endedMonotonicMilliseconds: monotonicMilliseconds(),
                closeReason: closeReason
            )
        }
        try await stream.stopCapture()
        stopped = true
        let ended = monotonicMilliseconds()
        return try await sink.finishedResult(
            segmentId: segmentId,
            startedMonotonicMilliseconds: startedMonotonicMilliseconds,
            endedMonotonicMilliseconds: ended,
            closeReason: closeReason
        )
    }
}

private struct RegionRecordingFrameMetrics {
    let durationMilliseconds: Int
    let frameCount: Int
    let videoWidth: Int
    let videoHeight: Int
    let firstFrameMonotonicMilliseconds: Int?
    let firstFrameWallTimeEpochMilliseconds: Int?
    let finalFrameMonotonicMilliseconds: Int?
}

private struct RegionRecordingFinishSnapshot {
    let writer: AVAssetWriter
    let durationMilliseconds: Int
    let frameCount: Int
    let videoWidth: Int
    let videoHeight: Int
    let firstFrameMonotonicMilliseconds: Int?
    let firstFrameWallTimeEpochMilliseconds: Int?
    let finalFrameMonotonicMilliseconds: Int?
}

private final class RegionRecordingFinishContinuation: @unchecked Sendable {
    private let lock = NSLock()
    private var continuation: CheckedContinuation<Void, Error>?

    init(_ continuation: CheckedContinuation<Void, Error>) {
        self.continuation = continuation
    }

    func resume(returning result: Result<Void, Error>) {
        lock.lock()
        let continuation = continuation
        self.continuation = nil
        lock.unlock()
        guard let continuation else { return }
        switch result {
        case .success:
            continuation.resume()
        case .failure(let error):
            continuation.resume(throwing: error)
        }
    }
}

private final class RegionRecordingWriterBox: @unchecked Sendable {
    private let writer: AVAssetWriter

    init(_ writer: AVAssetWriter) {
        self.writer = writer
    }

    func resultAfterFinishCallback() -> Result<Void, Error> {
        guard writer.status == .completed else {
            return .failure(
                writer.error.map { RegionRecordingFailure.writerFailed($0.localizedDescription) }
                    ?? RegionRecordingFailure.writerFailed("\(writer.status.rawValue)")
            )
        }
        return .success(())
    }

    func cancelIfStillWriting() {
        if writer.status == .writing {
            writer.cancelWriting()
        }
    }
}

private final class RegionRecordingFrameSink: NSObject, SCStreamOutput, @unchecked Sendable {
    private let videoURL: URL
    private let startFrameURL: URL
    private let finalFrameURL: URL
    private let lock = NSLock()
    private var writer: AVAssetWriter?
    private var writerInput: AVAssetWriterInput?
    private var adaptor: AVAssetWriterInputPixelBufferAdaptor?
    private var firstPresentationTime: CMTime?
    private var firstFrameMonotonicMilliseconds: Int?
    private var firstFrameWallTimeEpochMilliseconds: Int?
    private var finalFrameMonotonicMilliseconds: Int?
    private var lastRelativePresentationTime = CMTime.zero
    private var frameCount = 0
    private var videoWidth = 0
    private var videoHeight = 0
    private var frameProcessingError: RegionRecordingFailure?
    private var cachedMetrics: RegionRecordingFrameMetrics?

    init(videoURL: URL, startFrameURL: URL, finalFrameURL: URL) {
        self.videoURL = videoURL
        self.startFrameURL = startFrameURL
        self.finalFrameURL = finalFrameURL
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of type: SCStreamOutputType) {
        guard type == .screen, sampleBuffer.isValid, let pixelBuffer = sampleBuffer.imageBuffer else {
            return
        }
        guard sampleBufferFrameStatus(sampleBuffer) == .complete else {
            return
        }
        lock.lock()
        defer { lock.unlock() }
        guard frameProcessingError == nil, cachedMetrics == nil else {
            return
        }
        do {
            try appendCompleteFrame(sampleBuffer: sampleBuffer, pixelBuffer: pixelBuffer)
        } catch let error as RegionRecordingFailure {
            frameProcessingError = error
        } catch {
            frameProcessingError = .frameProcessingFailed(String(describing: error))
        }
    }

    func finishedResult(
        segmentId: String,
        startedMonotonicMilliseconds: Int,
        endedMonotonicMilliseconds: Int,
        closeReason: ActiveCaptureRecordingSegmentCloseReason
    ) async throws -> RecordingSegmentCaptureResult {
        let metrics = try await finish()
        let containerDuration = try await mp4ContainerDurationMilliseconds(videoURL: videoURL)
        return RecordingSegmentCaptureResult(
            segmentId: segmentId,
            videoURL: videoURL,
            startFrameURL: startFrameURL,
            finalFrameURL: finalFrameURL,
            durationMilliseconds: metrics.durationMilliseconds,
            containerDurationMilliseconds: containerDuration,
            frameCount: metrics.frameCount,
            videoWidth: metrics.videoWidth,
            videoHeight: metrics.videoHeight,
            startedMonotonicMilliseconds: startedMonotonicMilliseconds,
            firstFrameMonotonicMilliseconds: metrics.firstFrameMonotonicMilliseconds,
            firstFrameWallTimeEpochMilliseconds: metrics.firstFrameWallTimeEpochMilliseconds,
            finalFrameMonotonicMilliseconds: metrics.finalFrameMonotonicMilliseconds,
            endedMonotonicMilliseconds: endedMonotonicMilliseconds,
            closeReason: closeReason
        )
    }

    private func finish() async throws -> RegionRecordingFrameMetrics {
        if let cached = cachedFinishMetrics() {
            return cached
        }
        let snapshot = try finishSnapshot()
        try await finishWriting(snapshot.writer)
        let metrics = RegionRecordingFrameMetrics(
            durationMilliseconds: snapshot.durationMilliseconds,
            frameCount: snapshot.frameCount,
            videoWidth: snapshot.videoWidth,
            videoHeight: snapshot.videoHeight,
            firstFrameMonotonicMilliseconds: snapshot.firstFrameMonotonicMilliseconds,
            firstFrameWallTimeEpochMilliseconds: snapshot.firstFrameWallTimeEpochMilliseconds,
            finalFrameMonotonicMilliseconds: snapshot.finalFrameMonotonicMilliseconds
        )
        cacheFinishMetrics(metrics)
        return metrics
    }

    private func cachedFinishMetrics() -> RegionRecordingFrameMetrics? {
        lock.lock()
        let cachedMetrics = cachedMetrics
        lock.unlock()
        return cachedMetrics
    }

    private func finishSnapshot() throws -> RegionRecordingFinishSnapshot {
        lock.lock()
        let writer = writer
        let writerInput = writerInput
        let frameCount = frameCount
        let durationMilliseconds = Int((CMTimeGetSeconds(lastRelativePresentationTime) * 1000).rounded())
        let firstFrameMonotonicMilliseconds = firstFrameMonotonicMilliseconds
        let firstFrameWallTimeEpochMilliseconds = firstFrameWallTimeEpochMilliseconds
        let finalFrameMonotonicMilliseconds = finalFrameMonotonicMilliseconds
        let videoWidth = videoWidth
        let videoHeight = videoHeight
        let frameProcessingError = frameProcessingError
        writerInput?.markAsFinished()
        lock.unlock()

        if let frameProcessingError {
            throw frameProcessingError
        }
        guard frameCount > 0, let writer else {
            throw RegionRecordingFailure.noFramesWritten
        }
        return RegionRecordingFinishSnapshot(
            writer: writer,
            durationMilliseconds: durationMilliseconds,
            frameCount: frameCount,
            videoWidth: videoWidth,
            videoHeight: videoHeight,
            firstFrameMonotonicMilliseconds: firstFrameMonotonicMilliseconds,
            firstFrameWallTimeEpochMilliseconds: firstFrameWallTimeEpochMilliseconds,
            finalFrameMonotonicMilliseconds: finalFrameMonotonicMilliseconds
        )
    }

    private func cacheFinishMetrics(_ metrics: RegionRecordingFrameMetrics) {
        lock.lock()
        cachedMetrics = metrics
        lock.unlock()
    }

    private func finishWriting(_ writer: AVAssetWriter) async throws {
        try await withCheckedThrowingContinuation { continuation in
            let finish = RegionRecordingFinishContinuation(continuation)
            let writerBox = RegionRecordingWriterBox(writer)
            writer.finishWriting {
                finish.resume(returning: writerBox.resultAfterFinishCallback())
            }
            DispatchQueue.global(qos: .userInitiated).asyncAfter(deadline: .now() + .seconds(12)) {
                writerBox.cancelIfStillWriting()
                finish.resume(returning: .failure(RegionRecordingFailure.writerTimedOut))
            }
        }
    }

    private func appendCompleteFrame(sampleBuffer: CMSampleBuffer, pixelBuffer: CVPixelBuffer) throws {
        try ensureWriter(pixelBuffer: pixelBuffer)
        guard let writerInput, let adaptor else {
            throw RegionRecordingFailure.writerFailed("writer not initialized")
        }
        guard writerInput.isReadyForMoreMediaData else {
            return
        }
        let presentationTime = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        let firstTime = firstPresentationTime ?? presentationTime
        firstPresentationTime = firstTime
        let relativeTime = max(CMTimeSubtract(presentationTime, firstTime), .zero)
        guard adaptor.append(pixelBuffer, withPresentationTime: relativeTime) else {
            throw RegionRecordingFailure.writerFailed("pixel buffer append rejected")
        }
        lastRelativePresentationTime = relativeTime
        frameCount += 1
        let frameMonotonicMilliseconds = monotonicMilliseconds()
        finalFrameMonotonicMilliseconds = frameMonotonicMilliseconds
        if firstFrameMonotonicMilliseconds == nil {
            firstFrameMonotonicMilliseconds = frameMonotonicMilliseconds
            firstFrameWallTimeEpochMilliseconds = Int((Date().timeIntervalSince1970 * 1_000).rounded())
        }
    }

    private func ensureWriter(pixelBuffer: CVPixelBuffer) throws {
        if writer != nil {
            return
        }
        videoWidth = CVPixelBufferGetWidth(pixelBuffer)
        videoHeight = CVPixelBufferGetHeight(pixelBuffer)
        let writer = try AVAssetWriter(outputURL: videoURL, fileType: .mp4)
        let settings: [String: Any] = [
            AVVideoCodecKey: AVVideoCodecType.h264,
            AVVideoWidthKey: videoWidth,
            AVVideoHeightKey: videoHeight,
            AVVideoCompressionPropertiesKey: [
                AVVideoAverageBitRateKey: 5_000_000,
                AVVideoExpectedSourceFrameRateKey: 24,
            ],
        ]
        let input = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
        input.expectsMediaDataInRealTime = true
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: input,
            sourcePixelBufferAttributes: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                kCVPixelBufferWidthKey as String: videoWidth,
                kCVPixelBufferHeightKey as String: videoHeight,
            ]
        )
        guard writer.canAdd(input) else {
            throw RegionRecordingFailure.writerFailed("cannot add video input")
        }
        writer.add(input)
        guard writer.startWriting() else {
            throw writer.error.map { RegionRecordingFailure.writerFailed($0.localizedDescription) }
                ?? RegionRecordingFailure.writerFailed("startWriting returned false")
        }
        writer.startSession(atSourceTime: .zero)
        self.writer = writer
        writerInput = input
        self.adaptor = adaptor
    }

    private func sampleBufferFrameStatus(_ sampleBuffer: CMSampleBuffer) -> SCFrameStatus? {
        guard
            let attachments = CMSampleBufferGetSampleAttachmentsArray(sampleBuffer, createIfNecessary: false)
                as? [[SCStreamFrameInfo: Any]],
            let statusRawValue = attachments.first?[.status] as? Int
        else {
            return nil
        }
        return SCFrameStatus(rawValue: statusRawValue)
    }
}

private func mp4ContainerDurationMilliseconds(videoURL: URL) async throws -> Int {
    let asset = AVURLAsset(url: videoURL)
    let duration = try await asset.load(.duration)
    let seconds = CMTimeGetSeconds(duration)
    guard seconds.isFinite, seconds > 0 else {
        throw RegionRecordingFailure.assetDurationUnavailable("duration=\(seconds)")
    }
    return Int((seconds * 1000).rounded())
}
