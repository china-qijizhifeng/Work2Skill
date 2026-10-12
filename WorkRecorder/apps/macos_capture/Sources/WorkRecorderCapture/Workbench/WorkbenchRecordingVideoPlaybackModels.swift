import Foundation

struct WorkbenchRecordingVideoPlaybackView: Decodable, Equatable, Sendable {
    let sessionId: String
    let eventId: String
    let artifactId: String
    let contentType: String
    let byteSize: Int
    let playbackFilePath: String?
    let contentBase64: String?

    enum CodingKeys: String, CodingKey {
        case sessionId = "session_id"
        case eventId = "event_id"
        case artifactId = "artifact_id"
        case contentType = "content_type"
        case byteSize = "byte_size"
        case playbackFilePath = "playback_file_path"
        case contentBase64 = "content_base64"
    }

    var contentData: Data? {
        guard let contentBase64 else { return nil }
        return Data(base64Encoded: contentBase64)
    }
}
