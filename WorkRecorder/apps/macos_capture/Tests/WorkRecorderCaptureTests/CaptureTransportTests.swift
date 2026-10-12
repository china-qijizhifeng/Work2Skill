import Foundation
import Testing
@testable import WorkRecorderCapture

@Suite(.serialized)
struct CaptureTransportTests {
    @Test func saveCaptureAcceptsSuccessfulAttempt() async throws {
        let transport = Self.transport { request in
            switch request.url?.path {
            case "/v1/auth/tokens":
                return Self.tokenResponse()
            case "/v1/captures":
                return Self.captureResponse(status: "accepted", eventId: "evt_transport_saved")
            default:
                return Self.response(statusCode: 404, body: "{}")
            }
        }

        let result = try await transport.saveCapture(Self.captureAttempt())

        let paths = URLProtocolStub.requests().compactMap { $0.url?.path }
        #expect(paths == ["/v1/auth/tokens", "/v1/captures"])
        #expect(result.eventId == "evt_transport_saved")
        let captureBody = try #require(URLProtocolStub.jsonBodies().last)
        #expect(captureBody["schema_version"] as? Int == 1)
        #expect((captureBody["trigger"] as? [String: Any])?["trigger_type"] as? String == "manual_os_region_hotkey")
        #expect((captureBody["trigger"] as? [String: Any])?["capture_strategy"] as? String == "os_region")
        #expect((captureBody["window_hints"] as? [[String: Any]])?.first?["app_name"] as? String == "Google Chrome")
    }

    @Test func saveCaptureReportsUnsupportedAttempt() async throws {
        let unsupportedMessage = "录制关键帧没有保存成功，请稍后重试。"
        let transport = Self.transport { request in
            switch request.url?.path {
            case "/v1/auth/tokens":
                return Self.tokenResponse()
            case "/v1/captures":
                return Self.captureResponse(status: "unsupported", message: unsupportedMessage)
            default:
                return Self.response(statusCode: 404, body: "{}")
            }
        }

        do {
            _ = try await transport.saveCapture(Self.captureAttempt())
            Issue.record("Expected unsupported capture response")
        } catch CaptureTransportError.unsupported(let message) {
            #expect(message == unsupportedMessage)
        } catch {
            Issue.record("Expected unsupported error, got \(error)")
        }
    }

    @Test func saveCaptureSurfacesDaemonReject() async throws {
        let transport = Self.transport { request in
            switch request.url?.path {
            case "/v1/auth/tokens":
                return Self.tokenResponse()
            case "/v1/captures":
                return Self.response(statusCode: 500, body: "capture failed")
            default:
                return Self.response(statusCode: 404, body: "{}")
            }
        }

        do {
            _ = try await transport.saveCapture(Self.captureAttempt())
            Issue.record("Expected daemon rejection")
        } catch CaptureTransportError.daemonRejected(let body) {
            #expect(body == "本地 daemon 拒绝了这次保存。")
        } catch {
            Issue.record("Expected daemonRejected error, got \(error)")
        }
    }

    @Test func tokenFailureStopsBeforeCaptureSubmit() async throws {
        let transport = Self.transport { request in
            switch request.url?.path {
            case "/v1/auth/tokens":
                return Self.response(statusCode: 403, body: "{}")
            default:
                return Self.response(statusCode: 500, body: "{}")
            }
        }

        do {
            _ = try await transport.saveCapture(Self.captureAttempt())
            Issue.record("Expected token rejection")
        } catch CaptureTransportError.daemonRejected(let message) {
            #expect(message == "本地服务授权失败，请重启 WorkRecorder。")
            let paths = URLProtocolStub.requests().compactMap { $0.url?.path }
            #expect(paths == ["/v1/auth/tokens"])
        } catch {
            Issue.record("Expected daemonRejected error, got \(error)")
        }
    }

    @Test func timeoutPropagatesWithoutRetryingCapture() async throws {
        let transport = Self.transport { request in
            if request.url?.path == "/v1/auth/tokens" {
                throw URLError(.timedOut)
            }
            return Self.response(statusCode: 500, body: "{}")
        }

        do {
            _ = try await transport.saveCapture(Self.captureAttempt())
            Issue.record("Expected timeout")
        } catch let error as URLError {
            #expect(error.code == .timedOut)
            let paths = URLProtocolStub.requests().compactMap { $0.url?.path }
            #expect(paths == ["/v1/auth/tokens"])
        } catch {
            Issue.record("Expected URLError.timedOut, got \(error)")
        }
    }

