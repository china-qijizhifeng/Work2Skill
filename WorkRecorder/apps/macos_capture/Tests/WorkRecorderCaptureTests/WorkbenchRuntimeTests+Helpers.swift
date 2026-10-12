import AppKit
import Foundation
import Testing
@testable import WorkRecorderCapture

extension WorkbenchRuntimeTests {
    static func previewThumbnail() -> NSImage {
        let image = NSImage(size: NSSize(width: 640, height: 360))
        image.lockFocus()
        NSColor(calibratedRed: 0.96, green: 0.985, blue: 0.985, alpha: 1).setFill()
        NSRect(x: 0, y: 0, width: 640, height: 360).fill()
        NSColor.white.withAlphaComponent(0.92).setFill()
        NSBezierPath(roundedRect: NSRect(x: 38, y: 34, width: 564, height: 292), xRadius: 18, yRadius: 18).fill()
        NSColor(calibratedRed: 0.77, green: 0.86, blue: 0.87, alpha: 0.55).setStroke()
        NSBezierPath(roundedRect: NSRect(x: 38, y: 34, width: 564, height: 292), xRadius: 18, yRadius: 18).stroke()
        NSColor(calibratedRed: 0.94, green: 0.98, blue: 0.98, alpha: 1).setFill()
        NSBezierPath(rect: NSRect(x: 38, y: 34, width: 142, height: 292)).fill()
        let titleAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 26, weight: .semibold),
            .foregroundColor: NSColor(calibratedRed: 0.12, green: 0.16, blue: 0.18, alpha: 1),
        ]
        "网页内容抽取策略".draw(at: NSPoint(x: 212, y: 266), withAttributes: titleAttrs)
        let bodyAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 13, weight: .medium),
            .foregroundColor: NSColor(calibratedRed: 0.34, green: 0.45, blue: 0.48, alpha: 0.92),
        ]
        "优先为 Agent 提供安全、可引用的默认视图；长网页、原图和原始材料按需加载或保持锁定。"
            .draw(in: NSRect(x: 214, y: 226, width: 330, height: 36), withAttributes: bodyAttrs)
        let tocAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 12, weight: .medium),
            .foregroundColor: NSColor(calibratedRed: 0.35, green: 0.46, blue: 0.49, alpha: 0.84),
        ]
        for (index, text) in ["默认视图会看到什么？", "共享模式对比", "证据栈", "示例对比", "实施建议"].enumerated() {
            "\(index + 1).  \(text)".draw(at: NSPoint(x: 62, y: 276 - index * 34), withAttributes: tocAttrs)
        }
        let card = NSRect(x: 214, y: 72, width: 330, height: 112)
        NSColor(calibratedRed: 0.93, green: 0.99, blue: 0.97, alpha: 1).setFill()
        NSBezierPath(roundedRect: card, xRadius: 13, yRadius: 13).fill()
        NSColor(calibratedRed: 0.72, green: 0.88, blue: 0.84, alpha: 0.65).setStroke()
        NSBezierPath(roundedRect: card, xRadius: 13, yRadius: 13).stroke()
        let bulletAttrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 12, weight: .medium),
            .foregroundColor: NSColor(calibratedRed: 0.12, green: 0.50, blue: 0.40, alpha: 1),
        ]
        for (index, text) in ["网页正文（结构化）", "关键信息摘要与列表", "必要的上下文说明"].enumerated() {
            "✓  \(text)".draw(at: NSPoint(x: 238, y: 148 - index * 28), withAttributes: bulletAttrs)
        }
        image.unlockFocus()
        return image
    }

    struct SnapshotFacts {
        let width: Int
        let height: Int
        let uniqueSampleCount: Int
        let averageLuminance: Double
    }

    static func snapshotFacts(_ image: NSImage) throws -> SnapshotFacts {
        let data = try #require(image.tiffRepresentation)
        let bitmap = try #require(NSBitmapImageRep(data: data))
        var samples = Set<UInt32>()
        var luminanceTotal = 0.0
        var luminanceCount = 0.0
        let stepX = max(1, bitmap.pixelsWide / 20)
        let stepY = max(1, bitmap.pixelsHigh / 20)
        for y in stride(from: 0, to: bitmap.pixelsHigh, by: stepY) {
            for x in stride(from: 0, to: bitmap.pixelsWide, by: stepX) {
                let color = bitmap.colorAt(x: x, y: y) ?? .clear
                samples.insert(color.sampleKey)
                luminanceTotal += color.relativeLuminance
                luminanceCount += 1
            }
        }
        return SnapshotFacts(
            width: bitmap.pixelsWide,
            height: bitmap.pixelsHigh,
            uniqueSampleCount: samples.count,
            averageLuminance: luminanceCount == 0 ? 0 : luminanceTotal / luminanceCount
        )
    }

    static func writeSnapshotIfRequested(_ image: NSImage, name: String) throws {
        guard ProcessInfo.processInfo.environment["WORKRECORDER_WRITE_WORKBENCH_SNAPSHOTS"] == "1" else {
            return
        }
        let root = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
            .appendingPathComponent("../../.qa/workbench", isDirectory: true)
            .standardizedFileURL
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let file = root.appendingPathComponent("\(name.replacingOccurrences(of: " ", with: "-").lowercased()).png")
        try image.writePNG(to: file)
    }

}
