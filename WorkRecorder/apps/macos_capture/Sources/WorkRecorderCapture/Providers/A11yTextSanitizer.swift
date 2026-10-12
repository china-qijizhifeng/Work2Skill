import Foundation

struct A11yTextSanitizer {
    func redact(_ text: String) -> String {
        var redacted = text
        redacted = redacted.replacingOccurrences(
            of: #"(?i)((?:authorization\s*:\s*)?bearer\s+)[A-Za-z0-9._~+/=-]+"#,
            with: "$1REDACTED",
            options: .regularExpression
        )
        redacted = redacted.replacingOccurrences(
            of: #"(?i)(authorization\s*:\s*)(?!bearer\s+)[^\s"'<>]{3,}"#,
            with: "$1REDACTED",
            options: .regularExpression
        )
        redacted = redacted.replacingOccurrences(
            of: #"(?i)((?:api[-_ ]?key|token|secret|password|credential|jwt|session(?:\s*id)?|csrf|xsrf)\s*[:=]\s*)[^\s"'<>]{3,}"#,
            with: "$1REDACTED",
            options: .regularExpression
        )
        redacted = redacted.replacingOccurrences(
            of: #"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9_=-]{6,}\b"#,
            with: "REDACTED",
            options: .regularExpression
        )
        redacted = redacted.replacingOccurrences(
            of: #"\bAKIA[0-9A-Z]{16}\b"#,
            with: "REDACTED",
            options: .regularExpression
        )
        redacted = redacted.replacingOccurrences(
            of: #"\b[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"#,
            with: "REDACTED",
            options: .regularExpression
        )
        return redacted
    }
}
