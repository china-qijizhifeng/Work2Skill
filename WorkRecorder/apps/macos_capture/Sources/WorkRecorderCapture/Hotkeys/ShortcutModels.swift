import AppKit
import Carbon
import Foundation

enum CaptureCommandKind: String, Codable, CaseIterable, Hashable {
    case regionRecording = "region_recording"

    var title: String {
        "区域录制"
    }

    var detail: String {
        "框选工作区域，确认后开始录制。"
    }

    var defaultShortcut: KeyboardShortcut {
        KeyboardShortcut(keyCode: UInt32(kVK_ANSI_R), keyLabel: "R", modifiers: [.control, .option, .command])
    }

    var hotKeyIdentifier: UInt32 {
        2204
    }
}

enum KeyboardModifier: String, Codable, CaseIterable, Hashable {
    case control
    case option
    case shift
    case command

    var carbonMask: UInt32 {
        switch self {
        case .control:
            return UInt32(controlKey)
        case .option:
            return UInt32(optionKey)
        case .shift:
            return UInt32(shiftKey)
        case .command:
            return UInt32(cmdKey)
        }
    }

    var eventMask: NSEvent.ModifierFlags {
        switch self {
        case .control:
            return .control
        case .option:
            return .option
        case .shift:
            return .shift
        case .command:
            return .command
        }
    }

    var displaySymbol: String {
        switch self {
        case .control:
            return "⌃"
        case .option:
            return "⌥"
        case .shift:
            return "⇧"
        case .command:
            return "⌘"
        }
    }

    static let displayOrder: [KeyboardModifier] = [.control, .option, .shift, .command]
}

struct KeyboardShortcut: Codable, Hashable {
    let keyCode: UInt32
    let keyLabel: String
    let modifiers: Set<KeyboardModifier>

    private static let strongModifiers: Set<KeyboardModifier> = [.control, .option, .command]
    private static let modifierOnlyKeyCodes: Set<UInt32> = [
        UInt32(kVK_Shift),
        UInt32(kVK_RightShift),
        UInt32(kVK_Control),
        UInt32(kVK_RightControl),
        UInt32(kVK_Option),
        UInt32(kVK_RightOption),
        UInt32(kVK_Command),
    ]

    var carbonModifiers: UInt32 {
        modifiers.reduce(UInt32(0)) { $0 | $1.carbonMask }
    }

    var displayString: String {
        let modifierText = KeyboardModifier.displayOrder
            .filter { modifiers.contains($0) }
            .map(\.displaySymbol)
            .joined()
        return "\(modifierText)\(keyLabel.uppercased())"
    }

    static func from(event: NSEvent) -> KeyboardShortcut? {
        let cleanFlags = event.modifierFlags.intersection([.control, .option, .shift, .command])
        let modifiers = Set(KeyboardModifier.allCases.filter { cleanFlags.contains($0.eventMask) })
        let shortcut = KeyboardShortcut(
            keyCode: UInt32(event.keyCode),
            keyLabel: label(forKeyCode: UInt32(event.keyCode), characters: event.charactersIgnoringModifiers),
            modifiers: modifiers
        )
        guard shortcut.policyViolationMessage == nil else { return nil }
        return shortcut
    }

    var policyViolationMessage: String? {
        guard !modifiers.isEmpty else {
            return "快捷键需要包含 Control、Command 或 Option。"
        }
        guard !modifiers.isDisjoint(with: Self.strongModifiers) else {
            return "快捷键不能只使用 Shift；请加入 Control、Command 或 Option。"
        }
        guard !Self.modifierOnlyKeyCodes.contains(keyCode) else {
            return "快捷键不能只有修饰键；请再按一个字母、数字或功能键。"
        }
        return nil
    }

