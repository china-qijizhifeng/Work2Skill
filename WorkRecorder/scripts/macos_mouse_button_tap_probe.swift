import CoreGraphics
import Foundation

final class TapContext {
    let layer: String

    init(layer: String) {
        self.layer = layer
    }
}

struct ProbeOptions {
    let includeSessionTap: Bool
    let includeHIDTap: Bool
}

struct ProbeError: Error, CustomStringConvertible {
    let description: String
}

func printUsage() {
    print("""
    Usage:
      swift scripts/macos_mouse_button_tap_probe.swift [--session-only|--hid-only]

    Prints raw mouse button events from macOS CGEvent taps. Press Control-C to stop.
    Use this to compare the session tap and HID tap when diagnosing right-click capture.
    """)
}

func parseOptions(_ arguments: [String]) throws -> ProbeOptions {
    var includeSessionTap = true
    var includeHIDTap = true
    var index = 1
    while index < arguments.count {
        switch arguments[index] {
        case "--session-only":
            includeSessionTap = true
            includeHIDTap = false
        case "--hid-only":
            includeSessionTap = false
            includeHIDTap = true
        case "--help", "-h":
            printUsage()
            exit(0)
        default:
            throw ProbeError(description: "unknown argument: \(arguments[index])")
        }
        index += 1
    }
    return ProbeOptions(includeSessionTap: includeSessionTap, includeHIDTap: includeHIDTap)
}

func mouseEventMask() -> CGEventMask {
    var mask = 0
    for type in [
        CGEventType.leftMouseDown,
        CGEventType.rightMouseDown,
        CGEventType.otherMouseDown,
        CGEventType.leftMouseUp,
        CGEventType.rightMouseUp,
        CGEventType.otherMouseUp,
        CGEventType.leftMouseDragged,
        CGEventType.rightMouseDragged,
        CGEventType.otherMouseDragged
    ] {
        mask |= 1 << type.rawValue
    }
    return CGEventMask(mask)
}

func eventTypeName(_ type: CGEventType) -> String {
    switch type {
    case .leftMouseDown: return "leftMouseDown"
    case .rightMouseDown: return "rightMouseDown"
    case .otherMouseDown: return "otherMouseDown"
    case .leftMouseUp: return "leftMouseUp"
    case .rightMouseUp: return "rightMouseUp"
    case .otherMouseUp: return "otherMouseUp"
    case .leftMouseDragged: return "leftMouseDragged"
    case .rightMouseDragged: return "rightMouseDragged"
    case .otherMouseDragged: return "otherMouseDragged"
    case .tapDisabledByTimeout: return "tapDisabledByTimeout"
    case .tapDisabledByUserInput: return "tapDisabledByUserInput"
    default: return "type_\(type.rawValue)"
    }
}

func flagNames(_ flags: CGEventFlags) -> String {
    var names: [String] = []
    if flags.contains(.maskControl) { names.append("control") }
    if flags.contains(.maskCommand) { names.append("command") }
    if flags.contains(.maskAlternate) { names.append("option") }
    if flags.contains(.maskShift) { names.append("shift") }
    if flags.contains(.maskSecondaryFn) { names.append("secondaryFn") }
    if flags.contains(.maskAlphaShift) { names.append("capsLock") }
    return names.isEmpty ? "-" : names.joined(separator: ",")
}

func timestamp() -> String {
    let formatter = DateFormatter()
    formatter.dateFormat = "HH:mm:ss.SSS"
    return formatter.string(from: Date())
}

func logEvent(layer: String, type: CGEventType, event: CGEvent) {
    let location = event.location
    let buttonNumber = event.getIntegerValueField(.mouseEventButtonNumber)
    let clickState = event.getIntegerValueField(.mouseEventClickState)
    let subtype = event.getIntegerValueField(.eventSourceUnixProcessID)
    print(
        "\(timestamp()) layer=\(layer) type=\(eventTypeName(type)) raw_type=\(type.rawValue) " +
        "button_number=\(buttonNumber) click_state=\(clickState) " +
        "flags=\(flagNames(event.flags)) flags_raw=\(event.flags.rawValue) " +
        "pid=\(subtype) x=\(Int(location.x.rounded())) y=\(Int(location.y.rounded()))"
    )
    fflush(stdout)
}

let callback: CGEventTapCallBack = { _, type, event, userInfo in
    guard let userInfo else {
        return Unmanaged.passUnretained(event)
    }
    let context = Unmanaged<TapContext>.fromOpaque(userInfo).takeUnretainedValue()
    if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
        print("\(timestamp()) layer=\(context.layer) type=\(eventTypeName(type)) note=tap-disabled")
        fflush(stdout)
        return Unmanaged.passUnretained(event)
    }
    logEvent(layer: context.layer, type: type, event: event)
    return Unmanaged.passUnretained(event)
}

func createTap(location: CGEventTapLocation, layer: String) -> (tap: CFMachPort, source: CFRunLoopSource, context: TapContext)? {
    let context = TapContext(layer: layer)
    guard let tap = CGEvent.tapCreate(
        tap: location,
        place: .headInsertEventTap,
        options: .listenOnly,
        eventsOfInterest: mouseEventMask(),
        callback: callback,
        userInfo: Unmanaged.passUnretained(context).toOpaque()
    ) else {
        return nil
    }
    guard let source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0) else {
        CFMachPortInvalidate(tap)
        return nil
    }
    return (tap, source, context)
}

do {
    let options = try parseOptions(CommandLine.arguments)
    var activeTaps: [(tap: CFMachPort, source: CFRunLoopSource, context: TapContext)] = []

    if options.includeSessionTap {
        guard let tap = createTap(location: .cgSessionEventTap, layer: "session") else {
            throw ProbeError(description: "could not start session event tap; check Accessibility/Input Monitoring permissions")
        }
        activeTaps.append(tap)
    }
    if options.includeHIDTap {
        guard let tap = createTap(location: .cghidEventTap, layer: "hid") else {
            throw ProbeError(description: "could not start HID event tap; check Accessibility/Input Monitoring permissions")
        }
        activeTaps.append(tap)
    }

    for activeTap in activeTaps {
        CFRunLoopAddSource(CFRunLoopGetCurrent(), activeTap.source, .commonModes)
        CGEvent.tapEnable(tap: activeTap.tap, enable: true)
    }

    print("""
    WorkRecorder mouse button tap probe running. Press left/right/middle mouse buttons, then Control-C to stop.
    Expected physical right click: type=rightMouseDown/rightMouseUp and button_number=1.
    """)
    fflush(stdout)
    RunLoop.current.run()
} catch {
    fputs("WorkRecorder mouse button tap probe failed: \(error)\n", stderr)
    printUsage()
    exit(1)
}
