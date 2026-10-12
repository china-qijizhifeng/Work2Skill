import Foundation

struct WorkbenchEnvelope<Value: Decodable>: Decodable {
    let ok: Bool
    let data: Value?
    let requestId: String?
    let agentRunId: String?
    let retrievalCallId: String?
    let snapshotId: String?
    let error: WorkbenchAPIError?

    enum CodingKeys: String, CodingKey {
        case ok
        case data
        case requestId = "request_id"
        case agentRunId = "agent_run_id"
        case retrievalCallId = "retrieval_call_id"
        case snapshotId = "snapshot_id"
        case error
    }
}

struct WorkbenchAPIError: Decodable {
    let code: String?
    let message: String?
}

struct WorkbenchTokenRequest: Encodable {
    let actorId: String
    let displayName: String
    let scopes: [String]

    enum CodingKeys: String, CodingKey {
        case actorId = "actor_id"
        case displayName = "display_name"
        case scopes
    }
}

struct WorkbenchTokenData: Decodable {
    let accessToken: String

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
    }
}

struct WorkbenchDeleteEventData: Decodable {}

struct WorkbenchSearchData: Decodable {
    let results: [SearchCardView]
    let degraded: Bool?
    let backend: String?
}

struct SearchCardView: Decodable, Identifiable {
    var id: String { eventId }

    let eventId: String
    let eventType: String?
    let capturedAt: String
    let source: SearchSourceView
    let selectionBBox: WorkbenchBoundingBoxView?
    let userNote: String?
    let selectionText: String?
    let selectionTextSnippet: String?
    let selectionTextTruncated: Bool?
    let previewConfidence: Double?
    let hiddenArtifacts: [String]
    let providerContributions: [String]?
    let providerDiagnosticsCount: Int?
    let sourceKind: String?

    enum CodingKeys: String, CodingKey {
        case eventId = "event_id"
        case eventType = "event_type"
        case capturedAt = "captured_at"
        case source
        case selectionBBox = "selection_bbox"
        case userNote = "user_note"
        case selectionText = "selection_text"
        case selectionTextSnippet = "selection_text_snippet"
        case selectionTextTruncated = "selection_text_truncated"
        case previewConfidence = "preview_confidence"
        case hiddenArtifacts = "hidden_artifacts"
        case providerContributions = "provider_contributions"
        case providerDiagnosticsCount = "provider_diagnostics_count"
        case sourceKind = "source_kind"
    }

    init(
        eventId: String,
        eventType: String? = nil,
        capturedAt: String,
        source: SearchSourceView,
        selectionBBox: WorkbenchBoundingBoxView?,
        userNote: String?,
        selectionText: String?,
        selectionTextSnippet: String?,
        selectionTextTruncated: Bool?,
        previewConfidence: Double?,
        hiddenArtifacts: [String],
        providerContributions: [String]? = nil,
        providerDiagnosticsCount: Int? = nil,
        sourceKind: String? = nil
    ) {
        self.eventId = eventId
        self.eventType = eventType
        self.capturedAt = capturedAt
        self.source = source
        self.selectionBBox = selectionBBox
        self.userNote = userNote
        self.selectionText = selectionText
        self.selectionTextSnippet = selectionTextSnippet
        self.selectionTextTruncated = selectionTextTruncated
        self.previewConfidence = previewConfidence
        self.hiddenArtifacts = hiddenArtifacts
        self.providerContributions = providerContributions
        self.providerDiagnosticsCount = providerDiagnosticsCount
        self.sourceKind = sourceKind
    }
}

struct SearchSourceView: Decodable, Equatable {
    let appName: String?
    let title: String
    let origin: String?
    let sanitizedURL: String?

    enum CodingKeys: String, CodingKey {
        case appName = "app_name"
        case title
        case origin
        case sanitizedURL = "sanitized_url"
    }
}

struct WorkbenchEventInspectView: Decodable, Equatable {
    let eventId: String
    let capturedAt: String
    let source: SearchSourceView
    let selectionBBox: WorkbenchBoundingBoxView?
    let canonicalText: String
    let cleanPageText: String
    let sourceContributions: [WorkbenchSourceContributionView]
    let readableEvidence: [WorkbenchReadableEvidenceView]
    let rawArtifacts: [WorkbenchRawArtifactRef]
    let hiddenArtifacts: [WorkbenchHiddenArtifactSummary]
    let activeCapture: WorkbenchActiveCaptureInspectView?
    let disclosureDecision: WorkbenchDisclosureDecisionView?

    enum CodingKeys: String, CodingKey {
        case eventId = "event_id"
        case capturedAt = "captured_at"
        case source
        case selectionBBox = "selection_bbox"
        case canonicalText = "canonical_text"
        case cleanPageText = "clean_page_text"
        case sourceContributions = "source_contributions"
        case readableEvidence = "readable_evidence"
        case rawArtifacts = "raw_artifacts"
        case hiddenArtifacts = "hidden_artifacts"
        case activeCapture = "active_capture"
        case disclosureDecision = "disclosure_decision"
    }

