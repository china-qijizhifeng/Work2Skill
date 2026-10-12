import Foundation
import Darwin

struct RuntimeConfig: Sendable {
    let repoRoot: URL
    let daemonURL: URL
    let databasePath: URL
    let stagingDirectory: URL
    let vaultDirectory: URL
    let installSecret: String
    let providerRegistrationSecret: String
    let nativeCaptureSecret: String
    let feishuAppID: String?
    let feishuAppSecret: String?
    let feishuFolderToken: String?
    let feishuAPIBaseURL: String?

    static func load() -> RuntimeConfig {
        load(
            environment: ProcessInfo.processInfo.environment,
            homeDirectory: FileManager.default.homeDirectoryForCurrentUser
        )
    }

    static func load(environment: [String: String], homeDirectory home: URL) -> RuntimeConfig {
        let appDataRoot = Self.appDataRoot(environment: environment, homeDirectory: home)
        let feishuPayload = Self.loadFeishuConfig(from: appDataRoot)
        let repoRoot = environment["WORKRECORDER_REPO_ROOT"].map(URL.init(fileURLWithPath:))
            ?? Bundle.main.runtimeConfigRepoRoot()
            ?? URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
        let installSecret = environment["WORKRECORDER_INSTALL_SECRET"]
            ?? Self.loadOrCreateInstallSecret(in: appDataRoot)
            ?? Bundle.main.runtimeConfigInstallSecret()
            ?? "dev-install-secret"
        let providerRegistrationSecret = environment["WORKRECORDER_PROVIDER_REGISTRATION_SECRET"]
            ?? Self.loadOrCreateProviderRegistrationSecret(in: appDataRoot)
            ?? Bundle.main.runtimeConfigProviderRegistrationSecret()
            ?? "dev-provider-secret"
        let nativeCaptureSecret = environment["WORKRECORDER_NATIVE_CAPTURE_SECRET"]
            ?? Self.loadOrCreateNativeCaptureSecret(in: appDataRoot)
            ?? Bundle.main.runtimeConfigString(key: "native_capture_secret")
            ?? ""
        let configuredDaemonURL = URL(
            string: environment["WORKRECORDER_DAEMON_URL"]
                ?? Bundle.main.runtimeConfigString(key: "daemon_url")
                ?? "http://127.0.0.1:8765"
        )
            ?? URL(string: "http://127.0.0.1:8765")!
        let daemonURL = environment["WORKRECORDER_DAEMON_URL"].flatMap(URL.init(string:))
            ?? Self.loadLocalDaemonURL(in: appDataRoot)
            ?? configuredDaemonURL
        return RuntimeConfig(
            repoRoot: repoRoot,
            daemonURL: daemonURL,
            databasePath: environment["WORKRECORDER_DATABASE_PATH"].map(URL.init(fileURLWithPath:))
                ?? appDataRoot.appendingPathComponent("workrecorder.db"),
            stagingDirectory: environment["WORKRECORDER_ARTIFACT_STAGING_DIR"].map(URL.init(fileURLWithPath:))
                ?? appDataRoot.appendingPathComponent("staging", isDirectory: true),
            vaultDirectory: environment["WORKRECORDER_ARTIFACT_VAULT_DIR"].map(URL.init(fileURLWithPath:))
                ?? appDataRoot.appendingPathComponent("artifacts", isDirectory: true),
            installSecret: installSecret,
            providerRegistrationSecret: providerRegistrationSecret,
            nativeCaptureSecret: nativeCaptureSecret,
            feishuAppID: environment["WORKRECORDER_FEISHU_APP_ID"]
                ?? Bundle.main.runtimeConfigString(key: "feishu_app_id")
                ?? feishuPayload["feishu_app_id"],
            feishuAppSecret: environment["WORKRECORDER_FEISHU_APP_SECRET"]
                ?? Bundle.main.runtimeConfigString(key: "feishu_app_secret")
                ?? feishuPayload["feishu_app_secret"],
            feishuFolderToken: environment["WORKRECORDER_FEISHU_FOLDER_TOKEN"]
                ?? Bundle.main.runtimeConfigString(key: "feishu_folder_token")
                ?? feishuPayload["feishu_folder_token"],
            feishuAPIBaseURL: environment["WORKRECORDER_FEISHU_API_BASE_URL"]
                ?? Bundle.main.runtimeConfigString(key: "feishu_api_base_url")
                ?? feishuPayload["feishu_api_base_url"]
        )
    }

    var pythonExecutable: URL {
        repoRoot.appendingPathComponent(".venv/bin/python")
    }

