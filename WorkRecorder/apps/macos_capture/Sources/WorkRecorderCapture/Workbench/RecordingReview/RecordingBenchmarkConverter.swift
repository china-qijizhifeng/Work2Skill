import Foundation

struct WorkbenchRecordingBenchmarkConversionResult: Equatable, Sendable {
    let taskExportRoot: URL
    let benchmarkOutputRoot: URL
    let benchmarkTaskDirectory: URL
    let command: String
    let output: String
}

struct WorkbenchRecordingBenchmarkConversionConfiguration: Equatable, Sendable {
    let uvExecutable: URL
    let pipelineScript: URL
    let workingDirectory: URL
    let benchmarkOutputRoot: URL
}

enum WorkbenchRecordingBenchmarkConversionError: LocalizedError, Equatable {
    case uvNotFound
    case pipelineNotFound(String)
    case repositoryNotFound(String)
    case incompleteExport(String)
    case launchFailed(String)
    case commandFailed(status: Int32, output: String)

    var errorDescription: String? {
        switch self {
        case .uvNotFound:
            return "未找到 uv。请安装 uv，或通过 WORKRECORDER_UV_EXECUTABLE 指定其路径。"
        case .pipelineNotFound(let path):
            return "未找到 benchmark 转换脚本：\(path)。可通过 WORKRECORDER_BENCHMARK_PIPELINE_SCRIPT 指定。"
        case .repositoryNotFound(let path):
            return "未找到 WorkRecorder 仓库目录：\(path)。可通过 WORKRECORDER_REPO_ROOT 指定。"
        case .incompleteExport(let detail):
            return "三模式导出目录不完整：\(detail)"
        case .launchFailed(let detail):
            return "无法启动 benchmark 转换：\(detail)"
        case .commandFailed(let status, let output):
            let detail = output.trimmingCharacters(in: .whitespacesAndNewlines)
            return detail.isEmpty
                ? "benchmark 转换失败（退出码 \(status)）。"
                : "benchmark 转换失败（退出码 \(status)）：\(detail)"
        }
    }
}

enum WorkbenchRecordingBenchmarkConverter {
    private struct ModeExport: Sendable {
        let mode: WorkbenchRecordingExportFallbackMode
        let directory: URL
    }

    static let pipelineEnvironmentKey = "WORKRECORDER_BENCHMARK_PIPELINE_SCRIPT"
    static let uvEnvironmentKey = "WORKRECORDER_UV_EXECUTABLE"
    static let maximumCapturedOutputBytes: UInt64 = 64 * 1_024

    static func taskExportRoot(selectedDirectory: URL, userNote: String?) -> URL {
        let taskName = safeFolderComponent(userNote ?? "recording")
        let noteRoot = selectedDirectory.lastPathComponent == taskName
            ? selectedDirectory
            : selectedDirectory.appendingPathComponent(taskName, isDirectory: true)
        return noteRoot.appendingPathComponent("video", isDirectory: true)
    }

    static func benchmarkOutputRoot(for taskExportRoot: URL) -> URL {
        if taskExportRoot.lastPathComponent == "video" {
            return taskExportRoot.deletingLastPathComponent().appendingPathComponent("benchmark", isDirectory: true)
        }
        var candidate = taskExportRoot
        while candidate.path != candidate.deletingLastPathComponent().path {
            if candidate.lastPathComponent == "videos" {
                return candidate.deletingLastPathComponent().appendingPathComponent("benchmark", isDirectory: true)
            }
            candidate.deleteLastPathComponent()
        }
        return taskExportRoot.deletingLastPathComponent().appendingPathComponent("benchmark", isDirectory: true)
    }

