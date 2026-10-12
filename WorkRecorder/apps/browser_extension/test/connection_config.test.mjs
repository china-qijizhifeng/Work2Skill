import assert from "node:assert/strict";
import test from "node:test";

import {
  ConnectionConfigMemo,
  DAEMON_URL_STORAGE_KEY,
  DEFAULT_DAEMON_URL,
  DEFAULT_PROVIDER_REGISTRATION_SECRET,
  PROVIDER_SECRET_STORAGE_KEY,
  connectionConfigChanged,
  resolveConnectionConfig
} from "../dist/connection_config.js";

test("materialized endpoint wins over stale storage daemon URL and secret", () => {
  const config = resolveConnectionConfig(
    {
      daemonUrl: "http://127.0.0.1:8767",
      providerRegistrationSecret: "provider-secret-current"
    },
    {
      daemonUrl: "http://127.0.0.1:8765",
      providerRegistrationSecret: "provider-secret-old"
    }
  );

  assert.equal(config.daemonUrl, "http://127.0.0.1:8767");
  assert.equal(config.providerRegistrationSecret, "provider-secret-current");
  assert.deepEqual(config.staleStorageKeys, [DAEMON_URL_STORAGE_KEY, PROVIDER_SECRET_STORAGE_KEY]);
});

test("stored config is a fallback when the materialized config is unavailable", () => {
  const config = resolveConnectionConfig(
    {},
    {
      daemonUrl: "http://localhost:8788/path-is-ignored",
      providerRegistrationSecret: "stored-provider-secret"
    }
  );

  assert.equal(config.daemonUrl, "http://localhost:8788");
  assert.equal(config.providerRegistrationSecret, "stored-provider-secret");
  assert.deepEqual(config.staleStorageKeys, []);
});

test("invalid or remote daemon URLs fail closed to local defaults", () => {
  const config = resolveConnectionConfig(
    { daemonUrl: "https://example.com:443", providerRegistrationSecret: "short" },
    { daemonUrl: "file:///tmp/workrecorder.sock", providerRegistrationSecret: 123 }
  );

  assert.equal(config.daemonUrl, DEFAULT_DAEMON_URL);
  assert.equal(config.providerRegistrationSecret, DEFAULT_PROVIDER_REGISTRATION_SECRET);
  assert.deepEqual(config.staleStorageKeys, []);
});

test("connection config memo reloads after invalidation", async () => {
  const values = [
    {
      daemonUrl: "http://127.0.0.1:8765",
      providerRegistrationSecret: "provider-secret-one",
      staleStorageKeys: []
    },
    {
      daemonUrl: "http://127.0.0.1:8766",
      providerRegistrationSecret: "provider-secret-two",
      staleStorageKeys: []
    }
  ];
  let calls = 0;
  const memo = new ConnectionConfigMemo(async () => values[Math.min(calls++, values.length - 1)]);

  assert.equal((await memo.load()).daemonUrl, "http://127.0.0.1:8765");
  assert.equal((await memo.load()).daemonUrl, "http://127.0.0.1:8765");
  memo.invalidate();
  assert.equal((await memo.load()).daemonUrl, "http://127.0.0.1:8766");
});

test("connected provider can detect materialized endpoint changes", () => {
  const active = {
    daemonUrl: "http://127.0.0.1:8765",
    providerRegistrationSecret: "provider-secret-one",
    staleStorageKeys: []
  };

  assert.equal(connectionConfigChanged(null, active), false);
  assert.equal(connectionConfigChanged(active, { ...active }), false);
  assert.equal(connectionConfigChanged(active, { ...active, daemonUrl: "http://127.0.0.1:8766" }), true);
  assert.equal(
    connectionConfigChanged(active, { ...active, providerRegistrationSecret: "provider-secret-two" }),
    true
  );
});