    @Test func installSecretIsOnlySentToTokenEndpoint() async throws {
        let transport = Self.transport { request in
            switch request.url?.path {
            case "/v1/auth/tokens":
                return Self.tokenResponse(accessToken: "provider-token")
            case "/v1/captures":
                return Self.captureResponse(status: "accepted")
            default:
                return Self.response(statusCode: 404, body: "{}")
            }
        }

        _ = try await transport.saveCapture(Self.captureAttempt())

        let requests = URLProtocolStub.requests()
        #expect(requests.count == 2)
        #expect(requests[0].value(forHTTPHeaderField: "x-workrecorder-install-secret") == "install-secret")
        #expect(requests[1].value(forHTTPHeaderField: "x-workrecorder-install-secret") == nil)
        #expect(requests[1].value(forHTTPHeaderField: "authorization") == "Bearer provider-token")
    }

    @Test func nativeTimingCaptureSendsNativeSecretToCaptureEndpoint() async throws {
        let transport = Self.transport { request in
            switch request.url?.path {
            case "/v1/auth/tokens":
                return Self.tokenResponse(accessToken: "provider-token")
            case "/v1/captures":
                #expect(request.value(forHTTPHeaderField: "x-workrecorder-install-secret") == nil)
                #expect(request.value(forHTTPHeaderField: "x-workrecorder-native-capture-secret") == "native-secret")
                return Self.captureResponse(status: "accepted", eventId: "evt_native_timing")
            default:
                return Self.response(statusCode: 404, body: "{}")
            }
        }

        let result = try await transport.saveCapture(Self.nativeTimingCaptureAttempt(), trustedNativeTiming: true)

        let requests = URLProtocolStub.requests()
        #expect(requests.count == 2)
        #expect(requests[0].value(forHTTPHeaderField: "x-workrecorder-install-secret") == "install-secret")
        #expect(requests[1].value(forHTTPHeaderField: "x-workrecorder-install-secret") == nil)
        #expect(requests[1].value(forHTTPHeaderField: "x-workrecorder-native-capture-secret") == "native-secret")
        #expect(result.eventId == "evt_native_timing")
    }

    @Test func nativeTimingCaptureDefaultsToUntrustedCaptureSubmit() async throws {
        let transport = Self.transport { request in
            switch request.url?.path {
            case "/v1/auth/tokens":
                return Self.tokenResponse(accessToken: "provider-token")
            case "/v1/captures":
                #expect(request.value(forHTTPHeaderField: "x-workrecorder-install-secret") == nil)
                #expect(request.value(forHTTPHeaderField: "x-workrecorder-native-capture-secret") == nil)
                return Self.response(
                    statusCode: 403,
                    body: #"{"error":{"code":"policy_denied","message":"Native timing receipts require trusted local native authority"}}"#
                )
            default:
                return Self.response(statusCode: 404, body: "{}")
            }
        }

        do {
            _ = try await transport.saveCapture(Self.nativeTimingCaptureAttempt())
            Issue.record("Expected native timing capture rejection without trusted header")
        } catch CaptureTransportError.daemonRejected(let message) {
            #expect(message == "Native timing receipts require trusted local native authority")
        } catch {
            Issue.record("Expected daemonRejected error, got \(error)")
        }
    }

