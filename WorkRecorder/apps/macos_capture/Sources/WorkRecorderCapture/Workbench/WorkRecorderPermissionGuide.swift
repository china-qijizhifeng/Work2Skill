import AppKit
import ApplicationServices
import CoreGraphics

struct WorkRecorderPermissionSnapshot: Equatable {
    let accessibility: Bool
    let inputMonitoring: Bool
    let screenRecording: Bool

    var allGranted: Bool {
        accessibility && inputMonitoring && screenRecording
    }

    static func current() -> WorkRecorderPermissionSnapshot {
        WorkRecorderPermissionSnapshot(
            accessibility: AXIsProcessTrusted(),
            inputMonitoring: CGPreflightListenEventAccess(),
            screenRecording: CGPreflightScreenCaptureAccess()
        )
    }
}

enum WorkRecorderPermissionGuidePolicy {
    static let seenKey = "WorkRecorder.PermissionGuideSeen.v1"

    static func shouldPresentAutomatically(hasSeenGuide: Bool) -> Bool {
        !hasSeenGuide
    }
}

private enum WorkRecorderPrivacyPane: CaseIterable {
    case accessibility
    case inputMonitoring
    case screenRecording

    var title: String {
        switch self {
        case .accessibility:
            return "辅助功能"
        case .inputMonitoring:
            return "输入监控"
        case .screenRecording:
            return "屏幕与系统音频录制"
        }
    }

    var detail: String {
        switch self {
        case .accessibility:
            return "帮助识别当前窗口、控件和操作目标。"
        case .inputMonitoring:
            return "用于记录点击、滚动与键盘操作线索。"
        case .screenRecording:
            return "用于录制框选区域的画面与系统音频。"
        }
    }

    var symbolName: String {
        switch self {
        case .accessibility:
            return "accessibility"
        case .inputMonitoring:
            return "keyboard"
        case .screenRecording:
            return "rectangle.inset.filled.and.person.filled"
        }
    }

    var settingsURL: URL? {
        let rawValue: String
        switch self {
        case .accessibility:
            rawValue = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
        case .inputMonitoring:
            rawValue = "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"
        case .screenRecording:
            rawValue = "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"
        }
        return URL(string: rawValue)
    }

    func isGranted(in snapshot: WorkRecorderPermissionSnapshot) -> Bool {
        switch self {
        case .accessibility:
            return snapshot.accessibility
        case .inputMonitoring:
            return snapshot.inputMonitoring
        case .screenRecording:
            return snapshot.screenRecording
        }
    }

    func requestAuthorizationIfNeeded() {
        switch self {
        case .accessibility:
            guard !AXIsProcessTrusted() else { return }
            let options = ["AXTrustedCheckOptionPrompt": true] as CFDictionary
            _ = AXIsProcessTrustedWithOptions(options)
        case .inputMonitoring:
            guard !CGPreflightListenEventAccess() else { return }
            _ = CGRequestListenEventAccess()
        case .screenRecording:
            guard !CGPreflightScreenCaptureAccess() else { return }
            _ = CGRequestScreenCaptureAccess()
        }
    }
}

@MainActor
final class WorkRecorderPermissionGuideWindowController: NSWindowController, NSWindowDelegate {
    private let guideView: WorkRecorderPermissionGuideView
    private var activationObserver: NSObjectProtocol?
    private var refreshTask: Task<Void, Never>?

    init() {
        guideView = WorkRecorderPermissionGuideView()
        let window = NSPanel(
            contentRect: NSRect(origin: .zero, size: NSSize(width: 660, height: 520)),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        window.title = "WorkRecorder 权限引导"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.isMovableByWindowBackground = true
        window.isReleasedWhenClosed = false
        window.backgroundColor = WorkbenchDesignTokens.Color.canvas
        window.contentView = guideView
        super.init(window: window)
        window.delegate = self
        guideView.onClose = { [weak self] in self?.close() }
        activationObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.didBecomeActiveNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                self?.schedulePermissionRefresh()
            }
        }
    }

    required init?(coder: NSCoder) {
        nil
    }

    func show(relativeTo parent: NSWindow?) {
        schedulePermissionRefresh()
        if let parent, let window {
            let frame = window.frame
            let origin = NSPoint(
                x: parent.frame.midX - frame.width / 2,
                y: parent.frame.midY - frame.height / 2
            )
            window.setFrameOrigin(origin)
        } else {
            window?.center()
        }
        showWindow(nil)
        window?.makeKeyAndOrderFront(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }

    deinit {
        MainActor.assumeIsolated {
            refreshTask?.cancel()
            if let activationObserver {
                NotificationCenter.default.removeObserver(activationObserver)
            }
        }
    }

    private func schedulePermissionRefresh() {
        refreshTask?.cancel()
        refreshTask = Task { [weak self] in
            for delay in [UInt64(0), 450_000_000, 1_100_000_000, 2_200_000_000] {
                if delay > 0 {
                    try? await Task.sleep(nanoseconds: delay)
                }
                guard !Task.isCancelled else { return }
                self?.guideView.refresh()
            }
        }
    }
}

