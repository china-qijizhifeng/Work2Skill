import AppKit
import Foundation
import ImageIO
import UniformTypeIdentifiers

struct ScreenCaptureDiagnostic: Sendable, Equatable {
    let command: [String]
    let processIdentifier: Int32?
    let durationMilliseconds: Int
    let exitCode: Int32?
    let stderr: String
    let outputPath: String
    let outputExists: Bool
    let outputSizeBytes: Int64

    var summary: String {
        let pid = processIdentifier.map(String.init) ?? "n/a"
        return "pid=\(pid) exit=\(exitCode.map(String.init) ?? "timeout") duration_ms=\(durationMilliseconds) bytes=\(outputSizeBytes) file=\(outputExists ? "yes" : "no")"
    }
}

struct ScreenCaptureOutput: Sendable, Equatable {
    let file: URL
    let diagnostic: ScreenCaptureDiagnostic
}

struct ScreenCaptureVisualProbe: Sendable, Equatable {
    let sampleFingerprint: String
    let sampledPixelCount: Int
    let meanLuminance: Double
}

enum ScreenCaptureError: Error, LocalizedError, Equatable {
    case missingOutput(ScreenCaptureDiagnostic)
    case emptyOutput(ScreenCaptureDiagnostic)
    case missingDisplay(String)
    case imageCreationFailed(ScreenCaptureDiagnostic)
    case imageWriteFailed(ScreenCaptureDiagnostic)

    var errorDescription: String? {
        switch self {
        case .missingOutput(let diagnostic):
            return "录制关键帧没有生成文件：\(diagnostic.summary)"
        case .emptyOutput(let diagnostic):
            return "录制关键帧文件为空：\(diagnostic.summary)"
        case .missingDisplay(let message):
            return "无法识别目标屏幕：\(message)"
        case .imageCreationFailed(let diagnostic):
            return "录制关键帧生成失败：\(diagnostic.summary)"
        case .imageWriteFailed(let diagnostic):
            return "录制关键帧写入失败：\(diagnostic.summary)"
        }
    }
}

final class ScreenCaptureService: @unchecked Sendable {
    private let stagingDirectory: URL

    init(stagingDirectory: URL) {
        self.stagingDirectory = stagingDirectory
    }

    @MainActor
    func captureRegion(_ appKitScreenRect: CGRect, on screen: NSScreen) async throws -> ScreenCaptureOutput {
        guard let screenNumber = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else {
            throw ScreenCaptureError.missingDisplay("screen=\(screen)")
        }
        let displayId = CGDirectDisplayID(screenNumber.uint32Value)
        let pixelRect = Geometry.displayPixelRect(from: appKitScreenRect, on: screen)
        let stagingDirectory = stagingDirectory
        return try await Task.detached(priority: .userInitiated) {
            try captureDisplayRegion(
                displayId: displayId,
                pixelRect: pixelRect,
                stagingDirectory: stagingDirectory
            )
        }.value
    }

    @MainActor
    func probeRegionFingerprint(_ appKitScreenRect: CGRect, on screen: NSScreen) async throws -> ScreenCaptureVisualProbe {
        guard let screenNumber = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else {
            throw ScreenCaptureError.missingDisplay("screen=\(screen)")
        }
        let displayId = CGDirectDisplayID(screenNumber.uint32Value)
        let pixelRect = Geometry.displayPixelRect(from: appKitScreenRect, on: screen)
        return try await Task.detached(priority: .utility) {
            try probeDisplayRegion(displayId: displayId, pixelRect: pixelRect)
        }.value
    }

}

private func probeDisplayRegion(displayId: CGDirectDisplayID, pixelRect: CGRect) throws -> ScreenCaptureVisualProbe {
    guard let displayImage = CGDisplayCreateImage(displayId) else {
        throw ScreenCaptureError.imageCreationFailed(makeImageDiagnostic(
            command: ["CGDisplayCreateImage", "-D\(displayId)", "-probe"],
            startedAt: Date(),
            file: URL(fileURLWithPath: "/dev/null"),
            stderr: "CGDisplayCreateImage returned nil for display \(displayId)"
        ))
    }
    let cropRect = clippedPixelCropRect(pixelRect, imageWidth: displayImage.width, imageHeight: displayImage.height)
    guard let image = displayImage.cropping(to: cropRect) else {
        throw ScreenCaptureError.imageCreationFailed(makeImageDiagnostic(
            command: ["CGDisplayCreateImage", "-D\(displayId)", "-probe"],
            startedAt: Date(),
            file: URL(fileURLWithPath: "/dev/null"),
            stderr: "CGImage cropping failed for probe display \(displayId) rect=\(cropRect)"
        ))
    }
    let sampleWidth = 16
    let sampleHeight = 16
    var pixels = [UInt8](repeating: 0, count: sampleWidth * sampleHeight * 4)
    let colorSpace = CGColorSpaceCreateDeviceRGB()
    guard let context = CGContext(
        data: &pixels,
        width: sampleWidth,
        height: sampleHeight,
        bitsPerComponent: 8,
        bytesPerRow: sampleWidth * 4,
        space: colorSpace,
        bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
    ) else {
        throw ScreenCaptureError.imageCreationFailed(makeImageDiagnostic(
            command: ["CGDisplayCreateImage", "-D\(displayId)", "-probe"],
            startedAt: Date(),
            file: URL(fileURLWithPath: "/dev/null"),
            stderr: "CGContext probe allocation failed"
        ))
    }
    context.interpolationQuality = .low
    context.draw(image, in: CGRect(x: 0, y: 0, width: sampleWidth, height: sampleHeight))
    var hash: UInt64 = 14_695_981_039_346_656_037
    var luminanceTotal = 0
    for offset in stride(from: 0, to: pixels.count, by: 4) {
        let red = Int(pixels[offset])
        let green = Int(pixels[offset + 1])
        let blue = Int(pixels[offset + 2])
        let luminance = (red * 299 + green * 587 + blue * 114) / 1_000
        luminanceTotal += luminance
        hash ^= UInt64(luminance)
        hash = hash &* 1_099_511_628_211
    }
    let count = sampleWidth * sampleHeight
    return ScreenCaptureVisualProbe(
        sampleFingerprint: String(format: "fnv64:%016llx", hash),
        sampledPixelCount: count,
        meanLuminance: Double(luminanceTotal) / Double(count)
    )
}

