import AppKit
import Foundation

enum WorkbenchPage: String {
    case recordings
}

@MainActor
final class WorkbenchWindowController: NSWindowController, NSWindowDelegate, NSCollectionViewDataSource, NSCollectionViewDelegate {
    private static let itemIdentifier = NSUserInterfaceItemIdentifier("RecordingCenterCard")
    private static let minimumWindowSize = NSSize(width: 700, height: 560)
    private static let preferredWindowSize = NSSize(width: 980, height: 720)
    private static let libraryInset: CGFloat = 18
    private static let itemSpacing: CGFloat = 16
    private static let minimumTwoColumnCardWidth: CGFloat = 360

    private let daemon: DaemonSupervisor
    private let client: WorkbenchDaemonClient
    private weak var coordinator: CaptureCoordinator?
    private let logStore: AppLogStore

    private let countLabel = NSTextField(labelWithString: "")
    private let statusLabel = NSTextField(labelWithString: "")
    private let searchField = WorkbenchSearchField()
    private let progress = NSProgressIndicator()
    private let collectionView = RecordingCenterCollectionView()
    private let emptyView = RecordingCenterEmptyView()
    private var permissionGuideController: WorkRecorderPermissionGuideWindowController?
    private var recordings: [SearchCardView] = []
    private var searchTask: Task<Void, Never>?
    private var refreshTask: Task<Void, Never>?
    private var isLoading = false
    private var didEvaluateAutomaticPermissionGuide = false

    var openRecordingReview: ((RecordingReviewOpenRequest) -> Void)?

    init(
        daemon: DaemonSupervisor,
        client: WorkbenchDaemonClient,
        coordinator: CaptureCoordinator,
        logStore: AppLogStore
    ) {
        self.daemon = daemon
        self.client = client
        self.coordinator = coordinator
        self.logStore = logStore
        let window = NSWindow(
            contentRect: NSRect(origin: .zero, size: Self.preferredWindowSize),
            styleMask: [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView],
            backing: .buffered,
            defer: false
        )
        window.title = "WorkRecorder 录制中心"
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.minSize = Self.minimumWindowSize
        window.isMovableByWindowBackground = true
        super.init(window: window)
        window.delegate = self
        configureWindow()
    }

    required init?(coder: NSCoder) {
        nil
    }

    deinit {
        searchTask?.cancel()
        refreshTask?.cancel()
    }

    func show(page _: WorkbenchPage = .recordings) {
        NSApplication.shared.setActivationPolicy(.regular)
        if window?.isVisible != true {
            window?.center()
        }
        window?.makeKeyAndOrderFront(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)
        window?.contentView?.layoutSubtreeIfNeeded()
        collectionView.collectionViewLayout?.invalidateLayout()
        refresh()
        showPermissionGuideAutomaticallyIfNeeded()
    }

    func showPermissionGuide() {
        let controller: WorkRecorderPermissionGuideWindowController
        if let permissionGuideController {
            controller = permissionGuideController
        } else {
            controller = WorkRecorderPermissionGuideWindowController()
            permissionGuideController = controller
        }
        controller.show(relativeTo: window)
    }

    func refreshAfterCaptureSaved(eventId _: String? = nil) {
        searchField.stringValue = ""
        refresh()
    }

    func openRecordingReviewForEventId(_ eventId: String) {
        guard !eventId.isEmpty else { return }
        statusLabel.stringValue = "正在打开录制…"
        Task { [weak self] in
            guard let self else { return }
            do {
                let inspect = try await client.inspectEvent(eventId: eventId, includeCleanPageText: true)
                guard inspect.activeCapture?.isRecordingSession == true else {
                    throw WorkbenchClientError.daemonRejected("这条记录不是录制会话。")
                }
                let selectedStepId = RecordingReviewCore.selectedStep(
                    in: inspect.activeCapture!,
                    selectedStepId: nil
                )?.stepId
                let request = RecordingReviewOpenRequest(
                    inspect: inspect,
                    thumbnail: nil,
                    selectedStepId: selectedStepId,
                    currentMediaTimeMs: nil,
                    sourceWindowFrame: window?.frame,
                    sourceScreenVisibleFrame: window?.screen?.visibleFrame,
                    onCommit: { _ in }
                )
                statusLabel.stringValue = ""
                openRecordingReview?(request)
            } catch {
                let message = error.localizedDescription
                statusLabel.stringValue = message
                logStore.append("打开录制复盘失败：\(message)")
            }
        }
    }

