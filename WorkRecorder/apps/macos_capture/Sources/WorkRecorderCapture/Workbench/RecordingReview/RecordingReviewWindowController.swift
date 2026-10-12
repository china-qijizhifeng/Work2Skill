import AppKit
import AVFoundation
import WorkRecorderCaptureDesign

@MainActor
final class RecordingReviewWindowController: NSWindowController, NSWindowDelegate {
    private enum Layout {
        static let defaultSize = NSSize(width: 1280, height: 820)
        static let minSize = NSSize(width: 1100, height: 720)
        static let headerHeight: CGFloat = 68
        static let inspectorWidth: CGFloat = 368
        static let materialsWidth: CGFloat = 368
        static let timelineHeight: CGFloat = 156
        static let outerPadding: CGFloat = 18
        static let panelRadius: CGFloat = 16
    }

    let playbackController: RecordingPlaybackController
    let exportClient: RecordingExportingClient?
    var chooseExportDirectory: @MainActor () -> URL? = RecordingReviewWindowController.runExportDirectoryPanel
    var revealInFinder: @MainActor (URL) -> Void = { NSWorkspace.shared.activateFileViewerSelecting([$0]) }
    var convertExportToBenchmark: @MainActor (URL, String) async throws -> WorkbenchRecordingBenchmarkConversionResult = {
        try await WorkbenchRecordingBenchmarkConverter.convert(taskExportRoot: $0, expectedSessionId: $1)
    }
    var isExportInProgress = false
    let logStore: AppLogStore
    var currentRequest: RecordingReviewOpenRequest?
    var state = RecordingReviewState.initial(selectedStepId: nil, currentMediaTimeMs: nil)
    private var followTimer: Timer?
    private var didFinalizeWindowLifecycle = false
    private var e2eReportWrittenSessionId: String?
    var onClosed: (() -> Void)?

