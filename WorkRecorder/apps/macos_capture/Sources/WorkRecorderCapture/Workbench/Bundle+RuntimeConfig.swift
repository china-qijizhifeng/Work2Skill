import Foundation

extension Bundle {
    func bundledResource(named name: String) -> URL? {
        guard let url = resourceURL?.appendingPathComponent(name, isDirectory: true),
              FileManager.default.fileExists(atPath: url.path)
        else {
            return nil
        }
        return url
    }

    func runtimeConfigRepoRoot() -> URL? {
        guard let path = runtimeConfigString(key: "repo_root") else {
            return nil
        }
        if path.hasPrefix("/") {
            return URL(fileURLWithPath: path)
        }
        return resourceURL?.appendingPathComponent(path, isDirectory: true)
    }

    func runtimeConfigString(key: String) -> String? {
        runtimeConfigPayload()?[key] as? String
    }

    func runtimeConfigInstallSecret() -> String? {
        guard let secret = runtimeConfigString(key: "install_secret"),
              secret != RuntimeConfig.generatedSecretPlaceholder,
              secret.count >= 32
        else {
            return nil
        }
        return secret
    }

    func runtimeConfigProviderRegistrationSecret() -> String? {
        guard let secret = runtimeConfigString(key: "provider_registration_secret"),
              secret != RuntimeConfig.generatedSecretPlaceholder,
              secret.count >= 32
        else {
            return nil
        }
        return secret
    }

    private func runtimeConfigPayload() -> [String: Any]? {
        guard let url = resourceURL?.appendingPathComponent("runtime-config.json"),
              let data = try? Data(contentsOf: url),
              let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return nil
        }
        return payload
    }
}