    static func resolveStartupConfig(from bootstrap: RuntimeConfig) -> RuntimeConfig {
        let environment = ProcessInfo.processInfo.environment
        let appDataRoot = Self.appDataRoot(
            environment: environment,
            homeDirectory: FileManager.default.homeDirectoryForCurrentUser
        )
        let daemonURL = environment["WORKRECORDER_DAEMON_URL"] == nil
            ? DaemonEndpointResolver.resolvedDaemonURL(
                preferred: bootstrap.daemonURL,
                installSecret: bootstrap.installSecret,
                nativeCaptureSecret: bootstrap.nativeCaptureSecret
            )
            : bootstrap.daemonURL
        DaemonEndpointResolver.writeLocalConfig(
            appDataRoot: appDataRoot,
            daemonURL: daemonURL,
            installSecret: bootstrap.installSecret
        )
        return bootstrap.with(daemonURL: daemonURL)
    }

    private static func appDataRoot(environment: [String: String], homeDirectory home: URL) -> URL {
        if let rawPath = environment["WORKRECORDER_APP_DATA_ROOT"],
           !rawPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return URL(fileURLWithPath: rawPath, isDirectory: true)
        }
        return home.appendingPathComponent(".workrecorder/app-dev", isDirectory: true)
    }

    func hasSameRuntimeEndpoints(as other: RuntimeConfig) -> Bool {
        daemonURL == other.daemonURL
    }

    func with(daemonURL: URL) -> RuntimeConfig {
        RuntimeConfig(
            repoRoot: repoRoot,
            daemonURL: daemonURL,
            databasePath: databasePath,
            stagingDirectory: stagingDirectory,
            vaultDirectory: vaultDirectory,
            installSecret: installSecret,
            providerRegistrationSecret: providerRegistrationSecret,
            nativeCaptureSecret: nativeCaptureSecret,
            feishuAppID: feishuAppID,
            feishuAppSecret: feishuAppSecret,
            feishuFolderToken: feishuFolderToken,
            feishuAPIBaseURL: feishuAPIBaseURL
        )
    }

    private static func loadLocalDaemonURL(in appDataRoot: URL) -> URL? {
        let url = appDataRoot.appendingPathComponent("daemon-endpoint.json")
        guard let data = try? Data(contentsOf: url),
              let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let rawURL = payload["daemon_url"] as? String,
              let daemonURL = URL(string: rawURL),
              daemonURL.scheme == "http",
              ["127.0.0.1", "localhost"].contains(daemonURL.host ?? ""),
              daemonURL.port != nil
        else {
            return nil
        }
        return daemonURL
    }
}

@MainActor
final class AppLogStore {
    private(set) var entries: [String] = []

    func add(_ message: String) {
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm:ss"
        entries.append("[\(formatter.string(from: Date()))] \(message)")
        if entries.count > 80 {
            entries.removeFirst(entries.count - 80)
        }
    }

    func append(_ message: String) {
        add(message)
    }

    func joined() -> String {
        entries.joined(separator: "\n")
    }

    func recent(limit: Int) -> [String] {
        Array(entries.suffix(limit))
    }
}

enum DaemonSupervisorState: Equatable {
    case stopped
    case starting
    case runningExternal
    case runningOwned(processIdentifier: Int32)
    case portConflict
    case installSecretMismatch
    case failed(String)

    var label: String {
        localizedLabel
    }

    var localizedLabel: String {
        switch self {
        case .stopped:
            return "未启动"
        case .starting:
            return "启动中"
        case .runningExternal:
            return "已运行"
        case .runningOwned(let processIdentifier):
            return "已运行（pid \(processIdentifier)）"
        case .portConflict:
            return "端口冲突"
        case .installSecretMismatch:
            return "服务密钥不匹配"
        case .failed(let message):
            return "启动失败：\(message)"
        }
    }

    var isRunning: Bool {
        switch self {
        case .runningExternal, .runningOwned:
            true
        default:
            false
        }
    }

    var ownedProcessId: Int32? {
        switch self {
        case .runningOwned(let processIdentifier):
            processIdentifier
        default:
            nil
        }
    }
}

@MainActor
final class DaemonSupervisor {
    private let config: RuntimeConfig
    private let logs: AppLogStore
    private let externalDaemonOnly: Bool
    private var process: Process?
    private(set) var state: DaemonSupervisorState = .stopped

    init(config: RuntimeConfig, logs: AppLogStore) {
        self.config = config
        self.logs = logs
        self.externalDaemonOnly = ProcessInfo.processInfo.environment["WORKRECORDER_EXTERNAL_DAEMON"] == "1"
    }

