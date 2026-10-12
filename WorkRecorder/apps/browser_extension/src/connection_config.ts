export const DEFAULT_DAEMON_URL = "http://127.0.0.1:8765";
export const DEFAULT_PROVIDER_REGISTRATION_SECRET = "dev-provider-secret";
export const PROVIDER_SECRET_STORAGE_KEY = "workrecorderProviderRegistrationSecret";
export const DAEMON_URL_STORAGE_KEY = "workrecorderDaemonUrl";
export const LOCAL_CONFIG_FILE = "workrecorder-extension-config.json";

export type RawConnectionConfig = {
  daemonUrl?: unknown;
  providerRegistrationSecret?: unknown;
};

export type ResolvedConnectionConfig = {
  daemonUrl: string;
  providerRegistrationSecret: string;
  staleStorageKeys: string[];
};

export class ConnectionConfigMemo {
  private current: Promise<ResolvedConnectionConfig> | null = null;

  constructor(private readonly loader: () => Promise<ResolvedConnectionConfig>) {}

  load(): Promise<ResolvedConnectionConfig> {
    this.current ??= this.loader();
    return this.current;
  }

  invalidate(): void {
    this.current = null;
  }
}

export function resolveConnectionConfig(
  materialized: RawConnectionConfig,
  stored: RawConnectionConfig
): ResolvedConnectionConfig {
  const materializedDaemonUrl = validDaemonURL(materialized.daemonUrl);
  const storedDaemonUrl = validDaemonURL(stored.daemonUrl);
  const materializedSecret = validProviderSecret(materialized.providerRegistrationSecret);
  const storedSecret = validProviderSecret(stored.providerRegistrationSecret);
  const staleStorageKeys: string[] = [];

  if (materializedDaemonUrl && storedDaemonUrl && materializedDaemonUrl !== storedDaemonUrl) {
    staleStorageKeys.push(DAEMON_URL_STORAGE_KEY);
  }
  if (materializedSecret && storedSecret && materializedSecret !== storedSecret) {
    staleStorageKeys.push(PROVIDER_SECRET_STORAGE_KEY);
  }

  return {
    daemonUrl: materializedDaemonUrl ?? storedDaemonUrl ?? DEFAULT_DAEMON_URL,
    providerRegistrationSecret: materializedSecret ?? storedSecret ?? DEFAULT_PROVIDER_REGISTRATION_SECRET,
    staleStorageKeys
  };
}

export function connectionConfigChanged(
  active: ResolvedConnectionConfig | null,
  latest: ResolvedConnectionConfig
): boolean {
  return Boolean(
    active &&
      (latest.daemonUrl !== active.daemonUrl ||
        latest.providerRegistrationSecret !== active.providerRegistrationSecret)
  );
}

function validDaemonURL(value: unknown): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  try {
    const url = new URL(value);
    if ((url.protocol === "http:" || url.protocol === "https:") && ["127.0.0.1", "localhost"].includes(url.hostname)) {
      return url.origin;
    }
  } catch {
    return undefined;
  }
  return undefined;
}

function validProviderSecret(value: unknown): string | undefined {
  if (typeof value === "string" && value.length >= 8) {
    return value;
  }
  return undefined;
}
