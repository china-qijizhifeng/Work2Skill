import Foundation

extension CaptureTransport {
    func recordProducerEvents(
        sessionId: String,
        events: [ActiveCaptureProducerEventCommand]
    ) async throws -> ProducerEventSaveResult {
        guard !events.isEmpty else {
            return ProducerEventSaveResult(accepted: true, captureInstructions: [])
        }
        let token = try await issueToken(scopes: ["create_event"])
        var httpRequest = URLRequest(
            url: daemonURL
                .appendingPathComponent("v1/active-captures")
                .appendingPathComponent(sessionId)
                .appendingPathComponent("producer-events")
        )
        httpRequest.httpMethod = "POST"
        httpRequest.addValue("application/json", forHTTPHeaderField: "content-type")
        httpRequest.addValue("Bearer \(token)", forHTTPHeaderField: "authorization")
        httpRequest.addValue(installSecret, forHTTPHeaderField: "x-workrecorder-install-secret")
        httpRequest.httpBody = try encoder.encode(ProducerEventBatchRequest(events: events))
        let (data, response) = try await session.data(for: httpRequest)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw CaptureTransportError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw CaptureTransportError.daemonRejected(Self.errorMessage(
                from: data,
                fallback: "本地 daemon 拒绝了这批输入事件记录。"
            ))
        }
        let envelope = try decoder.decode(ProducerEventEnvelope.self, from: data)
        let instructions = envelope.data?.results.flatMap(\.captureInstructions) ?? []
        return ProducerEventSaveResult(accepted: !instructions.isEmpty || envelope.ok, captureInstructions: instructions)
    }

    func recordProducerEvent(
        sessionId: String,
        event: ActiveCaptureProducerEventCommand
    ) async throws -> ProducerEventSaveResult {
        let token = try await issueToken(scopes: ["create_event"])
        var httpRequest = URLRequest(
            url: daemonURL
                .appendingPathComponent("v1/active-captures")
                .appendingPathComponent(sessionId)
                .appendingPathComponent("producer-events")
        )
        httpRequest.httpMethod = "POST"
        httpRequest.addValue("application/json", forHTTPHeaderField: "content-type")
        httpRequest.addValue("Bearer \(token)", forHTTPHeaderField: "authorization")
        httpRequest.addValue(installSecret, forHTTPHeaderField: "x-workrecorder-install-secret")
        httpRequest.httpBody = try encoder.encode(event)
        let (data, response) = try await session.data(for: httpRequest)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw CaptureTransportError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw CaptureTransportError.daemonRejected(Self.errorMessage(
                from: data,
                fallback: "本地 daemon 拒绝了这次输入事件记录。"
            ))
        }
        let envelope = try decoder.decode(ProducerEventEnvelope.self, from: data)
        let instructions = envelope.data?.results.flatMap(\.captureInstructions) ?? []
        return ProducerEventSaveResult(accepted: !instructions.isEmpty || envelope.ok, captureInstructions: instructions)
    }

    func pollPendingCaptureInstructions(
        sessionId: String,
        probeSnapshot: ActiveCaptureSettleProbeSnapshot? = nil,
        allowDegradedSample: Bool = true
    ) async throws -> ProducerEventSaveResult {
        let token = try await issueToken(scopes: ["create_event"])
        var httpRequest = URLRequest(
            url: daemonURL
                .appendingPathComponent("v1/active-captures")
                .appendingPathComponent(sessionId)
                .appendingPathComponent("capture-instructions")
                .appendingPathComponent("pending")
        )
        httpRequest.httpMethod = "POST"
        httpRequest.addValue("application/json", forHTTPHeaderField: "content-type")
        httpRequest.addValue("Bearer \(token)", forHTTPHeaderField: "authorization")
        httpRequest.addValue(installSecret, forHTTPHeaderField: "x-workrecorder-install-secret")
        if let nativeCaptureSecret, !nativeCaptureSecret.isEmpty, nativeCaptureSecret != installSecret {
            httpRequest.addValue(nativeCaptureSecret, forHTTPHeaderField: "x-workrecorder-native-capture-secret")
        }
        httpRequest.httpBody = try encoder.encode(PendingCaptureInstructionPollRequest(
            nowMonotonicMs: monotonicMilliseconds(),
            limit: 32,
            probeSnapshot: probeSnapshot,
            allowDegradedSample: allowDegradedSample
        ))
        let (data, response) = try await session.data(for: httpRequest)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw CaptureTransportError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw CaptureTransportError.daemonRejected(Self.errorMessage(
                from: data,
                fallback: "本地 daemon 拒绝了这次关键帧指令轮询。"
            ))
        }
        let envelope = try decoder.decode(PendingCaptureInstructionEnvelope.self, from: data)
        let instructions = envelope.data?.instructions ?? []
        return ProducerEventSaveResult(
            accepted: envelope.ok,
            captureInstructions: instructions,
            observedCandidateCount: envelope.data?.observedCandidateCount ?? 0,
            readyCandidateCount: envelope.data?.readyCandidateCount ?? instructions.count,
            probeRequiredCandidateCount: envelope.data?.probeRequiredCandidateCount ?? 0
        )
    }

    func reportCaptureInstructionFailure(
        sessionId: String,
        candidateId: String,
        reason: String,
        diagnostic: String
    ) async throws {
        let token = try await issueToken(scopes: ["create_event"])
        var httpRequest = URLRequest(
            url: daemonURL
                .appendingPathComponent("v1/active-captures")
                .appendingPathComponent(sessionId)
                .appendingPathComponent("capture-instructions")
                .appendingPathComponent("failure")
        )
        httpRequest.httpMethod = "POST"
        httpRequest.addValue("application/json", forHTTPHeaderField: "content-type")
        httpRequest.addValue("Bearer \(token)", forHTTPHeaderField: "authorization")
        httpRequest.addValue(installSecret, forHTTPHeaderField: "x-workrecorder-install-secret")
        if let nativeCaptureSecret, !nativeCaptureSecret.isEmpty, nativeCaptureSecret != installSecret {
            httpRequest.addValue(nativeCaptureSecret, forHTTPHeaderField: "x-workrecorder-native-capture-secret")
        }
        httpRequest.httpBody = try encoder.encode(CaptureInstructionFailureReport(
            candidateId: candidateId,
            reason: reason,
            diagnostic: diagnostic
        ))
        let (data, response) = try await session.data(for: httpRequest)
        guard let httpResponse = response as? HTTPURLResponse else {
            throw CaptureTransportError.invalidResponse
        }
        guard (200..<300).contains(httpResponse.statusCode) else {
            throw CaptureTransportError.daemonRejected(Self.errorMessage(
                from: data,
                fallback: "本地 daemon 拒绝了这次关键帧失败回报。"
            ))
        }
    }
}