    func windowDidResize(_ notification: Notification) {
        guard notification.object as? NSWindow === window else { return }
        collectionView.collectionViewLayout?.invalidateLayout()
    }

    func collectionView(_ collectionView: NSCollectionView, numberOfItemsInSection section: Int) -> Int {
        recordings.count
    }

    func collectionView(_ collectionView: NSCollectionView, itemForRepresentedObjectAt indexPath: IndexPath) -> NSCollectionViewItem {
        let item = collectionView.makeItem(withIdentifier: Self.itemIdentifier, for: indexPath)
        guard let card = item as? RecordingCenterCardItem else { return item }
        let recording = recordings[indexPath.item]
        card.configure(
            recording: recording,
            onOpen: { [weak self] in self?.openRecordingReviewForEventId(recording.eventId) },
            onDelete: { [weak self] in self?.confirmDelete(recording) }
        )
        return card
    }

    private func configureWindow() {
        guard let contentView = window?.contentView else { return }
        contentView.wantsLayer = true
        contentView.layer?.backgroundColor = WorkbenchDesignTokens.Color.canvas.cgColor

        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .width
        root.spacing = 18
        root.edgeInsets = NSEdgeInsets(top: 30, left: 32, bottom: 28, right: 32)
        root.translatesAutoresizingMaskIntoConstraints = false
        contentView.addSubview(root)
        NSLayoutConstraint.activate([
            root.leadingAnchor.constraint(equalTo: contentView.leadingAnchor),
            root.trailingAnchor.constraint(equalTo: contentView.trailingAnchor),
            root.topAnchor.constraint(equalTo: contentView.topAnchor),
            root.bottomAnchor.constraint(equalTo: contentView.bottomAnchor),
        ])

        root.addArrangedSubview(makeHeader())
        root.addArrangedSubview(makeStatusRow())
        root.addArrangedSubview(makeLibrary())

        emptyView.onRecord = { [weak self] in self?.coordinator?.startRegionRecordingPreparation() }
        updateState()
    }

    private func makeHeader() -> NSView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 14

        let icon = NSImageView(image: WorkRecorderGlyph.makeBrandImage(size: CGSize(width: 52, height: 52)))
        icon.imageScaling = .scaleProportionallyUpOrDown
        icon.imageAlignment = .alignCenter
        icon.widthAnchor.constraint(equalToConstant: 52).isActive = true
        icon.heightAnchor.constraint(equalToConstant: 52).isActive = true
        row.addArrangedSubview(icon)

        let copy = NSStackView()
        copy.orientation = .vertical
        copy.alignment = .leading
        copy.spacing = 3
        copy.addArrangedSubview(makeLabel("WorkRecorder", size: 23, weight: .bold, color: WorkbenchDesignTokens.Color.primaryText))
        copy.addArrangedSubview(makeLabel("录制中心", size: 12, weight: .semibold, color: WorkbenchDesignTokens.Color.brandBlueStrong))
        copy.setContentHuggingPriority(.required, for: .horizontal)
        copy.setContentCompressionResistancePriority(.required, for: .horizontal)
        row.addArrangedSubview(copy)

        let spacer = NSView()
        spacer.setContentHuggingPriority(.defaultLow, for: .horizontal)
        spacer.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        row.addArrangedSubview(spacer)

        searchField.placeholderString = "搜索录制"
        searchField.target = self
        searchField.action = #selector(searchChanged)
        let searchBox = WorkbenchSearchBox(searchField: searchField)
        searchBox.setContentHuggingPriority(.defaultLow, for: .horizontal)
        searchBox.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        searchBox.widthAnchor.constraint(greaterThanOrEqualToConstant: 160).isActive = true
        let preferredSearchWidth = searchBox.widthAnchor.constraint(equalToConstant: 320)
        preferredSearchWidth.priority = .defaultHigh
        preferredSearchWidth.isActive = true
        searchBox.heightAnchor.constraint(equalToConstant: 42).isActive = true
        row.addArrangedSubview(searchBox)

