import Foundation

enum WorkbenchUserMessages {
    static func friendlyError(_ raw: String) -> String {
        let redacted = redact(raw)
        let lowered = raw.lowercased()
        if lowered.contains("install secret") {
            return "WorkRecorder 暂时无法连接本机服务，请重新打开应用。"
        }
        if lowered.contains("daemon") || lowered.contains("connection") {
            return "WorkRecorder 暂时无法连接录制服务，请稍后重试。"
        }
        return redacted
    }

    static func redact(_ raw: String) -> String {
        var value = raw
        let replacements: [(String, String)] = [
            (#"(?i)bearer\s+[A-Za-z0-9._~+/\-=]+"#, "Bearer [redacted]"),
            (#"(?i)(token|access_token|install_secret|secret)=([^&\s]+)"#, "$1=[redacted]"),
            (#"(?i)(?:/users|/private|/tmp|/var/folders)/[^\s,\"'\]\)]+"#, "[local-path]"),
        ]
        for (pattern, replacement) in replacements {
            value = value.replacingOccurrences(of: pattern, with: replacement, options: .regularExpression)
        }
        return value
    }
}
