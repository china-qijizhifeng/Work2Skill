import AppKit
import Foundation

final class WindowResolver {
    func resolve(selectionScreenRect: CGRect? = nil) -> SourceBinding {
        let resolvedAt = Date()
        if let selectionScreenRect, let candidate = windowCandidates(overlapping: selectionScreenRect).first {
            let sourceType = sourceType(for: candidate.appName)
            return SourceBinding(
                bindingId: "src_\(UUID().uuidString.replacingOccurrences(of: "-", with: ""))",
                sourceRef: SourceRef(
                    sourceType: sourceType,
                    title: candidate.title ?? candidate.appName,
                    appName: candidate.appName,
                    url: nil,
                    origin: nil,
                    connectorName: "macos_window_resolver",
                    externalId: candidate.processIdentifier.map(String.init),
                    version: nil
                ),
                confidence: Self.sourceConfidence(for: sourceType, base: candidate.confidence, hasURL: false),
                resolvedAt: resolvedAt
            )
        }
        if selectionScreenRect != nil {
            return SourceBinding(
                bindingId: "src_\(UUID().uuidString.replacingOccurrences(of: "-", with: ""))",
                sourceRef: SourceRef(
                    sourceType: "desktop_window",
                    title: "屏幕选区",
                    appName: nil,
                    url: nil,
                    origin: nil,
                    connectorName: "macos_window_resolver",
                    externalId: nil,
                    version: nil
                ),
                confidence: 0.25,
                resolvedAt: resolvedAt
            )
        }

        let activeApp = NSWorkspace.shared.frontmostApplication
        let appName = activeApp?.localizedName ?? "Unknown App"
        let title = frontmostWindowTitle(processIdentifier: activeApp?.processIdentifier) ?? appName
        return SourceBinding(
            bindingId: "src_\(UUID().uuidString.replacingOccurrences(of: "-", with: ""))",
            sourceRef: SourceRef(
                sourceType: sourceType(for: appName),
                title: title,
                appName: appName,
                url: nil,
                origin: nil,
                connectorName: "macos_window_resolver",
                externalId: activeApp.map { String($0.processIdentifier) },
                version: nil
            ),
            confidence: Self.sourceConfidence(for: sourceType(for: appName), base: activeApp == nil ? 0.25 : 0.62, hasURL: false),
            resolvedAt: resolvedAt
        )
    }

    func resolveWindowHints(selectionScreenRect: CGRect) -> [WindowHint] {
        windowCandidates(overlapping: selectionScreenRect).map { candidate in
            WindowHint(
                appName: candidate.appName,
                title: candidate.title,
                processId: candidate.processIdentifier.map(Int.init),
                windowId: candidate.windowIdentifier.map(String.init),
                frame: Geometry.intBox(from: candidate.frame, coordinateSpace: "macos_global"),
                overlapRatio: candidate.overlapRatio,
                confidence: candidate.confidence,
                bundleId: candidate.bundleIdentifier,
                bundleUrl: nil,
                windowLayer: candidate.windowLayer,
                windowOrder: candidate.windowOrder,
                displayId: candidate.displayId,
                visibleAreaRatio: candidate.visibleAreaRatio,
                isFrontmost: candidate.isFrontmost,
                appIconRef: nil
            )
        }
    }

    private struct WindowCandidate {
        let appName: String
        let title: String?
        let processIdentifier: pid_t?
        let windowIdentifier: Int?
        let frame: CGRect
        let overlapRatio: Double
        let confidence: Double
        let bundleIdentifier: String?
        let bundleURL: String?
        let windowLayer: Int?
        let windowOrder: Int?
        let displayId: String?
        let visibleAreaRatio: Double?
        let isFrontmost: Bool?
    }

    private func sourceType(for appName: String) -> String {
        let browsers = ["Chrome", "Safari", "Arc", "Microsoft Edge", "Firefox"]
        return browsers.contains { appName.localizedCaseInsensitiveContains($0) } ? "web" : "desktop_window"
    }

    static func sourceConfidence(for sourceType: String, base: Double, hasURL: Bool) -> Double {
        // A browser window without a verified URL is still strong enough to
        // route the capture into the web provider. The extension raises the
        // confidence again when it returns URL/title/DOM evidence, but this
        // first hint must clear the submission threshold used for windowHints.
        if sourceType == "web", !hasURL {
            return min(base, 0.82)
        }
        return base
    }

    private func frontmostWindowTitle(processIdentifier: pid_t?) -> String? {
        guard let processIdentifier else { return nil }
        let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
        guard let windowInfo = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else {
            return nil
        }
        for window in windowInfo {
            guard let pid = window[kCGWindowOwnerPID as String] as? pid_t, pid == processIdentifier else {
                continue
            }
            if let title = window[kCGWindowName as String] as? String, !title.isEmpty {
                return title
            }
        }
        return nil
    }