        let permissionButton = WorkbenchButton(
            title: "权限",
            variant: .secondary,
            symbolName: "checkmark.shield",
            target: self,
            action: #selector(showPermissionGuideButtonPressed)
        )
        permissionButton.applyCompactMinimumWidth()
        permissionButton.setContentHuggingPriority(.required, for: .horizontal)
        permissionButton.setContentCompressionResistancePriority(.required, for: .horizontal)
        row.addArrangedSubview(permissionButton)

        let recordButton = WorkbenchButton(
            title: "开始录制",
            variant: .primary,
            symbolName: "record.circle",
            target: self,
            action: #selector(startRecording)
        )
        recordButton.applyActionRowMinimumWidth()
        recordButton.keyEquivalent = "r"
        recordButton.keyEquivalentModifierMask = [.control, .option, .command]
        recordButton.setContentHuggingPriority(.required, for: .horizontal)
        recordButton.setContentCompressionResistancePriority(.required, for: .horizontal)
        row.addArrangedSubview(recordButton)
        return row
    }

    private func makeStatusRow() -> NSView {
        let row = NSStackView()
        row.orientation = .horizontal
        row.alignment = .centerY
        row.spacing = 10
        countLabel.font = NSFont.systemFont(ofSize: 12, weight: .semibold)
        countLabel.textColor = WorkbenchDesignTokens.Color.secondaryText
        row.addArrangedSubview(countLabel)
        row.addArrangedSubview(NSView())
        statusLabel.font = NSFont.systemFont(ofSize: 11.5, weight: .medium)
        statusLabel.textColor = WorkbenchDesignTokens.Color.warning
        statusLabel.lineBreakMode = .byTruncatingTail
        row.addArrangedSubview(statusLabel)
        progress.style = .spinning
        progress.controlSize = .small
        row.addArrangedSubview(progress)
        return row
    }

    private func makeLibrary() -> NSView {
        let container = NSView()
        container.wantsLayer = true
        container.layer?.backgroundColor = WorkbenchDesignTokens.Color.panelSoft.withAlphaComponent(0.52).cgColor
        container.layer?.cornerRadius = 24
        container.layer?.borderWidth = 1
        container.layer?.borderColor = WorkbenchDesignTokens.Color.brandSky.withAlphaComponent(0.72).cgColor

        let layout = RecordingCenterAdaptiveLayout(
            inset: Self.libraryInset,
            spacing: Self.itemSpacing,
            minimumTwoColumnCardWidth: Self.minimumTwoColumnCardWidth,
            itemHeight: 214
        )
        collectionView.collectionViewLayout = layout
        collectionView.dataSource = self
        collectionView.delegate = self
        collectionView.isSelectable = false
        collectionView.backgroundColors = [.clear]
        collectionView.register(RecordingCenterCardItem.self, forItemWithIdentifier: Self.itemIdentifier)

        let scroll = NSScrollView()
        scroll.drawsBackground = false
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.documentView = collectionView
        collectionView.frame = scroll.contentView.bounds
        collectionView.autoresizingMask = [.width]
        scroll.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(scroll)

        emptyView.translatesAutoresizingMaskIntoConstraints = false
        container.addSubview(emptyView)
        NSLayoutConstraint.activate([
            scroll.leadingAnchor.constraint(equalTo: container.leadingAnchor),
            scroll.trailingAnchor.constraint(equalTo: container.trailingAnchor),
            scroll.topAnchor.constraint(equalTo: container.topAnchor),
            scroll.bottomAnchor.constraint(equalTo: container.bottomAnchor),
            emptyView.centerXAnchor.constraint(equalTo: container.centerXAnchor),
            emptyView.centerYAnchor.constraint(equalTo: container.centerYAnchor),
            emptyView.widthAnchor.constraint(lessThanOrEqualTo: container.widthAnchor, constant: -72),
        ])
        container.heightAnchor.constraint(greaterThanOrEqualToConstant: 360).isActive = true
        return container
    }

    private func refresh() {
        refreshTask?.cancel()
        isLoading = true
        statusLabel.stringValue = ""
        updateState()
        let query = searchField.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        refreshTask = Task { [weak self] in
            guard let self else { return }
            await daemon.startIfNeeded()
            do {
                let result = try await client.recordingCaptures(limit: 5_000, query: query)
                guard !Task.isCancelled else { return }
                recordings = result
            } catch {
                guard !Task.isCancelled else { return }
                statusLabel.stringValue = error.localizedDescription
                logStore.append("录制中心刷新失败：\(error.localizedDescription)")
            }
            isLoading = false
            updateState()
        }
    }

    private func showPermissionGuideAutomaticallyIfNeeded() {
        guard !didEvaluateAutomaticPermissionGuide else { return }
        didEvaluateAutomaticPermissionGuide = true
        let defaults = UserDefaults.standard
        guard WorkRecorderPermissionGuidePolicy.shouldPresentAutomatically(
            hasSeenGuide: defaults.bool(forKey: WorkRecorderPermissionGuidePolicy.seenKey)
        ) else {
            return
        }
        defaults.set(true, forKey: WorkRecorderPermissionGuidePolicy.seenKey)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
            self?.showPermissionGuide()
        }
    }

    private func updateState() {
        if isLoading {
            progress.startAnimation(nil)
        } else {
            progress.stopAnimation(nil)
        }
        progress.isHidden = !isLoading
        countLabel.stringValue = recordings.isEmpty ? "" : "\(recordings.count) 段录制"
        emptyView.isHidden = isLoading || !recordings.isEmpty
        collectionView.isHidden = recordings.isEmpty
        collectionView.enclosingScrollView?.layoutSubtreeIfNeeded()
        collectionView.reloadData()
        collectionView.collectionViewLayout?.invalidateLayout()
    }

    private func confirmDelete(_ recording: SearchCardView) {
        let alert = NSAlert()
        alert.messageText = "Delete this recording?"
        alert.informativeText = "This recording cannot be recovered from the Recording Center after deletion."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Cancel")
        alert.addButton(withTitle: "Delete")
        guard alert.runModal() == .alertSecondButtonReturn else { return }
        Task { [weak self] in
            guard let self else { return }
            do {
                try await client.deleteEvent(eventId: recording.eventId)
                recordings.removeAll { $0.eventId == recording.eventId }
                updateState()
            } catch {
                statusLabel.stringValue = error.localizedDescription
                logStore.append("删除录制失败：\(error.localizedDescription)")
            }
        }
    }

    @objc private func startRecording() {
        coordinator?.startRegionRecordingPreparation()
    }

    @objc private func showPermissionGuideButtonPressed() {
        showPermissionGuide()
    }

    @objc private func searchChanged() {
        searchTask?.cancel()
        searchTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 250_000_000)
            guard !Task.isCancelled else { return }
            self?.refresh()
        }
    }
}

