import Foundation

struct ProviderSessionRegisterMessage: Codable {
    let messageType: String
    let registration: ProviderSessionRegistration

    enum CodingKeys: String, CodingKey {
        case messageType = "message_type"
        case registration
    }
}

struct ProviderSessionRegistration: Codable {
    let schemaVersion: Int
    let providerKey: String
    let providerSessionId: String
    let providerKind: String
    let displayName: String
    let appName: String
    let processId: Int?
    let windowId: String?
    let capabilities: [String]
    let registeredAt: Date
    let ttlMs: Int
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case providerKey = "provider_key"
        case providerSessionId = "provider_session_id"
        case providerKind = "provider_kind"
        case displayName = "display_name"
        case appName = "app_name"
        case processId = "process_id"
        case windowId = "window_id"
        case capabilities
        case registeredAt = "registered_at"
        case ttlMs = "ttl_ms"
        case metadata
    }
}

struct ProviderHeartbeatMessage: Codable {
    let messageType: String
    let heartbeat: ProviderHeartbeat

    enum CodingKeys: String, CodingKey {
        case messageType = "message_type"
        case heartbeat
    }
}

struct ProviderHeartbeat: Codable {
    let providerKey: String
    let providerSessionId: String
    let observedAt: Date
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case providerKey = "provider_key"
        case providerSessionId = "provider_session_id"
        case observedAt = "observed_at"
        case metadata
    }
}

struct ProviderMessageHeader: Codable {
    let messageType: String

    enum CodingKeys: String, CodingKey {
        case messageType = "message_type"
    }
}

struct ProviderCommandEnvelope: Codable {
    let schemaVersion: Int
    let messageType: String
    let command: CollectEvidenceCommand
    let sentAt: Date

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case messageType = "message_type"
        case command
        case sentAt = "sent_at"
    }
}

struct CollectEvidenceCommand: Codable {
    let commandId: String
    let providerKey: String
    let attempt: CaptureAttemptRequest
    let surface: DetectedSurface?
    let deadlineMs: Int

    enum CodingKeys: String, CodingKey {
        case commandId = "command_id"
        case providerKey = "provider_key"
        case attempt
        case surface
        case deadlineMs = "deadline_ms"
    }
}

struct DetectedSurface: Codable {
    let surfaceId: String
    let kind: String
    let appName: String
    let title: String?
    let processId: Int?
    let windowId: String?
    let frame: BoundingBox?
    let overlapRatio: Double
    let confidence: Double

    enum CodingKeys: String, CodingKey {
        case surfaceId = "surface_id"
        case kind
        case appName = "app_name"
        case title
        case processId = "process_id"
        case windowId = "window_id"
        case frame
        case overlapRatio = "overlap_ratio"
        case confidence
    }
}

struct CollectEvidenceResult: Codable {
    let schemaVersion: Int
    let messageType: String
    let commandId: String
    let providerKey: String
    let providerSessionId: String
    let status: String
    let evidenceKind: String
    let sourceBinding: SourceBinding?
    let evidenceBundle: ProviderEvidenceBundle?
    let diagnostics: [String: JSONScalar]
    let errorMessage: String?
    let completedAt: Date

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case messageType = "message_type"
        case commandId = "command_id"
        case providerKey = "provider_key"
        case providerSessionId = "provider_session_id"
        case status
        case evidenceKind = "evidence_kind"
        case sourceBinding = "source_binding"
        case evidenceBundle = "evidence_bundle"
        case diagnostics
        case errorMessage = "error_message"
        case completedAt = "completed_at"
    }
}

struct ProviderEvidenceBundle: Codable {
    let providerKey: String
    let providerSessionId: String
    let commandId: String
    let status: String
    let evidenceKind: String
    let sourceBinding: SourceBinding?
    let evidence: [EvidenceDraft]
    let diagnostics: [String: JSONScalar]
    let completedAt: Date

    enum CodingKeys: String, CodingKey {
        case providerKey = "provider_key"
        case providerSessionId = "provider_session_id"
        case commandId = "command_id"
        case status
        case evidenceKind = "evidence_kind"
        case sourceBinding = "source_binding"
        case evidence
        case diagnostics
        case completedAt = "completed_at"
    }
}

struct EvidenceDraft: Codable {
    let phase: String
    let kind: String
    let artifactType: String
    let role: String
    let payload: EvidencePayloadRef
    let locator: EvidenceLocator
    let observedAt: Date
    let capturedAt: Date
    let provenance: EvidenceProvenance
    let sensitivity: String
    let trustStateClaim: String
    let redactionStateClaim: String
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case phase
        case kind
        case artifactType = "artifact_type"
        case role
        case payload
        case locator
        case observedAt = "observed_at"
        case capturedAt = "captured_at"
        case provenance
        case sensitivity
        case trustStateClaim = "trust_state_claim"
        case redactionStateClaim = "redaction_state_claim"
        case metadata
    }
}