    func health() async -> Bool {
        do {
            let (data, response) = try await URLSession.shared.data(from: config.daemonURL.appendingPathComponent("health"))
            guard let httpResponse = response as? HTTPURLResponse, (200..<300).contains(httpResponse.statusCode) else {
                return false
            }
            let payload = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            guard payload?["ok"] as? Bool == true,
                  let payloadData = payload?["data"] as? [String: Any]
            else {
                return false
            }
            return payloadData["service"] as? String == "workrecorder-local-daemon"
        } catch {
            return false
        }
    }

    func startIfNeeded() async {
        if externalDaemonOnly {
            if await health() {
                state = .runningExternal
                logs.add("复用脚本管理的外部 daemon：\(config.daemonURL.absoluteString)")
            } else {
                state = .failed("脚本管理的外部 daemon 未健康：\(config.daemonURL.absoluteString)")
                logs.add(state.label)
            }
            return
        }
        if state == .starting {
            if await waitForHealth(timeoutSeconds: 8) {
                if let process, process.isRunning {
                    state = .runningOwned(processIdentifier: process.processIdentifier)
                } else {
                    state = .runningExternal
                }
            }
            return
        }
        if let process, process.isRunning {
            if await waitForHealth(timeoutSeconds: 8) {
                guard await installSecretMatches() else {
                    logs.add("应用启动的 daemon install secret 不匹配，正在重启。")
                    stopOwnedProcess()
                    await launchOwnedDaemon()
                    return
                }
                state = .runningOwned(processIdentifier: process.processIdentifier)
                logs.add("应用启动的 daemon 已健康：pid \(process.processIdentifier)")
            } else {
                state = .starting
                logs.add("应用启动的 daemon 仍在启动：pid \(process.processIdentifier)")
            }
            return
        }
        state = .starting
        if await health() {
            guard await installSecretMatches() else {
                if await stopMismatchedWorkRecorderDaemon() {
                    await launchOwnedDaemon()
                    return
                }
                state = .installSecretMismatch
                logs.add("8765 上已有服务，但授权密钥不匹配，且不能确认它是 WorkRecorder 本地服务。")
                return
            }
            if let process, process.isRunning {
                state = .runningOwned(processIdentifier: process.processIdentifier)
            } else {
                state = .runningExternal
            }
            logs.add("已有健康 daemon：\(config.daemonURL.absoluteString)")
            return
        }
        guard await preparePortForOwnedDaemonLaunch() else {
            return
        }
        await launchOwnedDaemon()
    }

    private func preparePortForOwnedDaemonLaunch() async -> Bool {
        guard let port = config.daemonURL.port else {
            return true
        }
        let pids = listeningProcessIDs(port: port).filter { $0 != getpid() }
        guard !pids.isEmpty else {
            return true
        }
        let workRecorderPids = pids.filter { isWorkRecorderDaemon(processIdentifier: $0) }
        if !workRecorderPids.isEmpty {
            let pidList = workRecorderPids.map(String.init).joined(separator: ", ")
            logs.add("检测到旧 WorkRecorder 本地服务占用端口但未通过健康检查，正在停止：\(pidList)")
            stopProcessIDs(workRecorderPids, reason: "旧 daemon 端口占用")
            _ = await waitForPortFree(port: port, timeoutSeconds: 4)
        }
        let remaining = listeningProcessIDs(port: port).filter { $0 != getpid() }
        guard remaining.isEmpty else {
            state = .portConflict
            logs.add("端口 \(port) 已被占用，WorkRecorder 无法启动本机服务：\(describeProcesses(remaining))")
            return false
        }
        return true
    }

