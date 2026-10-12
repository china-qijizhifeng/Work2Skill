import AppKit
import Foundation

struct ActorRef: Codable {
    let actorId: String
    let displayName: String?

    enum CodingKeys: String, CodingKey {
        case actorId = "actor_id"
        case displayName = "display_name"
    }
}

struct BoundingBox: Codable {
    let x: Int
    let y: Int
    let width: Int
    let height: Int
    let coordinateSpace: String

    enum CodingKeys: String, CodingKey {
        case x
        case y
        case width
        case height
        case coordinateSpace = "coordinate_space"
    }
}

struct SourceRef: Codable {
    let sourceType: String
    let title: String
    let appName: String?
    let url: String?
    let origin: String?
    let connectorName: String?
    let externalId: String?
    let version: String?

    enum CodingKeys: String, CodingKey {
        case sourceType = "source_type"
        case title
        case appName = "app_name"
        case url
        case origin
        case connectorName = "connector_name"
        case externalId = "external_id"
        case version
    }
}

struct SourceBinding: Codable {
    let bindingId: String
    let sourceRef: SourceRef
    let confidence: Double
    let resolvedAt: Date

    enum CodingKeys: String, CodingKey {
        case bindingId = "binding_id"
        case sourceRef = "source_ref"
        case confidence
        case resolvedAt = "resolved_at"
    }
}

struct TriggerEnvelope: Codable {
    let triggerId: String
    let triggerType: String
    let captureStrategy: String
    let actor: ActorRef
    let occurredAt: Date
    let selection: BoundingBox?
    let intentText: String?
    let surfaceId: String?
    let deviceId: String?
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case triggerId = "trigger_id"
        case triggerType = "trigger_type"
        case captureStrategy = "capture_strategy"
        case actor
        case occurredAt = "occurred_at"
        case selection
        case intentText = "intent_text"
        case surfaceId = "surface_id"
        case deviceId = "device_id"
        case metadata
    }
}

struct DisplayGeometry: Codable {
    let displayId: String
    let frame: BoundingBox
    let scaleFactor: Double

    enum CodingKeys: String, CodingKey {
        case displayId = "display_id"
        case frame
        case scaleFactor = "scale_factor"
    }
}

struct SelectionGeometry: Codable {
    let selectedRegion: BoundingBox
    let display: DisplayGeometry
    let pixelRegion: BoundingBox?

    enum CodingKeys: String, CodingKey {
        case selectedRegion = "selected_region"
        case display
        case pixelRegion = "pixel_region"
    }
}

struct WorkspaceSelection: Codable {
    let workspaceId: String
    let label: String
    let auto: Bool

    enum CodingKeys: String, CodingKey {
        case workspaceId = "workspace_id"
        case label
        case auto
    }
}

struct StagedArtifactRef: Codable {
    let localPath: String
    let artifactType: String
    let contentType: String
    let filename: String?
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case localPath = "local_path"
        case artifactType = "artifact_type"
        case contentType = "content_type"
        case filename
        case metadata
    }
}

struct WindowHint: Codable {
    let appName: String
    let title: String?
    let processId: Int?
    let windowId: String?
    let frame: BoundingBox?
    let overlapRatio: Double
    let confidence: Double
    let bundleId: String?
    let bundleUrl: String?
    let windowLayer: Int?
    let windowOrder: Int?
    let displayId: String?
    let visibleAreaRatio: Double?
    let isFrontmost: Bool?
    let appIconRef: String?

    init(
        appName: String,
        title: String?,
        processId: Int?,
        windowId: String?,
        frame: BoundingBox?,
        overlapRatio: Double,
        confidence: Double,
        bundleId: String? = nil,
        bundleUrl: String? = nil,
        windowLayer: Int? = nil,
        windowOrder: Int? = nil,
        displayId: String? = nil,
        visibleAreaRatio: Double? = nil,
        isFrontmost: Bool? = nil,
        appIconRef: String? = nil
    ) {
        self.appName = appName
        self.title = title
        self.processId = processId
        self.windowId = windowId
        self.frame = frame
        self.overlapRatio = overlapRatio
        self.confidence = confidence
        self.bundleId = bundleId
        self.bundleUrl = bundleUrl
        self.windowLayer = windowLayer
        self.windowOrder = windowOrder
        self.displayId = displayId
        self.visibleAreaRatio = visibleAreaRatio
        self.isFrontmost = isFrontmost
        self.appIconRef = appIconRef
    }

