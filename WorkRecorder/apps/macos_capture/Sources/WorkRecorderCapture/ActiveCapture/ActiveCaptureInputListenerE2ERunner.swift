import AppKit
import Carbon
import CoreGraphics
import Darwin
import Foundation

enum ActiveCaptureInputListenerE2ERunner {
    private static let argument = "--active-capture-input-listener-e2e"
    private static let sessionId = "acs_native_input_listener_e2e"
    @MainActor private static var retainedProducer: ActiveCaptureInputEventProducer?

    static func isRequested(arguments: [String] = ProcessInfo.processInfo.arguments) -> Bool {
        arguments.contains(argument)
    }

    @MainActor
    static func runFromMain() {
        let application = NSApplication.shared
        application.setActivationPolicy(.regular)
        Task { @MainActor in
            let exitCode = await runAndPrintReport()
            fflush(stdout)
            fflush(stderr)
            Darwin._exit(Int32(exitCode))
        }
        application.run()
    }

    @MainActor
    private static func runAndPrintReport() async -> Int {
        let diagnostics = ActiveCaptureInputListenerE2EDiagnostics()
        let transport = ActiveCaptureInputListenerCollectingTransport()
        let host = ActiveCaptureInputListenerWindowHost()
        host.show()
        await sleep(milliseconds: 450)

        let scope = recordingScope(for: host.window.frame)
        let producer = ActiveCaptureInputEventProducer(
            sessionId: sessionId,
            transport: transport,
            typingPauseDelayMilliseconds: 320,
            scrollStopDelayMilliseconds: 140,
            scopeBounds: host.window.frame.insetBy(dx: -8, dy: -8),
            recordingScope: scope,
            diagnosticHandler: { message in diagnostics.append(message) }
        )
        retainedProducer = producer
        do {
            try producer.start()
        } catch {
            printReport(
                status: .permissionDenied,
                host: host,
                scope: scope,
                events: [],
                diagnostics: diagnostics.snapshot() + [error.localizedDescription]
            )
            return 2
        }

        guard await host.waitForExclusiveFocus(timeoutMilliseconds: 2_000) else {
            producer.stop()
            printReport(
                status: .focusNotOwned,
                host: host,
                scope: scope,
                events: [],
                diagnostics: diagnostics.snapshot() + [host.focusDiagnostic()]
            )
            return 4
        }

        let inputWasDriven = await driveInputEvents(in: host)
        guard inputWasDriven else {
            producer.stop()
            printReport(
                status: .focusNotOwned,
                host: host,
                scope: scope,
                events: [],
                diagnostics: diagnostics.snapshot() + [host.focusDiagnostic()]
            )
            return 4
        }
        await sleep(milliseconds: 1_200)
        producer.stop()
        await sleep(milliseconds: 2_000)

        let events = await transport.snapshot()
        let status: ActiveCaptureInputListenerE2EStatus = events.isEmpty ? .noEvents : .ok
        printReport(
            status: status,
            host: host,
            scope: scope,
            events: events,
            diagnostics: diagnostics.snapshot()
        )
        return status == .ok ? 0 : 3
    }

    @MainActor
    private static func driveInputEvents(in host: ActiveCaptureInputListenerWindowHost) async -> Bool {
        NSApp.activate(ignoringOtherApps: true)
        host.window.makeKeyAndOrderFront(nil)
        host.window.makeFirstResponder(host.textView)
        await sleep(milliseconds: 250)

        guard host.hasExclusiveFocus() else { return false }
        let center = CGPoint(x: host.window.frame.midX, y: host.window.frame.midY)
        postMouse(type: .mouseMoved, at: center)
        postMouse(type: .leftMouseDown, at: center)
        postMouse(type: .leftMouseUp, at: center)
        await sleep(milliseconds: 320)

        guard host.hasExclusiveFocus() else { return false }
        postScroll(deltaY: -8, at: center)
        postScroll(deltaY: -12, at: center)
        await sleep(milliseconds: 420)

        guard host.hasExclusiveFocus() else { return false }
        postKey(kVK_ANSI_K, flags: [.maskCommand])
        await sleep(milliseconds: 420)

        guard host.hasExclusiveFocus() else { return false }
        postKey(kVK_ANSI_A)
        postKey(kVK_ANSI_S)
        postKey(kVK_Delete)
        await sleep(milliseconds: 620)

        guard host.hasExclusiveFocus() else { return false }
        postKey(kVK_Return)
        return true
    }