private final class RecordingCenterAdaptiveLayout: NSCollectionViewLayout {
    private let inset: CGFloat
    private let spacing: CGFloat
    private let minimumTwoColumnCardWidth: CGFloat
    private let itemHeight: CGFloat
    private var cachedAttributes: [IndexPath: NSCollectionViewLayoutAttributes] = [:]
    private var cachedContentSize = NSSize.zero

    init(inset: CGFloat, spacing: CGFloat, minimumTwoColumnCardWidth: CGFloat, itemHeight: CGFloat) {
        self.inset = inset
        self.spacing = spacing
        self.minimumTwoColumnCardWidth = minimumTwoColumnCardWidth
        self.itemHeight = itemHeight
        super.init()
    }

    required init?(coder: NSCoder) {
        nil
    }

    override func prepare() {
        super.prepare()
        guard let collectionView else {
            cachedAttributes = [:]
            cachedContentSize = .zero
            return
        }

        let viewport = collectionView.enclosingScrollView?.contentView.bounds.size
            ?? collectionView.bounds.size
        let width = max(1, floor(viewport.width))
        let usableWidth = max(0, width - inset * 2)
        let columns = usableWidth >= minimumTwoColumnCardWidth * 2 + spacing ? 2 : 1
        let itemWidth = max(
            320,
            floor((usableWidth - CGFloat(columns - 1) * spacing) / CGFloat(columns))
        )
        let itemCount = collectionView.numberOfItems(inSection: 0)

        var attributes: [IndexPath: NSCollectionViewLayoutAttributes] = [:]
        for item in 0..<itemCount {
            let indexPath = IndexPath(item: item, section: 0)
            let column = item % columns
            let row = item / columns
            let frame = NSRect(
                x: inset + CGFloat(column) * (itemWidth + spacing),
                y: inset + CGFloat(row) * (itemHeight + spacing),
                width: itemWidth,
                height: itemHeight
            )
            let itemAttributes = NSCollectionViewLayoutAttributes(forItemWith: indexPath)
            itemAttributes.frame = frame
            attributes[indexPath] = itemAttributes
        }

        let rowCount = itemCount == 0 ? 0 : (itemCount + columns - 1) / columns
        let contentHeight = inset * 2
            + CGFloat(rowCount) * itemHeight
            + CGFloat(max(0, rowCount - 1)) * spacing
        cachedAttributes = attributes
        cachedContentSize = NSSize(width: width, height: max(viewport.height, contentHeight))
    }