    static func convert(
        taskExportRoot: URL,
        expectedSessionId: String? = nil,
        environment: [String: String] = ProcessInfo.processInfo.environment,
        homeDirectory: URL = FileManager.default.homeDirectoryForCurrentUser,
        currentDirectory: URL = URL(fileURLWithPath: FileManager.default.currentDirectoryPath, isDirectory: true)
    ) async throws -> WorkbenchRecordingBenchmarkConversionResult {
        let configuration = try resolveConfiguration(
            taskExportRoot: taskExportRoot,
            environment: environment,
            homeDirectory: homeDirectory,
            currentDirectory: currentDirectory
        )
        return try await Task.detached(priority: .userInitiated) {
            let modeExports = try validateNormalExport(taskExportRoot, expectedSessionId: expectedSessionId)
            return try run(
                taskExportRoot: taskExportRoot,
                modeExports: modeExports,
                configuration: configuration
            )
        }.value
    }

    static func resolveConfiguration(
        taskExportRoot: URL,
        environment: [String: String],
        homeDirectory: URL,
        currentDirectory: URL,
        fileManager: FileManager = .default
    ) throws -> WorkbenchRecordingBenchmarkConversionConfiguration {
        guard let uvExecutable = resolveUVExecutable(
            environment: environment,
            homeDirectory: homeDirectory,
            fileManager: fileManager
        ) else {
            throw WorkbenchRecordingBenchmarkConversionError.uvNotFound
        }

        let defaultRepository = Bundle.main.runtimeConfigRepoRoot()
            ?? currentDirectory.appendingPathComponent("WorkRecorder", isDirectory: true)
        let explicitRepository = environment["WORKRECORDER_REPO_ROOT"]
            .map { URL(fileURLWithPath: $0, isDirectory: true).standardizedFileURL }
        let workingDirectory: URL
        if let explicitRepository {
            workingDirectory = explicitRepository
        } else if fileManager.fileExists(atPath: currentDirectory.appendingPathComponent("pyproject.toml").path) {
            workingDirectory = currentDirectory
        } else {
            workingDirectory = defaultRepository
        }
        guard fileManager.fileExists(atPath: workingDirectory.appendingPathComponent("pyproject.toml").path) else {
            throw WorkbenchRecordingBenchmarkConversionError.repositoryNotFound(workingDirectory.path)
        }

        let pipelineScript = environment[pipelineEnvironmentKey]
            .map { URL(fileURLWithPath: $0).standardizedFileURL }
            ?? workingDirectory.appendingPathComponent("scripts/benchmark/raw_to_benchmark.py")
        guard fileManager.fileExists(atPath: pipelineScript.path) else {
            throw WorkbenchRecordingBenchmarkConversionError.pipelineNotFound(pipelineScript.path)
        }

        return WorkbenchRecordingBenchmarkConversionConfiguration(
            uvExecutable: uvExecutable,
            pipelineScript: pipelineScript,
            workingDirectory: workingDirectory,
            benchmarkOutputRoot: benchmarkOutputRoot(for: taskExportRoot)
        )
    }

    static func safeFolderComponent(_ value: String, maxLength: Int = 80) -> String {
        let normalized = value.split(whereSeparator: \Character.isWhitespace).joined(separator: " ")
        let replaced = normalized.map { character -> Character in
            let isControl = character.unicodeScalars.contains { $0.value < 32 }
            return character == "/" || character == ":" || character == "\\" || isControl ? "_" : character
        }
        let trimmed = String(replaced)
            .trimmingCharacters(in: CharacterSet.whitespaces.union(CharacterSet(charactersIn: ".")))
        let limited = String(trimmed.prefix(maxLength))
            .trimmingCharacters(in: CharacterSet.whitespaces.union(CharacterSet(charactersIn: ".")))
        return limited.isEmpty ? "recording" : limited
    }

    private static func resolveUVExecutable(
        environment: [String: String],
        homeDirectory: URL,
        fileManager: FileManager
    ) -> URL? {
        var candidates: [URL] = []
        if let explicit = environment[uvEnvironmentKey], !explicit.isEmpty {
            candidates.append(URL(fileURLWithPath: explicit))
        }
        candidates.append(contentsOf: [
            URL(fileURLWithPath: "/opt/homebrew/bin/uv"),
            URL(fileURLWithPath: "/usr/local/bin/uv"),
            homeDirectory.appendingPathComponent(".local/bin/uv"),
        ])
        if let path = environment["PATH"] {
            candidates.append(contentsOf: path.split(separator: ":").map {
                URL(fileURLWithPath: String($0), isDirectory: true).appendingPathComponent("uv")
            })
        }
        return candidates.first { fileManager.isExecutableFile(atPath: $0.path) }?.standardizedFileURL
    }