    private static func postMouse(type: CGEventType, at location: CGPoint) {
        let source = CGEventSource(stateID: .hidSystemState)
        let event = CGEvent(mouseEventSource: source, mouseType: type, mouseCursorPosition: location, mouseButton: .left)
        postToHarnessProcess(event)
    }

    private static func postScroll(deltaY: Int32, at location: CGPoint) {
        let source = CGEventSource(stateID: .hidSystemState)
        guard let event = CGEvent(
            scrollWheelEvent2Source: source,
            units: .line,
            wheelCount: 2,
            wheel1: deltaY,
            wheel2: 0,
            wheel3: 0
        ) else {
            return
        }
        event.location = location
        postToHarnessProcess(event)
    }

    private static func postKey(_ keyCode: Int, flags: CGEventFlags = []) {
        let source = CGEventSource(stateID: .hidSystemState)
        for keyDown in [true, false] {
            guard let event = CGEvent(
                keyboardEventSource: source,
                virtualKey: CGKeyCode(keyCode),
                keyDown: keyDown
            ) else {
                continue
            }
            event.flags = flags
            postToHarnessProcess(event)
        }
    }

    private static func postToHarnessProcess(_ event: CGEvent?) {
        guard let event else { return }
        event.postToPid(ProcessInfo.processInfo.processIdentifier)
    }

    @MainActor
    private static func recordingScope(for frame: CGRect) -> ActiveCaptureRecordingScope {
        let screen = NSScreen.screens.first { $0.frame.intersects(frame) } ?? NSScreen.main
        let displayId = screen?.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")].map { "\($0)" }
        let box = Geometry.intBox(from: frame, coordinateSpace: "macos_global")
        return ActiveCaptureRecordingScope(
            kind: .region,
            displayId: displayId ?? "main",
            scaleFactor: screen.map { Double($0.backingScaleFactor) },
            windowId: nil,
            processId: Int(ProcessInfo.processInfo.processIdentifier),
            bundleId: Bundle.main.bundleIdentifier ?? "io.workrecorder.capture",
            appName: ProcessInfo.processInfo.processName,
            title: ActiveCaptureInputListenerWindowHost.title,
            bounds: box,
            selectionRegion: box,
            scopeConfidence: 0.98,
            occlusionEstimate: 0,
            metadata: ["harness": .string("native_input_listener_e2e")]
        )
    }

    @MainActor
    private static func printReport(
        status: ActiveCaptureInputListenerE2EStatus,
        host: ActiveCaptureInputListenerWindowHost,
        scope: ActiveCaptureRecordingScope,
        events: [ActiveCaptureProducerEventCommand],
        diagnostics: [String]
    ) {
        let report = ActiveCaptureInputListenerE2EReport(
            status: status,
            sessionId: sessionId,
            targetFrame: Geometry.intBox(from: host.window.frame, coordinateSpace: "macos_global"),
            scope: scope,
            eventCount: events.count,
            events: events,
            diagnostics: diagnostics
        )
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        do {
            let data = try encoder.encode(report)
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data("\n".utf8))
        } catch {
            FileHandle.standardError.write(Data("failed to encode native input E2E report: \(error)\n".utf8))
        }
    }

    private static func sleep(milliseconds: Int) async {
        try? await Task.sleep(nanoseconds: UInt64(milliseconds) * 1_000_000)
    }
}

private enum ActiveCaptureInputListenerE2EStatus: String, Codable {
    case ok
    case focusNotOwned = "focus_not_owned"
    case permissionDenied = "permission_denied"
    case noEvents = "no_events"
}

private struct ActiveCaptureInputListenerE2EReport: Codable {
    let status: ActiveCaptureInputListenerE2EStatus
    let sessionId: String
    let targetFrame: BoundingBox
    let scope: ActiveCaptureRecordingScope
    let eventCount: Int
    let events: [ActiveCaptureProducerEventCommand]
    let diagnostics: [String]

    enum CodingKeys: String, CodingKey {
        case status
        case sessionId = "session_id"
        case targetFrame = "target_frame"
        case scope
        case eventCount = "event_count"
        case events
        case diagnostics
    }
}