    static func label(forKeyCode keyCode: UInt32, characters: String? = nil) -> String {
        if let characters, !characters.isEmpty {
            return characters.uppercased()
        }
        switch Int(keyCode) {
        case kVK_ANSI_0: return "0"
        case kVK_ANSI_1: return "1"
        case kVK_ANSI_2: return "2"
        case kVK_ANSI_3: return "3"
        case kVK_ANSI_4: return "4"
        case kVK_ANSI_5: return "5"
        case kVK_ANSI_6: return "6"
        case kVK_ANSI_7: return "7"
        case kVK_ANSI_8: return "8"
        case kVK_ANSI_9: return "9"
        case kVK_ANSI_A: return "A"
        case kVK_ANSI_B: return "B"
        case kVK_ANSI_C: return "C"
        case kVK_ANSI_D: return "D"
        case kVK_ANSI_E: return "E"
        case kVK_ANSI_F: return "F"
        case kVK_ANSI_G: return "G"
        case kVK_ANSI_H: return "H"
        case kVK_ANSI_I: return "I"
        case kVK_ANSI_J: return "J"
        case kVK_ANSI_K: return "K"
        case kVK_ANSI_L: return "L"
        case kVK_ANSI_M: return "M"
        case kVK_ANSI_N: return "N"
        case kVK_ANSI_O: return "O"
        case kVK_ANSI_P: return "P"
        case kVK_ANSI_Q: return "Q"
        case kVK_ANSI_R: return "R"
        case kVK_ANSI_S: return "S"
        case kVK_ANSI_T: return "T"
        case kVK_ANSI_U: return "U"
        case kVK_ANSI_V: return "V"
        case kVK_ANSI_W: return "W"
        case kVK_ANSI_X: return "X"
        case kVK_ANSI_Y: return "Y"
        case kVK_ANSI_Z: return "Z"
        case kVK_Escape: return "Esc"
        case kVK_Return: return "Return"
        case kVK_Tab: return "Tab"
        case kVK_Space: return "Space"
        default: return "Key \(keyCode)"
        }
    }
}

struct ShortcutCommandBinding: Codable, Equatable {
    let command: CaptureCommandKind
    var shortcut: KeyboardShortcut
    var enabled: Bool

    static func `default`(for command: CaptureCommandKind) -> ShortcutCommandBinding {
        ShortcutCommandBinding(command: command, shortcut: command.defaultShortcut, enabled: true)
    }
}

struct ShortcutSettings: Codable, Equatable {
    var bindings: [CaptureCommandKind: ShortcutCommandBinding]

    static var defaults: ShortcutSettings {
        ShortcutSettings(
            bindings: Dictionary(
                uniqueKeysWithValues: CaptureCommandKind.allCases.map { command in
                    (command, ShortcutCommandBinding.default(for: command))
                }
            )
        )
    }

    func binding(for command: CaptureCommandKind) -> ShortcutCommandBinding {
        bindings[command] ?? .default(for: command)
    }

    mutating func setShortcut(_ shortcut: KeyboardShortcut, for command: CaptureCommandKind) {
        var binding = binding(for: command)
        binding.shortcut = shortcut
        binding.enabled = true
        bindings[command] = binding
    }

    mutating func reset(_ command: CaptureCommandKind) {
        bindings[command] = .default(for: command)
    }
}

enum ShortcutRegistrationState: String, Codable, Equatable {
    case registered
    case disabled
    case conflict
    case failed
}

struct ShortcutRegistrationStatus: Codable, Equatable {
    let command: CaptureCommandKind
    let shortcut: KeyboardShortcut
    let state: ShortcutRegistrationState
    let osStatus: Int32?
    let message: String

    static func registered(command: CaptureCommandKind, shortcut: KeyboardShortcut) -> ShortcutRegistrationStatus {
        ShortcutRegistrationStatus(
            command: command,
            shortcut: shortcut,
            state: .registered,
            osStatus: nil,
            message: "已启用"
        )
    }

    static func disabled(command: CaptureCommandKind, shortcut: KeyboardShortcut) -> ShortcutRegistrationStatus {
        ShortcutRegistrationStatus(
            command: command,
            shortcut: shortcut,
            state: .disabled,
            osStatus: nil,
            message: "已关闭"
        )
    }

    static func conflict(command: CaptureCommandKind, shortcut: KeyboardShortcut, osStatus: OSStatus?) -> ShortcutRegistrationStatus {
        ShortcutRegistrationStatus(
            command: command,
            shortcut: shortcut,
            state: .conflict,
            osStatus: osStatus,
            message: "已被系统或其他 App 占用"
        )
    }

    static func internalDuplicate(command: CaptureCommandKind, shortcut: KeyboardShortcut) -> ShortcutRegistrationStatus {
        ShortcutRegistrationStatus(
            command: command,
            shortcut: shortcut,
            state: .conflict,
            osStatus: nil,
            message: "与 WorkRecorder 另一个命令重复"
        )
    }

    static func failed(command: CaptureCommandKind, shortcut: KeyboardShortcut, osStatus: OSStatus, message: String) -> ShortcutRegistrationStatus {
        ShortcutRegistrationStatus(
            command: command,
            shortcut: shortcut,
            state: .failed,
            osStatus: osStatus,
            message: message
        )
    }
}
