import Carbon
import Foundation

@MainActor
final class ShortcutRegistry {
    static let didUpdateStatusesNotification = Notification.Name("WorkRecorderShortcutRegistryDidUpdateStatuses")

    private enum Constants {
        static let signature = OSType(0x4E4C4854)
    }

    private let handler: (CaptureCommandKind) -> Void
    private weak var logStore: AppLogStore?
    private var eventHandler: EventHandlerRef?
    private var retainedContext: UnsafeMutableRawPointer?
    private var hotKeys: [CaptureCommandKind: EventHotKeyRef] = [:]
    private(set) var statuses: [CaptureCommandKind: ShortcutRegistrationStatus] = [:]

    init(handler: @escaping (CaptureCommandKind) -> Void, logStore: AppLogStore? = nil) {
        self.handler = handler
        self.logStore = logStore
    }

    func register(settings: ShortcutSettings) {
        unregister()
        statuses.removeAll()
        guard installHandler() else { return }
        let duplicates = ShortcutConflictDetector.duplicates(in: settings)
        for command in CaptureCommandKind.allCases {
            let binding = settings.binding(for: command)
            guard binding.enabled else {
                statuses[command] = .disabled(command: command, shortcut: binding.shortcut)
                continue
            }
            if let violation = binding.shortcut.policyViolationMessage {
                statuses[command] = .failed(command: command, shortcut: binding.shortcut, osStatus: noErr, message: violation)
                logStore?.append("\(command.title) 快捷键不符合策略：\(violation)")
                continue
            }
            if duplicates.contains(command) {
                statuses[command] = .internalDuplicate(command: command, shortcut: binding.shortcut)
                logStore?.append("\(command.title) 快捷键与另一个命令重复：\(binding.shortcut.displayString)")
                continue
            }
            register(command: command, shortcut: binding.shortcut)
        }
        NotificationCenter.default.post(name: Self.didUpdateStatusesNotification, object: self)
    }

    func unregister() {
        for hotKey in hotKeys.values {
            UnregisterEventHotKey(hotKey)
        }
        hotKeys.removeAll()
        if let eventHandler {
            RemoveEventHandler(eventHandler)
            self.eventHandler = nil
        }
        releaseRetainedContext()
    }

    private func installHandler() -> Bool {
        var eventSpec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let context = Unmanaged.passRetained(self).toOpaque()
        retainedContext = context
        let status = InstallEventHandler(
            GetApplicationEventTarget(),
            { _, event, userData in
                guard let event, let userData else { return noErr }
                var hotKeyID = EventHotKeyID()
                let status = GetEventParameter(
                    event,
                    EventParamName(kEventParamDirectObject),
                    EventParamType(typeEventHotKeyID),
                    nil,
                    MemoryLayout<EventHotKeyID>.size,
                    nil,
                    &hotKeyID
                )
                guard status == noErr else { return status }
                let registry = Unmanaged<ShortcutRegistry>.fromOpaque(userData).takeUnretainedValue()
                DispatchQueue.main.async {
                    registry.handle(id: hotKeyID.id)
                }
                return noErr
            },
            1,
            &eventSpec,
            context,
            &eventHandler
        )
        guard status == noErr else {
            NSLog("WorkRecorder failed to install shortcut handler: \(status)")
            logStore?.append("快捷键监听安装失败：\(status)")
            releaseRetainedContext()
            return false
        }
        return true
    }

    private func register(command: CaptureCommandKind, shortcut: KeyboardShortcut) {
        let hotKeyID = EventHotKeyID(signature: Constants.signature, id: command.hotKeyIdentifier)
        var ref: EventHotKeyRef?
        let status = RegisterEventHotKey(
            shortcut.keyCode,
            shortcut.carbonModifiers,
            hotKeyID,
            GetApplicationEventTarget(),
            0,
            &ref
        )
        guard status == noErr, let ref else {
            let registration = registrationStatus(for: status, command: command, shortcut: shortcut)
            statuses[command] = registration
            NSLog("WorkRecorder failed to register shortcut \(command.rawValue): \(status)")
            logStore?.append("\(command.title) 快捷键注册失败：\(shortcut.displayString) · \(status)")
            return
        }
        hotKeys[command] = ref
        statuses[command] = .registered(command: command, shortcut: shortcut)
        logStore?.append("\(command.title) 快捷键已注册：\(shortcut.displayString)")
    }

    private func registrationStatus(
        for status: OSStatus,
        command: CaptureCommandKind,
        shortcut: KeyboardShortcut
    ) -> ShortcutRegistrationStatus {
        if status == eventHotKeyExistsErr {
            return .conflict(command: command, shortcut: shortcut, osStatus: status)
        }
        return .failed(
            command: command,
            shortcut: shortcut,
            osStatus: status,
            message: "系统返回快捷键注册错误 \(status)"
        )
    }

    private func handle(id: UInt32) {
        guard let command = CaptureCommandKind.allCases.first(where: { $0.hotKeyIdentifier == id }) else {
            return
        }
        NSLog("WorkRecorder shortcut pressed \(command.rawValue)")
        handler(command)
    }

    private func releaseRetainedContext() {
        if let retainedContext {
            Unmanaged<ShortcutRegistry>.fromOpaque(retainedContext).release()
            self.retainedContext = nil
        }
    }
}

enum ShortcutConflictDetector {
    static func duplicates(in settings: ShortcutSettings) -> Set<CaptureCommandKind> {
        var owners: [KeyboardShortcut: [CaptureCommandKind]] = [:]
        for command in CaptureCommandKind.allCases {
            let binding = settings.binding(for: command)
            guard binding.enabled else { continue }
            owners[binding.shortcut, default: []].append(command)
        }
        return Set(owners.values.filter { $0.count > 1 }.flatMap { $0 })
    }
}
