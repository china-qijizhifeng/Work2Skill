import Foundation

enum RecordingPlaybackFileStore {
    static func preparePlaybackFile(_ playback: WorkbenchRecordingVideoPlaybackView) throws -> URL {
        if let playbackFilePath = playback.playbackFilePath {
            return try copyPlaybackFile(
                sourceURL: URL(fileURLWithPath: playbackFilePath),
                artifactId: playback.artifactId,
                contentType: playback.contentType
            )
        }
        guard let data = playback.contentData else {
            throw WorkbenchClientError.invalidResponse
        }
        return try writePlaybackFile(
            data: data,
            artifactId: playback.artifactId,
            contentType: playback.contentType
        )
    }

    static func writePlaybackFile(
        data: Data,
        artifactId: String,
        contentType: String?
    ) throws -> URL {
        let fileURL = try temporaryURL(artifactId: artifactId, contentType: contentType)
        do {
            try data.write(to: fileURL, options: .atomic)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: fileURL.path)
            return fileURL
        } catch {
            try? FileManager.default.removeItem(at: fileURL)
            throw error
        }
    }

    static func copyPlaybackFile(
        sourceURL: URL,
        artifactId: String,
        contentType: String?
    ) throws -> URL {
        guard sourceURL.isFileURL else {
            throw WorkbenchClientError.invalidResponse
        }
        let fileURL = try temporaryURL(artifactId: artifactId, contentType: contentType)
        do {
            try FileManager.default.copyItem(at: sourceURL, to: fileURL)
            try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: fileURL.path)
            return fileURL
        } catch {
            try? FileManager.default.removeItem(at: fileURL)
            throw error
        }
    }

    static func temporaryURL(artifactId: String, contentType: String?) throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("WorkRecorder", isDirectory: true)
            .appendingPathComponent("RecordingPlayback", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: directory.path)
        let safeArtifactId = artifactId
            .map { character in
                character.isLetter || character.isNumber || character == "_" || character == "-" ? character : "_"
            }
            .map(String.init)
            .joined()
        let suffix = (contentType ?? "").localizedCaseInsensitiveContains("quicktime") ? "mov" : "mp4"
        return directory.appendingPathComponent("\(safeArtifactId)-\(UUID().uuidString).\(suffix)")
    }
}
