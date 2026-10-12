import Carbon
import AppKit
import CoreGraphics
import Foundation

final class ActiveCaptureInputEventProducer: @unchecked Sendable {
    private let transport: any ActiveCaptureProducerEventTransport
    private let sessionId: String
    private let typingPauseDelayMilliseconds: Int
    private let scrollStopDelayMilliseconds: Int
    private let producerSubmitRetryInitialDelayMilliseconds: Int
    private let producerSubmitRetryMaxDelayMilliseconds: Int
    private let producerSubmitMaxRetryAttempts: Int
    private let recordFullKeystrokes: Bool
    private let scopeBounds: CGRect?
    private let recordingScope: ActiveCaptureRecordingScope?
    private let observedScopeProvider: @Sendable () -> ActiveCaptureRecordingScope?
    private let settleProbeProvider: (@Sendable () async -> ActiveCaptureSettleProbeSnapshot?)?
    private let captureInstructionHandler: @Sendable (ActiveCaptureCaptureInstruction) -> Void
    private let diagnosticHandler: @Sendable (String) -> Void
    private let stateQueue = DispatchQueue(label: "workrecorder.active-capture.input-producer")
    private var eventTap: CFMachPort?
    private var runLoopSource: CFRunLoopSource?
    private var supplementalKeyboardEventTap: CFMachPort?
    private var supplementalKeyboardRunLoopSource: CFRunLoopSource?
    private var tapContext: ActiveCaptureInputEventTapContext?
    private let tapRunLoop = InputEventTapRunLoop()
    private let supplementalKeyboardTapRunLoop = InputEventTapRunLoop()
    private let submissionQueue: ActiveCaptureProducerSubmissionQueue
    private var tapEventDeduper = ActiveCaptureInputEventDeduper()
    private var typingAggregator = TypingPauseAggregator()
    private var typingScope: ActiveCaptureRecordingScope?
    private var typingFlushWorkItem: DispatchWorkItem?
    private var activeTextKeyDowns: Set<Int> = []
    private var scrollAggregator = ScrollGestureAggregator()
    private var scrollScope: ActiveCaptureRecordingScope?
    private var scrollFlushWorkItem: DispatchWorkItem?
    private var pointerDragTracker: PointerDragTracker?
    private let captureInstructionWorkItemsLock = NSLock()
    private var captureInstructionWorkItems: [ScheduledCaptureInstruction] = []
    private let scheduledCaptureInstructionIdsLock = NSLock()
    private var scheduledCaptureInstructionIds: Set<String> = []
    private var pendingInstructionPollTask: Task<Void, Never>?
    private var pendingInstructionPollGeneration = 0
    private let pendingInstructionPollIntervalMilliseconds = 500
    private let pendingInstructionPollingActivityWindowMilliseconds = 3_000
    private var lastProducerSubmissionMonotonicMilliseconds: Int?
    private var producerSubmissionActivityGeneration = 0
    private let lifecycleLock = NSLock()
    private var isRunning = false

    init(
        sessionId: String,
        transport: any ActiveCaptureProducerEventTransport,
        typingPauseDelayMilliseconds: Int = 500,
        scrollStopDelayMilliseconds: Int = 180,
        producerSubmitRetryInitialDelayMilliseconds: Int = 150,
        producerSubmitRetryMaxDelayMilliseconds: Int = 2_000,
        producerSubmitMaxRetryAttempts: Int = 5,
        producerSubmissionBatchSize: Int = 32,
        producerSubmissionMaxPendingEvents: Int = 2_000,
        recordFullKeystrokes: Bool = false,
        scopeBounds: CGRect? = nil,
        recordingScope: ActiveCaptureRecordingScope? = nil,
        observedScopeProvider: @escaping @Sendable () -> ActiveCaptureRecordingScope? = {
            ActiveCaptureObservedScopeResolver.frontmostWindowScope()
        },
        settleProbeProvider: (@Sendable () async -> ActiveCaptureSettleProbeSnapshot?)? = nil,
        captureInstructionHandler: @escaping @Sendable (ActiveCaptureCaptureInstruction) -> Void = { instruction in
            NSLog("WorkRecorder active capture instruction ready candidate=\(instruction.candidateId)")
        },
        diagnosticHandler: @escaping @Sendable (String) -> Void = { message in
            NSLog("WorkRecorder active capture input producer: \(message)")
        }
    ) {
        self.sessionId = sessionId
        self.transport = transport
        self.typingPauseDelayMilliseconds = typingPauseDelayMilliseconds
        self.scrollStopDelayMilliseconds = scrollStopDelayMilliseconds
        self.producerSubmitRetryInitialDelayMilliseconds = producerSubmitRetryInitialDelayMilliseconds
        self.producerSubmitRetryMaxDelayMilliseconds = producerSubmitRetryMaxDelayMilliseconds
        self.producerSubmitMaxRetryAttempts = producerSubmitMaxRetryAttempts
        self.submissionQueue = ActiveCaptureProducerSubmissionQueue(
            batchSize: producerSubmissionBatchSize,
            maxPendingEvents: producerSubmissionMaxPendingEvents
        )
        self.recordFullKeystrokes = recordFullKeystrokes
        self.scopeBounds = scopeBounds
        self.recordingScope = recordingScope
        self.observedScopeProvider = observedScopeProvider
        self.settleProbeProvider = settleProbeProvider
        self.captureInstructionHandler = captureInstructionHandler
        self.diagnosticHandler = diagnosticHandler
    }