private func captureDisplayRegion(
    displayId: CGDirectDisplayID,
    pixelRect: CGRect,
    stagingDirectory: URL
) throws -> ScreenCaptureOutput {
    try FileManager.default.createDirectory(at: stagingDirectory, withIntermediateDirectories: true)
    let file = stagingDirectory.appendingPathComponent("capture-\(UUID().uuidString).png")
    let startedAt = Date()
    let command = [
        "CGDisplayCreateImage",
        "-D\(displayId)",
        "-full-display-crop",
        "-R\(Int(pixelRect.minX)),\(Int(pixelRect.minY)),\(Int(pixelRect.width)),\(Int(pixelRect.height))",
        file.path,
    ]
    guard let displayImage = CGDisplayCreateImage(displayId) else {
        let diagnostic = makeImageDiagnostic(
            command: command,
            startedAt: startedAt,
            file: file,
            stderr: "CGDisplayCreateImage returned nil for display \(displayId)"
        )
        throw ScreenCaptureError.imageCreationFailed(diagnostic)
    }
    let cropRect = clippedPixelCropRect(
        pixelRect,
        imageWidth: displayImage.width,
        imageHeight: displayImage.height
    )
    guard let image = displayImage.cropping(to: cropRect) else {
        let diagnostic = makeImageDiagnostic(
            command: command,
            startedAt: startedAt,
            file: file,
            stderr: "CGImage cropping failed for display \(displayId) rect=\(cropRect)"
        )
        throw ScreenCaptureError.imageCreationFailed(diagnostic)
    }
    guard
        let destination = CGImageDestinationCreateWithURL(file as CFURL, UTType.png.identifier as CFString, 1, nil)
    else {
        let diagnostic = makeImageDiagnostic(
            command: command,
            startedAt: startedAt,
            file: file,
            stderr: "CGImageDestinationCreateWithURL failed"
        )
        throw ScreenCaptureError.imageWriteFailed(diagnostic)
    }
    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else {
        let diagnostic = makeImageDiagnostic(
            command: command,
            startedAt: startedAt,
            file: file,
            stderr: "CGImageDestinationFinalize failed"
        )
        throw ScreenCaptureError.imageWriteFailed(diagnostic)
    }
    let diagnostic = makeImageDiagnostic(command: command, startedAt: startedAt, file: file, stderr: "")
    guard diagnostic.outputExists else {
        throw ScreenCaptureError.missingOutput(diagnostic)
    }
    guard diagnostic.outputSizeBytes > 0 else {
        throw ScreenCaptureError.emptyOutput(diagnostic)
    }
    return ScreenCaptureOutput(file: file, diagnostic: diagnostic)
}

private func clippedPixelCropRect(_ rect: CGRect, imageWidth: Int, imageHeight: Int) -> CGRect {
    let displayBounds = CGRect(x: 0, y: 0, width: imageWidth, height: imageHeight)
    let integralRect = rect.integral
    let clipped = integralRect.intersection(displayBounds)
    if !clipped.isNull, clipped.width >= 1, clipped.height >= 1 {
        return clipped
    }
    let x = min(max(integralRect.minX, displayBounds.minX), max(displayBounds.minX, displayBounds.maxX - 1))
    let y = min(max(integralRect.minY, displayBounds.minY), max(displayBounds.minY, displayBounds.maxY - 1))
    return CGRect(x: x, y: y, width: 1, height: 1)
}

private func makeImageDiagnostic(
    command: [String],
    startedAt: Date,
    file: URL,
    stderr: String
) -> ScreenCaptureDiagnostic {
    let exists = FileManager.default.fileExists(atPath: file.path)
    let attributes = try? FileManager.default.attributesOfItem(atPath: file.path)
    let size = (attributes?[.size] as? NSNumber)?.int64Value ?? 0
    return ScreenCaptureDiagnostic(
        command: command,
        processIdentifier: nil,
        durationMilliseconds: Int(Date().timeIntervalSince(startedAt) * 1000),
        exitCode: exists && size > 0 ? 0 : 1,
        stderr: stderr,
        outputPath: file.path,
        outputExists: exists,
        outputSizeBytes: size
    )
}
