import AppKit
import Foundation

extension RecordingReviewWindowController {
    @objc func exportRecordingAction() {
        guard !isExportInProgress else { return }
        guard let recording = currentRequest?.recording else { return }
        let sessionId = recording.sessionId
        guard let exportClient else {
            logStore.append("导出功能在当前环境不可用。")
            return
        }
        guard let selectedDirectory = chooseExportDirectory() else { return }
        let outputRoot = WorkbenchRecordingBenchmarkConverter.taskExportRoot(
            selectedDirectory: selectedDirectory,
            userNote: recording.userNote
        )
        isExportInProgress = true
        logStore.append("正在导出录制到 \(outputRoot.path)…")
        render()
        Task { @MainActor [weak self] in
            guard let self else { return }
            defer {
                self.isExportInProgress = false
                self.render()
            }
            do {
                let result = try await exportClient.recordingExport(
                    sessionId: sessionId,
                    outputRoot: outputRoot.path,
                    purpose: "workbench_user_export_recording",
                    fallbackMode: .normal
                )
                if let warning = result.fallbackWarning {
                    self.logStore.append("导出提示：\(warning)")
                }
            } catch {
                self.logStore.append("导出失败：" + WorkbenchUserMessages.friendlyError(error.localizedDescription))
                return
            }
            self.logStore.append("录制已导出，正在转换为 benchmark 格式…")
            self.render()
            do {
                let conversion = try await self.convertExportToBenchmark(outputRoot, sessionId)
                self.logStore.append("benchmark 转换命令：\(conversion.command)")
                let output = conversion.output.trimmingCharacters(in: .whitespacesAndNewlines)
                if !output.isEmpty {
                    self.logStore.append("benchmark 转换输出：\(String(output.suffix(4_000)))")
                }
                self.logStore.append("完整导出与 benchmark 转换已完成：\(conversion.benchmarkTaskDirectory.path)")
                self.revealInFinder(conversion.benchmarkTaskDirectory)
            } catch {
                self.logStore.append(
                    "录制已导出到 \(outputRoot.path)，但 benchmark 转换失败："
                        + WorkbenchUserMessages.friendlyError(error.localizedDescription)
                )
                self.revealInFinder(outputRoot)
            }
        }
    }

    static func runExportDirectoryPanel() -> URL? {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.canCreateDirectories = true
        panel.allowsMultipleSelection = false
        panel.prompt = "Export Here"
        panel.message = "Choose a folder to export and convert the recording to benchmark"
        return panel.runModal() == .OK ? panel.url : nil
    }
}