    func start() throws {
        stop()
        var mask = (1 << CGEventType.leftMouseDown.rawValue)
            | (1 << CGEventType.rightMouseDown.rawValue)
            | (1 << CGEventType.otherMouseDown.rawValue)
            | (1 << CGEventType.leftMouseDragged.rawValue)
            | (1 << CGEventType.rightMouseDragged.rawValue)
            | (1 << CGEventType.otherMouseDragged.rawValue)
            | (1 << CGEventType.leftMouseUp.rawValue)
            | (1 << CGEventType.rightMouseUp.rawValue)
            | (1 << CGEventType.otherMouseUp.rawValue)
            | (1 << CGEventType.scrollWheel.rawValue)
            | (1 << CGEventType.keyDown.rawValue)
        if recordFullKeystrokes {
            mask |= (1 << CGEventType.keyUp.rawValue)
        }
        let tapContext = ActiveCaptureInputEventTapContext(producer: self)
        let callback: CGEventTapCallBack = { _, type, event, userInfo in
            guard let userInfo else {
                return Unmanaged.passUnretained(event)
            }
            let context = Unmanaged<ActiveCaptureInputEventTapContext>
                .fromOpaque(userInfo)
                .takeUnretainedValue()
            guard let producer = context.producerSnapshot() else {
                return Unmanaged.passUnretained(event)
            }
            if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
                producer.diagnosticHandler("event tap disabled by system; re-enabling")
                producer.enableEventTaps()
                return Unmanaged.passUnretained(event)
            }
            producer.enqueueTapEvent(type: type, event: event)
            return Unmanaged.passUnretained(event)
        }
        guard let tap = createEventTap(
            tapLocation: .cgSessionEventTap,
            mask: mask,
            callback: callback,
            tapContext: tapContext
        ) else {
            throw CaptureTransportError.unsupported("WorkRecorder 无法启动输入事件监听，请检查辅助功能/输入监听权限。")
        }
        self.tapContext = tapContext
        eventTap = tap
        guard let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0) else {
            CFMachPortInvalidate(tap)
            eventTap = nil
            self.tapContext = nil
            throw CaptureTransportError.unsupported("WorkRecorder 无法启动输入事件监听，请检查辅助功能/输入监听权限。")
        }
        runLoopSource = source
        setRunning(true)
        tapRunLoop.start(tap: tap, source: source)
        startSupplementalKeyboardTap(
            keyMask: keyEventMask(),
            callback: callback,
            tapContext: tapContext
        )
        startPendingInstructionPolling()
    }

    private func createEventTap(
        tapLocation: CGEventTapLocation,
        mask: Int,
        callback: @escaping CGEventTapCallBack,
        tapContext: ActiveCaptureInputEventTapContext
    ) -> CFMachPort? {
        if let tap = CGEvent.tapCreate(
            tap: tapLocation,
            place: .headInsertEventTap,
            options: .listenOnly,
            eventsOfInterest: CGEventMask(mask),
            callback: callback,
            userInfo: Unmanaged.passUnretained(tapContext).toOpaque()
        ) {
            diagnosticHandler("input event tap started at \(tapLocation == .cghidEventTap ? "hid" : "session") layer")
            return tap
        }
        return nil
    }

    private func keyEventMask() -> Int {
        var mask = (1 << CGEventType.keyDown.rawValue)
        if recordFullKeystrokes {
            mask |= (1 << CGEventType.keyUp.rawValue)
        }
        return mask
    }

    private func startSupplementalKeyboardTap(
        keyMask: Int,
        callback: @escaping CGEventTapCallBack,
        tapContext: ActiveCaptureInputEventTapContext
    ) {
        guard let tap = createEventTap(
            tapLocation: .cghidEventTap,
            mask: keyMask,
            callback: callback,
            tapContext: tapContext
        ) else {
            diagnosticHandler("supplemental hid keyboard event tap unavailable; session tap remains active")
            return
        }
        guard let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0) else {
            CFMachPortInvalidate(tap)
            diagnosticHandler("supplemental hid keyboard event tap source unavailable; session tap remains active")
            return
        }
        supplementalKeyboardEventTap = tap
        supplementalKeyboardRunLoopSource = source
        supplementalKeyboardTapRunLoop.start(tap: tap, source: source)
    }

    private func enableEventTaps() {
        guard isRunningSnapshot() else { return }
        tapRunLoop.enableIfRunning()
        supplementalKeyboardTapRunLoop.enableIfRunning()
    }

    func stop(
        flushPendingAggregates: Bool = true,
        cancelPendingCaptureInstructions: Bool = true
    ) {
        stopInternal(
            flushPendingAggregates: flushPendingAggregates,
            cancelPendingCaptureInstructions: cancelPendingCaptureInstructions
        )
    }

    private func stopInternal(
        flushPendingAggregates: Bool,
        cancelPendingCaptureInstructions: Bool
    ) {
        setRunning(false)
        tapContext?.clearProducer()
        // Stop and join both tap threads before disabling, invalidating, or
        // releasing either port or the callback context.
        tapRunLoop.stop()
        supplementalKeyboardTapRunLoop.stop()
        if let eventTap {
            CGEvent.tapEnable(tap: eventTap, enable: false)
        }
        if let supplementalKeyboardEventTap {
            CGEvent.tapEnable(tap: supplementalKeyboardEventTap, enable: false)
        }
        if let eventTap {
            CFMachPortInvalidate(eventTap)
        }
        if let supplementalKeyboardEventTap {
            CFMachPortInvalidate(supplementalKeyboardEventTap)
        }
        typingFlushWorkItem?.cancel()
        typingFlushWorkItem = nil
        scrollFlushWorkItem?.cancel()
        scrollFlushWorkItem = nil
        if cancelPendingCaptureInstructions {
            captureInstructionWorkItemsLock.lock()
            let cancelled = captureInstructionWorkItems
            cancelled.forEach { $0.workItem.cancel() }
            captureInstructionWorkItems.removeAll()
            captureInstructionWorkItemsLock.unlock()
            reportCancelledCaptureInstructions(cancelled)
        }
        stopPendingInstructionPolling()
        pendingInstructionPollTask = nil
        scheduledCaptureInstructionIdsLock.lock()
        scheduledCaptureInstructionIds.removeAll()
        scheduledCaptureInstructionIdsLock.unlock()
        runLoopSource = nil
        supplementalKeyboardRunLoopSource = nil
        eventTap = nil
        supplementalKeyboardEventTap = nil
        tapContext = nil
        tapEventDeduper.reset()
        stateQueue.sync {
            if flushPendingAggregates {
                flushScrollLocked()
                flushTypingLocked()
            }
            activeTextKeyDowns.removeAll()
            pointerDragTracker = nil
        }
    }

    private func startPendingInstructionPolling() {
        stopPendingInstructionPolling()
        let generation = nextPendingInstructionPollGeneration()
        let pollIntervalMilliseconds = pendingInstructionPollIntervalMilliseconds
        pendingInstructionPollTask = Task { [weak self, transport, sessionId, settleProbeProvider, diagnosticHandler, generation] in
            while true {
                do {
                    try await Task.sleep(
                        nanoseconds: UInt64(pollIntervalMilliseconds) * 1_000_000
                    )
                } catch {
                    return
                }
                guard let self, isRunningSnapshot(), isPendingInstructionPollingCurrent(generation) else { return }
                guard let pollingActivity = pendingInstructionPollingActivity(
                    nowMonotonicMilliseconds: monotonicMilliseconds()
                ) else {
                    continue
                }
                do {
                    let probePlan = try await transport.pollPendingCaptureInstructions(
                        sessionId: sessionId,
                        probeSnapshot: nil,
                        allowDegradedSample: false
                    )
                    guard isRunningSnapshot(), isPendingInstructionPollingCurrent(generation) else { return }
                    for instruction in probePlan.captureInstructions {
                        scheduleCaptureInstruction(instruction)
                    }
                    if probePlan.observedCandidateCount == 0,
                       probePlan.probeRequiredCandidateCount == 0
                    {
                        clearProducerSubmissionActivityIfUnchanged(pollingActivity)
                    }
                    guard probePlan.probeRequiredCandidateCount > 0 else {
                        continue
                    }
                    let probeSnapshot = await settleProbeProvider?()
                    guard isRunningSnapshot(), isPendingInstructionPollingCurrent(generation) else { return }
                    let result = try await transport.pollPendingCaptureInstructions(
                        sessionId: sessionId,
                        probeSnapshot: probeSnapshot,
                        allowDegradedSample: true
                    )
                    guard isRunningSnapshot(), isPendingInstructionPollingCurrent(generation) else { return }
                    for instruction in result.captureInstructions {
                        scheduleCaptureInstruction(instruction)
                    }
                } catch is CancellationError {
                    return
                } catch let error as URLError where error.code == .cancelled {
                    return
                } catch {
                    diagnosticHandler("failed to poll pending capture instructions: \(error.localizedDescription)")
                }
            }
        }
    }

    private func stopPendingInstructionPolling() {
        _ = nextPendingInstructionPollGeneration()
        pendingInstructionPollTask = nil
    }

    private func nextPendingInstructionPollGeneration() -> Int {
        lifecycleLock.lock()
        pendingInstructionPollGeneration += 1
        let generation = pendingInstructionPollGeneration
        lifecycleLock.unlock()
        return generation
    }

    private func isPendingInstructionPollingCurrent(_ generation: Int) -> Bool {
        lifecycleLock.lock()
        let current = pendingInstructionPollGeneration == generation
        lifecycleLock.unlock()
        return current
    }

    func submit(_ command: ActiveCaptureProducerEventCommand) {
        markProducerSubmissionActivity(nowMonotonicMilliseconds: monotonicMilliseconds())
        let outcome = submissionQueue.enqueue(command)
        if outcome.droppedCount > 0 {
            diagnosticHandler(
                "producer submission backlog exceeded limit; dropped \(outcome.droppedCount) oldest event(s), pending=\(outcome.pendingCount)"
            )
        } else if outcome.pendingCount == 100 || outcome.pendingCount.isMultiple(of: 500) {
            diagnosticHandler("producer submission backlog pending=\(outcome.pendingCount)")
        }
        guard outcome.shouldStartDrain else { return }
        Task { [weak self] in
            await self?.drainProducerSubmissions()
        }
    }

    private func markProducerSubmissionActivity(nowMonotonicMilliseconds: Int) {
        lifecycleLock.lock()
        lastProducerSubmissionMonotonicMilliseconds = nowMonotonicMilliseconds
        producerSubmissionActivityGeneration += 1
        lifecycleLock.unlock()
    }

    private func pendingInstructionPollingActivity(nowMonotonicMilliseconds: Int) -> Int? {
        lifecycleLock.lock()
        let lastSubmission = lastProducerSubmissionMonotonicMilliseconds
        let generation = producerSubmissionActivityGeneration
        lifecycleLock.unlock()
        guard let lastSubmission,
              nowMonotonicMilliseconds - lastSubmission <= pendingInstructionPollingActivityWindowMilliseconds
        else {
            return nil
        }
        return generation
    }

    private func clearProducerSubmissionActivityIfUnchanged(_ expectedGeneration: Int) {
        lifecycleLock.lock()
        if producerSubmissionActivityGeneration == expectedGeneration {
            lastProducerSubmissionMonotonicMilliseconds = nil
        }
        lifecycleLock.unlock()
    }

    func waitForPendingSubmissions() async {
        await submissionQueue.waitUntilDrained()
    }

    private func drainProducerSubmissions() async {
        while let batch = submissionQueue.takeNextBatch() {
            await submitProducerBatch(batch, allowIndividualFallback: true)
        }
    }

    private func submitProducerBatch(
        _ batch: [ActiveCaptureProducerEventCommand],
        allowIndividualFallback: Bool
    ) async {
        var retryAttempt = 0
        var retryDelayMilliseconds = max(1, producerSubmitRetryInitialDelayMilliseconds)
        let cappedRetryDelayMilliseconds = max(retryDelayMilliseconds, producerSubmitRetryMaxDelayMilliseconds)
        while true {
            do {
                let result = try await transport.recordProducerEvents(sessionId: sessionId, events: batch)
                if isRunningSnapshot() {
                    // Re-arm settle polling only after the daemon has persisted
                    // this batch. An earlier empty poll may have raced the write.
                    markProducerSubmissionActivity(nowMonotonicMilliseconds: monotonicMilliseconds())
                    for instruction in result.captureInstructions {
                        scheduleCaptureInstruction(instruction)
                    }
                }
                return
            } catch is CancellationError {
                return
            } catch let error as URLError where error.code == .cancelled {
                return
            } catch {
                guard Self.isRetryableProducerSubmissionError(error) else {
                    if allowIndividualFallback, batch.count > 1 {
                        diagnosticHandler(
                            "producer batch of \(batch.count) rejected; isolating events: \(error.localizedDescription)"
                        )
                        for event in batch {
                            await submitProducerBatch([event], allowIndividualFallback: false)
                        }
                    } else {
                        diagnosticHandler("failed to submit producer event: \(error.localizedDescription)")
                    }
                    return
                }
                guard retryAttempt < producerSubmitMaxRetryAttempts else {
                    diagnosticHandler(
                        "producer submission retry limit reached; dropped batch of \(batch.count): \(error.localizedDescription)"
                    )
                    return
                }
                retryAttempt += 1
                if retryAttempt == 1 || retryAttempt == producerSubmitMaxRetryAttempts {
                    diagnosticHandler(
                        "failed to submit producer batch of \(batch.count): \(error.localizedDescription); "
                            + "retry \(retryAttempt)/\(producerSubmitMaxRetryAttempts) in \(retryDelayMilliseconds)ms"
                    )
                }
                do {
                    try await Task.sleep(nanoseconds: UInt64(retryDelayMilliseconds) * 1_000_000)
                } catch {
                    return
                }
                retryDelayMilliseconds = min(retryDelayMilliseconds * 2, cappedRetryDelayMilliseconds)
            }
        }
    }

    private static func isRetryableProducerSubmissionError(_ error: Error) -> Bool {
        if let transportError = error as? CaptureTransportError {
            switch transportError {
            case .invalidResponse:
                return true
            case .daemonRejected, .unsupported:
                return false
            }
        }
        guard let urlError = error as? URLError else {
            return false
        }
        switch urlError.code {
        case .timedOut,
             .cannotFindHost,
             .cannotConnectToHost,
             .networkConnectionLost,
             .dnsLookupFailed,
             .notConnectedToInternet,
             .badServerResponse,
             .cannotLoadFromNetwork:
            return true
        case .cancelled:
            return false
        default:
            return false
        }
    }

    private func setRunning(_ value: Bool) {
        lifecycleLock.lock()
        isRunning = value
        lifecycleLock.unlock()
    }

    private func isRunningSnapshot() -> Bool {
        lifecycleLock.lock()
        let current = isRunning
        lifecycleLock.unlock()
        return current
    }

    private func enqueueTapEvent(type: CGEventType, event: CGEvent) {
        guard let snapshot = ActiveCaptureInputEventSnapshot(type: type, event: event) else { return }
        stateQueue.async { [weak self] in
            self?.handle(snapshot)
        }
    }

    private func handle(_ snapshot: ActiveCaptureInputEventSnapshot) {
        guard tapEventDeduper.shouldAccept(snapshot) else { return }
        switch snapshot {
        case .pointerDown(let button, let clickCount, let location, let occurredAtWallTime, let occurredAtMonotonicMs):
            handlePointerDown(
                button: button,
                clickCount: clickCount,
                location: location,
                wallTime: occurredAtWallTime,
                monotonicMilliseconds: occurredAtMonotonicMs
            )
        case .pointerDragged(let button, let location, _, let occurredAtMonotonicMs):
            handlePointerDragged(
                button: button,
                location: location,
                monotonicMilliseconds: occurredAtMonotonicMs
            )
        case .pointerUp(let button, let clickCount, let location, let occurredAtWallTime, let occurredAtMonotonicMs):
            handlePointerUp(
                button: button,
                clickCount: clickCount,
                location: location,
                wallTime: occurredAtWallTime,
                monotonicMilliseconds: occurredAtMonotonicMs
            )
        case .scroll(let deltaX, let deltaY, let location, let occurredAtWallTime, let occurredAtMonotonicMs):
            guard isPointInScope(location) else { return }
            handleScroll(
                deltaX: deltaX,
                deltaY: deltaY,
                location: location,
                wallTime: occurredAtWallTime,
                monotonicMilliseconds: occurredAtMonotonicMs
            )
        case .keyDown(let keyCode, let characters, let flags, let isRepeat, let occurredAtWallTime, let occurredAtMonotonicMs):
            handleKeyDown(
                keyCode: keyCode,
                characters: characters,
                flags: flags,
                isRepeat: isRepeat,
                wallTime: occurredAtWallTime,
                monotonicMilliseconds: occurredAtMonotonicMs
            )
        case .keyUp(let keyCode, let characters, let flags, let occurredAtWallTime, let occurredAtMonotonicMs):
            handleKeyUp(
                keyCode: keyCode,
                characters: characters,
                flags: flags,
                wallTime: occurredAtWallTime,
                monotonicMilliseconds: occurredAtMonotonicMs
            )
        }
    }

    private func handlePointerDown(
        button: ActiveCapturePointerButton,
        clickCount: Int,
        location: CGPoint,
        wallTime: Date,
        monotonicMilliseconds eventTime: Int
    ) {
        guard isPointInScope(location) else {
            pointerDragTracker = nil
            return
        }
        pointerDragTracker = PointerDragTracker(
            button: button,
            clickCount: max(1, clickCount),
            startLocation: location,
            startedAtMonotonicMilliseconds: eventTime
        )
    }

    private func handlePointerDragged(
        button: ActiveCapturePointerButton,
        location: CGPoint,
        monotonicMilliseconds eventTime: Int
    ) {
        guard var tracker = pointerDragTracker, tracker.button == button else { return }
        tracker.record(location: location, monotonicMilliseconds: eventTime)
        pointerDragTracker = tracker
    }

    private func handlePointerUp(
        button: ActiveCapturePointerButton,
        clickCount: Int,
        location: CGPoint,
        wallTime: Date,
        monotonicMilliseconds eventTime: Int
    ) {
        guard isPointInScope(location) else {
            pointerDragTracker = nil
            return
        }
        defer { pointerDragTracker = nil }
        guard var tracker = pointerDragTracker, tracker.button == button else {
            submit(ActiveCaptureInputEventClassifier.pointerClick(
                button: button,
                clickCount: clickCount,
                location: location,
                scope: recordingScope,
                wallTime: wallTime,
                monotonicMilliseconds: eventTime
            ))
            return
        }
        tracker.record(location: location, monotonicMilliseconds: eventTime, force: true)
        if tracker.shouldSubmitDrag(endingAt: location, endedAtMonotonicMilliseconds: eventTime) {
            let drag = tracker.summary(endingAt: location, endedAtMonotonicMilliseconds: eventTime)
            submit(ActiveCaptureInputEventClassifier.pointerDrag(
                button: button,
                startLocation: drag.startLocation,
                endLocation: drag.endLocation,
                path: drag.path,
                durationMilliseconds: drag.durationMilliseconds,
                scope: recordingScope,
                wallTime: wallTime,
                monotonicMilliseconds: eventTime
            ))
            return
        }
        submit(ActiveCaptureInputEventClassifier.pointerClick(
            button: button,
            clickCount: max(1, clickCount),
            location: location,
            scope: recordingScope,
            wallTime: wallTime,
            monotonicMilliseconds: eventTime
        ))
    }

    private func handleKeyDown(
        keyCode: Int,
        characters: String?,
        flags: CGEventFlags,
        isRepeat: Bool,
        wallTime: Date,
        monotonicMilliseconds eventTime: Int
    ) {
        let observedScope = observedScopeProvider() ?? recordingScope
        if recordFullKeystrokes {
            submit(ActiveCaptureInputEventClassifier.rawKey(
                eventKind: .keyDown,
                keyCode: keyCode,
                characters: characters,
                flags: flags,
                isRepeat: isRepeat,
                scope: observedScope,
                wallTime: wallTime,
                monotonicMilliseconds: eventTime
            ))
        }
        if ActiveCaptureInputEventClassifier.isShortcut(keyCode: keyCode, flags: flags) {
            flushTypingLocked()
            submit(ActiveCaptureInputEventClassifier.hotkey(
                keyCode: keyCode,
                flags: flags,
                isRepeat: isRepeat,
                scope: observedScope,
                wallTime: wallTime,
                monotonicMilliseconds: eventTime
            ))
            return
        }
        if ActiveCaptureInputEventClassifier.keyboardInputClass(keyCode: keyCode, characters: characters, flags: flags) == .textInput {
            activeTextKeyDowns.insert(keyCode)
        }
        typingScope = observedScope
        typingAggregator.record(keyCode: keyCode, wallTime: wallTime, monotonicMilliseconds: eventTime)
        scheduleTypingFlush()
    }

    private func handleKeyUp(
        keyCode: Int,
        characters: String?,
        flags: CGEventFlags,
        wallTime: Date,
        monotonicMilliseconds eventTime: Int
    ) {
        guard recordFullKeystrokes else { return }
        submit(ActiveCaptureInputEventClassifier.rawKey(
            eventKind: .keyUp,
            keyCode: keyCode,
            characters: characters,
            flags: flags,
            scope: observedScopeProvider() ?? recordingScope,
            wallTime: wallTime,
            monotonicMilliseconds: eventTime
        ))
        guard !ActiveCaptureInputEventClassifier.isShortcut(keyCode: keyCode, flags: flags),
              ActiveCaptureInputEventClassifier.keyboardInputClass(keyCode: keyCode, characters: characters, flags: flags) == .textInput
        else {
            return
        }
        if activeTextKeyDowns.remove(keyCode) == nil {
            typingScope = observedScopeProvider() ?? recordingScope
            typingAggregator.record(keyCode: keyCode, wallTime: wallTime, monotonicMilliseconds: eventTime)
            scheduleTypingFlush()
        }
    }

    private func isPointInScope(_ location: CGPoint) -> Bool {
        guard let scopeBounds else { return true }
        return scopeBounds.insetBy(dx: -2, dy: -2).contains(location)
    }

    private func scheduleTypingFlush() {
        typingFlushWorkItem?.cancel()
        let workItem = DispatchWorkItem { [weak self] in
            self?.flushTyping()
        }
        typingFlushWorkItem = workItem
        stateQueue.asyncAfter(
            deadline: .now() + .milliseconds(typingPauseDelayMilliseconds),
            execute: workItem
        )
    }

    private func flushTyping() {
        stateQueue.async { [weak self] in
            self?.flushTypingLocked()
        }
    }

    private func flushTypingLocked() {
        guard let summary = typingAggregator.drain(durationMilliseconds: typingPauseDelayMilliseconds) else {
            return
        }
        submit(ActiveCaptureInputEventClassifier.typingPause(
            eventCount: summary.eventCount,
            textEventCount: summary.textEventCount,
            characterCount: summary.characterCount,
            deletionKeyCount: summary.deletionKeyCount,
            nonTextKeyCount: summary.nonTextKeyCount,
            submittedByEnter: summary.submittedByEnter,
            durationMs: summary.durationMilliseconds,
            scope: typingScope ?? recordingScope,
            wallTime: summary.endedAtWallTime,
            monotonicMilliseconds: summary.endedAtMonotonicMilliseconds
        ))
        typingScope = nil
    }

    private func handleScroll(
        deltaX: Double,
        deltaY: Double,
        location: CGPoint,
        wallTime: Date,
        monotonicMilliseconds eventTime: Int
    ) {
        let observedScope = observedScopeProvider() ?? recordingScope
        scrollScope = observedScope
        scrollAggregator.record(
            deltaX: deltaX,
            deltaY: deltaY,
            location: location,
            wallTime: wallTime,
            monotonicMilliseconds: eventTime
        )
        scheduleScrollFlush()
    }

    private func scheduleScrollFlush() {
        scrollFlushWorkItem?.cancel()
        let workItem = DispatchWorkItem { [weak self] in
            self?.flushScrollLocked()
        }
        scrollFlushWorkItem = workItem
        stateQueue.asyncAfter(
            deadline: .now() + .milliseconds(scrollStopDelayMilliseconds),
            execute: workItem
        )
    }

    private func flushScroll() {
        stateQueue.async { [weak self] in
            self?.flushScrollLocked()
        }
    }

    private func flushScrollLocked() {
        guard let summary = scrollAggregator.drain() else {
            return
        }
        submit(ActiveCaptureInputEventClassifier.scroll(
            deltaX: summary.deltaX,
            deltaY: summary.deltaY,
            phase: .ended,
            durationMilliseconds: summary.durationMilliseconds,
            location: summary.location,
            scope: scrollScope ?? recordingScope,
            wallTime: summary.endedAtWallTime,
            monotonicMilliseconds: summary.endedAtMonotonicMilliseconds
        ))
        scrollScope = nil
    }

    private func scheduleCaptureInstruction(_ instruction: ActiveCaptureCaptureInstruction) {
        let rememberKey = captureInstructionKey(instruction)
        guard rememberCaptureInstruction(key: rememberKey) else { return }
        let executeAfter = instruction.executeAfterMonotonicMs ?? monotonicMilliseconds()
        let delay = max(0, executeAfter - monotonicMilliseconds())
        let handler = captureInstructionHandler
        let workItem = DispatchWorkItem { [weak self, handler] in
            handler(instruction)
            self?.forgetScheduledCaptureInstruction(rememberKey)
        }
        captureInstructionWorkItemsLock.lock()
        captureInstructionWorkItems.append(ScheduledCaptureInstruction(key: rememberKey, instruction: instruction, workItem: workItem))
        captureInstructionWorkItemsLock.unlock()
        DispatchQueue.main.asyncAfter(deadline: .now() + .milliseconds(delay), execute: workItem)
    }

    private func captureInstructionKey(_ instruction: ActiveCaptureCaptureInstruction) -> String {
        instruction.binding.metadata.stringValue(for: "settle_capture_claim_id")
            ?? instruction.candidateId
    }

    private func rememberCaptureInstruction(key: String) -> Bool {
        scheduledCaptureInstructionIdsLock.lock()
        let inserted = scheduledCaptureInstructionIds.insert(key).inserted
        scheduledCaptureInstructionIdsLock.unlock()
        return inserted
    }

    private func forgetScheduledCaptureInstruction(_ key: String) {
        captureInstructionWorkItemsLock.lock()
        captureInstructionWorkItems.removeAll { $0.key == key }
        captureInstructionWorkItemsLock.unlock()
        scheduledCaptureInstructionIdsLock.lock()
        scheduledCaptureInstructionIds.remove(key)
        scheduledCaptureInstructionIdsLock.unlock()
    }

    private func reportCancelledCaptureInstructions(_ scheduled: [ScheduledCaptureInstruction]) {
        guard !scheduled.isEmpty else { return }
        let transport = transport
        let sessionId = sessionId
        let candidateIds = scheduled.map { $0.instruction.candidateId }
        Task {
            for candidateId in candidateIds {
                try? await transport.reportCaptureInstructionFailure(
                    sessionId: sessionId,
                    candidateId: candidateId,
                    reason: "invalid_evidence",
                    diagnostic: "native_capture_instruction_cancelled"
                )
            }
        }
    }
}

