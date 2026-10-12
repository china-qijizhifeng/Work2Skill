import Carbon
import CoreGraphics
import Foundation
import Testing
@testable import WorkRecorderCapture

@Suite(.serialized)
struct ActiveCaptureInputProducerTests {
    @Test func eventTapActivationGateSerializesReenableAgainstShutdown() {
        let gate = InputEventTapActivationGate()
        let reenableEntered = DispatchSemaphore(value: 0)
        let allowReenableToFinish = DispatchSemaphore(value: 0)
        let reenableFinished = DispatchSemaphore(value: 0)
        let shutdownFinished = DispatchSemaphore(value: 0)
        gate.activate()

        DispatchQueue.global(qos: .userInitiated).async {
            gate.performIfActive {
                reenableEntered.signal()
                allowReenableToFinish.wait()
            }
            reenableFinished.signal()
        }
        #expect(reenableEntered.wait(timeout: .now() + 1) == .success)

        DispatchQueue.global(qos: .userInitiated).async {
            gate.deactivate()
            shutdownFinished.signal()
        }
        #expect(shutdownFinished.wait(timeout: .now() + 0.05) == .timedOut)

        allowReenableToFinish.signal()
        #expect(reenableFinished.wait(timeout: .now() + 1) == .success)
        #expect(shutdownFinished.wait(timeout: .now() + 1) == .success)

        var reenabledAfterShutdown = false
        #expect(!gate.performIfActive {
            reenabledAfterShutdown = true
        })
        #expect(!reenabledAfterShutdown)
    }

    @Test func classifierStoresExactShortcutChordButTypingPauseOnlyAggregates() throws {
        let hotkey = ActiveCaptureInputEventClassifier.hotkey(
            keyCode: kVK_ANSI_K,
            flags: [.maskCommand],
            monotonicMilliseconds: 1_000
        )
        let typing = ActiveCaptureInputEventClassifier.typingPause(
            eventCount: 4,
            textEventCount: 4,
            characterCount: 4,
            deletionKeyCount: 0,
            nonTextKeyCount: 0,
            submittedByEnter: false,
            durationMs: 500,
            monotonicMilliseconds: 1_500
        )
        let hotkeyBody = try Self.jsonBody(hotkey)
        let typingBody = try Self.jsonBody(typing)
        let hotkeyKeyboard = try #require(hotkeyBody["keyboard"] as? [String: Any])
        let keyChord = try #require(hotkeyKeyboard["key_chord"] as? [String: Any])
        let typingKeyboard = try #require(typingBody["keyboard"] as? [String: Any])

        #expect(hotkeyBody["event_kind"] as? String == "hotkey")
        #expect(keyChord["normalized_key_label"] as? String == "k")
        #expect(keyChord["semantic"] as? String == "open_command")
        #expect(keyChord["modifiers"] as? [String] == ["command"])
        #expect(typingBody["event_kind"] as? String == "typing_pause")
        #expect(typingKeyboard["key_chord"] == nil)
        #expect((typingKeyboard["typing_summary"] as? [String: Any])?["character_count"] as? Int == 4)
    }

    @Test func classifierSerializesOptedInFullContentKeystroke() throws {
        let rawKey = ActiveCaptureInputEventClassifier.rawKey(
            eventKind: .keyDown,
            keyCode: kVK_ANSI_H,
            characters: "H",
            flags: [.maskShift],
            monotonicMilliseconds: 1_250
        )
        let body = try Self.jsonBody(rawKey)
        let keyboard = try #require(body["keyboard"] as? [String: Any])
        let chord = try #require(keyboard["key_chord"] as? [String: Any])

        #expect(body["event_kind"] as? String == "key_down")
        #expect(keyboard["keyboard_event_kind"] as? String == "key_down")
        #expect(keyboard["input_class"] as? String == "text_input")
        #expect(keyboard["capture_policy"] as? String == "full_content")
        #expect(chord["normalized_key_label"] as? String == "h")
        #expect(chord["characters"] as? String == "H")
        #expect(chord["modifiers"] as? [String] == ["shift"])
    }

    @Test func fullKeystrokeCaptureRequiresExplicitOptIn() {
        let suiteName = "WorkRecorderCaptureTests.FullKeystrokes.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }

        #expect(!ActiveCaptureFullKeystrokePreference.isEnabled(environment: [:], defaults: defaults))
        defaults.set(true, forKey: ActiveCaptureFullKeystrokePreference.defaultsKey)
        #expect(ActiveCaptureFullKeystrokePreference.isEnabled(environment: [:], defaults: defaults))
        #expect(ActiveCaptureFullKeystrokePreference.isEnabled(
            environment: [ActiveCaptureFullKeystrokePreference.environmentKey: "1"],
            defaults: defaults
        ))
        #expect(!ActiveCaptureFullKeystrokePreference.isEnabled(
            environment: [ActiveCaptureFullKeystrokePreference.environmentKey: "0"],
            defaults: defaults
        ))
    }

    @Test func classifierTreatsKeypadEnterAsSubmitCommand() throws {
        let keypadEnter = ActiveCaptureInputEventClassifier.hotkey(
            keyCode: kVK_ANSI_KeypadEnter,
            flags: [],
            monotonicMilliseconds: 1_000
        )
        let body = try Self.jsonBody(keypadEnter)
        let keyboard = try #require(body["keyboard"] as? [String: Any])
        let keyChord = try #require(keyboard["key_chord"] as? [String: Any])

        #expect(body["event_kind"] as? String == "hotkey")
        #expect(keyboard["hotkey_semantic"] as? String == "submit")
        #expect(keyChord["normalized_key_label"] as? String == "enter")
        #expect(ActiveCaptureInputEventClassifier.isCommandKey(keyCode: kVK_ANSI_KeypadEnter))
    }

    @Test func classifierKeepsUnmodifiedNavigationKeysAggregateOnly() throws {
        #expect(!ActiveCaptureInputEventClassifier.isShortcut(keyCode: kVK_Tab, flags: []))
        #expect(!ActiveCaptureInputEventClassifier.isShortcut(keyCode: kVK_LeftArrow, flags: []))
        #expect(!ActiveCaptureInputEventClassifier.isShortcut(keyCode: kVK_PageDown, flags: []))
        #expect(ActiveCaptureInputEventClassifier.isShortcut(keyCode: kVK_Tab, flags: [.maskCommand]))
        #expect(ActiveCaptureInputEventClassifier.isShortcut(keyCode: kVK_LeftArrow, flags: [.maskControl]))
        #expect(ActiveCaptureInputEventClassifier.normalizedKeyLabel(for: kVK_LeftArrow) == "left_arrow")
    }

    @Test func classifierStoresUnknownControlShortcutChordForReviewableHotkeyTrace() throws {
        let controlB = ActiveCaptureInputEventClassifier.hotkey(
            keyCode: kVK_ANSI_B,
            flags: [.maskControl],
            monotonicMilliseconds: 1_000
        )
        let body = try Self.jsonBody(controlB)
        let keyboard = try #require(body["keyboard"] as? [String: Any])
        let keyChord = try #require(keyboard["key_chord"] as? [String: Any])

        #expect(ActiveCaptureInputEventClassifier.isShortcut(keyCode: kVK_ANSI_B, flags: [.maskControl]))
        #expect(!ActiveCaptureInputEventClassifier.isShortcut(keyCode: kVK_ANSI_B, flags: [.maskAlternate]))
        #expect(!ActiveCaptureInputEventClassifier.isShortcut(keyCode: kVK_ANSI_B, flags: []))
        #expect(body["event_kind"] as? String == "hotkey")
        #expect(keyboard["capture_policy"] as? String == "key_chord_allowed")
        #expect(keyboard["hotkey_semantic"] as? String == "unknown")
        #expect(keyChord["normalized_key_label"] as? String == "b")
        #expect(keyChord["semantic"] as? String == "unknown")
        #expect(keyChord["modifiers"] as? [String] == ["control"])
    }

    @Test func currentAppScopeSerializesToBackendContractKind() throws {
        let scope = ActiveCaptureRecordingScope(
            kind: .currentApp,
            displayId: nil,
            scaleFactor: nil,
            windowId: nil,
            processId: 4242,
            bundleId: "com.example.App",
            appName: "Example",
            title: "Example",
            bounds: nil,
            selectionRegion: nil,
            scopeConfidence: 0.62,
            occlusionEstimate: nil,
            metadata: [:]
        )
        let data = try JSONEncoder().encode(scope)
        let body = try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])

        #expect(body["kind"] as? String == "current_app")
        #expect(body["process_id"] as? Int == 4242)
        #expect(body["bounds"] == nil)
    }

    @Test func transportPostsProducerEventsWithInstallSecret() async throws {
        let transport = Self.transport { request in
            switch request.url?.path {
            case "/v1/auth/tokens":
                return Self.response(body: #"{"ok":true,"data":{"access_token":"producer-token"}}"#)
            case "/v1/active-captures/acs_transport/producer-events":
                #expect(request.value(forHTTPHeaderField: "authorization") == "Bearer producer-token")
                #expect(request.value(forHTTPHeaderField: "x-workrecorder-install-secret") == "install-secret")
                return Self.response(
                    body: """
                    {
                      "ok": true,
                      "data": {
                        "results": [
                          {
                            "trigger": {
                              "capture_instruction": {
                                "candidate_id": "kfc_transport",
                                "session_id": "acs_transport",
                                "role": "settle",
                                "trigger_kind": "hotkey_settle",
                                "execute_after_monotonic_ms": 2100,
                                "binding": {
                                  "session_id": "acs_transport",
                                  "role": "settle",
                                  "trigger_kind": "hotkey_settle",
                                  "keep_reason": "policy_accepted",
                                  "candidate_id": "kfc_transport",
                                  "metadata": {}
                                }
                              }
                            },
                            "triggers": [
                              {
                                "capture_instruction": {
                                  "candidate_id": "kfc_before",
                                  "session_id": "acs_transport",
                                  "role": "before_action",
                                  "trigger_kind": "action_before",
                                  "execute_after_monotonic_ms": 2000,
                                  "binding": {
                                    "session_id": "acs_transport",
                                    "role": "before_action",
                                    "trigger_kind": "action_before",
                                    "keep_reason": "before_action_context",
                                    "candidate_id": "kfc_before",
                                    "metadata": {}
                                  }
                                }
                              },
                              {
                                "capture_instruction": {
                                  "candidate_id": "kfc_transport",
                                  "session_id": "acs_transport",
                                  "role": "settle",
                                  "trigger_kind": "hotkey_settle",
                                  "execute_after_monotonic_ms": 2100,
                                  "binding": {
                                    "session_id": "acs_transport",
                                    "role": "settle",
                                    "trigger_kind": "hotkey_settle",
                                    "keep_reason": "policy_accepted",
                                    "candidate_id": "kfc_transport",
                                    "metadata": {}
                                  }
                                }
                              }
                            ]
                          }
                        ]
                      }
                    }
                    """
                )
            default:
                return Self.response(statusCode: 404, body: "{}")
            }
        }

        let result = try await transport.recordProducerEvent(
            sessionId: "acs_transport",
            event: ActiveCaptureInputEventClassifier.hotkey(
                keyCode: kVK_Return,
                flags: [],
                monotonicMilliseconds: 2_000
            )
        )

        let bodies = ProducerURLProtocolStub.jsonBodies()
        let producerBody = try #require(bodies.last)
        #expect(producerBody["event_kind"] as? String == "hotkey")
        #expect((producerBody["keyboard"] as? [String: Any])?["hotkey_semantic"] as? String == "submit")
        #expect(result.captureInstructions.map(\.candidateId) == ["kfc_before", "kfc_transport"])
        #expect(result.captureInstructions.first?.candidateId == "kfc_before")
        #expect(result.captureInstructions.last?.binding.candidateId == "kfc_transport")
    }

    @Test func transportPollsPendingCaptureInstructionsWithInstallSecret() async throws {
        let transport = Self.transport { request in
            switch request.url?.path {
            case "/v1/auth/tokens":
                return Self.response(body: #"{"ok":true,"data":{"access_token":"producer-token"}}"#)
            case "/v1/active-captures/acs_transport/capture-instructions/pending":
                #expect(request.value(forHTTPHeaderField: "authorization") == "Bearer producer-token")
                #expect(request.value(forHTTPHeaderField: "x-workrecorder-install-secret") == "install-secret")
                #expect(request.value(forHTTPHeaderField: "x-workrecorder-native-capture-secret") == "native-secret")
                return Self.response(
                    body: """
                    {
                      "ok": true,
                      "data": {
                        "instructions": [
                          {
                            "candidate_id": "kfc_settled",
                            "session_id": "acs_transport",
                            "role": "settle",
                            "trigger_kind": "click_settle",
                            "execute_after_monotonic_ms": 3250,
                            "binding": {
                              "session_id": "acs_transport",
                              "role": "settle",
                              "trigger_kind": "click_settle",
                              "keep_reason": "policy_accepted",
                              "candidate_id": "kfc_settled",
                              "metadata": {}
                            }
                          }
                        ],
                        "observed_candidate_count": 1,
                        "ready_candidate_count": 1,
                        "probe_required_candidate_count": 0
                      }
                    }
                    """
                )
            default:
                return Self.response(statusCode: 404, body: "{}")
            }
        }

        let result = try await transport.pollPendingCaptureInstructions(
            sessionId: "acs_transport",
            probeSnapshot: ActiveCaptureSettleProbeSnapshot(
                sampleId: "kfs_native",
                sampledAtMonotonicMs: 3_250,
                visual: ActiveCaptureVisualDiffSummary(sampleFingerprint: "fnv64:0000000000000001"),
                diagnostics: ["native visual probe sampled recording scope"],
                metadata: ["probe_source": .string("macos_cgdisplay_in_memory")]
            )
        )

        let bodies = ProducerURLProtocolStub.jsonBodies()
        let pollBody = try #require(bodies.last)
        #expect(pollBody["limit"] as? Int == 32)
        #expect(pollBody["now_monotonic_ms"] is Int)
        #expect(pollBody["allow_degraded_sample"] as? Bool == true)
        let probe = try #require(pollBody["probe_snapshot"] as? [String: Any])
        let visual = try #require(probe["visual"] as? [String: Any])
        #expect(visual["sample_fingerprint"] as? String == "fnv64:0000000000000001")
        #expect(result.accepted == true)
        #expect(result.observedCandidateCount == 1)
        #expect(result.readyCandidateCount == 1)
        #expect(result.probeRequiredCandidateCount == 0)
        #expect(result.captureInstructions.map(\.candidateId) == ["kfc_settled"])
        #expect(result.captureInstructions.first?.binding.triggerKind == .clickSettle)
    }

    @Test func transportPostsProducerEventsAsOneBatch() async throws {
        let transport = Self.transport { request in
            switch request.url?.path {
            case "/v1/auth/tokens":
                return Self.response(body: #"{"ok":true,"data":{"access_token":"producer-token"}}"#)
            case "/v1/active-captures/acs_transport/producer-events":
                return Self.response(body: #"{"ok":true,"data":{"results":[]}}"#)
            default:
                return Self.response(statusCode: 404, body: "{}")
            }
        }
        let events = [1_000, 2_000].map {
            ActiveCaptureInputEventClassifier.hotkey(
                keyCode: kVK_Return,
                flags: [],
                monotonicMilliseconds: $0
            )
        }

        let result = try await transport.recordProducerEvents(sessionId: "acs_transport", events: events)

        let body = try #require(ProducerURLProtocolStub.jsonBodies().last)
        let encodedEvents = try #require(body["events"] as? [[String: Any]])
        #expect(encodedEvents.count == 2)
        #expect(encodedEvents.compactMap { $0["occurred_at_monotonic_ms"] as? Int } == [1_000, 2_000])
        #expect(result.accepted)
    }

    @Test func producerSubmissionQueueBatchesAndKeepsNewestEventsWhenBounded() async throws {
        let queue = ActiveCaptureProducerSubmissionQueue(batchSize: 2, maxPendingEvents: 3)
        let events = (1...5).map { index in
            ActiveCaptureInputEventClassifier.hotkey(
                keyCode: kVK_Return,
                flags: [],
                monotonicMilliseconds: index * 1_000
            )
        }

        let outcomes = events.map { queue.enqueue($0) }

        #expect(outcomes.first?.shouldStartDrain == true)
        #expect(outcomes.dropFirst().allSatisfy { !$0.shouldStartDrain })
        #expect(outcomes[3].droppedCount == 1)
        #expect(outcomes[4].droppedCount == 1)
        let first = try #require(queue.takeNextBatch())
        let second = try #require(queue.takeNextBatch())
        #expect(first.compactMap(\.occurredAtMonotonicMs) == [3_000, 4_000])
        #expect(second.compactMap(\.occurredAtMonotonicMs) == [5_000])
        #expect(queue.takeNextBatch() == nil)
        await queue.waitUntilDrained()
    }

    @Test func transportReportsCaptureInstructionFailureWithNativeSecret() async throws {
        let transport = Self.transport { request in
            switch request.url?.path {
            case "/v1/auth/tokens":
                return Self.response(body: #"{"ok":true,"data":{"access_token":"producer-token"}}"#)
            case "/v1/active-captures/acs_transport/capture-instructions/failure":
                #expect(request.value(forHTTPHeaderField: "authorization") == "Bearer producer-token")
                #expect(request.value(forHTTPHeaderField: "x-workrecorder-install-secret") == "install-secret")
                #expect(request.value(forHTTPHeaderField: "x-workrecorder-native-capture-secret") == "native-secret")
                return Self.response(
                    body: #"{"ok":true,"data":{"candidate_id":"kfc_failed","status":"dropped","trigger_kind":"click_settle","role":"settle","priority":"normal","drop_reason":"invalid_evidence"}}"#
                )
            default:
                return Self.response(statusCode: 404, body: "{}")
            }
        }

        try await transport.reportCaptureInstructionFailure(
            sessionId: "acs_transport",
            candidateId: "kfc_failed",
            reason: "invalid_evidence",
            diagnostic: "native_capture_instruction_failed"
        )

        let body = try #require(ProducerURLProtocolStub.jsonBodies().last)
        #expect(body["candidate_id"] as? String == "kfc_failed")
        #expect(body["reason"] as? String == "invalid_evidence")
        #expect(body["diagnostic"] as? String == "native_capture_instruction_failed")
    }

    private static func transport(handler: @escaping (URLRequest) throws -> ProducerHTTPResponse) -> CaptureTransport {
        ProducerURLProtocolStub.configure(handler: handler)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [ProducerURLProtocolStub.self]
        let session = URLSession(configuration: configuration)
        return CaptureTransport(
            daemonURL: URL(string: "http://workrecorder.test")!,
            installSecret: "install-secret",
            nativeCaptureSecret: "native-secret",
            session: session
        )
    }

    private static func response(statusCode: Int = 200, body: String) -> ProducerHTTPResponse {
        ProducerHTTPResponse(statusCode: statusCode, body: Data(body.utf8))
    }

    private static func jsonBody(_ event: ActiveCaptureProducerEventCommand) throws -> [String: Any] {
        let data = try JSONEncoder().encode(event)
        return try #require(JSONSerialization.jsonObject(with: data) as? [String: Any])
    }
}

private struct ProducerHTTPResponse {
    let statusCode: Int
    let body: Data
}

private final class ProducerURLProtocolStub: URLProtocol, @unchecked Sendable {
    private final class State: @unchecked Sendable {
        private let lock = NSLock()
        private var handler: ((URLRequest) throws -> ProducerHTTPResponse)?
        private var capturedBodies: [[String: Any]] = []

        func configure(handler: @escaping (URLRequest) throws -> ProducerHTTPResponse) {
            lock.lock()
            self.handler = handler
            capturedBodies = []
            lock.unlock()
        }

        func response(for request: URLRequest) throws -> ProducerHTTPResponse {
            let jsonBody = Self.jsonBody(from: request)
            lock.lock()
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
                if read <= 0 {
                    break
                }
                data.append(buffer, count: read)
            }
            return data.isEmpty ? nil : data
        }
    }

    private static let state = State()

    static func configure(handler: @escaping (URLRequest) throws -> ProducerHTTPResponse) {
        state.configure(handler: handler)
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
                      headerFields: ["content-type": "application/json"]
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
