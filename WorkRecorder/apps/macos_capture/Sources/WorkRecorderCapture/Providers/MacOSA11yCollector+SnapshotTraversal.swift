import AppKit
import ApplicationServices
import CoreGraphics
import Foundation

extension MacOSA11yCollector {
    func collect(command: CollectEvidenceCommand, providerSessionId: String) -> CollectEvidenceResult {
        let snapshot = snapshot(for: command)
        let succeeded = snapshot.permissionState == "granted"
        return CollectEvidenceResult(
            schemaVersion: 1,
            messageType: "collect_evidence_result",
            commandId: command.commandId,
            providerKey: "system.macos_a11y",
            providerSessionId: providerSessionId,
            status: succeeded ? "succeeded" : "failed",
            evidenceKind: "a11y",
            sourceBinding: nil,
            evidenceBundle: evidenceBundle(for: snapshot, command: command, providerSessionId: providerSessionId, status: succeeded ? "succeeded" : "failed"),
            diagnostics: [
                "permission_state": .string(snapshot.permissionState),
                "node_count": .int(snapshot.coverage.nodeCount),
                "text_block_count": .int(snapshot.coverage.textBlockCount)
            ],
            errorMessage: succeeded ? nil : snapshot.coverage.errorMessage,
            completedAt: Date()
        )
    }

    func snapshot(for command: CollectEvidenceCommand) -> A11ySnapshot {
        let selection = command.attempt.selectionGeometry.selectedRegion
        guard selection.coordinateSpace == "macos_global" else {
            let coverage = A11yCoverageReport(
                selection: selection,
                permissionState: "unknown",
                nodeCount: 0,
                textBlockCount: 0,
                coveredAreaRatio: 0,
                confidence: 0,
                errorMessage: "a11y selection must use macos_global coordinates"
            )
            return A11ySnapshot(
                extractionRevision: extractionRevision,
                permissionState: "unknown",
                appName: command.surface?.appName,
                processId: command.surface?.processId,
                windowId: command.surface?.windowId,
                selection: selection,
                rootNodes: [],
                textBlocks: [],
                fullText: "",
                coverage: coverage,
                maxDepth: maxDepth,
                maxNodes: maxNodes,
                truncated: false
            )
        }
        if shouldSkipSelfApplication(command: command) {
            return selfApplicationSnapshot(command: command, selection: selection)
        }
        guard AXIsProcessTrusted() else {
            let coverage = A11yCoverageReport(
                selection: selection,
                permissionState: "denied",
                nodeCount: 0,
                textBlockCount: 0,
                coveredAreaRatio: 0,
                confidence: 0,
                errorMessage: "macOS Accessibility permission is not granted"
            )
            return A11ySnapshot(
                extractionRevision: extractionRevision,
                permissionState: "denied",
                appName: command.surface?.appName,
                processId: command.surface?.processId,
                windowId: command.surface?.windowId,
                selection: selection,
                rootNodes: [],
                textBlocks: [],
                fullText: "",
                coverage: coverage,
                maxDepth: maxDepth,
                maxNodes: maxNodes,
                truncated: false
            )
        }
        let rootElements = rootElements(for: command)
        var nodes: [A11yNode] = []
        var visited = 0
        var truncated = false
        for element in rootElements {
            if let node = node(
                for: element,
                selection: selection.cgRect,
                depth: 0,
                visited: &visited,
                recursionStack: [],
                ancestorOverlaps: false,
                truncated: &truncated
            ) {
                nodes.append(node)
            }
            if visited >= maxNodes {
                truncated = true
                break
            }
        }
        let textBlocks = textBlocks(from: nodes, selection: selection)
        let fullText = textBlocks.map(\.text).joined(separator: "\n")
        let covered = min(1, Double(textBlocks.count) / 12.0)
        let coverage = A11yCoverageReport(
            selection: selection,
            permissionState: "granted",
            nodeCount: visited,
            textBlockCount: textBlocks.count,
            coveredAreaRatio: covered,
            confidence: textBlocks.isEmpty ? 0.35 : 0.82,
            errorMessage: nil
        )
        return A11ySnapshot(
            extractionRevision: extractionRevision,
            permissionState: "granted",
            appName: command.surface?.appName,
            processId: command.surface?.processId,
            windowId: command.surface?.windowId,
            selection: selection,
            rootNodes: nodes,
            textBlocks: textBlocks,
            fullText: fullText,
            coverage: coverage,
            maxDepth: maxDepth,
            maxNodes: maxNodes,
            truncated: truncated || visited >= maxNodes
        )
    }

