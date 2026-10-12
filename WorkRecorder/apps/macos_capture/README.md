# WorkRecorder macOS Recording App

[English product guide](../../README.md) | [中文产品说明](../../README.zh-CN.md)

Native macOS app for recording human workflows, reviewing sessions, and exporting operation evidence.

## User Workflow

1. Press `⌃⌥⌘R` (Control + Option + Command + R), or choose **Start recording** in the menu bar.
2. Select the recording region and confirm the recording.
3. Perform the workflow; use the recording controls to pause, resume, or finish.
4. Open the recording center to review the session and export it to a folder.

The app exposes region recording as its user entry point. Keyframe images are generated internally during recording as operation evidence.

## Evidence Collection

The app records video and operation events, captures keyframes, and connects its macOS Accessibility provider to the local daemon. The AX collector returns region-associated UI hierarchy, text, and geometry, subject to permissions, target-app support, redaction, and traversal limits. Browser evidence requires the browser provider.

Follow the permission guide for Screen Recording, Accessibility, and Input Monitoring. Full keystroke content is disabled by default; see the product guide for the optional setting.

## Run Locally

Start the daemon from `WorkRecorder/`:

```bash
uv sync --extra dev
./.venv/bin/python -m scripts.repair_uv_editable_install
./.venv/bin/workrecorder-daemon
```

In another terminal, from `WorkRecorder/`:

```bash
cd apps/macos_capture
swift run WorkRecorderCapture
```

The Swift executable is named `WorkRecorderCapture`; the packaged application is `WorkRecorder.app`.

Useful environment variables:

```bash
export WORKRECORDER_DAEMON_URL=http://127.0.0.1:8765
export WORKRECORDER_INSTALL_SECRET=dev-install-secret
export WORKRECORDER_ARTIFACT_STAGING_DIR="$HOME/.workrecorder/staging"
```

## Verification

From `WorkRecorder/apps/macos_capture/`:

```bash
swift test
```

For the repository quality gate, run from `WorkRecorder/`:

```bash
./.venv/bin/python -m scripts.quality_gate
```
