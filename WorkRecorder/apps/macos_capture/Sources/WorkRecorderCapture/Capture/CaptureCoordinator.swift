import AppKit
import CoreGraphics
import Foundation

enum CaptureKeyCode {
    static let escape: UInt16 = 53
    static let space: UInt16 = 49
    static let `return`: UInt16 = 36
    static let keypadEnter: UInt16 = 76
}

@MainActor
final class CaptureCoordinator {
    let environment: CaptureEnvironment
    let screenCapture: ScreenCaptureService
    let windowResolver = WindowResolver()
    let transport: CaptureTransport
    weak var logStore: AppLogStore?
    var overlayWindows: [CaptureOverlayWindow] = []
    var anchorOverlay: CaptureAnchorOverlayWindow?
    var recordingPreparationWindow: RecordingPreparationWindow?
    var recordingHUDWindow: RecordingHUDWindow?
    var recordingBoundaryWindow: RecordingBoundaryOverlayWindow?
    var recordingCountdownWindow: RecordingCountdownWindow?
    var recordingCompletionWindow: RecordingCompletionWindow?
    var recordingDiscardConfirmationWindow: RecordingDiscardConfirmationWindow?
    var recordingPermissionIssueWindow: RecordingPermissionIssueWindow?
    var recordingHUDTimer: Timer?
    var recordingPausedAtMonotonicMilliseconds: Int?
    var recordingPausedAccumulatedMilliseconds = 0
    var recordingControlInFlight = false
    var recordingSessionController = RecordingSessionController()
    var recordingCompletionSubmitting = false
    var recordingInputTraceDegraded = false
    var recordingScopeNeedsReview = false
    var recordingLastScopeHealthCheckMonotonicMilliseconds = 0
    let recordingScopeHealthPolicy = RecordingScopeHealthPolicy()
    var recordingStartupTask: Task<Void, Never>?
    var recordingStartupToken: UUID?
    var recordingStartupBackendSessionId: String?
    let regionRecorder = ScreenCaptureKitRegionRecorder()
    var activeRecordingSegment: ScreenCaptureKitRegionRecordingSegment?
    var activeRecordingContext: RecordingRuntimeContext?
    var pendingRecordingCompletion: RecordingCompletionDraft?
    var recordingCompletionCaptureDrainAllowed = false
    var recordingPreviewVideoURL: URL?
    var lastRecordingChromeSuppressionMonotonicMilliseconds: Int?
    var retiredHUDWindows: [NSWindow] = []
    var selectionLocalKeyMonitor: Any?
    var selectionGlobalKeyMonitor: Any?
    var armedSourceBinding: SourceBinding?
    var activeSessionId: UUID?
    var openRecentCaptures: (() -> Void)?
    var openRecordingsLibrary: (() -> Void)?
    var openRecordingReviewForSavedEvent: ((String) -> Void)?
    var onCaptureSaved: ((String?) -> Void)?
    var onStateChanged: ((State) -> Void)?
    var activeCaptureInputProducer: ActiveCaptureInputEventProducer?

    var state: State = .idle

    init(environment: CaptureEnvironment, logStore: AppLogStore? = nil) {
        self.environment = environment
        self.screenCapture = ScreenCaptureService(stagingDirectory: environment.stagingDirectory)
        self.transport = CaptureTransport(
            daemonURL: environment.daemonURL,
            installSecret: environment.installSecret,
            nativeCaptureSecret: environment.nativeCaptureSecret
        )
        self.logStore = logStore
    }

    var recordingMenuPresentation: RecordingMenuPresentation {
        RecordingMenuPresentation.make(
            state: state,
            hasActiveRecordingContext: activeRecordingContext != nil,
            hasRecordingStartup: recordingStartupTask != nil || recordingStartupBackendSessionId != nil,
            hasPendingCompletion: pendingRecordingCompletion != nil,
            isControlInFlight: recordingControlInFlight || recordingCompletionSubmitting
        )
    }

    var hasPendingRecordingSurface: Bool {
        pendingRecordingCompletion != nil || recordingCompletionSubmitting
    }

    var hasRecordingSessionSurface: Bool {
        activeRecordingContext != nil
            || pendingRecordingCompletion != nil
            || recordingControlInFlight
            || recordingCompletionSubmitting
            || recordingStartupTask != nil
            || recordingStartupBackendSessionId != nil
    }

    @discardableResult
    func focusBlockingRecordingSurfaceIfNeeded(reason: String) -> Bool {
        guard hasRecordingSessionSurface else { return false }
        log(reason)
        focusRecordingControls()
        return true
    }

    func syncRecordingControlFieldsFromSessionController() {
        let snapshot = recordingSessionController.snapshot
        recordingControlInFlight = snapshot.inFlight
        recordingPausedAtMonotonicMilliseconds = snapshot.pausedAtMonotonicMilliseconds
        recordingPausedAccumulatedMilliseconds = snapshot.pausedAccumulatedMilliseconds
    }
}

extension BoundingBox {
    var cgRect: CGRect {
        CGRect(x: x, y: y, width: width, height: height)
    }
}