private struct PointerDragSummary {
    let startLocation: CGPoint
    let endLocation: CGPoint
    let path: [CGPoint]
    let durationMilliseconds: Int?
}

private struct PointerDragTracker {
    private static let dragThresholdPoints: CGFloat = 6
    private static let dragHoldThresholdMilliseconds = 1000
    private static let pathSampleIntervalMilliseconds = 40
    private static let maxPathPoints = 32

    let button: ActiveCapturePointerButton
    let clickCount: Int
    let startLocation: CGPoint
    let startedAtMonotonicMilliseconds: Int
    private(set) var path: [CGPoint]
    private var lastSampledAtMonotonicMilliseconds: Int

    init(
        button: ActiveCapturePointerButton,
        clickCount: Int,
        startLocation: CGPoint,
        startedAtMonotonicMilliseconds: Int
    ) {
        self.button = button
        self.clickCount = clickCount
        self.startLocation = startLocation
        self.startedAtMonotonicMilliseconds = startedAtMonotonicMilliseconds
        self.path = [startLocation]
        self.lastSampledAtMonotonicMilliseconds = startedAtMonotonicMilliseconds
    }

    mutating func record(location: CGPoint, monotonicMilliseconds eventTime: Int, force: Bool = false) {
        guard force || eventTime - lastSampledAtMonotonicMilliseconds >= Self.pathSampleIntervalMilliseconds else {
            return
        }
        guard path.last.map({ distance(from: $0, to: location) > 0.5 }) ?? true else {
            return
        }
        if path.count >= Self.maxPathPoints {
            path.remove(at: 1)
        }
        path.append(location)
        lastSampledAtMonotonicMilliseconds = eventTime
    }

