import Foundation

private struct WorkbenchRecordingVideoPlaybackRequest: Encodable {
    let eventId: String
    let artifactId: String
    let purpose: String

    enum CodingKeys: String, CodingKey {
        case eventId = "event_id"
        case artifactId = "artifact_id"
        case purpose
    }
}

enum WorkbenchClientError: Error, LocalizedError {
    case invalidURL(String)
    case invalidResponse
    case daemonRejected(String)
    case missingToken

    var errorDescription: String? {
        switch self {
        case .invalidURL(let path):
            return "daemon 地址无效：\(path)。"
        case .invalidResponse:
            return "daemon 返回了无法读取的响应。"
        case .daemonRejected(let message):
            return message
        case .missingToken:
            return "daemon 没有签发访问令牌。"
        }
    }
}

final class WorkbenchDaemonClient: @unchecked Sendable {
    private let config: RuntimeConfig
    private let session: URLSession

    init(config: RuntimeConfig, session: URLSession = .shared) {
        self.config = config
        self.session = session
    }

    func recordingCaptures(limit: Int = 1000, query: String = "") async throws -> [SearchCardView] {
        let encodedQuery = query.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
        let payload: WorkbenchSearchData = try await getEnvelope(
            path: "v1/active-captures/recordings?limit=\(limit)&query=\(encodedQuery)",
            scopes: ["read_text"]
        )
        return payload.results
    }

    func inspectEvent(
        eventId: String,
        includeCleanPageText: Bool = false,
        views requestedViews: [String]? = nil,
        purpose: String = "workbench_inspect"
    ) async throws -> WorkbenchEventInspectView {
        var views = requestedViews ?? [
            "evidence_refs",
            "artifact_metadata",
            "active_capture_summary",
            "recording_timeline",
            "video_ref",
            "human_demo_summary",
        ]
        if includeCleanPageText {
            views.append("clean_page_text")
        }
        return try await inspectEvent(eventId: eventId, views: views, purpose: purpose)
    }

    private func inspectEvent(
        eventId: String,
        views: [String],
        purpose: String
    ) async throws -> WorkbenchEventInspectView {
        let encodedId = eventId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? eventId
        let viewQuery = views.joined(separator: ",").addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
        let encodedPurpose = purpose.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "workbench_inspect"
        let path = "v1/events/\(encodedId)?view=event_inspect&purpose=\(encodedPurpose)&inspect_views=\(viewQuery)"
        let envelope: WorkbenchEnvelope<WorkbenchEventInspectView> = try await getRawEnvelope(
            path: path,
            scopes: ["read_text", "read_metadata"]
        )
        guard envelope.ok, let data = envelope.data else {
            throw WorkbenchClientError.daemonRejected(envelope.error?.message ?? "daemon 拒绝了请求。")
        }
        return data
    }

    func recordingVideoPlayback(
        sessionId: String,
        eventId: String,
        artifactId: String,
        purpose: String
    ) async throws -> WorkbenchRecordingVideoPlaybackView {
        let encodedSession = sessionId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? sessionId
        let token = try await issueToken(scopes: ["read_raw_artifact"])
        var request = try request(path: "v1/active-captures/\(encodedSession)/video/playback")
        request.httpMethod = "POST"
        request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        request.addValue("application/json", forHTTPHeaderField: "content-type")
        request.addValue("no-store", forHTTPHeaderField: "cache-control")
        request.addValue("no-cache", forHTTPHeaderField: "pragma")
        request.addValue("Bearer \(token)", forHTTPHeaderField: "authorization")
        request.addValue(config.installSecret, forHTTPHeaderField: "x-workrecorder-install-secret")
        request.httpBody = try JSONEncoder().encode(
            WorkbenchRecordingVideoPlaybackRequest(eventId: eventId, artifactId: artifactId, purpose: purpose)
        )
        return try await sendEnvelope(request)
    }

    func recordingExport(
        sessionId: String,
        outputRoot: String,
        purpose: String,
        fallbackMode: WorkbenchRecordingExportFallbackMode
    ) async throws -> WorkbenchRecordingExportView {
        let encodedSession = sessionId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? sessionId
        let token = try await issueToken(scopes: ["read_raw_artifact"])
        var request = try request(path: "v1/active-captures/\(encodedSession)/export")
        request.httpMethod = "POST"
        request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        request.addValue("application/json", forHTTPHeaderField: "content-type")
        request.addValue("no-store", forHTTPHeaderField: "cache-control")
        request.addValue("no-cache", forHTTPHeaderField: "pragma")
        request.addValue("Bearer \(token)", forHTTPHeaderField: "authorization")
        request.addValue(config.installSecret, forHTTPHeaderField: "x-workrecorder-install-secret")
        request.httpBody = try JSONEncoder().encode(
            WorkbenchRecordingExportRequest(
                outputRoot: outputRoot,
                purpose: purpose,
                fallbackMode: fallbackMode
            )
        )
        return try await sendEnvelope(request)
    }

