import AppKit
import Foundation

@MainActor
protocol RecordingPlaybackLoadingClient: AnyObject {
    func recordingVideoPlayback(
        sessionId: String,
        eventId: String,
        artifactId: String,
        purpose: String
    ) async throws -> WorkbenchRecordingVideoPlaybackView
}

extension WorkbenchDaemonClient: RecordingPlaybackLoadingClient {}

@MainActor
protocol RecordingExportingClient: AnyObject {
    func recordingExport(
        sessionId: String,
        outputRoot: String,
        purpose: String,
        fallbackMode: WorkbenchRecordingExportFallbackMode
    ) async throws -> WorkbenchRecordingExportView
}

extension WorkbenchDaemonClient: RecordingExportingClient {}

struct RecordingPlaybackLoadRequest: Equatable {
    let sessionId: String
    let eventId: String
    let artifactId: String
    let purpose: String
    let initialMediaTimeMs: Int?
}

@MainActor
final class RecordingPlaybackController {
    private let client: RecordingPlaybackLoadingClient
    private let openFile: (URL) -> Bool
    private var loadGeneration = 0
    private var loadTask: Task<Void, Never>?
    private var externallyOpenAfterLoad = false
    private var playAfterLoadRate: Float?

    var playbackSession: RecordingPlaybackSession?
    var isLoading = false
    var errorMessage: String?
    var onStateChanged: (() -> Void)?

    init(
        client: RecordingPlaybackLoadingClient,
        openFile: @escaping (URL) -> Bool = { NSWorkspace.shared.open($0) }
    ) {
        self.client = client
        self.openFile = openFile
    }

    deinit {
        MainActor.assumeIsolated {
            clear(deleteFile: true)
        }
    }

    func load(
        _ request: RecordingPlaybackLoadRequest,
        openExternally: Bool = false,
        autoplayRate: Float? = nil
    ) {
        if let playbackSession,
           playbackSession.matches(
               sessionId: request.sessionId,
               eventId: request.eventId,
               artifactId: request.artifactId
           ) {
            playbackSession.seek(to: request.initialMediaTimeMs)
            if let autoplayRate {
                playbackSession.play(rate: autoplayRate)
            }
            if openExternally {
                _ = openFile(playbackSession.fileURL)
            }
            onStateChanged?()
            return
        }
        if isLoading {
            externallyOpenAfterLoad = externallyOpenAfterLoad || openExternally
            if let autoplayRate {
                playAfterLoadRate = autoplayRate
            }
            return
        }
        clear(deleteFile: true)
        loadGeneration += 1
        let generation = loadGeneration
        externallyOpenAfterLoad = openExternally
        playAfterLoadRate = autoplayRate
        isLoading = true
        errorMessage = nil
        onStateChanged?()
        loadTask = Task { @MainActor [weak self] in
            guard let self else { return }
            var preparedFileURL: URL?
            var didAdoptPreparedFile = false
            defer {
                if !didAdoptPreparedFile, let preparedFileURL {
                    try? FileManager.default.removeItem(at: preparedFileURL)
                }
            }
            do {
                let playback = try await client.recordingVideoPlayback(
                    sessionId: request.sessionId,
                    eventId: request.eventId,
                    artifactId: request.artifactId,
                    purpose: request.purpose
                )
                try Task.checkCancellation()
                let fileURL = try await Task.detached(priority: .userInitiated) {
                    try RecordingPlaybackFileStore.preparePlaybackFile(playback)
                }.value
                preparedFileURL = fileURL
                try Task.checkCancellation()
                guard self.loadGeneration == generation else {
                    return
                }
                let session = RecordingPlaybackSession(
                    fileURL: fileURL,
                    artifactId: playback.artifactId,
                    sessionId: request.sessionId,
                    eventId: request.eventId
                )
                self.playbackSession = session
                didAdoptPreparedFile = true
                session.seek(to: request.initialMediaTimeMs)
                let shouldOpenExternally = self.externallyOpenAfterLoad
                self.externallyOpenAfterLoad = false
                let autoplayRate = self.playAfterLoadRate
                self.playAfterLoadRate = nil
                self.isLoading = false
                self.loadTask = nil
                self.errorMessage = nil
                if let autoplayRate {
                    session.play(rate: autoplayRate)
                }
                if shouldOpenExternally {
                    _ = self.openFile(fileURL)
                }
                self.onStateChanged?()
            } catch {
                await MainActor.run {
                    guard self.loadGeneration == generation else { return }
                    self.isLoading = false
                    self.loadTask = nil
                    self.externallyOpenAfterLoad = false
                    self.playAfterLoadRate = nil
                    self.errorMessage = WorkbenchUserMessages.friendlyError(error.localizedDescription)
                    self.onStateChanged?()
                }
            }
        }
    }

    func openExternally(_ request: RecordingPlaybackLoadRequest) {
        if let playbackSession,
           playbackSession.matches(
               sessionId: request.sessionId,
               eventId: request.eventId,
               artifactId: request.artifactId
           ) {
            _ = openFile(playbackSession.fileURL)
            return
        }
        load(request, openExternally: true)
    }

    func togglePlayback(rate: Float = 1.0) {
        guard let playbackSession else { return }
        if playbackSession.player.rate == 0 {
            playbackSession.play(rate: rate)
        } else {
            playbackSession.pause()
        }
        onStateChanged?()
    }

    func seek(to mediaTimeMs: Int?) {
        playbackSession?.seek(to: mediaTimeMs)
        onStateChanged?()
    }

    @discardableResult
    func showFrame(at mediaTimeMs: Int?) -> Bool {
        guard let playbackSession, mediaTimeMs != nil else { return false }
        playbackSession.pause()
        playbackSession.seek(to: mediaTimeMs)
        onStateChanged?()
        return true
    }

    func pause() {
        playbackSession?.pause()
        onStateChanged?()
    }

    func currentMediaTimeMs(fallback: Int?) -> Int? {
        if let playbackSession {
            return playbackSession.currentMediaTimeMs
        }
        return fallback
    }

    func clear(deleteFile: Bool) {
        loadTask?.cancel()
        loadTask = nil
        loadGeneration += 1
        playbackSession?.close()
        if deleteFile, let fileURL = playbackSession?.fileURL {
            try? FileManager.default.removeItem(at: fileURL)
        }
        playbackSession = nil
        isLoading = false
        errorMessage = nil
        externallyOpenAfterLoad = false
        playAfterLoadRate = nil
        onStateChanged?()
    }
}