@MainActor
private final class WorkRecorderPermissionGuideView: NSView {
    var onClose: (() -> Void)?
    private let rows: [WorkRecorderPermissionRow]

    override init(frame frameRect: NSRect) {
        rows = WorkRecorderPrivacyPane.allCases.map { WorkRecorderPermissionRow(pane: $0) }
        super.init(frame: frameRect)
        wantsLayer = true
        layer?.backgroundColor = WorkbenchDesignTokens.Color.canvas.cgColor
        buildUI()
        refresh()
    }

    required init?(coder: NSCoder) {
        nil
    }

    func refresh() {
        let snapshot = WorkRecorderPermissionSnapshot.current()
        for row in rows {
            row.update(granted: row.pane.isGranted(in: snapshot))
        }
    }

    private func buildUI() {
        let mark = NSImageView()
        mark.image = NSImage(systemSymbolName: "checkmark.shield.fill", accessibilityDescription: "权限引导")
        mark.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 28, weight: .medium)
        mark.contentTintColor = WorkbenchDesignTokens.Color.brandBlue
        mark.translatesAutoresizingMaskIntoConstraints = false

        let eyebrow = permissionLabel("录制前准备", size: 11.5, weight: .semibold, color: WorkbenchDesignTokens.Color.brandBlueStrong)
        let title = permissionLabel("设置 WorkRecorder 权限", size: 23, weight: .bold, color: WorkbenchDesignTokens.Color.primaryText)
        let headerCopy = NSStackView(views: [eyebrow, title])
        headerCopy.orientation = .vertical
        headerCopy.alignment = .leading
        headerCopy.spacing = 3

        let header = NSStackView(views: [mark, headerCopy])
        header.orientation = .horizontal
        header.alignment = .centerY
        header.spacing = 14

        let instruction = permissionInstructionRow()

        let rowsStack = NSStackView(views: rows)
        rowsStack.orientation = .vertical
        rowsStack.alignment = .width
        rowsStack.spacing = 10

        let note = permissionLabel(
            "若开关已打开但仍显示未生效，请移除旧的 WorkRecorder，再点“+”添加当前应用；通过终端启动时也请检查“终端”。",
            size: 11.5,
            weight: .regular,
            color: WorkbenchDesignTokens.Color.muted
        )
        note.maximumNumberOfLines = 2
        note.lineBreakMode = .byWordWrapping

        let closeButton = WorkbenchButton(
            title: "完成",
            variant: .secondary,
            symbolName: "checkmark",
            target: self,
            action: #selector(closePressed)
        )
        closeButton.applyCompactMinimumWidth()

        let footer = NSStackView(views: [note, NSView(), closeButton])
        footer.orientation = .horizontal
        footer.alignment = .centerY
        footer.spacing = 16

        let root = NSStackView(views: [header, instruction, rowsStack, footer])
        root.orientation = .vertical
        root.alignment = .width
        root.spacing = 18
        root.translatesAutoresizingMaskIntoConstraints = false
        addSubview(root)

        NSLayoutConstraint.activate([
            mark.widthAnchor.constraint(equalToConstant: 44),
            mark.heightAnchor.constraint(equalToConstant: 44),
            root.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 30),
            root.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -30),
            root.topAnchor.constraint(equalTo: topAnchor, constant: 30),
            root.bottomAnchor.constraint(equalTo: bottomAnchor, constant: -28),
        ])
    }

    @objc private func closePressed() {
        onClose?()
    }

    private func permissionInstructionRow() -> NSView {
        let route = permissionLabel(
            "打开“系统设置 → 隐私与安全性”，给",
            size: 13,
            weight: .medium,
            color: WorkbenchDesignTokens.Color.secondaryText
        )
        let conjunction = permissionLabel(
            "和",
            size: 13,
            weight: .medium,
            color: WorkbenchDesignTokens.Color.secondaryText
        )
        let suffix = permissionLabel(
            "开启以下权限。",
            size: 13,
            weight: .medium,
            color: WorkbenchDesignTokens.Color.secondaryText
        )
        let row = NSStackView(views: [
            route,
            permissionEmphasisToken("WorkRecorder"),
            conjunction,
            permissionEmphasisToken("终端"),
            suffix,
        ])
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 7
        row.setAccessibilityLabel("打开系统设置、隐私与安全性，给 WorkRecorder 和终端开启以下权限。")
        return row
    }

    private func permissionEmphasisToken(_ text: String) -> NSView {
        let label = permissionLabel(
            text,
            size: 15.5,
            weight: .bold,
            color: WorkbenchDesignTokens.Color.brandBlueStrong
        )
        label.translatesAutoresizingMaskIntoConstraints = false

        let token = NSView()
        token.wantsLayer = true
        token.layer?.cornerRadius = 9
        token.layer?.backgroundColor = WorkbenchDesignTokens.Color.panelSoft.cgColor
        token.layer?.borderColor = WorkbenchDesignTokens.Color.brandSky.cgColor
        token.layer?.borderWidth = 1
        token.addSubview(label)
        NSLayoutConstraint.activate([
            label.leadingAnchor.constraint(equalTo: token.leadingAnchor, constant: 9),
            label.trailingAnchor.constraint(equalTo: token.trailingAnchor, constant: -9),
            label.topAnchor.constraint(equalTo: token.topAnchor, constant: 4),
            label.bottomAnchor.constraint(equalTo: token.bottomAnchor, constant: -4),
        ])
        token.setContentHuggingPriority(.required, for: .horizontal)
        token.setContentCompressionResistancePriority(.required, for: .horizontal)
        return token
    }
}

