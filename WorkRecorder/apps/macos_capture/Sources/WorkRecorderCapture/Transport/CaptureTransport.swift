import Foundation

enum CaptureTransportError: Error, LocalizedError {
    case invalidResponse
    case daemonRejected(String)
    case unsupported(String)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "本地服务返回异常响应，请重启 WorkRecorder 后再试。"
        case .daemonRejected(let message), .unsupported(let message):
            return message
        }
    }
}

struct CaptureSaveResult: Equatable {
    let eventId: String?
}

struct ProducerEventSaveResult {
    let accepted: Bool
    let captureInstructions: [ActiveCaptureCaptureInstruction]
    let observedCandidateCount: Int
    let readyCandidateCount: Int
    let probeRequiredCandidateCount: Int

    init(
        accepted: Bool,
        captureInstructions: [ActiveCaptureCaptureInstruction],
        observedCandidateCount: Int = 0,
        readyCandidateCount: Int = 0,
        probeRequiredCandidateCount: Int = 0
    ) {
        self.accepted = accepted
        self.captureInstructions = captureInstructions
        self.observedCandidateCount = observedCandidateCount
        self.readyCandidateCount = readyCandidateCount
        self.probeRequiredCandidateCount = probeRequiredCandidateCount
    }
}

protocol ActiveCaptureProducerEventTransport: Sendable {
    func recordProducerEvent(
        sessionId: String,
        event: ActiveCaptureProducerEventCommand
    ) async throws -> ProducerEventSaveResult

    func recordProducerEvents(
        sessionId: String,
        events: [ActiveCaptureProducerEventCommand]
    ) async throws -> ProducerEventSaveResult

    func pollPendingCaptureInstructions(
        sessionId: String,
        probeSnapshot: ActiveCaptureSettleProbeSnapshot?,
        allowDegradedSample: Bool
    ) async throws -> ProducerEventSaveResult

    func reportCaptureInstructionFailure(
        sessionId: String,
        candidateId: String,
        reason: String,
        diagnostic: String
    ) async throws
}

extension ActiveCaptureProducerEventTransport {
    func recordProducerEvents(
        sessionId: String,
        events: [ActiveCaptureProducerEventCommand]
    ) async throws -> ProducerEventSaveResult {
        var accepted = events.isEmpty
        var instructions: [ActiveCaptureCaptureInstruction] = []
        for event in events {
            let result = try await recordProducerEvent(sessionId: sessionId, event: event)
            accepted = accepted || result.accepted
            instructions.append(contentsOf: result.captureInstructions)
        }
        return ProducerEventSaveResult(accepted: accepted, captureInstructions: instructions)
    }

    func reportCaptureInstructionFailure(
        sessionId: String,
        candidateId: String,
        reason: String,
        diagnostic: String
    ) async throws {}
}

final class CaptureTransport: ActiveCaptureProducerEventTransport, @unchecked Sendable {
    let daemonURL: URL
    let installSecret: String
    let nativeCaptureSecret: String?
    let session: URLSession
    let encoder: JSONEncoder
    let decoder: JSONDecoder
    private let accessTokenCache = CaptureAccessTokenCache()

    init(
        daemonURL: URL,
        installSecret: String,
        nativeCaptureSecret: String? = nil,
        session: URLSession = .shared
    ) {
        self.daemonURL = daemonURL
        self.installSecret = installSecret
        self.nativeCaptureSecret = nativeCaptureSecret
        self.session = session
        self.encoder = JSONEncoder()
        self.decoder = JSONDecoder()
        encoder.dateEncodingStrategy = .iso8601
        decoder.dateDecodingStrategy = .custom(ProviderDateCoding.decode)
    }

