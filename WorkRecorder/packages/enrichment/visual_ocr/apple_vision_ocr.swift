import AppKit
import CoreGraphics
import Foundation
import Vision

struct OCRLine: Encodable {
    let text: String
    let reading_order: Int
    let confidence: Double
}

struct OCRQuality: Encodable {
    let confidence: Double
    let text_chars: Int
    let language_hint: String?
    let truncated: Bool
    let warnings: [String]
}

struct OCRResult: Encodable {
    let plain_text: String
    let readable_markdown: String
    let lines: [OCRLine]
    let ui_elements: [String]
    let quality: OCRQuality
    let raw_model_name: String?
    let metadata: [String: String]
}

if CommandLine.arguments.count == 2 && CommandLine.arguments[1] == "--probe" {
    guard let bitmap = NSBitmapImageRep(
        bitmapDataPlanes: nil,
        pixelsWide: 8,
        pixelsHigh: 8,
        bitsPerSample: 8,
        samplesPerPixel: 4,
        hasAlpha: true,
        isPlanar: false,
        colorSpaceName: .deviceRGB,
        bytesPerRow: 32,
        bitsPerPixel: 32
    ), let cgImage = bitmap.cgImage else {
        fputs("failed to create probe image\n", stderr)
        exit(67)
    }
    let request = VNRecognizeTextRequest()
    let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
    do {
        try handler.perform([request])
    } catch {
        fputs("Vision OCR probe failed: \(error.localizedDescription)\n", stderr)
        exit(68)
    }
    FileHandle.standardOutput.write(Data("{\"ok\":true}".utf8))
    exit(0)
}

guard CommandLine.arguments.count == 2 else {
    fputs("usage: apple_vision_ocr.swift <image-path>|--probe\n", stderr)
    exit(64)
}

let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
guard let image = NSImage(contentsOf: imageURL), let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    fputs("failed to load OCR image\n", stderr)
    exit(65)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
if #available(macOS 13.0, *) {
    request.automaticallyDetectsLanguage = true
}

let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
    try handler.perform([request])
} catch {
    fputs("Vision OCR failed: \(error.localizedDescription)\n", stderr)
    exit(66)
}

let observations = request.results ?? []
let lines = observations.enumerated().compactMap { index, observation -> OCRLine? in
    guard let candidate = observation.topCandidates(1).first else { return nil }
    let text = candidate.string.trimmingCharacters(in: .whitespacesAndNewlines)
    if text.isEmpty { return nil }
    return OCRLine(text: text, reading_order: index, confidence: Double(candidate.confidence))
}
let plainText = lines.map(\.text).joined(separator: "\n")
let confidence = lines.isEmpty ? 0.0 : lines.map(\.confidence).reduce(0.0, +) / Double(lines.count)
let result = OCRResult(
    plain_text: plainText,
    readable_markdown: plainText,
    lines: lines,
    ui_elements: [],
    quality: OCRQuality(
        confidence: confidence,
        text_chars: plainText.count,
        language_hint: nil,
        truncated: false,
        warnings: []
    ),
    raw_model_name: "apple_vision",
    metadata: ["source": "apple_vision"]
)

let encoder = JSONEncoder()
encoder.outputFormatting = [.sortedKeys]
let data = try encoder.encode(result)
FileHandle.standardOutput.write(data)