    init(
        eventId: String,
        capturedAt: String,
        source: SearchSourceView,
        selectionBBox: WorkbenchBoundingBoxView?,
        canonicalText: String,
        cleanPageText: String,
        sourceContributions: [WorkbenchSourceContributionView] = [],
        readableEvidence: [WorkbenchReadableEvidenceView],
        rawArtifacts: [WorkbenchRawArtifactRef],
        hiddenArtifacts: [WorkbenchHiddenArtifactSummary],
        activeCapture: WorkbenchActiveCaptureInspectView? = nil,
        disclosureDecision: WorkbenchDisclosureDecisionView?
    ) {
        self.eventId = eventId
        self.capturedAt = capturedAt
        self.source = source
        self.selectionBBox = selectionBBox
        self.canonicalText = canonicalText
        self.cleanPageText = cleanPageText
        self.sourceContributions = sourceContributions
        self.readableEvidence = readableEvidence
        self.rawArtifacts = rawArtifacts
        self.hiddenArtifacts = hiddenArtifacts
        self.activeCapture = activeCapture
        self.disclosureDecision = disclosureDecision
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        self.eventId = try container.decode(String.self, forKey: .eventId)
        self.capturedAt = try container.decode(String.self, forKey: .capturedAt)
        self.source = try container.decode(SearchSourceView.self, forKey: .source)
        self.selectionBBox = try container.decodeIfPresent(WorkbenchBoundingBoxView.self, forKey: .selectionBBox)
        self.canonicalText = try container.decode(String.self, forKey: .canonicalText)
        self.cleanPageText = try container.decode(String.self, forKey: .cleanPageText)
        self.sourceContributions = try container.decodeIfPresent([WorkbenchSourceContributionView].self, forKey: .sourceContributions) ?? []
        self.readableEvidence = try container.decode([WorkbenchReadableEvidenceView].self, forKey: .readableEvidence)
        self.rawArtifacts = try container.decode([WorkbenchRawArtifactRef].self, forKey: .rawArtifacts)
        self.hiddenArtifacts = try container.decode([WorkbenchHiddenArtifactSummary].self, forKey: .hiddenArtifacts)
        self.activeCapture = try container.decodeIfPresent(WorkbenchActiveCaptureInspectView.self, forKey: .activeCapture)
        self.disclosureDecision = try container.decodeIfPresent(WorkbenchDisclosureDecisionView.self, forKey: .disclosureDecision)
    }

}

struct WorkbenchSourceContributionView: Decodable, Equatable {
    let role: String
    let appName: String?
    let title: String?
    let sourceKind: String?
    let providerKey: String?
    let providerKind: String?
    let status: String?
    let surfaceId: String?
    let rank: Int?
    let overlapRatio: Double?
    let confidence: Double?
    let evidenceCount: Int
    let reasonCode: String?

    enum CodingKeys: String, CodingKey {
        case role
        case appName = "app_name"
        case title
        case sourceKind = "source_kind"
        case providerKey = "provider_key"
        case providerKind = "provider_kind"
        case status
        case surfaceId = "surface_id"
        case rank
        case overlapRatio = "overlap_ratio"
        case confidence
        case evidenceCount = "evidence_count"
        case reasonCode = "reason_code"
    }
}

struct WorkbenchBoundingBoxView: Decodable, Equatable {
    let x: Double
    let y: Double
    let width: Double
    let height: Double
    let coordinateSpace: String?

    enum CodingKeys: String, CodingKey {
        case x
        case y
        case width
        case height
        case coordinateSpace = "coordinate_space"
    }
}

struct WorkbenchReadableEvidenceView: Decodable, Equatable, Identifiable {
    var id: String { evidenceId ?? artifactId }

    let artifactId: String
    let artifactType: String
    let role: String
    let evidenceId: String?
    let disclosureClass: String
    let text: String
    let confidence: Double?
    let truncated: Bool?

    enum CodingKeys: String, CodingKey {
        case artifactId = "artifact_id"
        case artifactType = "artifact_type"
        case role
        case evidenceId = "evidence_id"
        case disclosureClass = "disclosure_class"
        case text
        case confidence
        case truncated = "text_truncated"
    }
}

struct WorkbenchRawArtifactRef: Decodable, Equatable, Identifiable {
    var id: String { artifactId }

    let artifactId: String
    let artifactType: String
    let role: String
    let contentType: String?
    let disclosureClass: String?
    let requiresScope: String?

    enum CodingKeys: String, CodingKey {
        case artifactId = "artifact_id"
        case artifactType = "artifact_type"
        case role
        case contentType = "content_type"
        case disclosureClass = "disclosure_class"
        case requiresScope = "requires_scope"
    }
}

struct WorkbenchHiddenArtifactSummary: Decodable, Equatable, Identifiable {
    var id: String { "\(artifactType)-\(role)" }

    let artifactType: String
    let role: String
    let disclosureClass: String?
    let reason: String?

    enum CodingKeys: String, CodingKey {
        case artifactType = "artifact_type"
        case role
        case disclosureClass = "disclosure_class"
        case reason
    }
}

struct WorkbenchDisclosureDecisionView: Decodable, Equatable {
    let allowed: Bool?
    let redactionState: String?

    enum CodingKeys: String, CodingKey {
        case allowed
        case redactionState = "redaction_state"
    }
}