    func shouldSubmitDrag(endingAt location: CGPoint, endedAtMonotonicMilliseconds eventTime: Int) -> Bool {
        if distance(from: startLocation, to: location) >= Self.dragThresholdPoints {
            return true
        }
        // Time-based fallback: a long press-and-hold counts as a drag even when the
        // host reports little or no cursor movement (e.g. a VM in relative-pointer
        // mode, where the on-screen location barely changes during the gesture).
        return eventTime - startedAtMonotonicMilliseconds >= Self.dragHoldThresholdMilliseconds
    }

    func summary(
        endingAt location: CGPoint,
        endedAtMonotonicMilliseconds eventTime: Int
    ) -> PointerDragSummary {
        var normalizedPath = path
        if normalizedPath.last.map({ distance(from: $0, to: location) > 0.5 }) ?? true {
            normalizedPath.append(location)
        }
        return PointerDragSummary(
            startLocation: startLocation,
            endLocation: location,
            path: normalizedPath,
            durationMilliseconds: max(0, eventTime - startedAtMonotonicMilliseconds)
        )
    }

    private func distance(from start: CGPoint, to end: CGPoint) -> CGFloat {
        hypot(end.x - start.x, end.y - start.y)
    }
}

private enum ActiveCaptureInputEventSnapshot {
    case pointerDown(
        button: ActiveCapturePointerButton,
        clickCount: Int,
        location: CGPoint,
        occurredAtWallTime: Date,
        occurredAtMonotonicMs: Int
    )
    case pointerDragged(
        button: ActiveCapturePointerButton,
        location: CGPoint,
        occurredAtWallTime: Date,
        occurredAtMonotonicMs: Int
    )
    case pointerUp(
        button: ActiveCapturePointerButton,
        clickCount: Int,
        location: CGPoint,
        occurredAtWallTime: Date,
        occurredAtMonotonicMs: Int
    )
    case scroll(
        deltaX: Double,
        deltaY: Double,
        location: CGPoint,
        occurredAtWallTime: Date,
        occurredAtMonotonicMs: Int
    )
    case keyDown(
        keyCode: Int,
        characters: String?,
        flags: CGEventFlags,
        isRepeat: Bool,
        occurredAtWallTime: Date,
        occurredAtMonotonicMs: Int
    )
    case keyUp(
        keyCode: Int,
        characters: String?,
        flags: CGEventFlags,
        occurredAtWallTime: Date,
        occurredAtMonotonicMs: Int
    )

