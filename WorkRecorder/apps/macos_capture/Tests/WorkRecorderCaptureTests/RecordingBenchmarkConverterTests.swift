import Foundation
import Testing
@testable import WorkRecorderCapture

struct RecordingBenchmarkConverterTests {
    @Test func taskExportRootUsesSanitizedRecordingNote() {
        let selected = URL(fileURLWithPath: "/tmp/videos", isDirectory: true)

        let result = WorkbenchRecordingBenchmarkConverter.taskExportRoot(
            selectedDirectory: selected,
            userNote: "  chrome/030ee:\nrun  "
        )

        #expect(result.path == "/tmp/videos/chrome_030ee_ run/video")
    }

    @Test func taskExportRootDoesNotDuplicateAlreadySelectedTaskFolder() {
        let selected = URL(fileURLWithPath: "/tmp/videos/chrome_030ee", isDirectory: true)

        let result = WorkbenchRecordingBenchmarkConverter.taskExportRoot(
            selectedDirectory: selected,
            userNote: "chrome_030ee"
        )

        #expect(result.path == "/tmp/videos/chrome_030ee/video")
    }

    @Test func benchmarkOutputIsSiblingOfNearestVideosDirectory() {
        let taskRoot = URL(
            fileURLWithPath: "/Users/demo/Desktop/BP/OSWorld_videos/chrome_030ee/video",
            isDirectory: true
        )

        let result = WorkbenchRecordingBenchmarkConverter.benchmarkOutputRoot(for: taskRoot)

        #expect(result.path == "/Users/demo/Desktop/BP/OSWorld_videos/chrome_030ee/benchmark")
    }

    @Test func conditionIsInferredFromRecordingNote() {
        #expect(WorkbenchRecordingBenchmarkConverter.inferredCondition(from: "cua_only-f003") == "cua_only")
        #expect(WorkbenchRecordingBenchmarkConverter.inferredCondition(from: "chrome_030ee") == "chrome_030ee")
    }

    @Test func converterProcessPathIncludesHomebrewToolsForGUIAppLaunches() {
        let environment = WorkbenchRecordingBenchmarkConverter.processEnvironment(
            base: ["PATH": "/usr/bin:/bin"],
            uvExecutable: URL(fileURLWithPath: "/opt/homebrew/bin/uv")
        )

        #expect(environment["PATH"]?.split(separator: ":").map(String.init) == [
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        ])
        #expect(environment["PYTHONUNBUFFERED"] == "1")
    }

    @Test func converterRunsUVPipelineWithNormalExportOnly() async throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("workrecorder-benchmark-converter-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let repository = root.appendingPathComponent("WorkRecorder", isDirectory: true)
        let taskRoot = root.appendingPathComponent("dataset/chrome_030ee/video", isDirectory: true)
        let pipeline = root.appendingPathComponent("highlight_then_benchmark.py")
        let highlightScript = root.appendingPathComponent("keylog_highlight_frames.py")
        let benchmarkScript = root.appendingPathComponent("raw_to_benchmark.py")
        let fakeUV = root.appendingPathComponent("uv")
        try FileManager.default.createDirectory(at: repository, withIntermediateDirectories: true)
        try "[project]\nname = \"test\"\nversion = \"0.0.0\"\n".write(
            to: repository.appendingPathComponent("pyproject.toml"),
            atomically: true,
            encoding: .utf8
        )
        try "# pipeline placeholder\n".write(to: pipeline, atomically: true, encoding: .utf8)
        try "# highlight placeholder\n".write(to: highlightScript, atomically: true, encoding: .utf8)
        try "# benchmark placeholder\n".write(to: benchmarkScript, atomically: true, encoding: .utf8)
        try "#!/bin/sh\ndd if=/dev/zero bs=70000 count=1 2>/dev/null | tr '\\0' x\nprintf '\\n%s\\n' \"$@\"\n".write(
            to: fakeUV,
            atomically: true,
            encoding: .utf8
        )
        try FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: fakeUV.path)
        for mode in [WorkbenchRecordingExportFallbackMode.normal] {
            let modeDirectory = taskRoot.appendingPathComponent("chrome_030ee+\(mode.rawValue)", isDirectory: true)
            try FileManager.default.createDirectory(at: modeDirectory, withIntermediateDirectories: true)
            try "{\"session_id\":\"session-demo\"}".write(
                to: modeDirectory.appendingPathComponent("recording.json"),
                atomically: true,
                encoding: .utf8
            )
        }

        let result = try await WorkbenchRecordingBenchmarkConverter.convert(
            taskExportRoot: taskRoot,
            expectedSessionId: "session-demo",
            environment: [
                WorkbenchRecordingBenchmarkConverter.uvEnvironmentKey: fakeUV.path,
                WorkbenchRecordingBenchmarkConverter.pipelineEnvironmentKey: pipeline.path,
                "WORKRECORDER_REPO_ROOT": repository.path,
            ],
            homeDirectory: root,
            currentDirectory: root
        )

        #expect(result.taskExportRoot == taskRoot)
        #expect(result.benchmarkOutputRoot.path == root.appendingPathComponent("dataset/chrome_030ee/benchmark").path)
        #expect(result.benchmarkTaskDirectory == result.benchmarkOutputRoot)
        #expect(result.command.contains(highlightScript.path))
        #expect(result.command.contains(benchmarkScript.path))
        #expect(result.output.contains(taskRoot.path))
        #expect(result.output.contains("--output-root"))
        #expect(result.output.contains("仅保留转换日志末尾 64 KiB"))
        #expect(result.output.utf8.count < 66_000)
    }
}
