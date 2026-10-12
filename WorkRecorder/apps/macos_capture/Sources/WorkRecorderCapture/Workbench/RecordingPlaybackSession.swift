import AVFoundation
import Foundation

@MainActor
final class RecordingPlaybackSession {
    let sessionId: String?
    let eventId: String?
    let artifactId: String
    let fileURL: URL
    let player: AVPlayer
    private(set) var hasStartedPlayback = false
    private(set) var lastRequestedSeekMediaTimeMs: Int?
    private(set) var currentMediaTimeMs: Int = 0
    private var timeObserver: Any?

    init(fileURL: URL, artifactId: String, sessionId: String? = nil, eventId: String? = nil) {
        self.sessionId = sessionId
        self.eventId = eventId
        self.fileURL = fileURL
        self.artifactId = artifactId
        self.player = AVPlayer(url: fileURL)
        installTimeObserver()
    }

    deinit {
        MainActor.assumeIsolated {
            removeTimeObserver()
        }
    }

    func play(rate: Float = 1.0) {
        hasStartedPlayback = true
        player.rate = rate
    }

    func seek(to mediaTimeMs: Int?) {
        guard let mediaTimeMs else { return }
        lastRequestedSeekMediaTimeMs = mediaTimeMs
        currentMediaTimeMs = max(0, mediaTimeMs)
        let seconds = Double(max(0, mediaTimeMs)) / 1000.0
        let time = CMTime(seconds: seconds, preferredTimescale: 600)
        player.seek(to: time, toleranceBefore: .zero, toleranceAfter: .zero)
    }

    func pause() {
        player.pause()
    }

    func close() {
        player.pause()
        removeTimeObserver()
        player.replaceCurrentItem(with: nil)
    }

    func matches(sessionId: String, eventId: String, artifactId: String?) -> Bool {
        self.sessionId == sessionId && self.eventId == eventId && self.artifactId == artifactId
    }

    private func installTimeObserver() {
        let interval = CMTime(seconds: 0.25, preferredTimescale: 600)
        timeObserver = player.addPeriodicTimeObserver(forInterval: interval, queue: .main) { [weak self] time in
            guard let self else { return }
            let seconds = CMTimeGetSeconds(time)
            guard seconds.isFinite, seconds >= 0 else { return }
            Task { @MainActor in
                self.currentMediaTimeMs = Int((seconds * 1000.0).rounded())
            }
        }
    }

    private func removeTimeObserver() {
        guard let timeObserver else { return }
        player.removeTimeObserver(timeObserver)
        self.timeObserver = nil
    }
}