    var occurredAtMonotonicMs: Int {
        switch self {
        case .pointerDown(_, _, _, _, let occurredAtMonotonicMs),
             .pointerDragged(_, _, _, let occurredAtMonotonicMs),
             .pointerUp(_, _, _, _, let occurredAtMonotonicMs),
             .scroll(_, _, _, _, let occurredAtMonotonicMs),
             .keyDown(_, _, _, _, _, let occurredAtMonotonicMs),
             .keyUp(_, _, _, _, let occurredAtMonotonicMs):
            return occurredAtMonotonicMs
        }
    }

    var keyboardDeduplicationKey: String? {
        switch self {
        case .keyDown(let keyCode, let characters, let flags, let isRepeat, _, _):
            return "down:\(keyCode):\(Int(flags.rawValue)):\(isRepeat):\(characters ?? "")"
        case .keyUp(let keyCode, let characters, let flags, _, _):
            return "up:\(keyCode):\(Int(flags.rawValue)):\(characters ?? "")"
        case .pointerDown, .pointerDragged, .pointerUp, .scroll:
            return nil
        }
    }

    init?(type: CGEventType, event: CGEvent) {
        let eventTime = monotonicMilliseconds()
        let wallTime = Date()
        switch type {
        case .leftMouseDown:
            self = .pointerDown(
                button: .left,
                clickCount: Int(event.getIntegerValueField(.mouseEventClickState)),
                location: event.location,
                occurredAtWallTime: wallTime,
                occurredAtMonotonicMs: eventTime
            )
        case .rightMouseDown:
            self = .pointerDown(
                button: .right,
                clickCount: Int(event.getIntegerValueField(.mouseEventClickState)),
                location: event.location,
                occurredAtWallTime: wallTime,
                occurredAtMonotonicMs: eventTime
            )
        case .otherMouseDown:
            self = .pointerDown(
                button: .other,
                clickCount: Int(event.getIntegerValueField(.mouseEventClickState)),
                location: event.location,
                occurredAtWallTime: wallTime,
                occurredAtMonotonicMs: eventTime
            )
        case .leftMouseDragged:
            self = .pointerDragged(
                button: .left,
                location: event.location,
                occurredAtWallTime: wallTime,
                occurredAtMonotonicMs: eventTime
            )
        case .rightMouseDragged:
            self = .pointerDragged(
                button: .right,
                location: event.location,
                occurredAtWallTime: wallTime,
                occurredAtMonotonicMs: eventTime
            )
        case .otherMouseDragged:
            self = .pointerDragged(
                button: .other,
                location: event.location,
                occurredAtWallTime: wallTime,
                occurredAtMonotonicMs: eventTime
            )
        case .leftMouseUp:
            self = .pointerUp(
                button: .left,
                clickCount: Int(event.getIntegerValueField(.mouseEventClickState)),
                location: event.location,
                occurredAtWallTime: wallTime,
                occurredAtMonotonicMs: eventTime
            )
        case .rightMouseUp:
            self = .pointerUp(
                button: .right,
                clickCount: Int(event.getIntegerValueField(.mouseEventClickState)),
                location: event.location,
                occurredAtWallTime: wallTime,
                occurredAtMonotonicMs: eventTime
            )
        case .otherMouseUp:
            self = .pointerUp(
                button: .other,
                clickCount: Int(event.getIntegerValueField(.mouseEventClickState)),
                location: event.location,
                occurredAtWallTime: wallTime,
                occurredAtMonotonicMs: eventTime
            )
        case .scrollWheel:
            self = .scroll(
                deltaX: Double(event.getIntegerValueField(.scrollWheelEventDeltaAxis2)),
                deltaY: Double(event.getIntegerValueField(.scrollWheelEventDeltaAxis1)),
                location: event.location,
                occurredAtWallTime: wallTime,
                occurredAtMonotonicMs: eventTime
            )
        case .keyDown:
            self = .keyDown(
                keyCode: Int(event.getIntegerValueField(.keyboardEventKeycode)),
                characters: Self.keyboardCharacters(from: event),
                flags: event.flags,
                isRepeat: event.getIntegerValueField(.keyboardEventAutorepeat) != 0,
                occurredAtWallTime: wallTime,
                occurredAtMonotonicMs: eventTime
            )
        case .keyUp:
            self = .keyUp(
                keyCode: Int(event.getIntegerValueField(.keyboardEventKeycode)),
                characters: Self.keyboardCharacters(from: event),
                flags: event.flags,
                occurredAtWallTime: wallTime,
                occurredAtMonotonicMs: eventTime
            )
        default:
            return nil
        }
    }