    init(
        client: RecordingPlaybackLoadingClient,
        logStore: AppLogStore,
        openPlaybackFile: @escaping (URL) -> Bool = { NSWorkspace.shared.open($0) }
    ) {
        self.playbackController = RecordingPlaybackController(client: client, openFile: openPlaybackFile)
        self.exportClient = client as? RecordingExportingClient
        self.logStore = logStore
        let window = RecordingReviewContentWindow(
            contentRect: NSRect(origin: .zero, size: Layout.defaultSize),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "WorkRecorder 录制复盘"
        window.minSize = Layout.minSize
        window.titleVisibility = .hidden
        window.toolbarStyle = .unifiedCompact
        window.isMovableByWindowBackground = true
        super.init(window: window)
        window.delegate = self
        window.onEscape = { [weak self] in
            Task { @MainActor [weak self] in
                self?.handleEscape()
            }
        }
        window.onTogglePlayback = { [weak self] in
            Task { @MainActor [weak self] in
                self?.togglePlaybackAction()
            }
        }
        window.onMoveStep = { [weak self] offset in
            Task { @MainActor [weak self] in
                self?.selectStep(offset: offset)
            }
        }
        window.onSeekRelative = { [weak self] delta in
            Task { @MainActor [weak self] in
                self?.seekRelative(delta)
            }
        }
        playbackController.onStateChanged = { [weak self] in
            guard let self else { return }
            self.render()
            self.writeE2EReportIfReady()
        }
    }

    required init?(coder: NSCoder) {
        nil
    }

    deinit {
        MainActor.assumeIsolated {
            followTimer?.invalidate()
            playbackController.clear(deleteFile: true)
        }
    }

    func present(_ request: RecordingReviewOpenRequest) {
        guard let recording = request.recording else { return }
        let switchingSession = currentRequest?.recording?.sessionId != nil
            && currentRequest?.recording?.sessionId != recording.sessionId
        if switchingSession {
            commitCurrentState()
            playbackController.pause()
            playbackController.clear(deleteFile: true)
        }
        let shouldPlaceWindow = switchingSession || window?.isVisible != true
        currentRequest = request
        didFinalizeWindowLifecycle = false
        let initialStepId = request.selectedStepId
            ?? RecordingReviewCore.selectedStep(in: recording, selectedStepId: nil)?.stepId
        state = RecordingReviewState.initial(
            selectedStepId: initialStepId,
            currentMediaTimeMs: request.currentMediaTimeMs
        )
        render()
        if shouldPlaceWindow {
            placeWindow(for: request)
        }
        showWindow(nil)
        window?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        ensureFollowTimer()
        autoLoadPlaybackForE2EIfNeeded()
    }

    func commitAndClose() {
        finalizeWindowLifecycle()
        close()
    }

    func windowWillClose(_ notification: Notification) {
        finalizeWindowLifecycle()
        onClosed?()
    }

    private func finalizeWindowLifecycle() {
        guard !didFinalizeWindowLifecycle else { return }
        didFinalizeWindowLifecycle = true
        commitCurrentState()
        playbackController.clear(deleteFile: true)
        followTimer?.invalidate()
        followTimer = nil
    }

    private func commitCurrentState() {
        guard let request = currentRequest,
              let recording = request.recording
        else { return }
        request.onCommit(
            RecordingReviewCommit(
                eventId: request.inspect.eventId,
                sessionId: recording.sessionId,
                selectedStepId: state.selectedStepId,
                currentMediaTimeMs: playbackController.currentMediaTimeMs(fallback: state.currentMediaTimeMs)
            )
        )
    }

    func selectedStep() -> WorkbenchRecordingTimelineStepView? {
        guard let recording = currentRequest?.recording else { return nil }
        return RecordingReviewCore.selectedStep(in: recording, selectedStepId: state.selectedStepId)
    }

    func playbackRequest() -> RecordingPlaybackLoadRequest? {
        guard let request = currentRequest,
              let recording = request.recording,
              let video = recording.videoRef,
              video.state == .available,
              let artifactId = video.artifactId,
              !artifactId.isEmpty
        else {
            return nil
        }
        return RecordingPlaybackLoadRequest(
            sessionId: recording.sessionId,
            eventId: request.inspect.eventId,
            artifactId: artifactId,
            purpose: "workbench_large_recording_review",
            initialMediaTimeMs: state.currentMediaTimeMs ?? selectedStep()?.mediaTimeMs
        )
    }

    func render() {
        guard let request = currentRequest,
              let recording = request.recording
        else {
            window?.contentView = emptyRootView("没有可复盘的录制。")
            return
        }
        let root = NSView()
        root.wantsLayer = true
        root.layer?.backgroundColor = WorkRecorderTheme.Prism.pearlWhite.cgColor

        let header = headerView(request: request, recording: recording)
        header.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(header)

        let body = NSView()
        body.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(body)
        let playback = playbackPane(request: request, recording: recording)
        playback.translatesAutoresizingMaskIntoConstraints = false
        playback.setContentHuggingPriority(.defaultLow, for: .horizontal)
        body.addSubview(playback)
        let sideContent = state.showsMaterialsPanel
            ? materialsPanel(inspect: request.inspect, recording: recording)
            : inspectorPanel(recording: recording)
        let side = sideScrollContainer(sideContent)
        side.translatesAutoresizingMaskIntoConstraints = false
        body.addSubview(side)

        let timeline = timelinePanel(recording: recording)
        timeline.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(timeline)

        let visibleStepCount = recording.timeline.map {
            RecordingReviewCore.visibleTimelineSteps(
                $0.steps,
                selectedStepId: state.selectedStepId,
                filter: state.timelineFilter,
                density: .default
            ).visibleSteps.count
        } ?? 0
        let timelineHeight: CGFloat = visibleStepCount <= 3 ? 168 : 240

        NSLayoutConstraint.activate([
            header.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: Layout.outerPadding),
            header.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -Layout.outerPadding),
            header.topAnchor.constraint(equalTo: root.topAnchor, constant: Layout.outerPadding),

            timeline.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: Layout.outerPadding),
            timeline.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -Layout.outerPadding),
            timeline.bottomAnchor.constraint(equalTo: root.bottomAnchor, constant: -Layout.outerPadding),
            timeline.heightAnchor.constraint(equalToConstant: timelineHeight),

            body.leadingAnchor.constraint(equalTo: root.leadingAnchor, constant: Layout.outerPadding),
            body.trailingAnchor.constraint(equalTo: root.trailingAnchor, constant: -Layout.outerPadding),
            body.topAnchor.constraint(equalTo: header.bottomAnchor, constant: 14),
            body.bottomAnchor.constraint(equalTo: timeline.topAnchor, constant: -14),