    override var collectionViewContentSize: NSSize {
        cachedContentSize
    }

    override func layoutAttributesForElements(in rect: NSRect) -> [NSCollectionViewLayoutAttributes] {
        cachedAttributes.values.filter { $0.frame.intersects(rect) }
    }

    override func layoutAttributesForItem(at indexPath: IndexPath) -> NSCollectionViewLayoutAttributes? {
        cachedAttributes[indexPath]
    }

    override func shouldInvalidateLayout(forBoundsChange newBounds: NSRect) -> Bool {
        guard let collectionView else { return true }
        return abs(newBounds.width - collectionView.bounds.width) > 0.5
    }
}

private final class RecordingCenterCollectionView: NSCollectionView {
    private var lastLayoutWidth: CGFloat = 0

    override func layout() {
        super.layout()
        let currentWidth = bounds.width
        guard abs(currentWidth - lastLayoutWidth) > 0.5 else { return }
        lastLayoutWidth = currentWidth
        collectionViewLayout?.invalidateLayout()
    }
}

@MainActor
private final class RecordingCenterCardItem: NSCollectionViewItem {
    private let titleLabel = NSTextField(labelWithString: "")
    private let metaLabel = NSTextField(labelWithString: "")
    private let noteLabel = NSTextField(labelWithString: "")
    private lazy var openButton = WorkbenchButton(
        title: "打开复盘",
        variant: .secondary,
        symbolName: "play.fill",
        target: self,
        action: #selector(openPressed)
    )
    private let deleteButton = NSButton(title: "", target: nil, action: nil)
    private var onOpen: (() -> Void)?
    private var onDelete: (() -> Void)?

    override func loadView() {
        let card = NSView()
        card.wantsLayer = true
        card.layer?.backgroundColor = WorkbenchDesignTokens.Color.panelElevated.cgColor
        card.layer?.cornerRadius = 20
        card.layer?.borderWidth = 1
        card.layer?.borderColor = WorkbenchDesignTokens.Color.brandSky.withAlphaComponent(0.78).cgColor
        card.layer?.shadowColor = WorkbenchDesignTokens.Color.brandBlueStrong.cgColor
        card.layer?.shadowOpacity = 0.10
        card.layer?.shadowRadius = 16
        card.layer?.shadowOffset = CGSize(width: 0, height: -6)
        view = card

        let preview = RecordingCenterPreviewView()
        preview.translatesAutoresizingMaskIntoConstraints = false
        card.addSubview(preview)

        titleLabel.font = NSFont.systemFont(ofSize: 15.5, weight: .semibold)
        titleLabel.textColor = WorkbenchDesignTokens.Color.primaryText
        titleLabel.lineBreakMode = .byTruncatingTail
        metaLabel.font = NSFont.systemFont(ofSize: 11.2, weight: .medium)
        metaLabel.textColor = WorkbenchDesignTokens.Color.muted
        metaLabel.lineBreakMode = .byTruncatingTail
        noteLabel.font = NSFont.systemFont(ofSize: 12, weight: .regular)
        noteLabel.textColor = WorkbenchDesignTokens.Color.secondaryText
        noteLabel.maximumNumberOfLines = 2
        noteLabel.lineBreakMode = .byTruncatingTail

        let copy = NSStackView(views: [titleLabel, metaLabel, noteLabel])
        copy.orientation = .vertical
        copy.alignment = .leading
        copy.spacing = 5
        copy.translatesAutoresizingMaskIntoConstraints = false
        card.addSubview(copy)

        openButton.applyCompactMinimumWidth()
        openButton.translatesAutoresizingMaskIntoConstraints = false
        card.addSubview(openButton)
        deleteButton.isBordered = false
        deleteButton.image = NSImage(systemSymbolName: "trash", accessibilityDescription: "删除录制")
        deleteButton.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 12, weight: .semibold)
        deleteButton.contentTintColor = WorkbenchDesignTokens.Color.recordingRedStrong.withAlphaComponent(0.82)
        deleteButton.toolTip = "删除录制"
        deleteButton.target = self
        deleteButton.action = #selector(deletePressed)
        deleteButton.translatesAutoresizingMaskIntoConstraints = false
        card.addSubview(deleteButton)