    @Test func nativeTimingCaptureDoesNotFallbackToInstallSecret() async throws {
        URLProtocolStub.configure { request in
            switch request.url?.path {
            case "/v1/auth/tokens":
                return Self.tokenResponse(accessToken: "provider-token")
            case "/v1/captures":
                #expect(request.value(forHTTPHeaderField: "x-workrecorder-native-capture-secret") == nil)
                return Self.response(
                    statusCode: 403,
                    body: #"{"error":{"code":"policy_denied","message":"Native timing receipts require trusted local native authority"}}"#
                )
            default:
                return Self.response(statusCode: 404, body: "{}")
            }
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [URLProtocolStub.self]
        let transport = CaptureTransport(
            daemonURL: URL(string: "http://workrecorder.test")!,
            installSecret: "install-secret",
            nativeCaptureSecret: "install-secret",
            session: URLSession(configuration: configuration)
        )

        do {
            _ = try await transport.saveCapture(Self.nativeTimingCaptureAttempt(), trustedNativeTiming: true)
            Issue.record("Expected native timing capture rejection when native secret equals install secret")
        } catch CaptureTransportError.daemonRejected(let message) {
            #expect(message == "Native timing receipts require trusted local native authority")
        } catch {
            Issue.record("Expected daemonRejected error, got \(error)")
        }
    }

    @MainActor
    @Test func a11yProviderUsesProviderSecretForTokenIssue() async throws {
        URLProtocolStub.configure { request in
            #expect(request.url?.path == "/v1/auth/tokens")
            #expect(request.value(forHTTPHeaderField: "x-workrecorder-provider-secret") == "provider-secret")
            #expect(request.value(forHTTPHeaderField: "x-workrecorder-install-secret") == nil)
            return Self.tokenResponse(accessToken: "a11y-provider-token")
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [URLProtocolStub.self]
        let session = URLSession(configuration: configuration)
        let provider = A11yProviderSession(
            environment: CaptureEnvironment(
                daemonURL: URL(string: "http://workrecorder.test")!,
                installSecret: "install-secret",
                nativeCaptureSecret: "native-secret",
                providerRegistrationSecret: "provider-secret",
                stagingDirectory: URL(fileURLWithPath: "/tmp")
            ),
            urlSession: session
        )

        let token = try await provider.issueToken()

        #expect(token == "a11y-provider-token")
    }

    @Test func a11yCollectorSkipsWorkRecorderOwnProcess() throws {
        let command = CollectEvidenceCommand(
            commandId: "cmd_self_a11y",
            providerKey: "system.macos_a11y",
            attempt: Self.captureAttempt(),
            surface: DetectedSurface(
                surfaceId: "surface_self",
                kind: "desktop_window",
                appName: "WorkRecorder",
                title: "录制库",
                processId: Int(ProcessInfo.processInfo.processIdentifier),
                windowId: "workrecorder-window",
                frame: nil,
                overlapRatio: 1,
                confidence: 1
            ),
            deadlineMs: 1_500
        )

        let snapshot = MacOSA11yCollector().snapshot(for: command)

        #expect(snapshot.permissionState == "skipped_self_app")
        #expect(snapshot.coverage.errorMessage == "WorkRecorder does not collect accessibility evidence from its own windows")
        #expect(snapshot.rootNodes.isEmpty)
        #expect(snapshot.fullText.isEmpty)
    }
}

extension CaptureTransportTests {
    private static func transport(
        handler: @escaping (URLRequest) throws -> StubbedHTTPResponse
    ) -> CaptureTransport {
        URLProtocolStub.configure(handler: handler)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [URLProtocolStub.self]
        let session = URLSession(configuration: configuration)
        return CaptureTransport(
            daemonURL: URL(string: "http://workrecorder.test")!,
            installSecret: "install-secret",
            nativeCaptureSecret: "native-secret",
            session: session
        )
    }

    private static func tokenResponse(accessToken: String = "capture-token") -> StubbedHTTPResponse {
        Self.response(body: #"{"ok":true,"data":{"access_token":"\#(accessToken)"}}"#)
    }

    private static func captureResponse(status: String, message: String? = nil, eventId: String? = nil) -> StubbedHTTPResponse {
        let encodedMessage = message.map { #""\#($0)""# } ?? "null"
        let encodedEvent = eventId.map { #","event":{"event_id":"\#($0)"}"# } ?? ""
        return Self.response(body: #"{"ok":true,"data":{"status":"\#(status)","message":\#(encodedMessage)\#(encodedEvent)}}"#)
    }

    private static func response(statusCode: Int = 200, body: String) -> StubbedHTTPResponse {
        StubbedHTTPResponse(statusCode: statusCode, body: Data(body.utf8))
    }

    private static func captureAttempt() -> CaptureAttemptRequest {
        let now = Date(timeIntervalSince1970: 1_700_000_000)
        let actor = ActorRef(actorId: "macos-capture", displayName: "WorkRecorder Capture")
        let selectedRegion = BoundingBox(
            x: -120,
            y: 84,
            width: 640,
            height: 360,
            coordinateSpace: "macos_global"
        )
        return CaptureAttemptRequest(
            schemaVersion: 1,
            trigger: TriggerEnvelope(
                triggerId: "trg_swift_transport",
                triggerType: "manual_os_region_hotkey",
                captureStrategy: "os_region",
                actor: actor,
                occurredAt: now,
                selection: selectedRegion,
                intentText: "pricing",
                surfaceId: nil,
                deviceId: "display-main",
                metadata: [:]
            ),
            selectionGeometry: SelectionGeometry(
                selectedRegion: selectedRegion,
                display: DisplayGeometry(
                    displayId: "main",
                    frame: BoundingBox(x: -400, y: 0, width: 1440, height: 900, coordinateSpace: "macos_global"),
                    scaleFactor: 2.0
                ),
                pixelRegion: nil
            ),
            windowHints: [
                WindowHint(
                    appName: "Google Chrome",
                    title: "ACME Pricing",
                    processId: 4242,
                    windowId: "chrome-window",
                    frame: selectedRegion,
                    overlapRatio: 1.0,
                    confidence: 0.91
                )
            ],
            workspace: WorkspaceSelection(workspaceId: "auto", label: "自动工作区", auto: true),
            actor: actor,
            stagedArtifact: StagedArtifactRef(
                localPath: "/tmp/workrecorder-staging/capture.png",
                artifactType: "screenshot",
                contentType: "image/png",
                filename: "capture.png",
                metadata: [:]
            ),
            intentText: "pricing",
            metadata: [:]
        )
    }

    private static func nativeTimingCaptureAttempt() -> CaptureAttemptRequest {
        var request = Self.captureAttempt()
        request.nativeTimingReceipt = NativeCaptureTimingReceipt(
            authority: "macos_capture",
            capturedAtMonotonicMs: 1_234,
            sourceClock: "system_uptime_ms",
            recordedAtWallTime: Date(timeIntervalSince1970: 1_700_000_001),
            metadata: [:]
        )
        return request
    }

}

struct StubbedHTTPResponse {
    let statusCode: Int
    let body: Data
    let headers: [String: String]

    init(statusCode: Int, body: Data, headers: [String: String] = ["content-type": "application/json"]) {
        self.statusCode = statusCode
        self.body = body
        self.headers = headers
    }
}

final class URLProtocolStub: URLProtocol, @unchecked Sendable {
    private final class State: @unchecked Sendable {
        private let lock = NSLock()
        private var handler: ((URLRequest) throws -> StubbedHTTPResponse)?
        private var capturedRequests: [URLRequest] = []
        private var capturedBodies: [[String: Any]] = []

        func configure(handler: @escaping (URLRequest) throws -> StubbedHTTPResponse) {
            lock.lock()
            self.handler = handler
            capturedRequests = []
            capturedBodies = []
            lock.unlock()
        }

        func response(for request: URLRequest) throws -> StubbedHTTPResponse {
            let jsonBody = Self.jsonBody(from: request)
            lock.lock()
            capturedRequests.append(request)
            if let jsonBody {
                capturedBodies.append(jsonBody)
            }
            let currentHandler = handler
            lock.unlock()
            guard let currentHandler else {
                throw URLError(.badServerResponse)
            }
            return try currentHandler(request)
        }

        func requests() -> [URLRequest] {
            lock.lock()
            let requests = capturedRequests
            lock.unlock()
            return requests
        }

        func jsonBodies() -> [[String: Any]] {
            lock.lock()
            let bodies = capturedBodies
            lock.unlock()
            return bodies
        }

        private static func jsonBody(from request: URLRequest) -> [String: Any]? {
            let body = request.httpBody ?? data(from: request.httpBodyStream)
            guard let body,
                  let object = try? JSONSerialization.jsonObject(with: body) as? [String: Any]
            else {
                return nil
            }
            return object
        }

        private static func data(from stream: InputStream?) -> Data? {
            guard let stream else { return nil }
            stream.open()
            defer { stream.close() }
            var data = Data()
            var buffer = [UInt8](repeating: 0, count: 4096)
            while stream.hasBytesAvailable {
                let read = stream.read(&buffer, maxLength: buffer.count)
                if read < 0 {
                    return nil
                }
                if read == 0 {
                    break
                }
                data.append(buffer, count: read)
            }
            return data.isEmpty ? nil : data
        }
    }

    private static let state = State()

    static func configure(handler: @escaping (URLRequest) throws -> StubbedHTTPResponse) {
        state.configure(handler: handler)
    }

    static func requests() -> [URLRequest] {
        state.requests()
    }

    static func jsonBodies() -> [[String: Any]] {
        state.jsonBodies()
    }

    override class func canInit(with request: URLRequest) -> Bool {
        true
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest {
        request
    }

    override func startLoading() {
        do {
            let response = try Self.state.response(for: request)
            guard let url = request.url,
                  let httpResponse = HTTPURLResponse(
                      url: url,
                      statusCode: response.statusCode,
                      httpVersion: nil,
                      headerFields: response.headers
                  )
            else {
                client?.urlProtocol(self, didFailWithError: URLError(.badServerResponse))
                return
            }
            client?.urlProtocol(self, didReceive: httpResponse, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: response.body)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}