    func updateShortcutSettings(_ settings: ShortcutSettings) async throws -> WorkbenchShortcutSettingsView {
        try await putEnvelope(
            path: "v1/settings/shortcuts",
            body: WorkbenchShortcutSettingsView(settings: settings),
            scopes: ["manage_local_settings"]
        )
    }

    func deleteEvent(eventId: String) async throws {
        let encodedId = eventId.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? eventId
        let _: WorkbenchDeleteEventData = try await deleteEnvelope(
            path: "v1/events/\(encodedId)",
            scopes: ["delete_event"]
        )
    }

    private func getEnvelope<Value: Decodable>(path: String, scopes: [String]) async throws -> Value {
        let envelope: WorkbenchEnvelope<Value> = try await getRawEnvelope(path: path, scopes: scopes)
        guard envelope.ok, let data = envelope.data else {
            throw WorkbenchClientError.daemonRejected(envelope.error?.message ?? "daemon 拒绝了请求。")
        }
        return data
    }

    private func getRawEnvelope<Value: Decodable>(
        path: String,
        scopes: [String]
    ) async throws -> WorkbenchEnvelope<Value> {
        let token = try await issueToken(scopes: scopes)
        var request = try request(path: path)
        request.httpMethod = "GET"
        request.addValue("Bearer \(token)", forHTTPHeaderField: "authorization")
        return try await sendRawEnvelope(request)
    }

    private func putEnvelope<Value: Decodable, Body: Encodable>(
        path: String,
        body: Body,
        scopes: [String]
    ) async throws -> Value {
        let token = try await issueToken(scopes: scopes)
        var request = try request(path: path)
        request.httpMethod = "PUT"
        request.addValue("application/json", forHTTPHeaderField: "content-type")
        request.addValue("Bearer \(token)", forHTTPHeaderField: "authorization")
        request.httpBody = try JSONEncoder().encode(body)
        return try await sendEnvelope(request)
    }

    private func deleteEnvelope<Value: Decodable>(path: String, scopes: [String]) async throws -> Value {
        let token = try await issueToken(scopes: scopes)
        var request = try request(path: path)
        request.httpMethod = "DELETE"
        request.addValue("Bearer \(token)", forHTTPHeaderField: "authorization")
        return try await sendEnvelope(request)
    }

    private func issueToken(scopes: [String]) async throws -> String {
        var request = try request(path: "v1/auth/tokens")
        request.httpMethod = "POST"
        request.addValue("application/json", forHTTPHeaderField: "content-type")
        request.addValue(config.installSecret, forHTTPHeaderField: "x-workrecorder-install-secret")
        request.httpBody = try JSONEncoder().encode(
            WorkbenchTokenRequest(actorId: "workrecorder-workbench", displayName: "WorkRecorder 录制中心", scopes: scopes)
        )
        let envelope: WorkbenchEnvelope<WorkbenchTokenData> = try await sendRawEnvelope(request)
        guard envelope.ok, let token = envelope.data?.accessToken else {
            throw WorkbenchClientError.missingToken
        }
        return token
    }

    private func request(path: String) throws -> URLRequest {
        guard let url = URL(string: path, relativeTo: config.daemonURL)?.absoluteURL else {
            throw WorkbenchClientError.invalidURL(path)
        }
        return URLRequest(url: url)
    }

    private func sendEnvelope<Value: Decodable>(_ request: URLRequest) async throws -> Value {
        let envelope: WorkbenchEnvelope<Value> = try await sendRawEnvelope(request)
        guard envelope.ok, let data = envelope.data else {
            throw WorkbenchClientError.daemonRejected(envelope.error?.message ?? "daemon 拒绝了请求。")
        }
        return data
    }

    private func sendRawEnvelope<Value: Decodable>(_ request: URLRequest) async throws -> WorkbenchEnvelope<Value> {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw WorkbenchClientError.invalidResponse
        }
        let envelope = try JSONDecoder().decode(WorkbenchEnvelope<Value>.self, from: data)
        if !(200..<300).contains(http.statusCode), !envelope.ok {
            throw WorkbenchClientError.daemonRejected(envelope.error?.message ?? "HTTP \(http.statusCode)")
        }
        return envelope
    }

}