    enum CodingKeys: String, CodingKey {
        case appName = "app_name"
        case title
        case processId = "process_id"
        case windowId = "window_id"
        case frame
        case overlapRatio = "overlap_ratio"
        case confidence
        case bundleId = "bundle_id"
        case bundleUrl = "bundle_url"
        case windowLayer = "window_layer"
        case windowOrder = "window_order"
        case displayId = "display_id"
        case visibleAreaRatio = "visible_area_ratio"
        case isFrontmost = "is_frontmost"
        case appIconRef = "app_icon_ref"
    }
}

struct CaptureAttemptRequest: Codable {
    let schemaVersion: Int
    let trigger: TriggerEnvelope
    let selectionGeometry: SelectionGeometry
    let windowHints: [WindowHint]
    let workspace: WorkspaceSelection
    let actor: ActorRef
    let stagedArtifact: StagedArtifactRef
    let intentText: String?
    var activeCapture: ActiveCaptureBinding?
    var nativeTimingReceipt: NativeCaptureTimingReceipt?
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case trigger
        case selectionGeometry = "selection_geometry"
        case windowHints = "window_hints"
        case workspace
        case actor
        case stagedArtifact = "staged_artifact"
        case intentText = "intent_text"
        case activeCapture = "active_capture"
        case nativeTimingReceipt = "native_timing_receipt"
        case metadata
    }
}

struct CaptureSaveRequest: Codable {
    let trigger: TriggerEnvelope
    let selectionGeometry: SelectionGeometry
    let sourceBinding: SourceBinding
    let workspace: WorkspaceSelection
    let actor: ActorRef
    let stagedArtifact: StagedArtifactRef
    let eventType: String
    let intentText: String?
    let metadata: [String: JSONScalar]

    enum CodingKeys: String, CodingKey {
        case trigger
        case selectionGeometry = "selection_geometry"
        case sourceBinding = "source_binding"
        case workspace
        case actor
        case stagedArtifact = "staged_artifact"
        case eventType = "event_type"
        case intentText = "intent_text"
        case metadata
    }
}

struct CaptureAttemptEnvelope: Codable {
    let ok: Bool
    let data: CaptureAttemptData?
}

struct CaptureAttemptData: Codable {
    let status: String
    let message: String?
    let event: CaptureAttemptEventData?
}

struct CaptureAttemptEventData: Codable {
    let eventId: String

    enum CodingKeys: String, CodingKey {
        case eventId = "event_id"
    }
}

enum JSONScalar: Codable {
    case string(String)
    case int(Int)
    case double(Double)
    case bool(Bool)
    case null

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            self = .null
        } else if let value = try? container.decode(Bool.self) {
            self = .bool(value)
        } else if let value = try? container.decode(Int.self) {
            self = .int(value)
        } else if let value = try? container.decode(Double.self) {
            self = .double(value)
        } else {
            self = .string(try container.decode(String.self))
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch self {
        case .string(let value):
            try container.encode(value)
        case .int(let value):
            try container.encode(value)
        case .double(let value):
            try container.encode(value)
        case .bool(let value):
            try container.encode(value)
        case .null:
            try container.encodeNil()
        }
    }
}

struct CaptureDraft {
    let stagedFile: URL
    let screen: NSScreen
    let sourceBinding: SourceBinding
    let windowHints: [WindowHint]
    let selectionGeometry: SelectionGeometry
    let trigger: TriggerEnvelope
    let actor: ActorRef
    let sourceTitle: String
    let nativeTimingReceipt: NativeCaptureTimingReceipt?
}

struct SelectionResult {
    let screen: NSScreen
    let screenRect: CGRect
    let captureRect: CGRect
}
