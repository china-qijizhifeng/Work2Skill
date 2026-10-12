import Foundation
import Testing
@testable import WorkRecorderCapture

@Suite(.serialized)
struct ActiveCaptureTransportTests {
    @Test func createActiveCaptureSessionPostsTypedRegionScope() async throws {
        let transport = Self.transport { request in
            switch request.url?.path {
            case "/v1/auth/tokens":
                return Self.tokenResponse(accessToken: "recording-token")
            case "/v1/active-captures/sessions":
                #expect(request.value(forHTTPHeaderField: "x-workrecorder-install-secret") == nil)
                #expect(request.value(forHTTPHeaderField: "authorization") == "Bearer recording-token")
                return Self.activeCaptureSessionResponse(sessionId: "acs_recording_transport")
            default:
                return Self.response(statusCode: 404, body: "{}")
            }
        }

        let view = try await transport.createActiveCaptureSession(scope: Self.recordingScope())

        let body = try #require(ActiveCaptureURLProtocolStub.jsonBodies().last)
        #expect(body["mode"] as? String == "recording_session")
        #expect(body["start_recording"] as? Bool == true)
        let scope = try #require(body["scope"] as? [String: Any])
        #expect(scope["kind"] as? String == "region")
        #expect((scope["selection_region"] as? [String: Any])?["width"] as? Int == 640)
        #expect(view.session.sessionId == "acs_recording_transport")
        #expect(view.session.status == .recording)
    }

    @Test func submitKeyframeTriggerUsesTrustedWriterAndDecodesInstruction() async throws {
        let transport = Self.transport { request in
            switch request.url?.path {
            case "/v1/auth/tokens":
                return Self.tokenResponse(accessToken: "trigger-token")
            case "/v1/active-captures/acs_recording/triggers":
                #expect(request.value(forHTTPHeaderField: "x-workrecorder-install-secret") == "install-secret")
                #expect(request.value(forHTTPHeaderField: "authorization") == "Bearer trigger-token")
                return Self.triggerSubmissionResponse()
            default:
                return Self.response(statusCode: 404, body: "{}")
            }
        }

        let instruction = try await transport.submitKeyframeTrigger(
            sessionId: "acs_recording",
            triggerKind: .recordingStart,
            role: .start,
            scope: Self.recordingScope()
        )

        let body = try #require(ActiveCaptureURLProtocolStub.jsonBodies().last)
        #expect(body["trigger_kind"] as? String == "recording_start")
        #expect(body["role"] as? String == "start")
        #expect(instruction?.sessionId == "acs_recording")
        #expect(instruction?.binding.candidateId == "kfc_recording_start")
    }

