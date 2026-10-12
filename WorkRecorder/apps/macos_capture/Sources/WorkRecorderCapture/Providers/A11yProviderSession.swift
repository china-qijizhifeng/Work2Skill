import AppKit
import ApplicationServices
import Foundation

@MainActor
final class A11yProviderSession {
    let providerWebSocketProtocol = "workrecorder-provider-v1"
    let tokenSubprotocolPrefix = "workrecorder-token."
    let daemonURL: URL
    let providerRegistrationSecret: String
    let providerSessionId = "macos_a11y_\(UUID().uuidString.replacingOccurrences(of: "-", with: ""))"
    let urlSession: URLSession
    let encoder: JSONEncoder
    let decoder: JSONDecoder
    let collector = MacOSA11yCollector()
    let heartbeatIntervalSeconds = 1.0
    var webSocket: URLSessionWebSocketTask?
    var heartbeatTask: Task<Void, Never>?
    var shouldReconnect = false

    init(environment: CaptureEnvironment, urlSession: URLSession = .shared) {
        daemonURL = environment.daemonURL
        providerRegistrationSecret = environment.providerRegistrationSecret
        self.urlSession = urlSession
        encoder = JSONEncoder()
        decoder = JSONDecoder()
        encoder.dateEncodingStrategy = .iso8601
        decoder.dateDecodingStrategy = .custom(ProviderDateCoding.decode)
    }

    func start() {
        shouldReconnect = true
        Task { [weak self] in
            await self?.connect()
        }
    }

    func stop() {
        shouldReconnect = false
        heartbeatTask?.cancel()
        webSocket?.cancel(with: .goingAway, reason: nil)
    }

    func connect() async {
        guard shouldReconnect else { return }
        do {
            let token = try await issueToken()
            let socketURL = providerSocketURL()
            let socket = urlSession.webSocketTask(
                with: socketURL,
                protocols: [providerWebSocketProtocol, "\(tokenSubprotocolPrefix)\(token)"]
            )
            webSocket = socket
            socket.resume()
            try await sendRegistration()
            startHeartbeat()
            await receiveLoop()
        } catch {
            scheduleReconnect()
        }
    }

    func receiveLoop() async {
        while !Task.isCancelled {
            do {
                guard let socket = webSocket else { return }
                let message = try await socket.receive()
                switch message {
                case .string(let value):
                    try await handleMessage(value)
                case .data:
                    continue
                @unknown default:
                    continue
                }
            } catch {
                NSLog("WorkRecorder a11y provider websocket receive failed; reconnecting")
                scheduleReconnect()
                return
            }
        }
    }

    func handleMessage(_ value: String) async throws {
        let header = try decoder.decode(ProviderMessageHeader.self, from: Data(value.utf8))
        guard header.messageType == "collect_evidence" else { return }
        let envelope = try decoder.decode(ProviderCommandEnvelope.self, from: Data(value.utf8))
        let collector = collector
        let providerSessionId = providerSessionId
        let result = await Task.detached(priority: .userInitiated) {
            collector.collect(command: envelope.command, providerSessionId: providerSessionId)
        }.value
        try await send(result)
    }

    func sendRegistration() async throws {
        let registration = ProviderSessionRegistration(
            schemaVersion: 1,
            providerKey: "system.macos_a11y",
            providerSessionId: providerSessionId,
            providerKind: "system_evidence",
            displayName: "macOS Accessibility Provider",
            appName: "macOS Accessibility",
            processId: nil,
            windowId: nil,
            capabilities: ["read_a11y"],
            registeredAt: Date(),
            ttlMs: 15000,
            metadata: ["transport": .string("local_websocket_v1")]
        )
        let message = ProviderSessionRegisterMessage(messageType: "provider_session_register", registration: registration)
        try await send(message)
    }

