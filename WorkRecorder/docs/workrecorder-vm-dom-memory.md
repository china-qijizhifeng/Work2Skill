# WorkRecorder VM DOM Hit Memory

This note records the current working understanding of WorkRecorder active capture
with VM Firefox DOM hit probing. It is intentionally practical: commands,
symptoms, causes, and known-good checks.

## Goal

WorkRecorder should no longer export host macOS accessibility trees for the VM
browser. For trusted local pointer clicks, it should now prefer the guest-side
event-watch HTTP service:

```text
WorkRecorder click -> local 127.0.0.1:7072/events -> SSH tunnel -> guest event-watch
  -> recent focus/click event with DOM element
```

The older direct lookup path is still useful as a fallback/debug endpoint:

```text
WorkRecorder click -> local 127.0.0.1:7071/dom_at_point -> SSH tunnel -> guest dom-daemon
  -> Firefox current tab DOM at x/y
```

The exported files should include per-keyframe `vm_a11y.json` and
`vm_a11y.jsonl` sidecars. In this context `vm_a11y` is the legacy filename, but
the payload is now VM-side DOM/event information, not host a11y.

## Startup

Use:

```bash
bash scripts/start_workrecorder_vm_a11y.sh
```

This script is expected to:

- Ensure the base SSH path to the guest exists through host port `2222`.
- Rebuild the local `7071 -> guest:7071` and `7072 -> guest:7072` tunnels when needed.
- Export WorkRecorder env:
  - `WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_ENABLED=true`
  - `WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_SOURCE=event_watch`
  - `WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_URL=http://127.0.0.1:7072`
  - `WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_EVENTS_PATH=/events`
  - VM geometry env for coordinate mapping.
- Restart the WorkRecorder app/daemon so the daemon inherits those env vars.
- Start the daemon as an external script-managed process, then launch the app with
  `WORKRECORDER_EXTERNAL_DAEMON=1` so the app does not replace or stop that daemon.
- Re-check daemon health and VM a11y settings after the app has started. This is
  important because an app-side daemon supervisor can otherwise silently kill a
  good external daemon.

If the guest VM was rebuilt, the tunnel can disappear. Restarting the script is
the first fix.

## Must-Pass Checks Before Recording

From the Mac host:

```bash
curl -i 'http://127.0.0.1:7072/health'
curl -i 'http://127.0.0.1:7072/events?n=20'
```

Expected:

- HTTP 200.
- `/health` reports ok/count-ish fields.
- `/events` returns recent records with monotonically increasing `seq`.
- After clicking in the VM, the latest event should describe the clicked/focused control.

The older DOM-at-point debug check is:

```bash
curl -i 'http://127.0.0.1:7071/dom_at_point?x=451&y=434'
```

Expected:

- HTTP 200.
- JSON contains `hit`, `path`, `cx`, `cy`, `url`, and `title`.
- `url` should match the current Firefox foreground tab.

Bad signs:

- `Connection refused`: local 7071/7072 tunnel is not up.
- `404 {"error": "use /a11y or /health"}`: old service or wrong tunnel target.
- `400 {"error": "need x & y"}`: older daemon wanted integer coordinates; current WorkRecorder rounds x/y.
- `500 {"error": "[Errno 111] Connection refused"}`: guest dom-daemon is up, but its Marionette backend cannot connect to Firefox.
- `vm_event_watch_no_event`: 7072 is reachable, but `/events` did not publish a new event within the polling attempts.

Also verify the WorkRecorder daemon itself before recording:

```bash
curl -i 'http://127.0.0.1:8765/health'
```

The startup script now performs the stronger check automatically:

- `/health` must stay healthy before and after the app starts.
- `/v1/settings/vm-a11y-probe` must report `source=event_watch`.
- The reported URL must match the selected local event-watch port, for example
  `http://127.0.0.1:7072` or fallback `http://127.0.0.1:17072`.

## Export Health Checks

After export, inspect:

```bash
find <export_dir> -maxdepth 2 -name 'vm_a11y.json' | sort
```

Healthy export:

- `recording.json` has non-empty `vm_a11y_files`.
- Some action steps in `trajectory.json` contain `dom_hit` and `dom_hit_label`.
- `summary.md` shows labels such as `点击 listitem ...`, `点击 button ...`, or `点击 div ...`.
- `keylog.jsonl` contains keyboard press/release rows when typing happened.

Unhealthy export:

- `vm_a11y_files: []` and no per-keyframe `vm_a11y.json`: capture-time probe records were not available to export. Check the tunnel and daemon env.
- DOM labels all missing but click actions exist: likely VM DOM/event probe was disabled, unconfigured, or 7072 was down during capture.
- `source: export_live_dom_probe`: dangerous for historical exports because it samples the current Firefox page at export time. This fallback is disabled by default.

## Known Good Runs

`/Users/example/Desktop/WorkRecorder_dev/20260627T053040_546_acs_7WyD8-c5qtUGXAjh`

- DOM probe worked.
- 5 probe records, 4 hits, 0 errors.
- One null hit had `cy < 0`, meaning the click was above the web viewport.

`/Users/example/Desktop/WorkRecorder_dev/20260627T054339_359_acs_FkMrFU5vquEE6Wgx`