    private func launchOwnedDaemon() async {
        state = .starting
        guard FileManager.default.fileExists(atPath: config.pythonExecutable.path) else {
            state = .failed("未找到 Python 运行时：\(config.pythonExecutable.path)")
            logs.add(state.label)
            return
        }
        logs.add("正在从仓库启动 daemon：\(config.repoRoot.path)")
        let daemon = Process()
        daemon.executableURL = config.pythonExecutable
        daemon.currentDirectoryURL = config.repoRoot
        daemon.arguments = ["-m", "services.context_daemon.main"]
        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONPATH"] = config.repoRoot.path
        environment["WORKRECORDER_DAEMON_URL"] = config.daemonURL.absoluteString
        environment["WORKRECORDER_DATABASE_PATH"] = config.databasePath.path
        environment["WORKRECORDER_ARTIFACT_STAGING_DIR"] = config.stagingDirectory.path
        environment["WORKRECORDER_ARTIFACT_VAULT_DIR"] = config.vaultDirectory.path
        environment["WORKRECORDER_INSTALL_SECRET"] = config.installSecret
        environment["WORKRECORDER_PROVIDER_REGISTRATION_SECRET"] = config.providerRegistrationSecret
        environment["WORKRECORDER_NATIVE_CAPTURE_SECRET"] = config.nativeCaptureSecret
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONPYCACHEPREFIX"] = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".workrecorder/app-dev/pycache", isDirectory: true)
            .path
        if let feishuAppID = config.feishuAppID {
            environment["WORKRECORDER_FEISHU_APP_ID"] = feishuAppID
        }
        if let feishuAppSecret = config.feishuAppSecret {
            environment["WORKRECORDER_FEISHU_APP_SECRET"] = feishuAppSecret
        }
        if let feishuFolderToken = config.feishuFolderToken {
            environment["WORKRECORDER_FEISHU_FOLDER_TOKEN"] = feishuFolderToken
        }
        if let feishuAPIBaseURL = config.feishuAPIBaseURL {
            environment["WORKRECORDER_FEISHU_API_BASE_URL"] = feishuAPIBaseURL
        }
        daemon.environment = environment
        let output = Pipe()
        daemon.standardOutput = output
        daemon.standardError = output
        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            guard let chunk = String(data: handle.availableData, encoding: .utf8), !chunk.isEmpty else { return }
            Task { @MainActor in self?.logs.add(chunk.trimmingCharacters(in: .whitespacesAndNewlines)) }
        }
        do {
            try daemon.run()
            process = daemon
            logs.add("daemon 进程已启动：pid \(daemon.processIdentifier)")
            if await waitForHealth(timeoutSeconds: 12) {
                guard await installSecretMatches() else {
                    state = .installSecretMismatch
                    logs.add("daemon 已启动，但 install secret 探测失败。")
                    return
                }
                state = .runningOwned(processIdentifier: daemon.processIdentifier)
                logs.add("daemon 已健康：\(config.daemonURL.absoluteString)")
            } else if daemon.isRunning {
                state = .starting
                logs.add("daemon 仍在启动：pid \(daemon.processIdentifier)")
            } else {
                process = nil
                state = .failed(daemonEarlyExitMessage())
                logs.add(state.label)
            }
        } catch {
            state = .failed(error.localizedDescription)
            logs.add("daemon 启动失败：\(error.localizedDescription)")
        }
    }

    private func daemonEarlyExitMessage() -> String {
        let tail = logs
            .recent(limit: 8)
            .map(redactRuntimeSecret)
            .filter { !$0.isEmpty }
            .joined(separator: "\n")
        guard !tail.isEmpty else {
            return "daemon 在健康检查通过前退出"
        }
        return "daemon 在健康检查通过前退出。最近日志：\n\(tail)"
    }

    private func redactRuntimeSecret(_ text: String) -> String {
        var value = text
        for (secret, replacement) in [
            (config.installSecret, "[redacted-install-secret]"),
            (config.providerRegistrationSecret, "[redacted-provider-secret]"),
            (config.nativeCaptureSecret, "[redacted-native-capture-secret]"),
        ] where !secret.isEmpty {
            value = value.replacingOccurrences(of: secret, with: replacement)
        }
        return value
    }

    private func waitForHealth(timeoutSeconds: Double) async -> Bool {
        let deadline = Date().addingTimeInterval(timeoutSeconds)
        while Date() < deadline {
            if await health() {
                return true
            }
            try? await Task.sleep(nanoseconds: 250_000_000)
        }
        return false
    }

    private func installSecretMatches() async -> Bool {
        var request = URLRequest(url: config.daemonURL.appendingPathComponent("v1/auth/tokens"))
        request.httpMethod = "POST"
        request.addValue("application/json", forHTTPHeaderField: "content-type")
        request.addValue(config.installSecret, forHTTPHeaderField: "x-workrecorder-install-secret")
        let body: [String: Any] = [
            "actor_id": "workrecorder-workbench-probe",
            "display_name": "WorkRecorder 录制中心探测",
            "scopes": ["read_metadata"],
        ]
        request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                return false
            }
            let payload = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            guard payload?["ok"] as? Bool == true else {
                return false
            }
            return await nativeCaptureSecretMatches()
        } catch {
            return false
        }
    }

    private func nativeCaptureSecretMatches() async -> Bool {
        guard !config.nativeCaptureSecret.isEmpty, config.nativeCaptureSecret != config.installSecret else {
            return false
        }
        var request = URLRequest(url: config.daemonURL.appendingPathComponent("v1/auth/native-capture-authority"))
        request.httpMethod = "GET"
        request.addValue(config.nativeCaptureSecret, forHTTPHeaderField: "x-workrecorder-native-capture-secret")
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                return false
            }
            let payload = try JSONSerialization.jsonObject(with: data) as? [String: Any]
            return payload?["ok"] as? Bool == true
        } catch {
            return false
        }
    }

    private func stopMismatchedWorkRecorderDaemon() async -> Bool {
        guard let port = config.daemonURL.port else {
            return false
        }
        let pids = listeningProcessIDs(port: port).filter { $0 != getpid() }
        let workRecorderPids = pids.filter { isWorkRecorderDaemon(processIdentifier: $0) }
        guard !workRecorderPids.isEmpty else {
            return false
        }
        let pidList = workRecorderPids.map(String.init).joined(separator: ", ")
        logs.add("检测到旧 WorkRecorder 本地服务密钥不一致，正在停止：\(pidList)")
        stopProcessIDs(workRecorderPids, reason: "密钥不一致")
        _ = await waitForPortFree(port: port, timeoutSeconds: 4)
        return true
    }

    private func stopProcessIDs(_ processIdentifiers: [Int32], reason: String) {
        for pid in processIdentifiers {
            logs.add("正在停止 \(reason)：pid \(pid)")
            Darwin.kill(pid, SIGTERM)
        }
        let deadline = Date().addingTimeInterval(3)
        while Date() < deadline {
            if processIdentifiers.allSatisfy({ !processIsAlive($0) }) {
                break
            }
            Thread.sleep(forTimeInterval: 0.12)
        }
        for pid in processIdentifiers {
            guard processIsAlive(pid) else {
                continue
            }
            Darwin.kill(pid, SIGKILL)
            logs.add("已强制停止 \(reason)：pid \(pid)")
        }
    }

    private func waitForPortFree(port: Int, timeoutSeconds: Double) async -> Bool {
        let deadline = Date().addingTimeInterval(timeoutSeconds)
        while Date() < deadline {
            let pids = listeningProcessIDs(port: port).filter { $0 != getpid() }
            if pids.isEmpty {
                return true
            }
            try? await Task.sleep(nanoseconds: 200_000_000)
        }
        return listeningProcessIDs(port: port).filter { $0 != getpid() }.isEmpty
    }

    private func listeningProcessIDs(port: Int) -> [Int32] {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        process.arguments = ["-nP", "-tiTCP:\(port)", "-sTCP:LISTEN"]
        let output = Pipe()
        process.standardOutput = output
        process.standardError = Pipe()
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            logs.add("无法检查 daemon 端口占用：\(error.localizedDescription)")
            return []
        }
        let data = output.fileHandleForReading.readDataToEndOfFile()
        guard let text = String(data: data, encoding: .utf8) else {
            return []
        }
        return text
            .split(whereSeparator: \.isNewline)
            .compactMap { Int32($0.trimmingCharacters(in: .whitespaces)) }
    }

    private func isWorkRecorderDaemon(processIdentifier: Int32) -> Bool {
        let command = processCommand(processIdentifier: processIdentifier)
        return command.contains("services.context_daemon.main")
            || (command.contains("uvicorn") && command.contains("services.context_daemon"))
    }

    private func processCommand(processIdentifier: Int32) -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/ps")
        process.arguments = ["-p", "\(processIdentifier)", "-o", "command="]
        let output = Pipe()
        process.standardOutput = output
        process.standardError = Pipe()
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            return ""
        }
        let data = output.fileHandleForReading.readDataToEndOfFile()
        return String(data: data, encoding: .utf8) ?? ""
    }

    private func describeProcesses(_ processIdentifiers: [Int32]) -> String {
        processIdentifiers
            .map { pid in
                let command = processCommand(processIdentifier: pid)
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                return command.isEmpty ? "pid \(pid)" : "pid \(pid) · \(command)"
            }
            .joined(separator: "；")
    }

    private func processIsAlive(_ processIdentifier: Int32) -> Bool {
        Darwin.kill(processIdentifier, 0) == 0
    }

    func stopOwnedProcess() {
        guard let process else {
            return
        }
        let processIdentifier = process.processIdentifier
        logs.add("正在停止 daemon：pid \(processIdentifier)")
        process.terminate()
        let deadline = Date().addingTimeInterval(2)
        while process.isRunning && Date() < deadline {
            Thread.sleep(forTimeInterval: 0.05)
        }
        if process.isRunning {
            Darwin.kill(processIdentifier, SIGKILL)
            process.waitUntilExit()
            logs.add("已强制停止 daemon：pid \(processIdentifier)")
        }
        self.process = nil
        state = .stopped
    }
}