    private func windowCandidates(overlapping selection: CGRect) -> [WindowCandidate] {
        let options: CGWindowListOption = [.optionOnScreenOnly, .excludeDesktopElements]
        guard let windowInfo = CGWindowListCopyWindowInfo(options, kCGNullWindowID) as? [[String: Any]] else {
            return []
        }
        let currentPID = ProcessInfo.processInfo.processIdentifier
        let frontmostPID = NSWorkspace.shared.frontmostApplication?.processIdentifier
        let candidates: [(WindowCandidate, CGFloat)] = windowInfo.enumerated().compactMap { index, window in
            guard
                let layer = window[kCGWindowLayer as String] as? Int,
                layer == 0,
                let boundsValue = window[kCGWindowBounds as String] as? NSDictionary,
                let rawBounds = CGRect(dictionaryRepresentation: boundsValue),
                rawBounds.width > 24,
                rawBounds.height > 24
            else {
                return nil
            }
            let pid = window[kCGWindowOwnerPID as String] as? pid_t
            if let pid, pid == currentPID {
                return nil
            }
            let owner = (window[kCGWindowOwnerName as String] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            guard let owner, !owner.isEmpty else { return nil }

            let title = (window[kCGWindowName as String] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines)
            guard let normalizedFrame = bestAppKitFrame(fromCGBounds: rawBounds) else {
                return nil
            }
            let bestOverlap = overlapArea(normalizedFrame.rect, selection)
            guard bestOverlap > 0 else { return nil }
            let selectionArea = max(selection.width * selection.height, 1)
            let overlapRatio = bestOverlap / selectionArea
            let selectedFrame = normalizedFrame.rect
            let windowArea = max(selectedFrame.width * selectedFrame.height, 1)
            let visibleAreaRatio = bestOverlap / windowArea
            let centerInside = selectedFrame.contains(CGPoint(x: selection.midX, y: selection.midY))
            guard overlapRatio >= 0.18 || (centerInside && overlapRatio >= 0.08) else { return nil }
            let confidenceBase = centerInside ? 0.74 : 0.66
            let confidence = min(0.92, confidenceBase + Double(min(overlapRatio, 1)) * 0.18)
            let windowNumber = window[kCGWindowNumber as String] as? Int
            let runningApp = pid.flatMap { NSRunningApplication(processIdentifier: $0) }
            return (
                WindowCandidate(
                    appName: owner,
                    title: title?.isEmpty == true ? nil : title,
                    processIdentifier: pid,
                    windowIdentifier: windowNumber,
                    frame: selectedFrame,
                    overlapRatio: Double(min(max(overlapRatio, 0), 1)),
                    confidence: confidence,
                    bundleIdentifier: runningApp?.bundleIdentifier,
                    bundleURL: runningApp?.bundleURL?.absoluteString,
                    windowLayer: layer,
                    windowOrder: index,
                    displayId: displayId(for: normalizedFrame.screen),
                    visibleAreaRatio: Double(min(max(visibleAreaRatio, 0), 1)),
                    isFrontmost: pid == frontmostPID
                ),
                routeScore(
                    overlapRatio: overlapRatio,
                    visibleAreaRatio: visibleAreaRatio,
                    centerInside: centerInside,
                    isFrontmost: pid == frontmostPID,
                    windowOrder: index
                )
            )
        }
        return candidates
            .sorted { lhs, rhs in
                if abs(lhs.0.overlapRatio - rhs.0.overlapRatio) <= 0.001 {
                    return (lhs.0.windowOrder ?? Int.max) < (rhs.0.windowOrder ?? Int.max)
                }
                if abs(lhs.1 - rhs.1) > 0.001 {
                    return lhs.1 > rhs.1
                }
                if abs(lhs.0.overlapRatio - rhs.0.overlapRatio) > 0.001 {
                    return lhs.0.overlapRatio > rhs.0.overlapRatio
                }
                return (lhs.0.windowOrder ?? Int.max) < (rhs.0.windowOrder ?? Int.max)
            }
            .prefix(4)
            .map(\.0)
    }

    private func bestAppKitFrame(fromCGBounds rect: CGRect) -> (rect: CGRect, screen: NSScreen)? {
        let converted = appKitRect(fromCGBounds: rect)
        let candidates = NSScreen.screens.map { screen in
            (screen: screen, overlap: overlapArea(screen.frame, converted))
        }
        if let best = candidates.max(by: { $0.overlap < $1.overlap }), best.overlap > 0 {
            return (converted, best.screen)
        }
        guard let fallbackScreen = NSScreen.screens.first(where: { $0.frame.intersects(converted) }) ?? NSScreen.main else {
            return nil
        }
        return (converted, fallbackScreen)
    }

    private func appKitRect(fromCGBounds rect: CGRect) -> CGRect {
        Self.appKitRect(fromCGBounds: rect, referenceMaxY: cgToAppKitReferenceMaxY())
    }

    static func appKitRect(fromCGBounds rect: CGRect, referenceMaxY: CGFloat) -> CGRect {
        CGRect(x: rect.minX, y: referenceMaxY - rect.maxY, width: rect.width, height: rect.height)
    }

    private func cgToAppKitReferenceMaxY() -> CGFloat {
        if let primary = NSScreen.screens.first(where: { $0.frame.origin == .zero }) {
            return primary.frame.maxY
        }
        return NSScreen.screens.first?.frame.maxY ?? NSScreen.main?.frame.maxY ?? 0
    }

    private func overlapArea(_ lhs: CGRect, _ rhs: CGRect) -> CGFloat {
        let intersection = lhs.intersection(rhs)
        guard !intersection.isNull else { return 0 }
        return max(0, intersection.width) * max(0, intersection.height)
    }

    private func routeScore(
        overlapRatio: CGFloat,
        visibleAreaRatio: CGFloat,
        centerInside: Bool,
        isFrontmost: Bool,
        windowOrder: Int
    ) -> CGFloat {
        let centerBoost: CGFloat = centerInside ? 0.08 : 0
        let frontmostBoost: CGFloat = isFrontmost ? 0.03 : 0
        let zOrderBoost = max(0, 0.04 - CGFloat(windowOrder) * 0.002)
        return overlapRatio * 0.72
            + min(visibleAreaRatio, 1) * 0.13
            + centerBoost
            + frontmostBoost
            + zOrderBoost
    }

    private func displayId(for screen: NSScreen) -> String? {
        guard let number = screen.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? NSNumber else {
            return nil
        }
        return number.stringValue
    }
}