    func shouldSkipSelfApplication(command: CollectEvidenceCommand) -> Bool {
        let currentProcessId = Int(ProcessInfo.processInfo.processIdentifier)
        if command.surface?.processId == currentProcessId {
            return true
        }
        guard command.surface == nil,
              let frontmostApplication = NSWorkspace.shared.frontmostApplication
        else {
            return false
        }
        return frontmostApplication.processIdentifier == currentProcessId
            || frontmostApplication.bundleIdentifier == Bundle.main.bundleIdentifier
    }

    func selfApplicationSnapshot(command: CollectEvidenceCommand, selection: BoundingBox) -> A11ySnapshot {
        let coverage = A11yCoverageReport(
            selection: selection,
            permissionState: "skipped_self_app",
            nodeCount: 0,
            textBlockCount: 0,
            coveredAreaRatio: 0,
            confidence: 0,
            errorMessage: "WorkRecorder does not collect accessibility evidence from its own windows"
        )
        return A11ySnapshot(
            extractionRevision: extractionRevision,
            permissionState: "skipped_self_app",
            appName: command.surface?.appName ?? "WorkRecorder",
            processId: command.surface?.processId,
            windowId: command.surface?.windowId,
            selection: selection,
            rootNodes: [],
            textBlocks: [],
            fullText: "",
            coverage: coverage,
            maxDepth: maxDepth,
            maxNodes: maxNodes,
            truncated: false
        )
    }

    func rootElements(for command: CollectEvidenceCommand) -> [AXUIElement] {
        if let processId = command.surface?.processId {
            let app = AXUIElementCreateApplication(pid_t(processId))
            if let windows: [AXUIElement] = attribute(app, kAXWindowsAttribute) {
                return windows
            }
            return [app]
        }
        guard let app = NSWorkspace.shared.frontmostApplication else { return [] }
        return [AXUIElementCreateApplication(app.processIdentifier)]
    }

    func node(
        for element: AXUIElement,
        selection: CGRect,
        depth: Int,
        visited: inout Int,
        recursionStack: Set<CFHashCode>,
        ancestorOverlaps: Bool,
        truncated: inout Bool
    ) -> A11yNode? {
        guard depth <= maxDepth else {
            truncated = true
            return nil
        }
        guard visited < maxNodes else {
            truncated = true
            return nil
        }
        let elementKey = CFHash(element)
        guard !recursionStack.contains(elementKey) else { return nil }
        var recursionStack = recursionStack
        recursionStack.insert(elementKey)
        visited += 1
        let frame = frame(for: element)
        let overlap = frame.map { overlapRatio($0, selection) } ?? 0
        let overlapsSelection = overlap > 0
        let mayAcceptFramelessText = ancestorOverlaps || overlapsSelection
        let children = childElements(for: element, truncated: &truncated)
        var childNodes: [A11yNode] = []
        for child in children {
            if let childNode = node(
                for: child,
                selection: selection,
                depth: depth + 1,
                visited: &visited,
                recursionStack: recursionStack,
                ancestorOverlaps: mayAcceptFramelessText,
                truncated: &truncated
            ) {
                childNodes.append(childNode)
            }
            if visited >= maxNodes {
                truncated = true
                break
            }
        }
        let role = stringAttribute(element, kAXRoleAttribute) ?? "AXUnknown"
        let name = stringAttribute(element, kAXTitleAttribute).map(sanitizer.redact)
        let value = stringAttribute(element, kAXValueAttribute).map(sanitizer.redact)
        let description = stringAttribute(element, kAXDescriptionAttribute).map(sanitizer.redact)
        let hasText = [name, value, description].contains { ($0 ?? "").isEmpty == false }
        guard overlapsSelection || !childNodes.isEmpty || hasText && frame == nil && mayAcceptFramelessText else { return nil }
        return A11yNode(
            elementId: "ax_\(elementKey)",
            role: role,
            name: name,
            value: value,
            description: description,
            frame: frame.map(BoundingBox.init),
            overlapRatio: min(max(Double(overlap), 0), 1),
            confidence: overlap > 0 ? 0.84 : 0.52,
            children: childNodes
        )
    }

    func textBlocks(from nodes: [A11yNode], selection: BoundingBox) -> [A11yTextBlock] {
        var blocks: [A11yTextBlock] = []
        var orderIndex = 0
        func visit(_ node: A11yNode, path: [Int], rolePath: [String]) {
            let textParts = textParts(for: node)
            let text = textParts
                .map { $0.value }
                .joined(separator: " ")
            if !text.isEmpty {
                let frame = node.frame
                let blockIndex = orderIndex
                orderIndex += 1
                blocks.append(
                    A11yTextBlock(
                        text: text,
                        blockId: "a11y_block_\(blockIndex)",
                        elementId: node.elementId,
                        role: node.role,
                        nodePath: path.map(String.init).joined(separator: "/"),
                        rolePath: rolePath + [node.role],
                        textSource: textParts.map { $0.source }.joined(separator: "+"),
                        frame: frame,
                        selectionOverlapRatio: frame.map { overlapRatio($0.cgRect, selection.cgRect, denominator: .selection) },
                        elementOverlapRatio: frame.map { overlapRatio($0.cgRect, selection.cgRect, denominator: .element) },
                        orderIndex: blockIndex,
                        isLeafText: node.children.isEmpty,
                        edgeRecovered: false,
                        confidence: node.confidence
                    )
                )
            }
            for (childIndex, child) in node.children.enumerated() {
                visit(child, path: path + [childIndex], rolePath: rolePath + [node.role])
            }
        }
        for (index, node) in nodes.enumerated() {
            visit(node, path: [index], rolePath: [])
        }
        return blocks
    }

