import XCTest
@testable import WorkRecorderCapture

final class WorkRecorderLocalizationTests: XCTestCase {
    func testCoreEnglishEditionCopy() {
        XCTAssertEqual(WorkRecorderLocalization.english("录制中心"), "Recording Center")
        XCTAssertEqual(WorkRecorderLocalization.english("开始录制"), "Start Recording")
        XCTAssertEqual(WorkRecorderLocalization.english("辅助功能"), "Accessibility")
        XCTAssertEqual(WorkRecorderLocalization.english("打开复盘"), "Open Review")
    }

    func testDynamicRecordingCountsDoNotRetainChinese() {
        let samples = [
            WorkRecorderLocalization.english("187 段录制"),
            WorkRecorderLocalization.english("31 个重点 · 2 处待确认"),
            WorkRecorderLocalization.english("视频不可用，已保留 12 个步骤 · 00:30"),
        ]

        for sample in samples {
            XCTAssertNil(sample.range(of: "\\p{Han}", options: .regularExpression), sample)
        }
    }

    func testEnglishSourceContentIsUnchanged() {
        XCTAssertEqual(
            WorkRecorderLocalization.english("QEMU (qemu) - TigerVNC"),
            "QEMU (qemu) - TigerVNC"
        )
    }
}