    private static func keyboardCharacters(from event: CGEvent) -> String? {
        var actualLength = 0
        var buffer = [UniChar](repeating: 0, count: 64)
        return buffer.withUnsafeMutableBufferPointer { pointer in
            event.keyboardGetUnicodeString(
                maxStringLength: pointer.count,
                actualStringLength: &actualLength,
                unicodeString: pointer.baseAddress
            )
            guard actualLength > 0, let baseAddress = pointer.baseAddress else { return nil }
            return String(utf16CodeUnits: baseAddress, count: actualLength)
        }
    }
}

private struct ActiveCaptureInputEventDeduper {
    private let duplicateWindowMilliseconds = 12
    private var recentKeyboardEvents: [(key: String, occurredAt: Int)] = []

    mutating func shouldAccept(_ snapshot: ActiveCaptureInputEventSnapshot) -> Bool {
        guard let key = snapshot.keyboardDeduplicationKey else { return true }
        let occurredAt = snapshot.occurredAtMonotonicMs
        recentKeyboardEvents.removeAll {
            occurredAt - $0.occurredAt > duplicateWindowMilliseconds
        }
        if recentKeyboardEvents.contains(where: { $0.key == key && abs(occurredAt - $0.occurredAt) <= duplicateWindowMilliseconds }) {
            return false
        }
        recentKeyboardEvents.append((key: key, occurredAt: occurredAt))
        return true
    }

