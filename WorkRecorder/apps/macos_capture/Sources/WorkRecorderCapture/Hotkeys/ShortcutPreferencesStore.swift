import Carbon
import Foundation

@MainActor
final class ShortcutPreferencesStore {
    static let didChangeNotification = Notification.Name("WorkRecorderShortcutPreferencesDidChange")

    private let defaults: UserDefaults
    private let key: String
    private let defaultsVersionKey: String
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()
    private let currentDefaultsVersion = 2

    init(defaults: UserDefaults = .standard, key: String = "WorkRecorder.Shortcuts.v1") {
        self.defaults = defaults
        self.key = key
        self.defaultsVersionKey = "\(key).defaultsVersion"
    }

    func load() -> ShortcutSettings {
        guard let data = defaults.data(forKey: key) else {
            defaults.set(currentDefaultsVersion, forKey: defaultsVersionKey)
            return .defaults
        }
        do {
            let decoded = try decoder.decode(ShortcutSettings.self, from: data)
            let merged = mergeDefaults(into: decoded)
            let migrated = migrateDefaultsIfNeeded(merged)
            if migrated != merged {
                persist(migrated, postNotification: false)
            }
            defaults.set(currentDefaultsVersion, forKey: defaultsVersionKey)
            return migrated
        } catch {
            NSLog("WorkRecorder failed to decode shortcut settings: \(String(describing: error))")
            defaults.set(currentDefaultsVersion, forKey: defaultsVersionKey)
            return .defaults
        }
    }

    func save(_ settings: ShortcutSettings) {
        let merged = mergeDefaults(into: settings)
        persist(merged, postNotification: true)
        defaults.set(currentDefaultsVersion, forKey: defaultsVersionKey)
    }

    private func persist(_ settings: ShortcutSettings, postNotification: Bool) {
        do {
            defaults.set(try encoder.encode(settings), forKey: key)
            if postNotification {
                NotificationCenter.default.post(name: Self.didChangeNotification, object: self)
            }
        } catch {
            NSLog("WorkRecorder failed to encode shortcut settings: \(String(describing: error))")
        }
    }

    func reset() {
        save(.defaults)
    }

    private func mergeDefaults(into settings: ShortcutSettings) -> ShortcutSettings {
        var merged = settings
        for command in CaptureCommandKind.allCases where merged.bindings[command] == nil {
            merged.bindings[command] = .default(for: command)
        }
        return merged
    }

    private func migrateDefaultsIfNeeded(_ settings: ShortcutSettings) -> ShortcutSettings {
        guard defaults.integer(forKey: defaultsVersionKey) < currentDefaultsVersion else {
            return settings
        }
        var migrated = settings
        let oldRecordingDefault = KeyboardShortcut(
            keyCode: UInt32(kVK_ANSI_R),
            keyLabel: "R",
            modifiers: [.control, .command]
        )
        let existing = migrated.binding(for: .regionRecording)
        if existing.enabled && existing.shortcut == oldRecordingDefault {
            migrated.bindings[.regionRecording] = .default(for: .regionRecording)
        }
        return migrated
    }
}