private struct ProducerEventBatchRequest: Codable {
    let events: [ActiveCaptureProducerEventCommand]
}

private struct CaptureInstructionFailureReport: Codable {
    let candidateId: String
    let reason: String
    let diagnostic: String

    enum CodingKeys: String, CodingKey {
        case candidateId = "candidate_id"
        case reason
        case diagnostic
    }
}

private struct PendingCaptureInstructionPollRequest: Codable {
    let nowMonotonicMs: Int
    let limit: Int
    let probeSnapshot: ActiveCaptureSettleProbeSnapshot?
    let allowDegradedSample: Bool

    enum CodingKeys: String, CodingKey {
        case nowMonotonicMs = "now_monotonic_ms"
        case limit
        case probeSnapshot = "probe_snapshot"
        case allowDegradedSample = "allow_degraded_sample"
    }
}

private struct PendingCaptureInstructionEnvelope: Codable {
    let ok: Bool
    let data: PendingCaptureInstructionData?
}

private struct PendingCaptureInstructionData: Codable {
    let instructions: [ActiveCaptureCaptureInstruction]
    let observedCandidateCount: Int
    let readyCandidateCount: Int
    let probeRequiredCandidateCount: Int

    enum CodingKeys: String, CodingKey {
        case instructions
        case observedCandidateCount = "observed_candidate_count"
        case readyCandidateCount = "ready_candidate_count"
        case probeRequiredCandidateCount = "probe_required_candidate_count"
    }
}

private struct ProducerEventEnvelope: Codable {
    let ok: Bool
    let data: ProducerEventBatchData?
}

private struct ProducerEventBatchData: Codable {
    let results: [ProducerEventResult]
}

private struct ProducerEventResult: Codable {
    let trigger: ProducerTriggerSubmission?
    let triggers: [ProducerTriggerSubmission]?

    var captureInstructions: [ActiveCaptureCaptureInstruction] {
        var seen: Set<String> = []
        var instructions: [ActiveCaptureCaptureInstruction] = []
        for instruction in (triggers ?? []).compactMap(\.captureInstruction) {
            if seen.insert(instruction.candidateId).inserted {
                instructions.append(instruction)
            }
        }
        if let instruction = trigger?.captureInstruction, seen.insert(instruction.candidateId).inserted {
            instructions.append(instruction)
        }
        return instructions
    }
}

private struct ProducerTriggerSubmission: Codable {
    let captureInstruction: ActiveCaptureCaptureInstruction?

    enum CodingKeys: String, CodingKey {
        case captureInstruction = "capture_instruction"
    }
}