    mutating func reset() {
        recentKeyboardEvents.removeAll()
    }
}

final class ActiveCaptureProducerSubmissionQueue: @unchecked Sendable {
    struct EnqueueOutcome {
        let shouldStartDrain: Bool
        let droppedCount: Int
        let pendingCount: Int
    }

    private let lock = NSLock()
    private let batchSize: Int
    private let maxPendingEvents: Int
    private var pending: [ActiveCaptureProducerEventCommand] = []
    private var isDraining = false
    private var drainWaiters: [CheckedContinuation<Void, Never>] = []

    init(batchSize: Int = 32, maxPendingEvents: Int = 2_000) {
        self.batchSize = max(1, min(100, batchSize))
        self.maxPendingEvents = max(1, maxPendingEvents)
    }

    func enqueue(_ event: ActiveCaptureProducerEventCommand) -> EnqueueOutcome {
        lock.lock()
        pending.append(event)
        let droppedCount = max(0, pending.count - maxPendingEvents)
        if droppedCount > 0 {
            pending.removeFirst(droppedCount)
        }
        let shouldStartDrain = !isDraining
        if shouldStartDrain {
            isDraining = true
        }
        let pendingCount = pending.count
        lock.unlock()
        return EnqueueOutcome(
            shouldStartDrain: shouldStartDrain,
            droppedCount: droppedCount,
            pendingCount: pendingCount
        )
    }

    func takeNextBatch() -> [ActiveCaptureProducerEventCommand]? {
        lock.lock()
        guard !pending.isEmpty else {
            isDraining = false
            let waiters = drainWaiters
            drainWaiters.removeAll()
            lock.unlock()
            waiters.forEach { $0.resume() }
            return nil
        }
        let count = min(batchSize, pending.count)
        let batch = Array(pending.prefix(count))
        pending.removeFirst(count)
        lock.unlock()
        return batch
    }

    func waitUntilDrained() async {
        await withCheckedContinuation { continuation in
            lock.lock()
            guard isDraining || !pending.isEmpty else {
                lock.unlock()
                continuation.resume()
                return
            }
            drainWaiters.append(continuation)
            lock.unlock()
        }
    }
}

private struct ScheduledCaptureInstruction {
    let key: String
    let instruction: ActiveCaptureCaptureInstruction
    let workItem: DispatchWorkItem
}

private extension Dictionary where Key == String, Value == JSONScalar {
    func stringValue(for key: String) -> String? {
        guard case .string(let value) = self[key], !value.isEmpty else {
            return nil
        }
        return value
    }
}

