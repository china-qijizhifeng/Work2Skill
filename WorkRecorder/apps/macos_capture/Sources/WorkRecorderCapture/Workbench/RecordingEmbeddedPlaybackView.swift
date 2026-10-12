import AppKit
import AVFoundation
import AVKit

@MainActor
final class RecordingEmbeddedPlaybackView: NSView {
    private let playbackSession: RecordingPlaybackSession
    private let playerView: AVPlayerView
    private let statusOverlay: NSStackView
    private let posterOverlay: RecordingPlaybackPosterOverlay?
    private var rateObservation: NSKeyValueObservation?

    init(playbackSession: RecordingPlaybackSession, posterImage: NSImage?) {
        self.playbackSession = playbackSession
        self.playerView = AVPlayerView()
        self.statusOverlay = NSStackView()
        self.posterOverlay = posterImage.map(RecordingPlaybackPosterOverlay.init(image:))
        super.init(frame: .zero)
        wantsLayer = true
        layer?.cornerRadius = 18
        layer?.masksToBounds = true
        layer?.borderColor = WorkbenchDesignTokens.Color.tiffanyStrong.withAlphaComponent(0.20).cgColor
        layer?.borderWidth = 0.9
        playerView.player = playbackSession.player
        playerView.controlsStyle = .none
        playerView.videoGravity = .resizeAspect
        playerView.translatesAutoresizingMaskIntoConstraints = false
        addSubview(playerView)
        if let posterOverlay {
            posterOverlay.translatesAutoresizingMaskIntoConstraints = false
            posterOverlay.isHidden = playbackSession.hasStartedPlayback
            addSubview(posterOverlay)
        }
        configureStatusOverlay()
        addSubview(statusOverlay)
        var constraints = [
            playerView.leadingAnchor.constraint(equalTo: leadingAnchor),
            playerView.trailingAnchor.constraint(equalTo: trailingAnchor),
            playerView.topAnchor.constraint(equalTo: topAnchor),
            playerView.bottomAnchor.constraint(equalTo: bottomAnchor),
            statusOverlay.leadingAnchor.constraint(equalTo: leadingAnchor, constant: 16),
            statusOverlay.topAnchor.constraint(equalTo: topAnchor, constant: 16),
            statusOverlay.trailingAnchor.constraint(lessThanOrEqualTo: trailingAnchor, constant: -16),
        ]
        if let posterOverlay {
            constraints.append(contentsOf: [
                posterOverlay.centerXAnchor.constraint(equalTo: centerXAnchor),
                posterOverlay.centerYAnchor.constraint(equalTo: centerYAnchor),
                posterOverlay.widthAnchor.constraint(lessThanOrEqualTo: widthAnchor, multiplier: 0.72),
                posterOverlay.heightAnchor.constraint(lessThanOrEqualTo: heightAnchor, multiplier: 0.68),
            ])
        }
        NSLayoutConstraint.activate(constraints)
        observePlaybackRate()
        setAccessibilityRole(.group)
        setAccessibilityLabel("录制视频内嵌播放器")
    }

    required init?(coder: NSCoder) {
        nil
    }

    private func observePlaybackRate() {
        rateObservation = playbackSession.player.observe(\.rate, options: [.initial, .new]) { [weak self] player, _ in
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.posterOverlay?.isHidden = self.playbackSession.hasStartedPlayback || player.rate != 0
            }
        }
    }

    private func configureStatusOverlay() {
        statusOverlay.orientation = .horizontal
        statusOverlay.alignment = .centerY
        statusOverlay.spacing = 7
        statusOverlay.edgeInsets = NSEdgeInsets(top: 7, left: 10, bottom: 7, right: 10)
        statusOverlay.translatesAutoresizingMaskIntoConstraints = false
        statusOverlay.wantsLayer = true
        statusOverlay.layer?.backgroundColor = NSColor.black.withAlphaComponent(0.34).cgColor
        statusOverlay.layer?.borderColor = NSColor.white.withAlphaComponent(0.14).cgColor
        statusOverlay.layer?.borderWidth = 0.7
        statusOverlay.layer?.cornerRadius = 14

        if let symbol = NSImage(systemSymbolName: "play.display", accessibilityDescription: nil) {
            let icon = NSImageView(image: symbol)
            icon.symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 11, weight: .semibold)
            icon.contentTintColor = NSColor.white.withAlphaComponent(0.78)
            icon.widthAnchor.constraint(equalToConstant: 14).isActive = true
            icon.heightAnchor.constraint(equalToConstant: 14).isActive = true
            statusOverlay.addArrangedSubview(icon)
        }

        let copy = NSTextField(labelWithString: "视频已载入 · Space 播放")
        copy.font = NSFont.systemFont(ofSize: 11.0, weight: .semibold)
        copy.textColor = NSColor.white.withAlphaComponent(0.78)
        copy.maximumNumberOfLines = 1
        copy.lineBreakMode = .byTruncatingTail
        statusOverlay.addArrangedSubview(copy)
    }
}

@MainActor
private final class RecordingPlaybackPosterOverlay: NSView {
    private let image: NSImage

    init(image: NSImage) {
        self.image = image
        super.init(frame: .zero)
        wantsLayer = true
        layer?.cornerRadius = 18
        layer?.masksToBounds = true
        layer?.backgroundColor = NSColor.white.withAlphaComponent(0.12).cgColor
        layer?.borderColor = NSColor.white.withAlphaComponent(0.18).cgColor
        layer?.borderWidth = 0.8
        setAccessibilityRole(.image)
        setAccessibilityLabel("录制视频待播放预览")
    }

    required init?(coder: NSCoder) {
        nil
    }

    override var intrinsicContentSize: NSSize {
        NSSize(width: 420, height: 260)
    }

    override func draw(_ dirtyRect: NSRect) {
        super.draw(dirtyRect)
        let rect = bounds
        let path = NSBezierPath(roundedRect: rect, xRadius: 18, yRadius: 18)
        NSGraphicsContext.saveGraphicsState()
        path.addClip()
        NSColor(calibratedRed: 0.92, green: 0.98, blue: 0.98, alpha: 0.92).setFill()
        rect.fill()
        image.drawWorkbenchAspectFit(in: rect.insetBy(dx: 14, dy: 36))
        drawFooter(in: rect)
        NSGraphicsContext.restoreGraphicsState()
    }

    private func drawFooter(in rect: NSRect) {
        let footer = NSRect(x: rect.minX, y: rect.minY, width: rect.width, height: 34)
        NSColor.white.withAlphaComponent(0.82).setFill()
        footer.fill()
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.systemFont(ofSize: 11.2, weight: .semibold),
            .foregroundColor: WorkbenchDesignTokens.Color.primaryText.withAlphaComponent(0.78),
        ]
        let text = WorkRecorderLocalization.text("待播放预览 · 按 Space 开始")
        let width = (text as NSString).size(withAttributes: attrs).width
        text.draw(
            in: NSRect(x: footer.midX - width / 2, y: footer.midY - 7.5, width: width + 1, height: 16),
            withAttributes: attrs
        )
    }
}