    func textParts(for node: A11yNode) -> [(source: String, value: String)] {
        var parts: [(source: String, value: String)] = []
        var seen = Set<String>()
        let candidates = [
            ("name", node.name),
            ("value", node.value),
            ("description", node.description)
        ]
        for (source, rawValue) in candidates {
            let value = rawValue?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            guard !value.isEmpty, seen.insert(value).inserted else { continue }
            parts.append((source, value))
        }
        return parts
    }

    func childElements(for element: AXUIElement, truncated: inout Bool) -> [AXUIElement] {
        var children: [AXUIElement] = []
        var seen = Set<CFHashCode>()
        for attributeName in childAttributeNames {
            let attributeChildren: [AXUIElement] = attributeArray(
                element,
                attributeName,
                limit: maxChildrenPerAttribute,
                truncated: &truncated
            )
            for child in attributeChildren {
                let key = CFHash(child)
                guard seen.insert(key).inserted else { continue }
                children.append(child)
            }
        }
        return children
    }

    func attributeArray<T>(
        _ element: AXUIElement,
        _ name: String,
        limit: Int,
        truncated: inout Bool
    ) -> [T] {
        var count: CFIndex = 0
        let countResult = AXUIElementGetAttributeValueCount(element, name as CFString, &count)
        if countResult == .success, count > 0 {
            var values: CFArray?
            let requested = min(CFIndex(limit), count)
            if count > requested {
                truncated = true
            }
            let result = AXUIElementCopyAttributeValues(element, name as CFString, 0, requested, &values)
            guard result == .success, let values else { return [] }
            return (values as? [T]) ?? []
        }
        return (attribute(element, name) as [T]?) ?? []
    }

    func evidenceBundle(
        for snapshot: A11ySnapshot,
        command: CollectEvidenceCommand,
        providerSessionId: String,
        status: String
    ) -> ProviderEvidenceBundle {
        var evidence = [
            evidenceDraft(
                kind: "a11y",
                artifactType: "a11y_tree",
                role: "ui_structure",
                contentType: "application/json",
                content: json(snapshot),
                sourceUri: sourceURI(for: snapshot, suffix: "tree"),
                command: command,
                providerSessionId: providerSessionId,
                sensitivity: "high_sensitivity",
                trustStateClaim: "quarantined",
                redactionStateClaim: "quarantined",
                payloadSchema: "a11y_snapshot"
            ),
            evidenceDraft(
                kind: "provider_diagnostics",
                artifactType: "a11y_coverage",
                role: "provider_diagnostics",
                contentType: "application/json",
                content: json(snapshot.coverage),
                sourceUri: sourceURI(for: snapshot, suffix: "coverage"),
                command: command,
                providerSessionId: providerSessionId,
                sensitivity: "internal",
                trustStateClaim: "provider_redacted",
                redactionStateClaim: "none",
                payloadSchema: "a11y_coverage"
            )
        ]
        if snapshot.fullText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false {
            evidence.append(evidenceDraft(
                kind: "a11y",
                artifactType: "a11y_text",
                role: "source_text",
                contentType: "text/plain; charset=utf-8",
                content: snapshot.fullText,
                sourceUri: sourceURI(for: snapshot, suffix: "text"),
                command: command,
                providerSessionId: providerSessionId,
                sensitivity: "internal",
                trustStateClaim: "provider_redacted",
                redactionStateClaim: "redacted",
                payloadSchema: "a11y_text"
            ))
        }
        return ProviderEvidenceBundle(
            providerKey: "system.macos_a11y",
            providerSessionId: providerSessionId,
            commandId: command.commandId,
            status: status,
            evidenceKind: "a11y",
            sourceBinding: nil,
            evidence: evidence,
            diagnostics: [
                "permission_state": .string(snapshot.permissionState),
                "node_count": .int(snapshot.coverage.nodeCount),
                "text_block_count": .int(snapshot.coverage.textBlockCount)
            ],
            completedAt: Date()
        )
    }
}