    @Test func keyframeTimingV2EnumsDecodeFromBackendInstruction() throws {
        let payload = Data(
            #"""
            {
              "candidate_id": "kfc_before",
              "session_id": "acs_recording",
              "role": "before_action",
              "trigger_kind": "action_before",
              "execute_after_monotonic_ms": 3000,
              "binding": {
                "session_id": "acs_recording",
                "role": "before_action",
                "trigger_kind": "action_before",
                "keep_reason": "before_action_context",
                "candidate_id": "kfc_before",
                "metadata": {}
              }
            }
            """#.utf8
        )

        let instruction = try JSONDecoder().decode(ActiveCaptureCaptureInstruction.self, from: payload)

        #expect(instruction.role == .beforeAction)
        #expect(instruction.triggerKind == .actionBefore)
        #expect(instruction.binding.keepReason == .beforeActionContext)
    }

    @Test func attachRecordingSegmentUsesTrustedWriterAndStagedVideoRef() async throws {
        let transport = Self.transport { request in
            switch request.url?.path {
            case "/v1/auth/tokens":
                return Self.tokenResponse(accessToken: "segment-token")
            case "/v1/active-captures/acs_recording/segments":
                #expect(request.value(forHTTPHeaderField: "x-workrecorder-install-secret") == "install-secret")
                return Self.recordingSegmentResponse()
            default:
                return Self.response(statusCode: 404, body: "{}")
            }
        }

        let segment = try await transport.attachRecordingSegment(
            sessionId: "acs_recording",
            request: AttachRecordingSegmentRequest(
                segmentId: "rseg_1",
                state: .available,
                startedAtMonotonicMs: 100,
                mediaStartMonotonicMs: 140,
                mediaStartWallTimeEpochMs: 1_782_300_000_140,
                endedAtMonotonicMs: 900,
                durationMs: 800,
                closeReason: .stopped,
                stagedVideo: StagedRecordingVideoRef(
                    localPath: "/tmp/workrecorder/recording.mp4",
                    contentType: "video/mp4",
                    filename: "recording.mp4",
                    durationMs: 800,
                    metadata: ["frame_count": .int(24)]
                ),
                metadata: [:]
            )
        )

        let body = try #require(ActiveCaptureURLProtocolStub.jsonBodies().last)
        #expect(body["segment_id"] as? String == "rseg_1")
        #expect(body["state"] as? String == "available")
        #expect(body["media_start_monotonic_ms"] as? Int == 140)
        #expect(body["media_start_wall_time_epoch_ms"] as? Int == 1_782_300_000_140)
        #expect((body["staged_video"] as? [String: Any])?["content_type"] as? String == "video/mp4")
        #expect(segment.video?.state == .available)
    }

    @Test func recordingControlsAndCompletionUseTrustedWriter() async throws {
        let transport = Self.transport { request in
            switch request.url?.path {
            case "/v1/auth/tokens":
                return Self.tokenResponse(accessToken: "control-token")
            case "/v1/active-captures/acs_recording/controls",
                 "/v1/active-captures/acs_recording/complete",
                 "/v1/active-captures/acs_recording/cancel":
                #expect(request.value(forHTTPHeaderField: "x-workrecorder-install-secret") == "install-secret")
                if request.url?.path == "/v1/active-captures/acs_recording/controls" {
                    return Self.activeCaptureControlResponse(sessionId: "acs_recording")
                }
                return Self.activeCaptureSessionResponse(sessionId: "acs_recording")
            default:
                return Self.response(statusCode: 404, body: "{}")
            }
        }

        let control = try await transport.applyRecordingControl(sessionId: "acs_recording", kind: .pause)
        #expect(control.captureInstruction?.candidateId == "kfc_pause")
        _ = try await transport.completeActiveCaptureSession(
            sessionId: "acs_recording",
            userNote: "  给 Agent 复盘这段配置流程  ",
            video: StagedRecordingVideoRef(
                localPath: "/tmp/workrecorder/stitched.mp4",
                contentType: "video/mp4",
                filename: "stitched.mp4",
                durationMs: 1600,
                metadata: ["segment_count": .int(2)]
            ),
            warnings: [
                ActiveCaptureWarning(
                    code: .videoUnavailable,
                    message: "stitched video unavailable; using segment fallback",
                    createdAt: Date(timeIntervalSince1970: 1_717_200_000)
                )
            ]
        )
        _ = try await transport.cancelActiveCaptureSession(sessionId: "acs_recording", reason: "test")

        let paths = ActiveCaptureURLProtocolStub.requests().compactMap { $0.url?.path }
        #expect(paths.filter { $0 == "/v1/auth/tokens" }.count == 1)
        #expect(paths.contains("/v1/active-captures/acs_recording/controls"))
        #expect(paths.contains("/v1/active-captures/acs_recording/complete"))
        #expect(paths.contains("/v1/active-captures/acs_recording/cancel"))
        let completeBody = try #require(ActiveCaptureURLProtocolStub.jsonBodies().first { body in
            body["user_note"] as? String == "给 Agent 复盘这段配置流程"
        })
        #expect(completeBody["user_note"] as? String == "给 Agent 复盘这段配置流程")
        let video = try #require(completeBody["video"] as? [String: Any])
        #expect(video["local_path"] as? String == "/tmp/workrecorder/stitched.mp4")
        #expect(video["content_type"] as? String == "video/mp4")
        #expect(video["duration_ms"] as? Int == 1600)
        #expect((video["metadata"] as? [String: Any])?["segment_count"] as? Int == 2)
        let warnings = try #require(completeBody["warnings"] as? [[String: Any]])
        #expect(warnings.first?["code"] as? String == "video_unavailable")
        #expect(warnings.first?["message"] as? String == "stitched video unavailable; using segment fallback")
    }

    private static func transport(
        handler: @escaping (URLRequest) throws -> ActiveCaptureStubbedHTTPResponse
    ) -> CaptureTransport {
        ActiveCaptureURLProtocolStub.configure(handler: handler)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ActiveCaptureURLProtocolStub.self]
        let session = URLSession(configuration: configuration)
        return CaptureTransport(
            daemonURL: URL(string: "http://workrecorder.test")!,
            installSecret: "install-secret",
            nativeCaptureSecret: "native-secret",
            session: session
        )
    }

    private static func tokenResponse(accessToken: String = "capture-token") -> ActiveCaptureStubbedHTTPResponse {
        Self.response(body: #"{"ok":true,"data":{"access_token":"\#(accessToken)"}}"#)
    }

    private static func activeCaptureSessionResponse(sessionId: String) -> ActiveCaptureStubbedHTTPResponse {
        Self.response(
            body: #"{"ok":true,"data":{"session":{"session_id":"\#(sessionId)","mode":"recording_session","status":"recording","primary_event_id":null,"started_at":null,"ended_at":null,"created_at":"2026-01-01T00:00:00Z","updated_at":"2026-01-01T00:00:00Z"}}}"#
        )
    }

    private static func triggerSubmissionResponse() -> ActiveCaptureStubbedHTTPResponse {
        Self.response(
            body: #"{"ok":true,"data":{"candidate":{"candidate_id":"kfc_recording_start","status":"accepted","trigger_kind":"recording_start","role":"start","priority":"required"},"capture_instruction":{"candidate_id":"kfc_recording_start","session_id":"acs_recording","role":"start","trigger_kind":"recording_start","execute_after_monotonic_ms":1234,"binding":{"session_id":"acs_recording","role":"start","trigger_kind":"recording_start","keep_reason":"required_boundary","candidate_id":"kfc_recording_start","metadata":{}}}}}"#
        )
    }

    private static func activeCaptureControlResponse(sessionId: String) -> ActiveCaptureStubbedHTTPResponse {
        Self.response(
            body: #"{"ok":true,"data":{"session":{"session_id":"\#(sessionId)","mode":"recording_session","status":"recording","primary_event_id":null,"started_at":null,"ended_at":null,"created_at":"2026-01-01T00:00:00Z","updated_at":"2026-01-01T00:00:00Z"},"control_trigger":{"candidate":{"candidate_id":"kfc_pause","status":"accepted","trigger_kind":"pause_boundary","role":"pause_boundary","priority":"required"},"capture_instruction":{"candidate_id":"kfc_pause","session_id":"\#(sessionId)","role":"pause_boundary","trigger_kind":"pause_boundary","execute_after_monotonic_ms":4321,"binding":{"session_id":"\#(sessionId)","role":"pause_boundary","trigger_kind":"pause_boundary","keep_reason":"pause_resume_boundary","candidate_id":"kfc_pause","metadata":{}}}}}}"#
        )
    }

    private static func recordingSegmentResponse() -> ActiveCaptureStubbedHTTPResponse {
        Self.response(
            body: #"{"ok":true,"data":{"segment_id":"rseg_1","session_id":"acs_recording","sequence_index":0,"state":"available","started_at_monotonic_ms":100,"ended_at_monotonic_ms":900,"duration_ms":800,"close_reason":"stopped","video":{"artifact_id":"art_video","state":"available","content_type":"video/mp4","duration_ms":800}}}"#
        )
    }

    private static func response(statusCode: Int = 200, body: String) -> ActiveCaptureStubbedHTTPResponse {
        ActiveCaptureStubbedHTTPResponse(statusCode: statusCode, body: Data(body.utf8))
    }

    private static func recordingScope() -> ActiveCaptureRecordingScope {
        ActiveCaptureRecordingScope(
            kind: .region,
            displayId: "display-main",
            scaleFactor: 2.0,
            windowId: nil,
            processId: nil,
            bundleId: nil,
            appName: "Safari",
            title: "Docs",
            bounds: nil,
            selectionRegion: BoundingBox(x: 20, y: 30, width: 640, height: 360, coordinateSpace: "macos_global"),
            scopeConfidence: 0.9,
            occlusionEstimate: nil,
            metadata: [:]
        )
    }
}

private struct ActiveCaptureStubbedHTTPResponse {
    let statusCode: Int
    let body: Data
    let headers: [String: String]

    init(statusCode: Int, body: Data, headers: [String: String] = ["content-type": "application/json"]) {
        self.statusCode = statusCode
        self.body = body
        self.headers = headers
    }
}

private final class ActiveCaptureURLProtocolStub: URLProtocol, @unchecked Sendable {
    private final class State: @unchecked Sendable {
        private let lock = NSLock()
        private var handler: ((URLRequest) throws -> ActiveCaptureStubbedHTTPResponse)?
        private var capturedRequests: [URLRequest] = []
        private var capturedBodies: [[String: Any]] = []

        func configure(handler: @escaping (URLRequest) throws -> ActiveCaptureStubbedHTTPResponse) {
            lock.lock()
            self.handler = handler
            capturedRequests = []
            capturedBodies = []
            lock.unlock()
        }

        func response(for request: URLRequest) throws -> ActiveCaptureStubbedHTTPResponse {
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

        func jsonBodies() -> [[String: Any]] {
            lock.lock()
            let bodies = capturedBodies
            lock.unlock()
            return bodies
        }

        func requests() -> [URLRequest] {
            lock.lock()
            let requests = capturedRequests
            lock.unlock()
            return requests
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

    static func configure(handler: @escaping (URLRequest) throws -> ActiveCaptureStubbedHTTPResponse) {
        state.configure(handler: handler)
    }

    static func jsonBodies() -> [[String: Any]] {
        state.jsonBodies()
    }

    static func requests() -> [URLRequest] {
        state.requests()
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
