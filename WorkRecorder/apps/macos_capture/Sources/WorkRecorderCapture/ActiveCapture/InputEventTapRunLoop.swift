import CoreGraphics
import Foundation

/// Serializes event-tap re-enablement against shutdown.
///
/// macOS can deliver a tap-disabled callback while recording shutdown is
/// invalidating the same `CFMachPort`. Calling `CGEvent.tapEnable` concurrently
/// with that invalidation is unsafe, so shutdown first closes this gate and
/// waits for any in-flight enable operation to leave it.
final class InputEventTapActivationGate: @unchecked Sendable {
    private let lock = NSLock()
    private var active = false

    func activate() {
        lock.lock()
        active = true
        lock.unlock()
    }

    func deactivate() {
        lock.lock()
        active = false
        lock.unlock()
    }

    @discardableResult
    func performIfActive(_ operation: () -> Void) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard active else { return false }
        operation()
        return true
    }
}

/// Hosts a CGEventTap on a dedicated high-priority thread and run loop.
///
/// The CGEventTap callback must never be starved. If its run loop lives on the
/// main thread, any main-thread stall during recording (HUD, overlays, screen
/// capture, AppKit layout) makes macOS time out the tap and silently drop
/// keystrokes. Running the tap on its own `.userInteractive` run loop keeps input
/// capture independent of UI work, which is what eliminates dropped keys.
final class InputEventTapRunLoop: @unchecked Sendable {
    private let lock = NSLock()
    private var running = false
    private var runLoop: CFRunLoop?
    private var thread: Thread?
    private var tap: CFMachPort?
    private var source: CFRunLoopSource?
    private var exitSignal: DispatchSemaphore?
    private let activationGate = InputEventTapActivationGate()

    /// Starts running the tap's source on a dedicated thread and enables the tap.
    func start(tap: CFMachPort, source: CFRunLoopSource) {
        let exitSignal = DispatchSemaphore(value: 0)
        lock.lock()
        running = true
        self.tap = tap
        self.source = source
        self.exitSignal = exitSignal
        lock.unlock()
        activationGate.activate()
        let thread = Thread { [weak self] in
            defer { exitSignal.signal() }
            guard let self, let source = self.sourceSnapshot() else { return }
            let runLoop = CFRunLoopGetCurrent()
            self.setRunLoop(runLoop)
            CFRunLoopAddSource(runLoop, source, .commonModes)
            self.enableIfRunning()
            while self.isRunning() {
                CFRunLoopRunInMode(.defaultMode, 0.5, false)
            }
            CFRunLoopRemoveSource(runLoop, source, .commonModes)
            self.setRunLoop(nil)
        }
        thread.name = "workrecorder.active-capture.input-tap"
        thread.qualityOfService = .userInteractive
        lock.lock()
        self.thread = thread
        lock.unlock()
        thread.start()
    }

    /// Stops the dedicated thread and waits until its source has been removed.
    func stop() {
        // Wait for any callback-driven re-enable to finish, then reject all
        // future attempts before the tap or its callback context can be freed.
        activationGate.deactivate()
        lock.lock()
        running = false
        let runLoop = self.runLoop
        let thread = self.thread
        let exitSignal = self.exitSignal
        self.tap = nil
        self.source = nil
        lock.unlock()
        if let runLoop {
            CFRunLoopStop(runLoop)
        }
        if let thread, Thread.current !== thread {
            exitSignal?.wait()
        }
        lock.lock()
        if self.thread === thread {
            self.thread = nil
            self.exitSignal = nil
        }
        lock.unlock()
    }

    /// Re-enables the tap only while its lifecycle is active.
    ///
    /// The activation gate remains locked across `CGEvent.tapEnable`, which
    /// prevents shutdown from invalidating the port concurrently.
    func enableIfRunning() {
        activationGate.performIfActive { [weak self] in
            guard let tap = self?.tapSnapshot() else { return }
            CGEvent.tapEnable(tap: tap, enable: true)
        }
    }

    private func isRunning() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        return running
    }

    private func setRunLoop(_ value: CFRunLoop?) {
        lock.lock()
        runLoop = value
        lock.unlock()
    }

    private func tapSnapshot() -> CFMachPort? {
        lock.lock()
        defer { lock.unlock() }
        return tap
    }

    private func sourceSnapshot() -> CFRunLoopSource? {
        lock.lock()
        defer { lock.unlock() }
        return source
    }
}
