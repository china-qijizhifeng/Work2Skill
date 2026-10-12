import Foundation

enum RecordingScopeHealthStatus: String, Equatable {
    case healthy
    case untracked
    case lowConfidence = "low_confidence"
    case needsReview = "needs_review"
}

enum RecordingScopeHealthReason: String, Equatable {
    case matchedWindowId = "matched_window_id"
    case matchedProcessOrBundle = "matched_process_or_bundle"
    case missingInitialIdentity = "missing_initial_identity"
    case noCurrentWindowCandidate = "no_current_window_candidate"
    case primaryCandidateChanged = "primary_candidate_changed"
    case weakCurrentCandidate = "weak_current_candidate"
}

struct RecordingScopeHealthVerdict: Equatable {
    let status: RecordingScopeHealthStatus
    let reason: RecordingScopeHealthReason
    let observedAppName: String?
    let observedWindowId: String?

    var needsReview: Bool {
        status == .needsReview || status == .lowConfidence
    }
}

struct RecordingScopeHealthPolicy {
    let minimumConfidence: Double
    let minimumOverlapRatio: Double

    init(minimumConfidence: Double = 0.54, minimumOverlapRatio: Double = 0.18) {
        self.minimumConfidence = minimumConfidence
        self.minimumOverlapRatio = minimumOverlapRatio
    }

    func evaluate(
        initialScope: ActiveCaptureRecordingScope,
        currentWindowHints: [WindowHint]
    ) -> RecordingScopeHealthVerdict {
        guard hasTrackableIdentity(initialScope) else {
            return RecordingScopeHealthVerdict(
                status: .untracked,
                reason: .missingInitialIdentity,
                observedAppName: currentWindowHints.first?.appName,
                observedWindowId: currentWindowHints.first?.windowId
            )
        }
        guard let primary = currentWindowHints.first else {
            return RecordingScopeHealthVerdict(
                status: .needsReview,
                reason: .noCurrentWindowCandidate,
                observedAppName: nil,
                observedWindowId: nil
            )
        }
        guard primary.confidence >= minimumConfidence, primary.overlapRatio >= minimumOverlapRatio else {
            return RecordingScopeHealthVerdict(
                status: .lowConfidence,
                reason: .weakCurrentCandidate,
                observedAppName: primary.appName,
                observedWindowId: primary.windowId
            )
        }
        if let initialWindowId = initialScope.windowId,
           currentWindowHints.contains(where: { $0.windowId == initialWindowId })
        {
            return RecordingScopeHealthVerdict(
                status: .healthy,
                reason: .matchedWindowId,
                observedAppName: primary.appName,
                observedWindowId: primary.windowId
            )
        }
        if matchesProcessOrBundle(initialScope, primary) {
            return RecordingScopeHealthVerdict(
                status: .healthy,
                reason: .matchedProcessOrBundle,
                observedAppName: primary.appName,
                observedWindowId: primary.windowId
            )
        }
        return RecordingScopeHealthVerdict(
            status: .needsReview,
            reason: .primaryCandidateChanged,
            observedAppName: primary.appName,
            observedWindowId: primary.windowId
        )
    }

    private func hasTrackableIdentity(_ scope: ActiveCaptureRecordingScope) -> Bool {
        scope.windowId != nil || scope.processId != nil || scope.bundleId != nil || scope.appName != nil
    }

    private func matchesProcessOrBundle(_ scope: ActiveCaptureRecordingScope, _ hint: WindowHint) -> Bool {
        if let processId = scope.processId, hint.processId == processId {
            return true
        }
        if let bundleId = scope.bundleId, hint.bundleId == bundleId {
            return true
        }
        if let appName = scope.appName?.trimmingCharacters(in: .whitespacesAndNewlines),
           !appName.isEmpty,
           appName.localizedCaseInsensitiveCompare(hint.appName) == .orderedSame
        {
            return true
        }
        return false
    }
}