- DOM probe worked again after restoring the 7071 tunnel.
- `recording.json` had 10 VM DOM sidecar file entries.
- 5 action steps had `dom_hit`.
- Keylog correctly captured `apple`.

Bad run:

`/Users/example/Desktop/WorkRecorder_dev/20260627T053716_996_acs_f2w4d_eOSFfXHPsY`

- `vm_a11y_files: []`.
- No `vm_a11y.json` sidecars.
- At investigation time, `curl http://127.0.0.1:7071/dom_at_point?...` failed with connection refused, and no local 7071 listener was present.
- Conclusion: the DOM tunnel/service was unavailable for that run, not an exporter label bug.

Bad runs from the 2026-06-29 daemon lifecycle issue:

`/Users/example/Desktop/WorkRecorder_dev/20260629T070012_777_acs_epNeCGSRkHaUAW2I`

`/Users/example/Desktop/WorkRecorder_dev/20260629T070501_875_acs_FSd_dNWbeaIJ31TQ`

- `keylog.jsonl` and click actions were present, but `recording.json` had
  `vm_a11y_files: []`.
- `/tmp/workrecorder-daemon.log` showed `uvicorn.error Shutting down` during the
  recording.
- The app log then showed `failed to submit producer event` / `无法连接服务器`.
- Root cause: daemon lifetime conflict. The startup script launched a correctly
  configured daemon, but the macOS app's daemon supervisor could still treat it
  as an owned/mismatched daemon and stop or replace it. VM a11y records live in
  daemon memory, so shutdown erased them before export.
- Fix: add `WORKRECORDER_EXTERNAL_DAEMON=1` to the app runtime path. In this mode
  the app only reuses the script-managed daemon and does not start, stop, or
  replace it. The startup script now starts daemon first, verifies VM a11y config,
  starts the app, then verifies daemon/config again.

## Interpretation Rules

`hit: null` is not always a bug.

If the daemon returns coordinates like `cy < 0`, the click is above the Firefox
web content viewport, usually in the tab bar, address bar, bookmarks bar, title
bar, or other browser/VM chrome. Because we intentionally stopped exporting host
a11y, those areas do not have DOM elements.

Clicks near window edges or outside the VM display can also legitimately have no
DOM hit.

## Marionette Constraint

Firefox Marionette is effectively single-client in this setup. The guest
dom-daemon owns the Marionette session for automatic DOM hit probing. Do not run
another independent Marionette automation client at the same time unless the
daemon is changed to proxy/multiplex Marionette.

## Proxy Pitfall

For scripts that call guest or local control APIs, proxy env can break localhost:

```bash
unset http_proxy https_proxy ALL_PROXY all_proxy HTTP_PROXY HTTPS_PROXY
```

or set:

```bash
export NO_PROXY=127.0.0.1,localhost
```

The observed failure mode was host requests to `127.0.0.1:5000/execute` being
sent through `127.0.0.1:7897` and returning 502.

## Current Code Expectations

- `packages/active_capture/application/vm_a11y_probe.py`
  - Can consume `event_watch` (`/events`) or `dom_at_point` depending on config.
  - The startup script currently defaults to `event_watch` on local port 7072.
  - Event-watch records are consumed with `n=20` first, then `since_seq=<last>`.
  - Event-watch probing is serialized because seq consumption is stateful.
  - Direct `dom_at_point` remains available for fallback/debugging.
  - Stores `hit_dom`, `sample`, `alignment`, and errors.
  - Does not periodic-poll by default.

- `packages/active_capture/application/export/recording_export.py`
  - Attaches DOM hits to `actions.json`, `trajectory.json`, and `summary.md`.
  - Does not use live export fallback unless explicitly enabled.
  - Filters keyframe summary rows without media time so `summary.md` does not show `--:--.---`.
  - Uses projected media time for sidecar metadata.

- `apps/macos_capture/.../ActiveCaptureInputEventProducer.swift`
  - Input event submission retries transient daemon connection failures.
  - Event taps are listen-only and should not swallow TigerVNC input.

- `apps/macos_capture/.../WorkbenchRuntime.swift`
  - `DaemonSupervisor` supports `WORKRECORDER_EXTERNAL_DAEMON=1`.
  - In external-daemon mode, the app must not manage daemon ownership. It only
    checks health and reuses the already-running daemon.
  - This mode is required for `scripts/start_workrecorder_vm_a11y.sh`, because that
    script owns the VM a11y env and performs the stricter startup checks.

- `scripts/start_workrecorder_vm_a11y.sh`
  - Starts daemon before the app using a detached Python `subprocess.Popen(...,
    start_new_session=True)` wrapper.
  - Exports `WORKRECORDER_EXTERNAL_DAEMON=1` for the app.
  - Fails fast if daemon health or `vm-a11y-probe` settings are wrong before
    recording.
  - Performs a second daemon/config check after launching the app to catch
    app-side daemon lifecycle regressions immediately.

## Test Commands

```bash
uv run pytest tests/unit/test_recording_export.py tests/unit/test_vm_a11y_probe.py
```

Last known result after exporter/probe fixes:

```text
32 passed
```

Swift app build was previously verified with:

```bash
swift build
```

`swift test` can fail on this local toolchain because the Swift `Testing` module
is unavailable; that failure is not evidence that the app target failed.
