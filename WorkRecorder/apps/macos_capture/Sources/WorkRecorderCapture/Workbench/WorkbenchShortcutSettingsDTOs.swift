import Foundation

struct WorkbenchKeyboardShortcutView: Codable, Equatable {
    let keyCode: Int
    let keyLabel: String
    let modifiers: [String]

    enum CodingKeys: String, CodingKey {
        case keyCode = "key_code"
        case keyLabel = "key_label"
        case modifiers
    }

    init(shortcut: KeyboardShortcut) {
        self.keyCode = Int(shortcut.keyCode)
        self.keyLabel = shortcut.keyLabel
        self.modifiers = KeyboardModifier.displayOrder
            .filter { shortcut.modifiers.contains($0) }
            .map(\.rawValue)
    }

    var shortcut: KeyboardShortcut? {
        let parsedModifiers = modifiers.compactMap(KeyboardModifier.init(rawValue:))
        guard parsedModifiers.count == modifiers.count else { return nil }
        return KeyboardShortcut(keyCode: UInt32(keyCode), keyLabel: keyLabel, modifiers: Set(parsedModifiers))
    }
}

struct WorkbenchShortcutCommandBindingView: Codable, Equatable {
    let command: String
    let shortcut: WorkbenchKeyboardShortcutView
    let enabled: Bool

    init(binding: ShortcutCommandBinding) {
        self.command = binding.command.rawValue
        self.shortcut = WorkbenchKeyboardShortcutView(shortcut: binding.shortcut)
        self.enabled = binding.enabled
    }

    var binding: ShortcutCommandBinding? {
        guard let command = CaptureCommandKind(rawValue: command),
              let shortcut = shortcut.shortcut
        else {
            return nil
        }
        return ShortcutCommandBinding(command: command, shortcut: shortcut, enabled: enabled)
    }
}

struct WorkbenchShortcutSettingsView: Codable, Equatable {
    let bindings: [WorkbenchShortcutCommandBindingView]

    init(settings: ShortcutSettings) {
        self.bindings = CaptureCommandKind.allCases.map { command in
            WorkbenchShortcutCommandBindingView(binding: settings.binding(for: command))
        }
    }

    var shortcutSettings: ShortcutSettings? {
        let parsed = bindings.compactMap(\.binding)
        guard parsed.count == bindings.count else { return nil }
        return ShortcutSettings(bindings: Dictionary(uniqueKeysWithValues: parsed.map { ($0.command, $0) }))
    }
}
