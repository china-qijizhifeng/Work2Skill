import Foundation
import Testing
@testable import WorkRecorderCapture

struct RuntimeCredentialTests {
    private let loaders: [(filename: String, prefix: String, load: (URL) -> String?)] = [
        ("install-secret", "workrecorder_", RuntimeConfig.loadOrCreateInstallSecret),
        ("native-capture-secret", "workrecorder_native_", RuntimeConfig.loadOrCreateNativeCaptureSecret),
        ("provider-registration-secret", "workrecorder_provider_", RuntimeConfig.loadOrCreateProviderRegistrationSecret),
    ]

    @Test func createsPersistentCredentialsWithCurrentPrefixes() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }

        for (filename, prefix, load) in loaders {
            let secret = try #require(load(root))
            #expect(secret.hasPrefix(prefix))
            #expect(load(root) == secret)
            let file = root.appendingPathComponent(filename)
            let permissions = try FileManager.default.attributesOfItem(atPath: file.path)[.posixPermissions] as? Int
            #expect(permissions == 0o600)
        }
    }

    @Test func preservesExistingCredentialsWithoutRequiringProductPrefixes() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        for (filename, _, load) in loaders {
            let existing = "saved_" + String(repeating: "a", count: 64)
            try (existing + "\n").write(to: root.appendingPathComponent(filename), atomically: true, encoding: .utf8)
            #expect(load(root) == existing)
        }
    }

    @Test func replacesInvalidSavedCredentials() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }

        for (filename, prefix, load) in loaders {
            for invalid in ["short", "__workrecorder_generate_on_first_launch__"] {
                try invalid.write(to: root.appendingPathComponent(filename), atomically: true, encoding: .utf8)
                let secret = try #require(load(root))
                #expect(secret.hasPrefix(prefix))
                #expect(load(root) == secret)
            }
        }
    }

    @Test func bundledCredentialsAcceptExistingValuesAndRejectInvalidValues() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".bundle")
        let resources = root.appendingPathComponent("Contents/Resources")
        try FileManager.default.createDirectory(at: resources, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let plist = try PropertyListSerialization.data(
            fromPropertyList: ["CFBundleIdentifier": "app.workrecorder.test." + UUID().uuidString],
            format: .xml,
            options: 0
        )
        try plist.write(to: root.appendingPathComponent("Contents/Info.plist"))
        let bundle = try #require(Bundle(url: root))
        let config = resources.appendingPathComponent("runtime-config.json")
        let existing = "saved_" + String(repeating: "b", count: 64)
        for secret in [existing, "short", "__workrecorder_generate_on_first_launch__"] {
            let data = try JSONSerialization.data(withJSONObject: [
                "install_secret": secret,
                "provider_registration_secret": secret,
            ])
            try data.write(to: config)
            let expected: String? = secret == existing ? existing : nil
            #expect(bundle.runtimeConfigInstallSecret() == expected)
            #expect(bundle.runtimeConfigProviderRegistrationSecret() == expected)
        }
    }
}
