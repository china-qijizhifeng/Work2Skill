import AppKit

@MainActor
final class MenuBarController: NSObject {
    private let statusItem: NSStatusItem
    private weak var coordinator: CaptureCoordinator?
    private let shortcutStore: ShortcutPreferencesStore
    private var shortcutObserver: NSObjectProtocol?
    var openRecordingCenter: (() -> Void)?
    var openPermissionGuide: (() -> Void)?

    init(coordinator: CaptureCoordinator, shortcutStore: ShortcutPreferencesStore = ShortcutPreferencesStore(), previewOnly _: Bool = false) {
        self.coordinator = coordinator
        self.shortcutStore = shortcutStore
        self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        super.init()
        configureStatusItem()
        shortcutObserver = NotificationCenter.default.addObserver(
            forName: ShortcutPreferencesStore.didChangeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.configureStatusItem()
            }
        }
    }

    func updateCoordinator(_ coordinator: CaptureCoordinator) {
        self.coordinator = coordinator
        configureStatusItem()
    }

    func refreshFromCoordinator() {
        configureStatusItem()
    }

    private func configureStatusItem() {
        let recording = coordinator?.recordingMenuPresentation ?? .inactive
        if let button = statusItem.button {
            button.image = recording.showsRecordingBadge
                ? WorkRecorderGlyph.makeRecordingStatusImage(size: CGSize(width: 18, height: 18))
                : WorkRecorderGlyph.makeStatusImage(size: CGSize(width: 18, height: 18))
            button.image?.isTemplate = false
            button.toolTip = recording.showsRecordingBadge ? "WorkRecorder · \(recording.statusTitle)" : "WorkRecorder"
        }
        let settings = shortcutStore.load()
        let menu = NSMenu()
        menu.addItem(item(
            "开始录制  \(settings.binding(for: .regionRecording).shortcut.displayString)",
            action: #selector(recordRegionPlaceholder),
            key: ""
        ))
        if recording.status != .inactive {
            menu.addItem(.separator())
            appendRecordingItems(to: menu, presentation: recording)
        }
        menu.addItem(.separator())
        menu.addItem(item("打开录制中心", action: #selector(openRecordingCenterAction), key: "o"))
        menu.addItem(item("权限引导…", action: #selector(openPermissionGuideAction), key: ""))
        menu.addItem(.separator())
        menu.addItem(item("退出 WorkRecorder", action: #selector(quit), key: "q"))
        statusItem.menu = menu
    }

    private func appendRecordingItems(to menu: NSMenu, presentation: RecordingMenuPresentation) {
        menu.addItem(disabledItem("录制状态：\(presentation.statusTitle)"))
        if let detail = presentation.statusDetail {
            menu.addItem(disabledItem(detail))
        }
        let focus = item("唤起录制控制", action: #selector(focusRecordingControlsAction), key: "")
        focus.isEnabled = presentation.canFocusControls
        menu.addItem(focus)
        let pause = item(presentation.pauseToggleTitle, action: #selector(toggleRecordingPauseAction), key: "")
        pause.isEnabled = presentation.canTogglePause
        menu.addItem(pause)
        let finish = item("完成录制", action: #selector(finishRecordingAction), key: "")
        finish.isEnabled = presentation.canFinish
        menu.addItem(finish)
    }

    private func item(_ title: String, action: Selector, key: String) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.keyEquivalentModifierMask = key.isEmpty ? [] : [.command, .shift]
        item.target = self
        return item
    }

    private func disabledItem(_ title: String) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: nil, keyEquivalent: "")
        item.isEnabled = false
        return item
    }

    @objc private func recordRegionPlaceholder() {
        coordinator?.startRegionRecordingPreparation()
    }

    @objc private func focusRecordingControlsAction() {
        coordinator?.focusRecordingControls()
    }

    @objc private func toggleRecordingPauseAction() {
        coordinator?.toggleRecordingPause()
    }

    @objc private func finishRecordingAction() {
        coordinator?.finishRecordingForReview()
    }

    @objc private func openRecordingCenterAction() {
        openRecordingCenter?()
    }

    @objc private func openPermissionGuideAction() {
        openPermissionGuide?()
    }

    @objc private func quit() {
        NSApplication.shared.terminate(nil)
    }

    deinit {
        MainActor.assumeIsolated {
            if let shortcutObserver {
                NotificationCenter.default.removeObserver(shortcutObserver)
            }
        }
    }
}

enum WorkRecorderGlyph {
    static func makeBrandImage(size: CGSize) -> NSImage {
        if let url = Bundle.main.url(forResource: "app-icon", withExtension: "png"),
           let image = NSImage(contentsOf: url) {
            image.size = size
            return image
        }
        return makeImage(size: size)
    }

    static func makeStatusImage(size: CGSize) -> NSImage {
        makeBrandImage(size: size)
    }

    static func makeRecordingStatusImage(size: CGSize) -> NSImage {
        let image = makeBrandImage(size: size)
        image.lockFocus()
        let diameter = max(4.0, size.width * 0.27)
        let badge = CGRect(
            x: size.width - diameter * 0.92,
            y: diameter * 0.08,
            width: diameter,
            height: diameter
        )
        NSColor.white.withAlphaComponent(0.95).setFill()
        NSBezierPath(ovalIn: badge.insetBy(dx: -1.0, dy: -1.0)).fill()
        NSColor(calibratedRed: 1.0, green: 0.28, blue: 0.20, alpha: 1).setFill()
        NSBezierPath(ovalIn: badge).fill()
        image.unlockFocus()
        image.isTemplate = false
        return image
    }

    static func makeImage(size: CGSize) -> NSImage {
        let image = NSImage(size: size)
        image.lockFocus()
        let rect = CGRect(origin: .zero, size: size)
        NSColor.clear.setFill()
        rect.fill()
        drawRecorderMark(in: rect.insetBy(dx: size.width * 0.06, dy: size.height * 0.06), active: false)
        image.unlockFocus()
        image.isTemplate = false
        return image
    }

    private static func drawRecorderMark(in rect: CGRect, active: Bool) {
        NSGraphicsContext.current?.shouldAntialias = true
        let navy = NSColor(calibratedRed: 0.035, green: 0.065, blue: 0.12, alpha: 1)
        let coral = NSColor(calibratedRed: 1.0, green: 0.24, blue: 0.20, alpha: 1)
        let background = NSBezierPath(
            roundedRect: rect,
            xRadius: rect.width * 0.25,
            yRadius: rect.height * 0.25
        )
        navy.setFill()
        background.fill()
        if active {
            coral.withAlphaComponent(0.92).setStroke()
            background.lineWidth = max(1.0, rect.width * 0.075)
            background.stroke()
        }

        let monogram = NSBezierPath()
        let points = [
            CGPoint(x: 0.16, y: 0.66),
            CGPoint(x: 0.34, y: 0.25),
            CGPoint(x: 0.50, y: 0.56),
            CGPoint(x: 0.66, y: 0.25),
            CGPoint(x: 0.84, y: 0.66),
        ].map { point in
            CGPoint(x: rect.minX + rect.width * point.x, y: rect.minY + rect.height * point.y)
        }
        monogram.move(to: points[0])
        points.dropFirst().forEach { monogram.line(to: $0) }
        monogram.lineWidth = max(1.2, rect.width * 0.15)
        monogram.lineCapStyle = .round
        monogram.lineJoinStyle = .round
        NSColor(calibratedWhite: 0.95, alpha: 1).setStroke()
        monogram.stroke()

        let fold = NSBezierPath()
        fold.move(to: points[1])
        fold.line(to: points[2])
        fold.line(to: points[3])
        fold.lineWidth = max(0.9, rect.width * 0.105)
        fold.lineCapStyle = .round
        fold.lineJoinStyle = .round
        coral.withAlphaComponent(0.96).setStroke()
        fold.stroke()

        let dotSize = rect.width * 0.12
        let dotRect = CGRect(
            x: rect.minX + rect.width * 0.76,
            y: rect.minY + rect.height * 0.74,
            width: dotSize,
            height: dotSize
        )
        coral.setFill()
        NSBezierPath(ovalIn: dotRect).fill()
    }
}
