import AppKit
import AVFoundation
import CoreImage
import Foundation
import ImageIO
import ScreenCaptureKit
import UniformTypeIdentifiers

final class WindowRecordingSession {
    private let outputDirectory: URL
    private let targetWindow: SCWindow
    private let durationMilliseconds: Int

    init(outputDirectory: URL, targetWindow: SCWindow, durationMilliseconds: Int) {
        self.outputDirectory = outputDirectory
        self.targetWindow = targetWindow
        self.durationMilliseconds = durationMilliseconds
    }

    func record() async throws -> RecordingCaptureMetadata {
        let videoURL = outputDirectory.appendingPathComponent("recording-\(UUID().uuidString).mp4")
        let startFrameURL = outputDirectory.appendingPathComponent("recording-start.png")
        let finalFrameURL = outputDirectory.appendingPathComponent("recording-final.png")
        let configuration = SCStreamConfiguration()
        let scale = NSScreen.main?.backingScaleFactor ?? 2.0
        configuration.width = max(64, Int(targetWindow.frame.width * scale))
        configuration.height = max(64, Int(targetWindow.frame.height * scale))
        configuration.minimumFrameInterval = CMTime(value: 1, timescale: 24)
        configuration.queueDepth = 8
        configuration.showsCursor = false
        configuration.pixelFormat = kCVPixelFormatType_32BGRA

        let filter = SCContentFilter(desktopIndependentWindow: targetWindow)
        let frameSink = RecordingFrameSink(
            videoURL: videoURL,
            startFrameURL: startFrameURL,
            finalFrameURL: finalFrameURL
        )
        let stream = SCStream(filter: filter, configuration: configuration, delegate: nil)
        let queue = DispatchQueue(label: "workrecorder.recording.e2e.frames", qos: .userInitiated)
        try stream.addStreamOutput(frameSink, type: .screen, sampleHandlerQueue: queue)
        let startedMonotonicMilliseconds = monotonicMilliseconds()
        try await stream.startCapture()
        try await Task.sleep(nanoseconds: UInt64(durationMilliseconds) * 1_000_000)
        try await stream.stopCapture()
        let endedMonotonicMilliseconds = monotonicMilliseconds()
        let metrics = try frameSink.finish()
        let containerDurationMilliseconds = try await mp4ContainerDurationMilliseconds(videoURL: videoURL)
        return RecordingCaptureMetadata(
            videoURL: videoURL,
            startFrameURL: startFrameURL,
            finalFrameURL: finalFrameURL,
            durationMilliseconds: metrics.durationMilliseconds,
            containerDurationMilliseconds: containerDurationMilliseconds,
            frameCount: metrics.frameCount,
            videoWidth: metrics.videoWidth,
            videoHeight: metrics.videoHeight,
            startedMonotonicMilliseconds: startedMonotonicMilliseconds,
            firstFrameMonotonicMilliseconds: metrics.firstFrameMonotonicMilliseconds,
            finalFrameMonotonicMilliseconds: metrics.finalFrameMonotonicMilliseconds,
            endedMonotonicMilliseconds: endedMonotonicMilliseconds
        )
    }
}

