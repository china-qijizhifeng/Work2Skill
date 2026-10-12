import AppKit
import Foundation

extension RecordingReviewWindowController {
    @objc func loadPlaybackAction() {
        loadPlayback(autoplay: true)
    }

    @objc func togglePlaybackAction() {
        if playbackController.playbackSession == nil {
            guard let recording = currentRequest?.recording, recordingCanPlay(recording) else {
                return
            }
            loadPlayback(autoplay: true)
            return
        }
        playbackController.togglePlayback(rate: state.playbackRate)
    }

    @objc func openExternalPlaybackAction() {
        guard let request = playbackRequest() else {
            playbackController.errorMessage = "这条录制没有可播放的视频。"
            render()
            return
        }
        playbackController.openExternally(request)
        logStore.append("已请求用系统播放器打开录制视频。")
    }
}
