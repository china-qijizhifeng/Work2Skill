import Foundation

@MainActor
extension CaptureCoordinator {
    func refreshRecordingScopeHealth(
        context: RecordingRuntimeContext,
        nowMonotonicMilliseconds: Int
    ) {
        guard !recordingScopeNeedsReview else {
            recordingHUDWindow?.setScopeNeedsReview(true)
            return
        }
        guard nowMonotonicMilliseconds - recordingLastScopeHealthCheckMonotonicMilliseconds >= 2_000 else {
            return
        }
        recordingLastScopeHealthCheckMonotonicMilliseconds = nowMonotonicMilliseconds
        let verdict = recordingScopeHealthPolicy.evaluate(
            initialScope: context.scope,
            currentWindowHints: windowResolver.resolveWindowHints(selectionScreenRect: context.selection.screenRect)
        )
        guard verdict.needsReview else { return }
        recordingScopeNeedsReview = true
        var updated = context
        updated.scopeNeedsReview = true
        activeRecordingContext = updated
        recordingHUDWindow?.setScopeNeedsReview(true)
        recordingHUDWindow?.showTransientStatus("范围需复核")
        log("录制范围需要复核：\(verdict.reason.rawValue) app=\(verdict.observedAppName ?? "unknown")")
    }
}