private final class RecordingFrameSink: NSObject, SCStreamOutput, @unchecked Sendable {
    private let videoURL: URL
    private let startFrameURL: URL
    private let finalFrameURL: URL
    private let context = CIContext()
    private let lock = NSLock()
    private var writer: AVAssetWriter?
    private var writerInput: AVAssetWriterInput?
    private var adaptor: AVAssetWriterInputPixelBufferAdaptor?
    private var firstPresentationTime: CMTime?
    private var firstFrameMonotonicMilliseconds: Int?
    private var finalFrameMonotonicMilliseconds: Int?
    private var lastRelativePresentationTime = CMTime.zero
    private var frameCount = 0
    private var videoWidth = 0
    private var videoHeight = 0
    private var frameProcessingError: FixtureError?

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
        guard frameProcessingError == nil else {
            return
        }
        do {
            try appendCompleteFrame(sampleBuffer: sampleBuffer, pixelBuffer: pixelBuffer)
        } catch let error as FixtureError {
            frameProcessingError = error
        } catch {
            frameProcessingError = .frameProcessingFailed(String(describing: error))
        }
    }

    func finish() throws -> RecordingFrameMetrics {
        lock.lock()
        let writer = writer
        let writerInput = writerInput
        let frameCount = frameCount
        let durationMilliseconds = Int((CMTimeGetSeconds(lastRelativePresentationTime) * 1000).rounded())
        let firstFrameMonotonicMilliseconds = firstFrameMonotonicMilliseconds
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
            throw FixtureError.noFramesWritten
        }
        let semaphore = DispatchSemaphore(value: 0)
        writer.finishWriting {
            semaphore.signal()
        }
        guard semaphore.wait(timeout: .now() + 10) == .success else {
            throw FixtureError.writerTimedOut
        }
        guard writer.status == .completed else {
            throw writer.error ?? FixtureError.writerFailed("\(writer.status.rawValue)")
        }
        return RecordingFrameMetrics(
            durationMilliseconds: durationMilliseconds,
            frameCount: frameCount,
            videoWidth: videoWidth,
            videoHeight: videoHeight,
            firstFrameMonotonicMilliseconds: firstFrameMonotonicMilliseconds,
            finalFrameMonotonicMilliseconds: finalFrameMonotonicMilliseconds
        )
    }

    private func appendCompleteFrame(sampleBuffer: CMSampleBuffer, pixelBuffer: CVPixelBuffer) throws {
        try ensureWriter(pixelBuffer: pixelBuffer)
        guard let writerInput, let adaptor else {
            throw FixtureError.writerFailed("writer not initialized")
        }
        guard writerInput.isReadyForMoreMediaData else {
            return
        }
        let presentationTime = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
        let firstTime = firstPresentationTime ?? presentationTime
        firstPresentationTime = firstTime
        let relativeTime = max(CMTimeSubtract(presentationTime, firstTime), .zero)
        guard adaptor.append(pixelBuffer, withPresentationTime: relativeTime) else {
            throw FixtureError.writerFailed("pixel buffer append rejected")
        }
        lastRelativePresentationTime = relativeTime
        frameCount += 1
        finalFrameMonotonicMilliseconds = monotonicMilliseconds()
        if firstFrameMonotonicMilliseconds == nil {
            firstFrameMonotonicMilliseconds = finalFrameMonotonicMilliseconds
            try writePNG(pixelBuffer: pixelBuffer, to: startFrameURL)
        }
        try writePNG(pixelBuffer: pixelBuffer, to: finalFrameURL)
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
            throw FixtureError.writerFailed("cannot add video input")
        }
        writer.add(input)
        guard writer.startWriting() else {
            throw writer.error ?? FixtureError.writerFailed("startWriting returned false")
        }
        writer.startSession(atSourceTime: .zero)
        self.writer = writer
        writerInput = input
        self.adaptor = adaptor
    }

    private func writePNG(pixelBuffer: CVPixelBuffer, to url: URL) throws {
        let image = CIImage(cvPixelBuffer: pixelBuffer)
        guard let cgImage = context.createCGImage(image, from: image.extent) else {
            throw FixtureError.pngWriteFailed("CIContext returned nil")
        }
        guard let destination = CGImageDestinationCreateWithURL(url as CFURL, UTType.png.identifier as CFString, 1, nil)
        else {
            throw FixtureError.pngWriteFailed("CGImageDestinationCreateWithURL failed")
        }
        CGImageDestinationAddImage(destination, cgImage, nil)
        guard CGImageDestinationFinalize(destination) else {
            throw FixtureError.pngWriteFailed("CGImageDestinationFinalize failed")
        }
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