        NSLayoutConstraint.activate([
            preview.leadingAnchor.constraint(equalTo: card.leadingAnchor, constant: 14),
            preview.topAnchor.constraint(equalTo: card.topAnchor, constant: 14),
            preview.bottomAnchor.constraint(equalTo: card.bottomAnchor, constant: -14),
            preview.widthAnchor.constraint(equalToConstant: 132),
            copy.leadingAnchor.constraint(equalTo: preview.trailingAnchor, constant: 15),
            copy.trailingAnchor.constraint(equalTo: card.trailingAnchor, constant: -16),
            copy.topAnchor.constraint(equalTo: card.topAnchor, constant: 19),
            copy.bottomAnchor.constraint(lessThanOrEqualTo: openButton.topAnchor, constant: -10),
            openButton.leadingAnchor.constraint(equalTo: copy.leadingAnchor),
            openButton.bottomAnchor.constraint(equalTo: card.bottomAnchor, constant: -16),
            deleteButton.trailingAnchor.constraint(equalTo: card.trailingAnchor, constant: -15),
            deleteButton.centerYAnchor.constraint(equalTo: openButton.centerYAnchor),
            deleteButton.widthAnchor.constraint(equalToConstant: 30),
            deleteButton.heightAnchor.constraint(equalToConstant: 30),
        ])
    }

    func configure(recording: SearchCardView, onOpen: @escaping () -> Void, onDelete: @escaping () -> Void) {
        self.onOpen = onOpen
        self.onDelete = onDelete
        let rawNote = recording.userNote?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let sourceTitle = recording.source.title.trimmingCharacters(in: .whitespacesAndNewlines)
        let meaningfulNote = rawNote.isEmpty || looksLikeIdentifier(rawNote) ? nil : rawNote
        let meaningfulSourceTitle = sourceTitle.isEmpty || looksLikeIdentifier(sourceTitle) ? nil : sourceTitle
        let appName = recording.source.appName?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        titleLabel.stringValue = meaningfulNote ?? meaningfulSourceTitle ?? (appName.isEmpty ? "未命名录制" : "\(appName) 录制")
        metaLabel.stringValue = [appName, formattedRecordingDate(recording.capturedAt)]
            .filter { !$0.isEmpty }
            .joined(separator: " · ")
        noteLabel.stringValue = meaningfulNote == nil ? "回放视频与操作时间线" : (meaningfulSourceTitle ?? "回放视频与操作时间线")
        view.setAccessibilityLabel("打开录制：\(titleLabel.stringValue)")
    }

    @objc private func openPressed() { onOpen?() }
    @objc private func deletePressed() { onDelete?() }
}

private final class RecordingCenterPreviewView: NSView {
    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        wantsLayer = true
        layer?.cornerRadius = 14
        layer?.backgroundColor = WorkbenchDesignTokens.Color.brandInk.cgColor
        layer?.borderColor = WorkbenchDesignTokens.Color.brandBlue.withAlphaComponent(0.34).cgColor
        layer?.borderWidth = 1

        let playBackground = NSView()
        playBackground.wantsLayer = true
        playBackground.layer?.backgroundColor = WorkbenchDesignTokens.Color.brandBlue.cgColor
        playBackground.layer?.cornerRadius = 24
        playBackground.translatesAutoresizingMaskIntoConstraints = false
        addSubview(playBackground)