struct EvidencePayloadRef: Codable {
    let contentType: String
    let inlineContent: String?
    let storageUri: String?
    let byteSize: Int?
    let sha256: String?
    let payloadSchema: String?
    let payloadVersion: String

    enum CodingKeys: String, CodingKey {
        case contentType = "content_type"
        case inlineContent = "inline_content"
        case storageUri = "storage_uri"
        case byteSize = "byte_size"
        case sha256
        case payloadSchema = "payload_schema"
        case payloadVersion = "payload_version"
    }
}

struct EvidenceLocator: Codable {
    let sourceUri: String
    let sourceType: String
    let coordinateSpace: String?
    let bbox: BoundingBox?
    let selector: String?
    let path: String?
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case sourceUri = "source_uri"
        case sourceType = "source_type"
        case coordinateSpace = "coordinate_space"
        case bbox
        case selector
        case path
        case metadata
    }
}

struct EvidenceProvenance: Codable {
    let providerKey: String
    let providerKind: String
    let providerSessionId: String?
    let commandId: String?
    let routeId: String?
    let sourceBindingId: String?
    let parentEvidenceIds: [String]
    let inputArtifactIds: [String]
    let extractor: ExtractorRef

    enum CodingKeys: String, CodingKey {
        case providerKey = "provider_key"
        case providerKind = "provider_kind"
        case providerSessionId = "provider_session_id"
        case commandId = "command_id"
        case routeId = "route_id"
        case sourceBindingId = "source_binding_id"
        case parentEvidenceIds = "parent_evidence_ids"
        case inputArtifactIds = "input_artifact_ids"
        case extractor
    }
}

struct ExtractorRef: Codable {
    let name: String
    let version: String
}

struct A11yTextBlock: Codable {
    let text: String
    let blockId: String?
    let elementId: String?
    let role: String?
    let nodePath: String?
    let rolePath: [String]?
    let textSource: String?
    let frame: BoundingBox?
    let selectionOverlapRatio: Double?
    let elementOverlapRatio: Double?
    let orderIndex: Int?
    let isLeafText: Bool?
    let edgeRecovered: Bool?
    let confidence: Double

    enum CodingKeys: String, CodingKey {
        case text
        case blockId = "block_id"
        case elementId = "element_id"
        case role
        case nodePath = "node_path"
        case rolePath = "role_path"
        case textSource = "text_source"
        case frame
        case selectionOverlapRatio = "selection_overlap_ratio"
        case elementOverlapRatio = "element_overlap_ratio"
        case orderIndex = "order_index"
        case isLeafText = "is_leaf_text"
        case edgeRecovered = "edge_recovered"
        case confidence
    }
}

struct A11yNode: Codable {
    let elementId: String?
    let role: String
    let name: String?
    let value: String?
    let description: String?
    let frame: BoundingBox?
    let overlapRatio: Double
    let confidence: Double
    let children: [A11yNode]

    enum CodingKeys: String, CodingKey {
        case elementId = "element_id"
        case role
        case name
        case value
        case description
        case frame
        case overlapRatio = "overlap_ratio"
        case confidence
        case children
    }
}

struct A11yCoverageReport: Codable {
    let selection: BoundingBox
    let permissionState: String
    let nodeCount: Int
    let textBlockCount: Int
    let coveredAreaRatio: Double
    let confidence: Double
    let errorMessage: String?

    enum CodingKeys: String, CodingKey {
        case selection
        case permissionState = "permission_state"
        case nodeCount = "node_count"
        case textBlockCount = "text_block_count"
        case coveredAreaRatio = "covered_area_ratio"
        case confidence
        case errorMessage = "error_message"
    }
}

struct A11ySnapshot: Codable {
    let extractionRevision: String
    let permissionState: String
    let appName: String?
    let processId: Int?
    let windowId: String?
    let selection: BoundingBox
    let rootNodes: [A11yNode]
    let textBlocks: [A11yTextBlock]
    let fullText: String
    let coverage: A11yCoverageReport
    let maxDepth: Int?
    let maxNodes: Int?
    let truncated: Bool

    enum CodingKeys: String, CodingKey {
        case extractionRevision = "extraction_revision"
        case permissionState = "permission_state"
        case appName = "app_name"
        case processId = "process_id"
        case windowId = "window_id"
        case selection
        case rootNodes = "root_nodes"
        case textBlocks = "text_blocks"
        case fullText = "full_text"
        case coverage
        case maxDepth = "max_depth"
        case maxNodes = "max_nodes"
        case truncated
    }
}