@MainActor
private final class WorkRecorderPermissionRow: NSView {
    let pane: WorkRecorderPrivacyPane
    private let statusLabel = permissionLabel("", size: 11.5, weight: .semibold, color: WorkbenchDesignTokens.Color.secondaryText)
    private let statusPill = NSView()

    init(pane: WorkRecorderPrivacyPane) {
        self.pane = pane
        super.init(frame: .zero)
        wantsLayer = true
        layer?.cornerRadius = 15
        layer?.backgroundColor = WorkbenchDesignTokens.Color.panelElevated.cgColor
        layer?.borderColor = WorkbenchDesignTokens.Color.brandSky.withAlphaComponent(0.88).cgColor
        layer?.borderWidth = 1
        buildUI()
    }

    required init?(coder: NSCoder) {
        nil
    }

    func update(granted: Bool) {
        statusLabel.stringValue = granted ? "已生效" : "当前未生效"
        statusLabel.textColor = granted
            ? WorkbenchDesignTokens.Color.brandBlueStrong
            : WorkbenchDesignTokens.Color.recordingRedStrong
        statusPill.layer?.backgroundColor = (granted
            ? WorkbenchDesignTokens.Color.panelSoft
            : WorkbenchDesignTokens.Color.recordingRed.withAlphaComponent(0.10)).cgColor
        statusPill.layer?.borderColor = (granted
            ? WorkbenchDesignTokens.Color.brandSky
            : WorkbenchDesignTokens.Color.recordingRed.withAlphaComponent(0.24)).cgColor
        setAccessibilityLabel("\(pane.title)：\(statusLabel.stringValue)。\(pane.detail)")
    }

    private func buildUI() {
        let icon = NSImageView()
        icon.image = NSImage(systemSymbolName: pane.symbolName, accessibilityDescription: pane.title)
        icon.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 16, weight: .medium)
        icon.contentTintColor = WorkbenchDesignTokens.Color.brandBlueStrong
        icon.translatesAutoresizingMaskIntoConstraints = false

        let title = permissionLabel(pane.title, size: 13.2, weight: .semibold, color: WorkbenchDesignTokens.Color.primaryText)
        let detail = permissionLabel(pane.detail, size: 11.5, weight: .regular, color: WorkbenchDesignTokens.Color.secondaryText)
        let copy = NSStackView(views: [title, detail])
        copy.orientation = .vertical
        copy.alignment = .leading
        copy.spacing = 3

        statusLabel.alignment = .center
        statusLabel.translatesAutoresizingMaskIntoConstraints = false

        statusPill.wantsLayer = true
        statusPill.layer?.cornerRadius = 9
        statusPill.layer?.borderWidth = 0.8
        statusPill.translatesAutoresizingMaskIntoConstraints = false
        statusPill.addSubview(statusLabel)

        let settingsButton = WorkbenchButton(
            title: "打开设置",
            variant: .quiet,
            symbolName: "arrow.up.right.square",
            target: self,
            action: #selector(openSettings)
        )
        settingsButton.applyCompactMinimumWidth()

        let row = NSStackView(views: [icon, copy, NSView(), statusPill, settingsButton])
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 13
        row.translatesAutoresizingMaskIntoConstraints = false
        addSubview(row)

        NSLayoutConstraint.activate([
            heightAnchor.constraint(equalToConstant: 76),
            icon.widthAnchor.constraint(equalToConstant: 24),
            icon.heightAnchor.constraint(equalToConstant: 24),
            statusPill.widthAnchor.constraint(equalToConstant: 116),
            statusPill.heightAnchor.constraint(equalToConstant: 24),
            statusLabel.leadingAnchor.constraint(equalTo: statusPill.leadingAnchor, constant: 8),
            statusLabel.trailingAnchor.constraint(equalTo: statusPill.trailingAnchor, constant: -8),
            statusLabel.centerYAnchor.constraint(equalTo: statusPill.centerYAnchor, constant: -1),
            row.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 16),
            row.trailingAnchor.constraint(equalTo: trailingAnchor, constant: -14),
            row.centerYAnchor.constraint(equalTo: centerYAnchor),
        ])
    }

    @objc private func openSettings() {
        guard let url = pane.settingsURL else { return }
        pane.requestAuthorizationIfNeeded()
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            NSWorkspace.shared.open(url)
        }
    }
}

@MainActor
private func permissionLabel(_ text: String, size: CGFloat, weight: NSFont.Weight, color: NSColor) -> NSTextField {
    let label = NSTextField(labelWithString: WorkRecorderLocalization.text(text))
    label.font = NSFont.systemFont(ofSize: size, weight: weight)
    label.textColor = color
    return label
}
