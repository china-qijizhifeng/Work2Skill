import Carbon
import Foundation

struct HelperError: Error, CustomStringConvertible {
    let description: String
}

struct HotKeySpec {
    let keyCode: UInt32
    let modifiers: UInt32
    let displayName: String
}

func parseArguments(_ arguments: [String]) throws -> HotKeySpec {
    var keyCode = UInt32(kVK_ANSI_9)
    var modifiers = UInt32(controlKey | optionKey | cmdKey)
    var displayName = "Control+Option+Command+9"
    var index = 1
    while index < arguments.count {
        switch arguments[index] {
        case "--key-code":
            index += 1
            guard index < arguments.count, let value = UInt32(arguments[index]) else {
                throw HelperError(description: "--key-code requires an integer Carbon key code")
            }
            keyCode = value
        case "--modifiers":
            index += 1
            guard index < arguments.count else {
                throw HelperError(description: "--modifiers requires comma-separated modifier names")
            }
            modifiers = try parseModifiers(arguments[index])
        case "--display-name":
            index += 1
            guard index < arguments.count else {
                throw HelperError(description: "--display-name requires text")
            }
            displayName = arguments[index]
        case "--help", "-h":
            printUsage()
            exit(0)
        default:
            throw HelperError(description: "unknown argument: \(arguments[index])")
        }
        index += 1
    }
    return HotKeySpec(keyCode: keyCode, modifiers: modifiers, displayName: displayName)
}

func parseModifiers(_ raw: String) throws -> UInt32 {
    var modifiers = UInt32(0)
    for part in raw.split(separator: ",").map({ $0.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }) {
        switch part {
        case "control", "ctrl":
            modifiers |= UInt32(controlKey)
        case "option", "alt":
            modifiers |= UInt32(optionKey)
        case "command", "cmd":
            modifiers |= UInt32(cmdKey)
        case "shift":
            modifiers |= UInt32(shiftKey)
        case "":
            continue
        default:
            throw HelperError(description: "unknown modifier: \(part)")
        }
    }
    guard modifiers != 0 else {
        throw HelperError(description: "at least one modifier is required")
    }
    return modifiers
}

func printUsage() {
    print("""
    Usage:
      swift scripts/macos_hotkey_conflict_helper.swift [--key-code 26] [--modifiers control,option,command]

    Default occupies Control+Option+Command+9 until the process is stopped.
    Use this as a release-lab diagnostic for Workbench shortcut-conflict UI.
    Do not mark the external-conflict row passed from this helper alone:
    some macOS versions allow another process to register the same Carbon chord.
    """)
}

do {
    let spec = try parseArguments(CommandLine.arguments)
    var hotKeyRef: EventHotKeyRef?
    let hotKeyID = EventHotKeyID(signature: OSType(0x4E4C484B), id: 9009)
    let status = RegisterEventHotKey(
        spec.keyCode,
        spec.modifiers,
        hotKeyID,
        GetApplicationEventTarget(),
        0,
        &hotKeyRef
    )
    guard status == noErr else {
        throw HelperError(description: "RegisterEventHotKey failed with status \(status)")
    }
    print("""
    WorkRecorder hotkey conflict helper occupying \(spec.displayName). Press Control-C to stop.
    Diagnostic note: only mark the release-lab row passed if Workbench itself reports a conflict.
    """)
    fflush(stdout)
    RunLoop.current.run()
    if let hotKeyRef {
        UnregisterEventHotKey(hotKeyRef)
    }
} catch {
    fputs("WorkRecorder hotkey conflict helper failed: \(error)\n", stderr)
    printUsage()
    exit(1)
}