            playback.leadingAnchor.constraint(equalTo: body.leadingAnchor),
            playback.topAnchor.constraint(equalTo: body.topAnchor),
            playback.bottomAnchor.constraint(equalTo: body.bottomAnchor),
            playback.trailingAnchor.constraint(equalTo: side.leadingAnchor, constant: -14),

            side.trailingAnchor.constraint(equalTo: body.trailingAnchor),
            side.topAnchor.constraint(equalTo: body.topAnchor),
            side.widthAnchor.constraint(equalToConstant: state.showsMaterialsPanel ? Layout.materialsWidth : Layout.inspectorWidth),
            side.bottomAnchor.constraint(equalTo: body.bottomAnchor),
        ])

        window?.contentView = root
        root.layoutSubtreeIfNeeded()
        alignSideScrollToTop(side)
    }

    private func emptyRootView(_ text: String) -> NSView {
        let label = label(text, size: 14, weight: .medium, color: WorkbenchDesignTokens.Color.secondaryText)
        let root = NSView()
        label.translatesAutoresizingMaskIntoConstraints = false
        root.addSubview(label)
        NSLayoutConstraint.activate([
            label.centerXAnchor.constraint(equalTo: root.centerXAnchor),
            label.centerYAnchor.constraint(equalTo: root.centerYAnchor),
        ])
        return root
    }

    private func placeWindow(for request: RecordingReviewOpenRequest) {
        guard let window else { return }
        let frame = RecordingReviewWindowPlacementPolicy.preferredFrame(
            defaultSize: Layout.defaultSize,
            minSize: Layout.minSize,
            sourceWindowFrame: request.sourceWindowFrame,
            sourceScreenVisibleFrame: request.sourceScreenVisibleFrame
        )
        window.setFrame(frame, display: false)
    }

    private func sideScrollContainer(_ content: NSView) -> NSScrollView {
        let scroll = NSScrollView()
        scroll.drawsBackground = false
        scroll.hasVerticalScroller = true
        scroll.hasHorizontalScroller = false
        scroll.autohidesScrollers = true
        scroll.borderType = .noBorder
        let document = RecordingReviewFlippedDocumentView()
        document.translatesAutoresizingMaskIntoConstraints = false
        content.translatesAutoresizingMaskIntoConstraints = false
        document.addSubview(content)
        scroll.documentView = document
        NSLayoutConstraint.activate([
            document.widthAnchor.constraint(equalTo: scroll.contentView.widthAnchor),
            content.leadingAnchor.constraint(equalTo: document.leadingAnchor),
            content.trailingAnchor.constraint(equalTo: document.trailingAnchor),
            content.topAnchor.constraint(equalTo: document.topAnchor),
            content.bottomAnchor.constraint(equalTo: document.bottomAnchor),
            content.widthAnchor.constraint(equalTo: scroll.contentView.widthAnchor),
        ])
        return scroll
    }

    private func alignSideScrollToTop(_ scroll: NSScrollView) {
        scroll.layoutSubtreeIfNeeded()
        scroll.contentView.scroll(to: .zero)
        scroll.reflectScrolledClipView(scroll.contentView)
    }

    private func ensureFollowTimer() {
        guard followTimer == nil else { return }
        followTimer = Timer.scheduledTimer(withTimeInterval: 0.45, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.tickFollowSelection()
            }
        }
    }

    private func tickFollowSelection() {
        guard state.selectionMode == .follow,
              let recording = currentRequest?.recording,
              let steps = recording.timeline?.steps,
              let mediaTime = playbackController.currentMediaTimeMs(fallback: state.currentMediaTimeMs),
              let followStep = RecordingReviewCore.followStep(
                in: RecordingReviewCore.visibleTimelineSteps(
                    steps,
                    selectedStepId: state.selectedStepId,
                    filter: state.timelineFilter,
                    density: .default
                ).visibleSteps,
                mediaTimeMs: mediaTime
              )
        else { return }
        state.currentMediaTimeMs = mediaTime
        guard state.selectedStepId != followStep.stepId else { return }
        state.selectedStepId = followStep.stepId
        render()
    }

    func handleEscape() {
        if state.showsMaterialsPanel {
            state.showsMaterialsPanel = false
            render()
            return
        }
        window?.makeFirstResponder(window?.contentView)
    }

    @objc func closeReviewAction() {
        commitAndClose()
    }

    func loadPlayback(autoplay: Bool) {
        guard let request = playbackRequest() else {
            playbackController.errorMessage = "这条录制没有可播放的视频。"
            render()
            return
        }
        playbackController.load(request, autoplayRate: autoplay ? state.playbackRate : nil)
    }

    @objc func toggleMaterialsAction() {
        state.showsMaterialsPanel.toggle()
        render()
    }

    @objc func restoreFollowAction() {
        state.selectionMode = .follow
        tickFollowSelection()
        render()
    }

    @objc func selectReviewStep(_ sender: NSControl) {
        guard let stepId = sender.identifier?.rawValue,
              let recording = currentRequest?.recording,
              let step = recording.timeline.flatMap({ timeline in
                  RecordingReviewCore.orderedSteps(timeline.steps).first { $0.stepId == stepId }
              })
        else { return }
        focusPlayback(on: step)
    }

    @objc func selectEvidenceFrame(_ sender: NSControl) {
        let mediaTimeMs = sender.tag
        state.selectionMode = .pinned
        state.currentMediaTimeMs = mediaTimeMs
        if playbackController.showFrame(at: mediaTimeMs) {
            return
        }
        if playbackRequest() != nil {
            loadPlayback(autoplay: false)
        } else {
            render()
        }
    }

    @objc func selectPreviousStepAction() {
        selectStep(offset: -1)
    }

    @objc func selectNextStepAction() {
        selectStep(offset: 1)
    }

    func selectStep(offset: Int) {
        guard let recording = currentRequest?.recording,
              let steps = recording.timeline?.steps,
              let next = RecordingReviewCore.stepNeighbor(
                in: RecordingReviewCore.visibleTimelineSteps(
                    steps,
                    selectedStepId: state.selectedStepId,
                    filter: state.timelineFilter,
                    density: .default
                ).visibleSteps,
                selectedStep: rawSelectedStep(in: steps) ?? selectedStep(),
                offset: offset
              )
        else { return }
        focusPlayback(on: next)
    }

    private func focusPlayback(on step: WorkbenchRecordingTimelineStepView) {
        state.selectedStepId = step.stepId
        state.selectionMode = .pinned
        state.currentMediaTimeMs = step.mediaTimeMs
        if playbackController.showFrame(at: step.mediaTimeMs) {
            return
        }
        if step.mediaTimeMs != nil, playbackRequest() != nil {
            loadPlayback(autoplay: false)
        } else {
            render()
        }
    }

    private func rawSelectedStep(in steps: [WorkbenchRecordingTimelineStepView]) -> WorkbenchRecordingTimelineStepView? {
        guard let selectedStepId = state.selectedStepId else { return nil }
        return RecordingReviewCore.orderedSteps(steps).first { $0.stepId == selectedStepId }
    }

    func seekRelative(_ deltaMs: Int) {
        let current = playbackController.currentMediaTimeMs(fallback: state.currentMediaTimeMs) ?? 0
        let next = max(0, current + deltaMs)
        state.currentMediaTimeMs = next
        playbackController.seek(to: next)
        if state.selectionMode == .follow {
            tickFollowSelection()
        }
        render()
    }

    @objc func playbackRateChanged(_ sender: NSSegmentedControl) {
        let rates: [Float] = [0.5, 1.0, 1.25, 1.5, 2.0]
        guard sender.selectedSegment >= 0, sender.selectedSegment < rates.count else { return }
        state.playbackRate = rates[sender.selectedSegment]
        if playbackController.playbackSession?.player.rate != 0 {
            playbackController.playbackSession?.play(rate: state.playbackRate)
        }
        render()
    }
}

@MainActor
private final class RecordingReviewFlippedDocumentView: NSView {
    override var isFlipped: Bool {
        true
    }
}

private extension RecordingReviewWindowController {
    func autoLoadPlaybackForE2EIfNeeded() {
        guard RecordingE2ELaunchResolver.shouldAutoLoadLargeReviewPlayback(),
              playbackRequest() != nil
        else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
            guard let self, self.currentRequest?.recording != nil else { return }
            self.loadPlayback(autoplay: false)
        }
    }

    func writeE2EReportIfReady() {
        guard let request = currentRequest,
              let recording = request.recording,
              e2eReportWrittenSessionId != recording.sessionId,
              let session = playbackController.playbackSession
        else { return }
        guard RecordingReviewE2EReporter.writeReportIfRequested(
            request: request,
            recording: recording,
            window: window,
            playbackSession: session
        ) else { return }
        e2eReportWrittenSessionId = recording.sessionId
    }
}