private actor ActiveCaptureInputListenerCollectingTransport: ActiveCaptureProducerEventTransport {
    private var events: [ActiveCaptureProducerEventCommand] = []

    func recordProducerEvent(
        sessionId: String,
        event: ActiveCaptureProducerEventCommand
    ) async throws -> ProducerEventSaveResult {
        events.append(event)
        return ProducerEventSaveResult(accepted: true, captureInstructions: [])
    }

    func pollPendingCaptureInstructions(
        sessionId: String,
        probeSnapshot: ActiveCaptureSettleProbeSnapshot?,
        allowDegradedSample: Bool
    ) async throws -> ProducerEventSaveResult {
        ProducerEventSaveResult(accepted: true, captureInstructions: [])
    }

    func snapshot() -> [ActiveCaptureProducerEventCommand] {
        events
    }
}

private final class ActiveCaptureInputListenerE2EDiagnostics: @unchecked Sendable {
    private let lock = NSLock()
    private var messages: [String] = []

    func append(_ message: String) {
        lock.lock()
        messages.append(message)
        lock.unlock()
    }

    func snapshot() -> [String] {
        lock.lock()
        let current = messages
        lock.unlock()
        return current
    }
}

@MainActor
private final class ActiveCaptureInputListenerWindowHost {
    static let title = "WorkRecorder Native Input Listener E2E"

    let window: NSWindow
    let textView: NSTextView

    init() {
        let screen = NSScreen.main ?? NSScreen.screens.first
        let visible = screen?.visibleFrame ?? CGRect(x: 80, y: 80, width: 900, height: 700)
        let frame = CGRect(x: visible.minX + 96, y: visible.maxY - 430, width: 620, height: 320)
        textView = NSTextView(frame: CGRect(x: 32, y: 34, width: 556, height: 120))
        textView.string = ""
        textView.isEditable = true
        textView.isSelectable = true
        textView.font = NSFont.monospacedSystemFont(ofSize: 15, weight: .regular)
        textView.backgroundColor = NSColor(calibratedRed: 0.96, green: 0.98, blue: 0.98, alpha: 1)

        let content = ActiveCaptureInputListenerContentView(frame: CGRect(origin: .zero, size: frame.size))
        content.addSubview(textView)

        window = NSWindow(
            contentRect: frame,
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        window.title = Self.title
        window.contentView = content
        window.isReleasedWhenClosed = false
        window.level = .normal
    }

    func show() {
        window.center()
        window.level = .floating
        window.orderFrontRegardless()
        window.makeKeyAndOrderFront(nil)
        window.makeFirstResponder(textView)
        NSApp.activate(ignoringOtherApps: true)
    }

    func waitForExclusiveFocus(timeoutMilliseconds: Int) async -> Bool {
        let deadline = Date().addingTimeInterval(Double(timeoutMilliseconds) / 1_000)
        while Date() < deadline {
            if hasExclusiveFocus() {
                return true
            }
            NSApp.activate(ignoringOtherApps: true)
            window.orderFrontRegardless()
            window.makeKeyAndOrderFront(nil)
            window.makeFirstResponder(textView)
            try? await Task.sleep(nanoseconds: 80_000_000)
        }
        return hasExclusiveFocus()
    }

    func hasExclusiveFocus() -> Bool {
        let frontmostProcessId = NSWorkspace.shared.frontmostApplication?.processIdentifier
        return frontmostProcessId == ProcessInfo.processInfo.processIdentifier
            && window.isKeyWindow
            && window.firstResponder === textView
    }

    func focusDiagnostic() -> String {
        let app = NSWorkspace.shared.frontmostApplication
        return [
            "frontmost_pid=\(app?.processIdentifier.description ?? "nil")",
            "frontmost_bundle=\(app?.bundleIdentifier ?? "nil")",
            "self_pid=\(ProcessInfo.processInfo.processIdentifier)",
            "window_is_key=\(window.isKeyWindow)",
            "text_view_is_first_responder=\(window.firstResponder === textView)",
        ].joined(separator: " ")
    }
}

private final class ActiveCaptureInputListenerContentView: NSView {
    override func draw(_ dirtyRect: NSRect) {
        NSColor(calibratedRed: 0.91, green: 0.96, blue: 0.97, alpha: 1).setFill()
        dirtyRect.fill()
        NSColor(calibratedRed: 0.12, green: 0.36, blue: 0.40, alpha: 1).setStroke()
        let border = NSBezierPath(roundedRect: bounds.insetBy(dx: 14, dy: 14), xRadius: 8, yRadius: 8)
        border.lineWidth = 3
        border.stroke()
    }
}