    private static func validateNormalExport(
        _ taskExportRoot: URL,
        expectedSessionId: String?
    ) throws -> [ModeExport] {
        let children: [URL]
        do {
            children = try FileManager.default.contentsOfDirectory(
                at: taskExportRoot,
                includingPropertiesForKeys: [.isDirectoryKey],
                options: [.skipsHiddenFiles]
            )
        } catch {
            throw WorkbenchRecordingBenchmarkConversionError.incompleteExport(error.localizedDescription)
        }
        var modeExports: [ModeExport] = []
        for mode in [WorkbenchRecordingExportFallbackMode.normal] {
            let matches = children.filter {
                $0.lastPathComponent.hasSuffix("+\(mode.rawValue)")
                    && FileManager.default.fileExists(atPath: $0.appendingPathComponent("recording.json").path)
            }
            guard matches.count == 1 else {
                throw WorkbenchRecordingBenchmarkConversionError.incompleteExport(
                    "\(taskExportRoot.path) 下应有且仅有一个 +\(mode.rawValue) 文件夹，实际为 \(matches.count) 个。"
                )
            }
            if let expectedSessionId {
                let metadataURL = matches[0].appendingPathComponent("recording.json")
                let exportedSessionId = try? JSONSerialization.jsonObject(with: Data(contentsOf: metadataURL))
                    as? [String: Any]
                guard exportedSessionId?["session_id"] as? String == expectedSessionId else {
                    throw WorkbenchRecordingBenchmarkConversionError.incompleteExport(
                        "\(matches[0].lastPathComponent) 不属于当前录制 \(expectedSessionId)，为避免转换旧数据已停止。"
                    )
                }
            }
            modeExports.append(ModeExport(mode: mode, directory: matches[0]))
        }
        return modeExports
    }

    private static func run(
        taskExportRoot: URL,
        modeExports: [ModeExport],
        configuration: WorkbenchRecordingBenchmarkConversionConfiguration
    ) throws -> WorkbenchRecordingBenchmarkConversionResult {
        let codeDirectory = configuration.pipelineScript.deletingLastPathComponent()
        let highlightScript = codeDirectory.appendingPathComponent("keylog_highlight_frames.py")
        let benchmarkScript = codeDirectory.appendingPathComponent("raw_to_benchmark.py")
        for script in [highlightScript, benchmarkScript] where !FileManager.default.fileExists(atPath: script.path) {
            throw WorkbenchRecordingBenchmarkConversionError.pipelineNotFound(script.path)
        }
        let outputURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("workrecorder-benchmark-\(UUID().uuidString).log")
        guard FileManager.default.createFile(atPath: outputURL.path, contents: nil) else {
            throw WorkbenchRecordingBenchmarkConversionError.launchFailed("无法创建临时转换日志。")
        }
        let outputHandle: FileHandle
        do {
            outputHandle = try FileHandle(forWritingTo: outputURL)
        } catch {
            try? FileManager.default.removeItem(at: outputURL)
            throw WorkbenchRecordingBenchmarkConversionError.launchFailed(error.localizedDescription)
        }
        defer {
            try? outputHandle.close()
            try? FileManager.default.removeItem(at: outputURL)
        }
        let processEnvironment = processEnvironment(
            base: ProcessInfo.processInfo.environment,
            uvExecutable: configuration.uvExecutable
        )
        var commands: [String] = []

        func execute(_ arguments: [String]) throws {
            let process = Process()
            process.executableURL = configuration.uvExecutable
            process.currentDirectoryURL = configuration.workingDirectory
            process.arguments = arguments
            process.environment = processEnvironment
            process.standardOutput = outputHandle
            process.standardError = outputHandle
            commands.append(([configuration.uvExecutable.path] + arguments).map(shellQuoted).joined(separator: " "))
            do {
                try process.run()
            } catch {
                throw WorkbenchRecordingBenchmarkConversionError.launchFailed(error.localizedDescription)
            }
            process.waitUntilExit()
            guard process.terminationStatus == 0 else {
                try? outputHandle.synchronize()
                throw WorkbenchRecordingBenchmarkConversionError.commandFailed(
                    status: process.terminationStatus,
                    output: String(capturedOutputTail(at: outputURL).suffix(4_000))
                )
            }
        }

        for export in modeExports {
            try execute([
                "run",
                "--no-sync",
                "python",
                highlightScript.path,
                export.directory.path,
                "--frame-offset-ms", "0",
                "--typing-gap-ms", "900",
                "--drag-click-window-ms", "800",
                "--double-click-window-ms", "200",
                "--action-match-window-ms", "750",
            ])
        }
        let condition = inferredCondition(
            from: taskExportRoot.deletingLastPathComponent().lastPathComponent
        )
        for export in modeExports {
            try execute([
                "run",
                "--no-sync",
                "python",
                benchmarkScript.path,
                export.directory.path,
                "--output-root", configuration.benchmarkOutputRoot.path,
                "--run-id", export.mode.rawValue,
                "--condition", condition,
                "--file-mode", "copy",
                "--overwrite",
            ])
        }

        try? outputHandle.synchronize()
        try? outputHandle.close()
        let output = capturedOutputTail(at: outputURL)
        return WorkbenchRecordingBenchmarkConversionResult(
            taskExportRoot: taskExportRoot,
            benchmarkOutputRoot: configuration.benchmarkOutputRoot,
            benchmarkTaskDirectory: configuration.benchmarkOutputRoot,
            command: commands.joined(separator: "\n"),
            output: output
        )
    }