enum ActiveCaptureObservedScopeResolver {
    static func frontmostWindowScope() -> ActiveCaptureRecordingScope? {
        guard let app = NSWorkspace.shared.frontmostApplication else { return nil }
        guard app.processIdentifier != ProcessInfo.processInfo.processIdentifier else { return nil }
        let window = frontmostWindow(for: app.processIdentifier)
        return ActiveCaptureRecordingScope(
            kind: window?.bounds == nil ? .currentApp : .window,
            displayId: nil,
            scaleFactor: nil,
            windowId: window?.windowId,
            processId: Int(app.processIdentifier),
            bundleId: app.bundleIdentifier,
            appName: app.localizedName,
            title: window?.title ?? app.localizedName,
            bounds: window?.bounds,
            selectionRegion: nil,
            scopeConfidence: window?.bounds == nil ? 0.62 : 0.86,
            occlusionEstimate: nil,
            metadata: ["producer_scope_provider": .string("frontmost_window")]
        )
    }

    private static func frontmostWindow(for processIdentifier: pid_t) -> (windowId: String?, title: String?, bounds: BoundingBox?)? {
        guard let windows = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID)
            as? [[String: Any]]
        else {
            return nil
        }
        for window in windows {
            guard (window[kCGWindowOwnerPID as String] as? pid_t) == processIdentifier else { continue }
            guard (window[kCGWindowLayer as String] as? Int) == 0 else { continue }
            let windowId = (window[kCGWindowNumber as String] as? Int).map(String.init)
            let title = window[kCGWindowName as String] as? String
            let bounds = boundingBox(from: window[kCGWindowBounds as String])
            return (windowId, title, bounds)
        }
        return nil
    }

    private static func boundingBox(from value: Any?) -> BoundingBox? {
        guard let dictionary = value as? NSDictionary,
              let rect = CGRect(dictionaryRepresentation: dictionary)
        else {
            return nil
        }
        return BoundingBox(
            x: Int(rect.origin.x.rounded()),
            y: Int(rect.origin.y.rounded()),
            width: Int(rect.width.rounded()),
            height: Int(rect.height.rounded()),
            coordinateSpace: "macos_global"
        )
    }
}

private final class ActiveCaptureInputEventTapContext {
    private let lock = NSLock()
    private weak var producer: ActiveCaptureInputEventProducer?

    init(producer: ActiveCaptureInputEventProducer) {
        self.producer = producer
    }

    func producerSnapshot() -> ActiveCaptureInputEventProducer? {
        lock.lock()
        let producer = producer
        lock.unlock()
        return producer
    }

    func clearProducer() {
        lock.lock()
        producer = nil
        lock.unlock()
    }
}

private struct TypingPauseAggregator {
    private(set) var eventCount = 0
    private(set) var textEventCount = 0
    private(set) var characterCount = 0
    private(set) var deletionKeyCount = 0
    private(set) var nonTextKeyCount = 0
    private(set) var submittedByEnter = false
    private(set) var startedAtMonotonicMilliseconds: Int?
    private(set) var endedAtMonotonicMilliseconds: Int?
    private(set) var endedAtWallTime: Date?

    mutating func record(keyCode: Int, wallTime: Date, monotonicMilliseconds: Int) {
        eventCount += 1
        if startedAtMonotonicMilliseconds == nil {
            startedAtMonotonicMilliseconds = monotonicMilliseconds
        }
        endedAtMonotonicMilliseconds = monotonicMilliseconds
        endedAtWallTime = wallTime
        switch keyCode {
        case kVK_Delete, kVK_ForwardDelete:
            deletionKeyCount += 1
            nonTextKeyCount += 1
        case kVK_Tab, kVK_Escape, kVK_LeftArrow, kVK_RightArrow, kVK_UpArrow,
             kVK_DownArrow, kVK_Home, kVK_End, kVK_PageUp, kVK_PageDown:
            nonTextKeyCount += 1
        default:
            textEventCount += 1
            characterCount += 1
        }
    }

    mutating func drain(durationMilliseconds: Int) -> TypingPauseSnapshot? {
        guard eventCount > 0 else {
            return nil
        }
        let snapshot = TypingPauseSnapshot(
            eventCount: eventCount,
            textEventCount: textEventCount,
            characterCount: characterCount,
            deletionKeyCount: deletionKeyCount,
            nonTextKeyCount: nonTextKeyCount,
            submittedByEnter: submittedByEnter,
            durationMilliseconds: durationMilliseconds,
            endedAtMonotonicMilliseconds: endedAtMonotonicMilliseconds,
            endedAtWallTime: endedAtWallTime
        )
        eventCount = 0
        textEventCount = 0
        characterCount = 0
        deletionKeyCount = 0
        nonTextKeyCount = 0
        submittedByEnter = false
        startedAtMonotonicMilliseconds = nil
        endedAtMonotonicMilliseconds = nil
        endedAtWallTime = nil
        return snapshot
    }
}

private struct TypingPauseSnapshot {
    let eventCount: Int
    let textEventCount: Int
    let characterCount: Int
    let deletionKeyCount: Int
    let nonTextKeyCount: Int
    let submittedByEnter: Bool
    let durationMilliseconds: Int
    let endedAtMonotonicMilliseconds: Int?
    let endedAtWallTime: Date?
}

private struct ScrollGestureAggregator {
    private(set) var deltaX = 0.0
    private(set) var deltaY = 0.0
    private(set) var location: CGPoint?
    private(set) var startedAtMonotonicMilliseconds: Int?
    private(set) var endedAtMonotonicMilliseconds: Int?
    private(set) var endedAtWallTime: Date?

    mutating func record(deltaX: Double, deltaY: Double, location: CGPoint, wallTime: Date, monotonicMilliseconds: Int) {
        if startedAtMonotonicMilliseconds == nil {
            startedAtMonotonicMilliseconds = monotonicMilliseconds
        }
        endedAtMonotonicMilliseconds = monotonicMilliseconds
        endedAtWallTime = wallTime
        self.location = location
        self.deltaX += deltaX
        self.deltaY += deltaY
    }

    mutating func drain() -> ScrollGestureSnapshot? {
        guard let start = startedAtMonotonicMilliseconds,
              let end = endedAtMonotonicMilliseconds,
              deltaX != 0 || deltaY != 0
        else {
            return nil
        }
        let snapshot = ScrollGestureSnapshot(
            deltaX: deltaX,
            deltaY: deltaY,
            durationMilliseconds: max(0, end - start),
            location: location,
            endedAtMonotonicMilliseconds: end,
            endedAtWallTime: endedAtWallTime
        )
        deltaX = 0
        deltaY = 0
        location = nil
        startedAtMonotonicMilliseconds = nil
        endedAtMonotonicMilliseconds = nil
        endedAtWallTime = nil
        return snapshot
    }
}

private struct ScrollGestureSnapshot {
    let deltaX: Double
    let deltaY: Double
    let durationMilliseconds: Int
    let location: CGPoint?
    let endedAtMonotonicMilliseconds: Int
    let endedAtWallTime: Date?
}
