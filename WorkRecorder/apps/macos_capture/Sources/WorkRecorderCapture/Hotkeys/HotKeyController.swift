import Foundation

@MainActor
final class HotKeyController {
    private let preferences: ShortcutPreferencesStore
    private let registry: ShortcutRegistry
    private var observer: NSObjectProtocol?

    var registrationStatuses: [CaptureCommandKind: ShortcutRegistrationStatus] {
        registry.statuses
    }

    init(
        preferences: ShortcutPreferencesStore = ShortcutPreferencesStore(),
        commandHandler: @escaping (CaptureCommandKind) -> Void,
        logStore: AppLogStore? = nil
    ) {
        self.preferences = preferences
        self.registry = ShortcutRegistry(handler: commandHandler, logStore: logStore)
    }

    func register() {
        if let observer {
            NotificationCenter.default.removeObserver(observer)
            self.observer = nil
        }
        registry.register(settings: preferences.load())
        observer = NotificationCenter.default.addObserver(
            forName: ShortcutPreferencesStore.didChangeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.registry.register(settings: self.preferences.load())
            }
        }
    }

    func unregister() {
        if let observer {
            NotificationCenter.default.removeObserver(observer)
            self.observer = nil
        }
        registry.unregister()
    }
}
