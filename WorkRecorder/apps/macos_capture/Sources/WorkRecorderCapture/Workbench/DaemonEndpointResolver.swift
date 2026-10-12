import Darwin
import Foundation

private final class EndpointProbeResultBox: @unchecked Sendable {
    private let lock = NSLock()
    private var data: Data?
    private var status: Int?

    func record(data: Data?, response: URLResponse?) {
        lock.lock()
        defer { lock.unlock() }
        self.data = data
        status = (response as? HTTPURLResponse)?.statusCode
    }

    func snapshot() -> (data: Data?, status: Int?) {
        lock.lock()
        defer { lock.unlock() }
        return (data, status)
    }
}

enum DaemonEndpointResolver {
    static func resolvedDaemonURL(preferred: URL, installSecret: String, nativeCaptureSecret: String) -> URL {
        resolvedDaemonURL(
            preferred: preferred,
            listeningProcessIDs: listeningProcessIDs(port:),
            authorityProbe: { url in
                isTrustedWorkRecorderDaemon(
                    at: url,
                    installSecret: installSecret,
                    nativeCaptureSecret: nativeCaptureSecret
                )
            }
        )
    }

    static func resolvedDaemonURL(
        preferred: URL,
        listeningProcessIDs: (Int) -> [Int32],
        authorityProbe: (URL) -> Bool
    ) -> URL {
        guard let preferredPort = preferred.port,
              preferred.scheme == "http",
              ["127.0.0.1", "localhost"].contains(preferred.host ?? "")
        else {
            return preferred
        }
        let currentOwners = listeningProcessIDs(preferredPort).filter { $0 != getpid() }
        guard !currentOwners.isEmpty else {
            return preferred
        }
        if authorityProbe(preferred) {
            return preferred
        }
        for candidatePort in 8766...8799 {
            guard listeningProcessIDs(candidatePort).filter({ $0 != getpid() }).isEmpty else {
                continue
            }
            return url(preferred, replacingPortWith: candidatePort) ?? preferred
        }
        return preferred
    }

    static func writeLocalConfig(appDataRoot: URL, daemonURL: URL, installSecret: String) {
        let payload: [String: String] = [
            "daemon_url": daemonURL.absoluteString,
            "install_secret": installSecret,
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.prettyPrinted, .sortedKeys]) else {
            return
        }
        do {
            try FileManager.default.createDirectory(at: appDataRoot, withIntermediateDirectories: true)
            let url = appDataRoot.appendingPathComponent("daemon-endpoint.json")
            try data.write(to: url, options: .atomic)
            try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
        } catch {
            return
        }
    }

    private static func url(_ url: URL, replacingPortWith port: Int) -> URL? {
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        components?.port = port
        return components?.url
    }

    private static func isTrustedWorkRecorderDaemon(
        at url: URL,
        installSecret: String,
        nativeCaptureSecret: String
    ) -> Bool {
        guard isHealthyWorkRecorderDaemon(at: url),
              !installSecret.isEmpty,
              !nativeCaptureSecret.isEmpty,
              nativeCaptureSecret != installSecret
        else {
            return false
        }
        guard let tokenResponse = httpJSON(
            url: url.appendingPathComponent("v1/auth/tokens"),
            method: "POST",
            headers: [
                "content-type": "application/json",
                "x-workrecorder-install-secret": installSecret,
            ],
            body: [
                "actor_id": "workrecorder-app-endpoint-probe",
                "display_name": "WorkRecorder endpoint probe",
                "scopes": ["read_metadata"],
            ]
        ),
              tokenResponse["ok"] as? Bool == true
        else {
            return false
        }
        guard let nativeResponse = httpJSON(
            url: url.appendingPathComponent("v1/auth/native-capture-authority"),
            method: "GET",
            headers: ["x-workrecorder-native-capture-secret": nativeCaptureSecret],
            body: nil
        ) else {
            return false
        }
        return nativeResponse["ok"] as? Bool == true
    }

    private static func isHealthyWorkRecorderDaemon(at url: URL) -> Bool {
        guard let payload = httpJSON(
            url: url.appendingPathComponent("health"),
            method: "GET",
            headers: [:],
            body: nil
        ) else {
            return false
        }
        guard payload["ok"] as? Bool == true,
              let data = payload["data"] as? [String: Any]
        else {
            return false
        }
        return data["service"] as? String == "workrecorder-local-daemon"
    }

    private static func httpJSON(
        url: URL,
        method: String,
        headers: [String: String],
        body: [String: Any]?
    ) -> [String: Any]? {
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 0.8
        for (name, value) in headers {
            request.setValue(value, forHTTPHeaderField: name)
        }
        if let body {
            guard JSONSerialization.isValidJSONObject(body),
                  let data = try? JSONSerialization.data(withJSONObject: body)
            else {
                return nil
            }
            request.httpBody = data
        }

        let resultBox = EndpointProbeResultBox()
        let semaphore = DispatchSemaphore(value: 0)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 0.8
        configuration.timeoutIntervalForResource = 0.8
        let session = URLSession(configuration: configuration)
        let task = session.dataTask(with: request) { data, response, _ in
            resultBox.record(data: data, response: response)
            semaphore.signal()
        }
        task.resume()
        guard semaphore.wait(timeout: .now() + 0.9) == .success else {
            task.cancel()
            session.invalidateAndCancel()
            return nil
        }
        session.finishTasksAndInvalidate()
        let result = resultBox.snapshot()
        guard let status = result.status,
              (200..<300).contains(status),
              let data = result.data
        else {
            return nil
        }
        return try? JSONSerialization.jsonObject(with: data) as? [String: Any]
    }

    private static func listeningProcessIDs(port: Int) -> [Int32] {
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

}
