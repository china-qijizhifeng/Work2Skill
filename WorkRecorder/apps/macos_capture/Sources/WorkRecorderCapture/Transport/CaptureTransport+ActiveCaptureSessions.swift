import Foundation

extension CaptureTransport {
    func createActiveCaptureSession(
        scope: ActiveCaptureRecordingScope
    ) async throws -> ActiveCaptureSessionPublicView {
        let body = CreateActiveCaptureSessionRequest(
            mode: .recordingSession,
            scope: scope,
            startRecording: true,
            metadata: ["ui": .string("macos_recording")]
        )
        return try await sendActiveCaptureRequest(
            pathComponents: ["v1", "active-captures", "sessions"],
            method: "POST",
            scopes: ["create_event"],
            body: body
        )
    }

    func getRecordingSegmentManifest(sessionId: String) async throws -> RecordingSegmentManifestPublicView {
        try await sendActiveCaptureRequest(
            pathComponents: ["v1", "active-captures", sessionId, "segments"],
            method: "GET",
            scopes: ["read_metadata"],
            body: Optional<EmptyActiveCaptureRequest>.none
        )
    }

    func applyRecordingControl(
        sessionId: String,
        kind: ActiveCaptureRecordingControlKind,
        note: String? = nil,
        metadata: [String: JSONScalar] = [:]
    ) async throws -> RecordingControlApplyResult {
        let body = ApplyRecordingControlRequest(
            kind: kind,
            source: .nativeClient,
            occurredAtMonotonicMs: monotonicMilliseconds(),
            note: note,
            metadata: metadata
        )
        let response: ApplyRecordingControlResponse = try await sendActiveCaptureRequest(
            pathComponents: ["v1", "active-captures", sessionId, "controls"],
            method: "POST",
            scopes: ["create_event"],
            trustedWriter: true,
            body: body
        )
        return RecordingControlApplyResult(
            session: ActiveCaptureSessionPublicView(session: response.session),
            captureInstruction: response.controlTrigger?.captureInstruction
        )
    }

    func submitKeyframeTrigger(
        sessionId: String,
        triggerKind: ActiveCaptureKeyframeTriggerKind,
        role: ActiveCaptureKeyframeRole? = nil,
        scope: ActiveCaptureRecordingScope? = nil,
        metadata: [String: JSONScalar] = [:]
    ) async throws -> ActiveCaptureCaptureInstruction? {
        let body = SubmitKeyframeTriggerRequest(
            triggerKind: triggerKind,
            role: role,
            occurredAtMonotonicMs: monotonicMilliseconds(),
            scope: scope,
            metadata: metadata
        )
        let response: KeyframeTriggerSubmissionResponse = try await sendActiveCaptureRequest(
            pathComponents: ["v1", "active-captures", sessionId, "triggers"],
            method: "POST",
            scopes: ["create_event"],
            trustedWriter: true,
            body: body
        )
        return response.captureInstruction
    }

    func attachRecordingSegment(
        sessionId: String,
        request: AttachRecordingSegmentRequest
    ) async throws -> RecordingVideoSegmentPublicSummary {
        try await sendActiveCaptureRequest(
            pathComponents: ["v1", "active-captures", sessionId, "segments"],
            method: "POST",
            scopes: ["create_event"],
            trustedWriter: true,
            body: request
        )
    }

    func completeActiveCaptureSession(
        sessionId: String,
        userNote: String? = nil,
        video: StagedRecordingVideoRef? = nil,
        warnings: [ActiveCaptureWarning] = []
    ) async throws -> ActiveCaptureSessionPublicView {
        let sanitizedNote = userNote?.trimmingCharacters(in: .whitespacesAndNewlines)
        let body = CompleteActiveCaptureSessionRequest(
            warnings: warnings,
            userNote: sanitizedNote?.isEmpty == true ? nil : sanitizedNote,
            video: video,
            metadata: ["ui": .string("macos_recording")]
        )
        return try await sendActiveCaptureRequest(
            pathComponents: ["v1", "active-captures", sessionId, "complete"],
            method: "POST",
            scopes: ["create_event"],
            trustedWriter: true,
            body: body
        )
    }

    func cancelActiveCaptureSession(sessionId: String, reason: String) async throws -> ActiveCaptureSessionPublicView {
        let body = CancelActiveCaptureSessionRequest(reason: reason, metadata: ["ui": .string("macos_recording")])
        return try await sendActiveCaptureRequest(
            pathComponents: ["v1", "active-captures", sessionId, "cancel"],
            method: "POST",
            scopes: ["create_event"],
            trustedWriter: true,
            body: body
        )
    }

    private func sendActiveCaptureRequest<Response: Decodable, Body: Encodable>(
        pathComponents: [String],
        method: String,
        scopes: [String],
        trustedWriter: Bool = false,
        body: Body?
    ) async throws -> Response {
        let token = try await issueToken(scopes: scopes)
        var url = daemonURL
        for component in pathComponents {
            url.appendPathComponent(component)
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.addValue("application/json", forHTTPHeaderField: "content-type")
        request.addValue("Bearer \(token)", forHTTPHeaderField: "authorization")
        if trustedWriter {
            request.addValue(installSecret, forHTTPHeaderField: "x-workrecorder-install-secret")
        }
        if let body {
            request.httpBody = try encoder.encode(body)
        }
        let (data, response) = try await session.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw CaptureTransportError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw CaptureTransportError.daemonRejected(Self.errorMessage(
                from: data,
                fallback: "本地 daemon 拒绝了录制操作。"
            ))
        }
        let envelope = try decoder.decode(ActiveCaptureResponseEnvelope<Response>.self, from: data)
        guard envelope.ok, let responseData = envelope.data else {
            throw CaptureTransportError.invalidResponse
        }
        return responseData
    }
}

private struct EmptyActiveCaptureRequest: Codable {}

private struct ActiveCaptureResponseEnvelope<DataType: Decodable>: Decodable {
    let ok: Bool
    let data: DataType?
}
