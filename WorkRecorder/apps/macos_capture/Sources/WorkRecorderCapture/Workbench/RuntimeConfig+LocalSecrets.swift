import Foundation

extension RuntimeConfig {
    static let generatedSecretPlaceholder = "__workrecorder_generate_on_first_launch__"

    static func loadOrCreateInstallSecret(in appDataRoot: URL) -> String? {
        loadOrCreateSecret(
            filename: "install-secret",
            prefix: "workrecorder_",
            minLength: 32,
            appDataRoot: appDataRoot
        )
    }

    static func loadOrCreateNativeCaptureSecret(in appDataRoot: URL) -> String? {
        loadOrCreateSecret(
            filename: "native-capture-secret",
            prefix: "workrecorder_native_",
            minLength: 40,
            appDataRoot: appDataRoot
        )
    }

    static func loadOrCreateProviderRegistrationSecret(in appDataRoot: URL) -> String? {
        loadOrCreateSecret(
            filename: "provider-registration-secret",
            prefix: "workrecorder_provider_",
            minLength: 42,
            appDataRoot: appDataRoot
        )
    }

    static func loadFeishuConfig(from appDataRoot: URL) -> [String: String] {
        let url = appDataRoot.appendingPathComponent("feishu-config.json")
        guard let data = try? Data(contentsOf: url),
              let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return [:]
        }
        return payload.compactMapValues { value in
            guard let text = value as? String, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                return nil
            }
            return text
        }
    }

    private static func loadOrCreateSecret(
        filename: String,
        prefix: String,
        minLength: Int,
        appDataRoot: URL
    ) -> String? {
        let url = appDataRoot.appendingPathComponent(filename)
        if let secret = try? String(contentsOf: url, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines),
            secret != generatedSecretPlaceholder,
            secret.count >= minLength {
            return secret
        }
        do {
            try FileManager.default.createDirectory(at: appDataRoot, withIntermediateDirectories: true)
            let secret = "\(prefix)\(UUID().uuidString.replacingOccurrences(of: "-", with: ""))\(UUID().uuidString.replacingOccurrences(of: "-", with: ""))"
            try (secret + "\n").write(to: url, atomically: true, encoding: .utf8)
            try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
            return secret
        } catch {
            return nil
        }
    }
}