    static func inferredCondition(from taskName: String) -> String {
        let base = taskName.split(separator: "+", maxSplits: 1).first.map(String.init) ?? taskName
        guard let match = base.range(of: #"-f\d+$"#, options: .regularExpression) else {
            return base
        }
        return String(base[..<match.lowerBound])
    }

    static func capturedOutputTail(at url: URL, fileManager: FileManager = .default) -> String {
        guard let attributes = try? fileManager.attributesOfItem(atPath: url.path),
              let fileSize = (attributes[.size] as? NSNumber)?.uint64Value,
              let handle = try? FileHandle(forReadingFrom: url)
        else {
            return ""
        }
        defer { try? handle.close() }
        let wasTruncated = fileSize > maximumCapturedOutputBytes
        if wasTruncated {
            try? handle.seek(toOffset: fileSize - maximumCapturedOutputBytes)
        }
        let data = handle.readDataToEndOfFile()
        let text = String(data: data, encoding: .utf8) ?? ""
        return wasTruncated ? "[仅保留转换日志末尾 64 KiB]\n\(text)" : text
    }

    static func processEnvironment(base: [String: String], uvExecutable: URL) -> [String: String] {
        var environment = base
        let inheritedPaths = base["PATH", default: ""]
            .split(separator: ":")
            .map(String.init)
        let requiredPaths = [
            uvExecutable.deletingLastPathComponent().path,
            "/opt/homebrew/bin",
            "/usr/local/bin",
            "/usr/bin",
            "/bin",
            "/usr/sbin",
            "/sbin",
        ]
        environment["PATH"] = (requiredPaths + inheritedPaths)
            .reduce(into: [String]()) { paths, path in
                if !path.isEmpty, !paths.contains(path) {
                    paths.append(path)
                }
            }
            .joined(separator: ":")
        environment["PYTHONUNBUFFERED"] = "1"
        return environment
    }

    private static func shellQuoted(_ value: String) -> String {
        guard !value.isEmpty else { return "''" }
        let safeCharacters = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "_./:-"))
        if value.unicodeScalars.allSatisfy({ safeCharacters.contains($0) }) {
            return value
        }
        return "'\(value.replacingOccurrences(of: "'", with: "'\\''"))'"
    }
}
