import AppKit
import Foundation
import Testing
@testable import WorkRecorderCapture

@Suite(.serialized)
struct WorkbenchRuntimeTests {}

extension NSColor {
    var sampleKey: UInt32 {
        let rgb = usingColorSpace(.sRGB) ?? self
        let red = UInt32(max(0, min(255, Int(round(rgb.redComponent * 255)))))
        let green = UInt32(max(0, min(255, Int(round(rgb.greenComponent * 255)))))
        let blue = UInt32(max(0, min(255, Int(round(rgb.blueComponent * 255)))))
        let alpha = UInt32(max(0, min(255, Int(round(rgb.alphaComponent * 255)))))
        return (red << 24) | (green << 16) | (blue << 8) | alpha
    }

    var relativeLuminance: Double {
        let rgb = usingColorSpace(.sRGB) ?? self
        return 0.2126 * Double(rgb.redComponent)
            + 0.7152 * Double(rgb.greenComponent)
            + 0.0722 * Double(rgb.blueComponent)
    }
}

extension NSImage {
    func writePNG(to file: URL) throws {
        guard let tiff = tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: tiff),
              let data = bitmap.representation(using: .png, properties: [:])
        else {
            throw CocoaError(.fileWriteUnknown)
        }
        try data.write(to: file)
    }
}