    func saveCapture(
        _ request: CaptureAttemptRequest,
        trustedNativeTiming: Bool = false
    ) async throws -> CaptureSaveResult {
        let token = try await issueToken(scopes: ["create_event"])
        var httpRequest = URLRequest(url: daemonURL.appendingPathComponent("v1/captures"))
        httpRequest.httpMethod = "POST"
        httpRequest.addValue("application/json", forHTTPHeaderField: "content-type")
        httpRequest.addValue("Bearer \(token)", forHTTPHeaderField: "authorization")
        if trustedNativeTiming,
           let nativeCaptureSecret,
           !nativeCaptureSecret.isEmpty,
           nativeCaptureSecret != installSecret {
            httpRequest.addValue(nativeCaptureSecret, forHTTPHeaderField: "x-workrecorder-native-capture-secret")
        }
        httpRequest.httpBody = try encoder.encode(request)
        let (data, response) = try await session.data(for: httpRequest)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw CaptureTransportError.invalidResponse
        }
        if !(200..<300).contains(httpResponse.statusCode) {
            throw CaptureTransportError.daemonRejected(Self.errorMessage(from: data, fallback: "本地 daemon 拒绝了这次保存。"))
        }
        let envelope = try decoder.decode(CaptureAttemptEnvelope.self, from: data)
        if envelope.data?.status == "unsupported" {
            throw CaptureTransportError.unsupported(envelope.data?.message ?? "录制关键帧没有保存成功，请稍后重试。")
        }
        return CaptureSaveResult(eventId: envelope.data?.event?.eventId)
    }

    func issueToken(scopes: [String]) async throws -> String {
        let cacheKey = scopes.sorted().joined(separator: "\u{1f}")
        if let cached = accessTokenCache.validToken(for: cacheKey, now: Date()) {
            return cached
        }
        var request = URLRequest(url: daemonURL.appendingPathComponent("v1/auth/tokens"))
        request.httpMethod = "POST"
        request.addValue("application/json", forHTTPHeaderField: "content-type")
        request.addValue(installSecret, forHTTPHeaderField: "x-workrecorder-install-secret")
        let body = TokenRequest(
            actorId: "macos-capture",
            displayName: "WorkRecorder",
            scopes: scopes
        )
        request.httpBody = try encoder.encode(body)
        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw CaptureTransportError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw CaptureTransportError.daemonRejected(Self.errorMessage(from: data, fallback: "本地服务授权失败，请重启 WorkRecorder。"))
        }
        let envelope = try decoder.decode(TokenEnvelope.self, from: data)
        guard envelope.ok, let tokenData = envelope.data else {
            throw CaptureTransportError.daemonRejected(Self.errorMessage(from: data, fallback: "本地服务授权失败，请重启 WorkRecorder。"))
        }
        // Daemon tokens normally live for ten minutes. Respect the returned
        // expiry when present and use a conservative five-minute fallback for
        // older/test daemons that omit claims. This avoids issuing and auditing
        // a fresh token for every 500 ms settle poll and every input batch.
        let expiresAt = tokenData.claims?.expiresAt ?? Date().addingTimeInterval(5 * 60)
        accessTokenCache.store(tokenData.accessToken, expiresAt: expiresAt, for: cacheKey)
        return tokenData.accessToken
    }

    static func errorMessage(from data: Data, fallback: String) -> String {
        guard let envelope = try? JSONDecoder().decode(ErrorEnvelope.self, from: data) else {
            return fallback
        }
        if envelope.error?.code == "auth.invalid" {
            return "WorkRecorder 与本地服务的授权密钥不一致，请重启 WorkRecorder。"
        }
        guard let message = envelope.error?.message, !message.isEmpty else {
            return fallback
        }
        return sanitizedUserFacingError(message, fallback: fallback)
    }

    private static func sanitizedUserFacingError(_ raw: String, fallback: String) -> String {
        var value = raw
        let replacements: [(String, String)] = [
            (#"(?i)bearer\s+[A-Za-z0-9._~+/\-=]+"#, "Bearer [redacted]"),
            (#"(?i)(token|file_token|access_token|install_secret|secret)=([^&\s]+)"#, "$1=[redacted]"),
            (#"(?i)"(token|file_token|access_token|install_secret|secret)"\s*:\s*"[^"]+""#, "\"$1\":\"[redacted]\""),
            (#"(?i)(?:/users|/private|/tmp|/var/folders)/[^\s,\"'\\]\\)]+"#, "[local-path]"),
            (#"https://[^\s\"']*(?:feishu\.cn|larksuite\.com)/[^\s\"']+"#, "[feishu-link]"),
        ]
        for (pattern, replacement) in replacements {
            value = value.replacingOccurrences(of: pattern, with: replacement, options: .regularExpression)
        }
        if value != raw {
            return fallback
        }
        return value.count > 180 ? fallback : value
    }
}

private struct TokenRequest: Codable {
    let actorId: String
    let displayName: String
    let scopes: [String]

    enum CodingKeys: String, CodingKey {
        case actorId = "actor_id"
        case displayName = "display_name"
        case scopes
    }
}

private struct TokenEnvelope: Codable {
    let ok: Bool
    let data: TokenData?
}

private struct TokenData: Codable {
    let accessToken: String
    let claims: TokenClaims?

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case claims
    }
}

private struct TokenClaims: Codable {
    let expiresAt: Date

    enum CodingKeys: String, CodingKey {
        case expiresAt = "expires_at"
    }
}

private final class CaptureAccessTokenCache: @unchecked Sendable {
    private struct Entry {
        let token: String
        let expiresAt: Date
    }

    private let lock = NSLock()
    private var entries: [String: Entry] = [:]

    func validToken(for key: String, now: Date) -> String? {
        lock.lock()
        defer { lock.unlock() }
        guard let entry = entries[key], entry.expiresAt.timeIntervalSince(now) > 30 else {
            entries.removeValue(forKey: key)
            return nil
        }
        return entry.token
    }

    func store(_ token: String, expiresAt: Date, for key: String) {
        lock.lock()
        entries[key] = Entry(token: token, expiresAt: expiresAt)
        lock.unlock()
    }
}

private struct ErrorEnvelope: Codable {
    let error: ErrorData?
}

private struct ErrorData: Codable {
    let code: String
    let message: String
}