    func startHeartbeat() {
        heartbeatTask?.cancel()
        heartbeatTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(self?.heartbeatIntervalSeconds ?? 1.0))
                try? await self?.sendHeartbeat()
            }
        }
    }

    func sendHeartbeat() async throws {
        let heartbeat = ProviderHeartbeatMessage(
            messageType: "provider_heartbeat",
            heartbeat: ProviderHeartbeat(
                providerKey: "system.macos_a11y",
                providerSessionId: providerSessionId,
                observedAt: Date(),
                metadata: ["transport": .string("local_websocket_v1")]
            )
        )
        try await send(heartbeat)
    }

    func send<T: Encodable>(_ value: T) async throws {
        guard let socket = webSocket else { return }
        let data = try encoder.encode(value)
        let text = String(decoding: data, as: UTF8.self)
        try await socket.send(.string(text))
    }

    func issueToken() async throws -> String {
        var request = URLRequest(url: daemonURL.appendingPathComponent("v1/auth/tokens"))
        request.httpMethod = "POST"
        request.addValue("application/json", forHTTPHeaderField: "content-type")
        request.addValue(providerRegistrationSecret, forHTTPHeaderField: "x-workrecorder-provider-secret")
        let body = ProviderTokenRequest(
            actorId: "macos-a11y-provider",
            displayName: "macOS Accessibility Provider",
            scopes: ["register_provider_context"]
        )
        request.httpBody = try encoder.encode(body)
        let (data, response) = try await urlSession.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse, (200..<300).contains(httpResponse.statusCode) else {
            throw CaptureTransportError.invalidResponse
        }
        let envelope = try decoder.decode(ProviderTokenEnvelope.self, from: data)
        guard envelope.ok, let token = envelope.data?.accessToken else {
            throw CaptureTransportError.invalidResponse
        }
        return token
    }

    func providerSocketURL() -> URL {
        var components = URLComponents(url: daemonURL, resolvingAgainstBaseURL: false)!
        components.scheme = components.scheme == "https" ? "wss" : "ws"
        components.path = "/v1/providers/sessions/ws"
        return components.url!
    }

    func scheduleReconnect() {
        guard shouldReconnect else { return }
        heartbeatTask?.cancel()
        webSocket?.cancel(with: .goingAway, reason: nil)
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(2))
            await self?.connect()
        }
    }
}

enum ProviderDateCoding {
    static func decode(_ decoder: Decoder) throws -> Date {
        let container = try decoder.singleValueContainer()
        let rawValue = try container.decode(String.self)
        if let date = formatter(options: [.withInternetDateTime, .withFractionalSeconds]).date(from: rawValue)
            ?? formatter(options: [.withInternetDateTime]).date(from: rawValue)
        {
            return date
        }
        throw DecodingError.dataCorruptedError(
            in: container,
            debugDescription: "Invalid ISO8601 date: \(rawValue)"
        )
    }

    static func formatter(options: ISO8601DateFormatter.Options) -> ISO8601DateFormatter {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = options
        return formatter
    }
}

final class MacOSA11yCollector: @unchecked Sendable {
    let maxDepth = 16
    let maxNodes = 1_600
    let maxChildrenPerAttribute = 200
    let extractionRevision = "macos_a11y_v2"
    let sanitizer = A11yTextSanitizer()
    let childAttributeNames = [
        kAXChildrenAttribute,
        "AXChildrenInNavigationOrder",
        "AXVisibleChildren",
        "AXContents",
        "AXRows",
        "AXColumns"
    ]

















}

extension BoundingBox {
    init(_ rect: CGRect) {
        self.init(
            x: Int(rect.origin.x.rounded(.down)),
            y: Int(rect.origin.y.rounded(.down)),
            width: max(1, Int(rect.width.rounded())),
            height: max(1, Int(rect.height.rounded())),
            coordinateSpace: "macos_global"
        )
    }
}

struct ProviderTokenRequest: Codable {
    let actorId: String
    let displayName: String
    let scopes: [String]

    enum CodingKeys: String, CodingKey {
        case actorId = "actor_id"
        case displayName = "display_name"
        case scopes
    }
}

struct ProviderTokenEnvelope: Codable {
    let ok: Bool
    let data: ProviderTokenData?
}

struct ProviderTokenData: Codable {
    let accessToken: String

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
    }
}
