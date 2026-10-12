import ApplicationServices
import CoreGraphics
import Foundation

extension MacOSA11yCollector {
    func evidenceDraft(
        kind: String,
        artifactType: String,
        role: String,
        contentType: String,
        content: String,
        sourceUri: String,
        command: CollectEvidenceCommand,
        providerSessionId: String,
        sensitivity: String,
        trustStateClaim: String,
        redactionStateClaim: String,
        payloadSchema: String
    ) -> EvidenceDraft {
        let now = Date()
        return EvidenceDraft(
            phase: "captured",
            kind: kind,
            artifactType: artifactType,
            role: role,
            payload: EvidencePayloadRef(
                contentType: contentType,
                inlineContent: content,
                storageUri: nil,
                byteSize: nil,
                sha256: nil,
                payloadSchema: payloadSchema,
                payloadVersion: "1"
            ),
            locator: EvidenceLocator(
                sourceUri: sourceUri,
                sourceType: "desktop_window",
                coordinateSpace: command.attempt.selectionGeometry.selectedRegion.coordinateSpace,
                bbox: command.attempt.selectionGeometry.selectedRegion,
                selector: nil,
                path: nil,
                metadata: [:]
            ),
            observedAt: now,
            capturedAt: now,
            provenance: EvidenceProvenance(
                providerKey: "system.macos_a11y",
                providerKind: "system_evidence",
                providerSessionId: providerSessionId,
                commandId: command.commandId,
                routeId: nil,
                sourceBindingId: nil,
                parentEvidenceIds: [],
                inputArtifactIds: [],
                extractor: ExtractorRef(name: "system.macos_a11y", version: "p3_a11y_v1")
            ),
            sensitivity: sensitivity,
            trustStateClaim: trustStateClaim,
            redactionStateClaim: redactionStateClaim,
            metadata: [:]
        )
    }

    func sourceURI(for snapshot: A11ySnapshot, suffix: String) -> String {
        let process = snapshot.processId.map(String.init) ?? "frontmost"
        let window = snapshot.windowId ?? "unknown"
        return "macos://a11y/\(process)/\(window)#\(suffix)"
    }

    func attribute<T>(_ element: AXUIElement, _ name: String) -> T? {
        var value: CFTypeRef?
        let result = AXUIElementCopyAttributeValue(element, name as CFString, &value)
        guard result == .success else { return nil }
        return value as? T
    }

    func stringAttribute(_ element: AXUIElement, _ name: String) -> String? {
        if let value: String = attribute(element, name) {
            return value
        }
        if let value: NSNumber = attribute(element, name) {
            return value.stringValue
        }
        return nil
    }

    func frame(for element: AXUIElement) -> CGRect? {
        var positionValue: CFTypeRef?
        var sizeValue: CFTypeRef?
        guard AXUIElementCopyAttributeValue(element, kAXPositionAttribute as CFString, &positionValue) == .success,
              AXUIElementCopyAttributeValue(element, kAXSizeAttribute as CFString, &sizeValue) == .success,
              let positionValue,
              let sizeValue,
              CFGetTypeID(positionValue) == AXValueGetTypeID(),
              CFGetTypeID(sizeValue) == AXValueGetTypeID()
        else {
            return nil
        }
        let position = positionValue as! AXValue
        let size = sizeValue as! AXValue
        var point = CGPoint.zero
        var cgSize = CGSize.zero
        AXValueGetValue(position, .cgPoint, &point)
        AXValueGetValue(size, .cgSize, &cgSize)
        guard cgSize.width > 0, cgSize.height > 0 else { return nil }
        return CGRect(origin: point, size: cgSize)
    }

    enum OverlapDenominator {
        case selection
        case element
    }

    func overlapRatio(
        _ lhs: CGRect,
        _ rhs: CGRect,
        denominator: OverlapDenominator = .selection
    ) -> CGFloat {
        let intersection = lhs.intersection(rhs)
        guard !intersection.isNull else { return 0 }
        let denominatorRect = denominator == .selection ? rhs : lhs
        let area = max(denominatorRect.width * denominatorRect.height, 1)
        return max(0, intersection.width) * max(0, intersection.height) / area
    }

    func json<T: Encodable>(_ value: T) -> String {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        guard let data = try? encoder.encode(value) else { return "{}" }
        return String(decoding: data, as: UTF8.self)
    }
}