        let icon = NSImageView(image: NSImage(systemSymbolName: "play.fill", accessibilityDescription: "录制") ?? NSImage())
        icon.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 18, weight: .bold)
        icon.contentTintColor = .white
        icon.translatesAutoresizingMaskIntoConstraints = false
        playBackground.addSubview(icon)

        let recordingDot = NSView()
        recordingDot.wantsLayer = true
        recordingDot.layer?.backgroundColor = WorkbenchDesignTokens.Color.recordingRed.cgColor
        recordingDot.layer?.cornerRadius = 4
        recordingDot.translatesAutoresizingMaskIntoConstraints = false
        addSubview(recordingDot)

        let recordingLabel = makeLabel("REC", size: 9.5, weight: .bold, color: NSColor.white.withAlphaComponent(0.82))
        recordingLabel.translatesAutoresizingMaskIntoConstraints = false
        addSubview(recordingLabel)
        NSLayoutConstraint.activate([
            playBackground.centerXAnchor.constraint(equalTo: centerXAnchor),
            playBackground.centerYAnchor.constraint(equalTo: centerYAnchor),
            playBackground.widthAnchor.constraint(equalToConstant: 48),
            playBackground.heightAnchor.constraint(equalToConstant: 48),
            icon.centerXAnchor.constraint(equalTo: playBackground.centerXAnchor, constant: 1),
            icon.centerYAnchor.constraint(equalTo: playBackground.centerYAnchor),
            icon.widthAnchor.constraint(equalToConstant: 19),
            icon.heightAnchor.constraint(equalToConstant: 19),
            recordingDot.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 12),
            recordingDot.topAnchor.constraint(equalTo: topAnchor, constant: 12),
            recordingDot.widthAnchor.constraint(equalToConstant: 8),
            recordingDot.heightAnchor.constraint(equalToConstant: 8),
            recordingLabel.leadingAnchor.constraint(equalTo: recordingDot.trailingAnchor, constant: 5),
            recordingLabel.centerYAnchor.constraint(equalTo: recordingDot.centerYAnchor),
        ])
    }

    required init?(coder: NSCoder) { nil }
}

@MainActor
private final class RecordingCenterEmptyView: NSView {
    var onRecord: (() -> Void)?

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        let title = makeLabel("开始第一段录制", size: 22, weight: .semibold, color: WorkbenchDesignTokens.Color.primaryText)
        let detail = makeLabel("框选工作区域，完成后可回放、备注并保存。", size: 12.5, weight: .regular, color: WorkbenchDesignTokens.Color.secondaryText)
        detail.alignment = .center
        let button = WorkbenchButton(
            title: "开始录制",
            variant: .primary,
            symbolName: "record.circle",
            target: self,
            action: #selector(recordPressed)
        )
        button.applyActionRowMinimumWidth()
        let hint = makeLabel("⌃⌥⌘R", size: 11.5, weight: .medium, color: WorkbenchDesignTokens.Color.muted)
        let stack = NSStackView(views: [title, detail, button, hint])
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false
        addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: trailingAnchor),
            stack.topAnchor.constraint(equalTo: topAnchor),
            stack.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])
    }

    required init?(coder: NSCoder) { nil }
    @objc private func recordPressed() { onRecord?() }
}

@MainActor
private func makeLabel(_ text: String, size: CGFloat, weight: NSFont.Weight, color: NSColor) -> NSTextField {
    let label = NSTextField(labelWithString: WorkRecorderLocalization.text(text))
    label.font = NSFont.systemFont(ofSize: size, weight: weight)
    label.textColor = color
    return label
}

private func looksLikeIdentifier(_ value: String) -> Bool {
    if UUID(uuidString: value) != nil {
        return true
    }
    let compact = value.replacingOccurrences(of: "-", with: "")
    return compact.count >= 28 && compact.allSatisfy { $0.isHexDigit }
}

private func formattedRecordingDate(_ value: String) -> String {
    let iso = ISO8601DateFormatter()
    iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    let date = iso.date(from: value) ?? ISO8601DateFormatter().date(from: value)
    guard let date else { return value }
    let formatter = DateFormatter()
    if WorkRecorderLocalization.isEnglishVariant {
        formatter.locale = Locale(identifier: "en_US")
        formatter.dateFormat = "MMM d, HH:mm"
    } else {
        formatter.locale = Locale(identifier: "zh_CN")
        formatter.dateFormat = "M月d日 HH:mm"
    }
    return formatter.string(from: date)
}
