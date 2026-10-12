import Foundation

struct CaptureEnvironment {
    let daemonURL: URL
    let installSecret: String
    let nativeCaptureSecret: String?
    let providerRegistrationSecret: String
    let stagingDirectory: URL

    static func fromRuntimeConfig(_ config: RuntimeConfig) -> CaptureEnvironment {
        CaptureEnvironment(
            daemonURL: config.daemonURL,
            installSecret: config.installSecret,
            nativeCaptureSecret: config.nativeCaptureSecret,
            providerRegistrationSecret: config.providerRegistrationSecret,
            stagingDirectory: config.stagingDirectory
        )
    }

    static func defaultEnvironment() -> CaptureEnvironment {
        let daemon = ProcessInfo.processInfo.environment["WORKRECORDER_DAEMON_URL"] ?? "http://127.0.0.1:8765"
        let secret = ProcessInfo.processInfo.environment["WORKRECORDER_INSTALL_SECRET"] ?? "dev-install-secret"
        let nativeSecret = ProcessInfo.processInfo.environment["WORKRECORDER_NATIVE_CAPTURE_SECRET"]
        let providerSecret = ProcessInfo.processInfo.environment["WORKRECORDER_PROVIDER_REGISTRATION_SECRET"]
            ?? "dev-provider-secret"
        let home = FileManager.default.homeDirectoryForCurrentUser
        let staging = ProcessInfo.processInfo.environment["WORKRECORDER_ARTIFACT_STAGING_DIR"]
            .map { URL(fileURLWithPath: $0) }
            ?? home.appendingPathComponent(".workrecorder/staging", isDirectory: true)
        return CaptureEnvironment(
            daemonURL: URL(string: daemon) ?? URL(string: "http://127.0.0.1:8765")!,
            installSecret: secret,
            nativeCaptureSecret: nativeSecret,
            providerRegistrationSecret: providerSecret,
            stagingDirectory: staging
        )
    }
}
