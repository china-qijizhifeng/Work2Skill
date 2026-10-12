import Testing
@testable import WorkRecorderCapture

struct RecordingScopeHealthPolicyTests {
    @Test func matchingWindowIdIsHealthy() {
        let verdict = RecordingScopeHealthPolicy().evaluate(
            initialScope: Self.scope(windowId: "win_1", processId: 42, bundleId: "com.example.App", appName: "Example"),
            currentWindowHints: [
                Self.hint(windowId: "win_1", processId: 99, bundleId: "com.other.App", appName: "Other")
            ]
        )

        #expect(verdict.status == .healthy)
        #expect(verdict.reason == .matchedWindowId)
    }

    @Test func matchingProcessOrBundleIsHealthyWhenWindowIdRotates() {
        let verdict = RecordingScopeHealthPolicy().evaluate(
            initialScope: Self.scope(windowId: "win_old", processId: 42, bundleId: "com.example.App", appName: "Example"),
            currentWindowHints: [
                Self.hint(windowId: "win_new", processId: 42, bundleId: "com.example.App", appName: "Example")
            ]
        )

        #expect(verdict.status == .healthy)
        #expect(verdict.reason == .matchedProcessOrBundle)
    }

    @Test func missingCurrentWindowCandidateNeedsReview() {
        let verdict = RecordingScopeHealthPolicy().evaluate(
            initialScope: Self.scope(windowId: "win_1", processId: 42, bundleId: "com.example.App", appName: "Example"),
            currentWindowHints: []
        )

        #expect(verdict.status == .needsReview)
        #expect(verdict.reason == .noCurrentWindowCandidate)
        #expect(verdict.needsReview)
    }

    @Test func changedPrimaryCandidateNeedsReview() {
        let verdict = RecordingScopeHealthPolicy().evaluate(
            initialScope: Self.scope(windowId: "win_1", processId: 42, bundleId: "com.example.App", appName: "Example"),
            currentWindowHints: [
                Self.hint(windowId: "win_2", processId: 7, bundleId: "com.example.Other", appName: "Other")
            ]
        )

        #expect(verdict.status == .needsReview)
        #expect(verdict.reason == .primaryCandidateChanged)
    }

    @Test func weakCandidateIsLowConfidenceNeedsReview() {
        let verdict = RecordingScopeHealthPolicy().evaluate(
            initialScope: Self.scope(windowId: "win_1", processId: 42, bundleId: "com.example.App", appName: "Example"),
            currentWindowHints: [
                Self.hint(windowId: "win_1", processId: 42, bundleId: "com.example.App", appName: "Example", confidence: 0.3)
            ]
        )

        #expect(verdict.status == .lowConfidence)
        #expect(verdict.reason == .weakCurrentCandidate)
        #expect(verdict.needsReview)
    }

    @Test func missingInitialIdentityIsUntrackedNotWarning() {
        let verdict = RecordingScopeHealthPolicy().evaluate(
            initialScope: Self.scope(windowId: nil, processId: nil, bundleId: nil, appName: nil),
            currentWindowHints: [Self.hint(windowId: "win_1", processId: 42, bundleId: "com.example.App", appName: "Example")]
        )

        #expect(verdict.status == .untracked)
        #expect(verdict.reason == .missingInitialIdentity)
        #expect(!verdict.needsReview)
    }

    private static func scope(
        windowId: String?,
        processId: Int?,
        bundleId: String?,
        appName: String?
    ) -> ActiveCaptureRecordingScope {
        ActiveCaptureRecordingScope(
            kind: .region,
            displayId: "main",
            scaleFactor: 2,
            windowId: windowId,
            processId: processId,
            bundleId: bundleId,
            appName: appName,
            title: appName,
            bounds: nil,
            selectionRegion: BoundingBox(x: 20, y: 20, width: 640, height: 360, coordinateSpace: "macos_global"),
            scopeConfidence: 0.9,
            occlusionEstimate: nil,
            metadata: [:]
        )
    }

    private static func hint(
        windowId: String?,
        processId: Int?,
        bundleId: String?,
        appName: String,
        confidence: Double = 0.84,
        overlapRatio: Double = 0.72
    ) -> WindowHint {
        WindowHint(
            appName: appName,
            title: appName,
            processId: processId,
            windowId: windowId,
            frame: BoundingBox(x: 20, y: 20, width: 640, height: 360, coordinateSpace: "macos_global"),
            overlapRatio: overlapRatio,
            confidence: confidence,
            bundleId: bundleId,
            displayId: "main",
            isFrontmost: true
        )
    }
}
