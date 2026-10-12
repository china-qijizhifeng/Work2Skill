# WorkRecorder

**English** | [简体中文](README.zh-CN.md) | [Project overview](../README.md)

**Human operation recording infrastructure for macOS and Linux.**

WorkRecorder records a human workflow and organizes video, input events, keyframes, and available system and web evidence into recording sessions for review, export, operation-evidence datasets, and downstream skill induction.

## Recording Workflow

```text
Start recording → Select a recording region → Confirm → Perform the workflow
    → Collect video, input events, and keyframe evidence
    → Finish → Review in the recording center → Export to a folder
```

The current user entry point is region recording, with the default shortcut **⌃⌥⌘R (Control + Option + Command + R)** or **Start recording** in the menu bar. Region selection defines the workspace for the recording session. Invoking the entry point during a session brings its controls forward.

Recordings generate keyframe images as evidence linked to the operation timeline.

## Collected Evidence

| Evidence | Purpose and limits |
| --- | --- |
| Video | Records the work region for playback. |
| Input events | Records mouse and keyboard activity with timing information; full keystroke content is disabled by default. |
| Keyframes | Captures visual evidence during recording and associates it with actions and the timeline. |
| macOS AX Tree | The native Accessibility provider collects UI hierarchy, text, and geometry associated with the recording region. Requires Accessibility permission; coverage depends on the target app and traversal limits. |
| Web evidence | The browser provider can collect URL, title, DOM, page text, and location information. Availability depends on the page, provider connection, and capture configuration. |
| Provenance and diagnostics | Associates evidence with applications, windows, collection status, and sources for review and debugging. |

macOS AX snapshots are filtered to the collection scope and their text is redacted. Traversal is limited to 16 levels, 1,600 nodes, and 200 elements per child attribute. A complete AX Tree is not guaranteed for every action. Stored evidence, agent-visible content, and exported content have different disclosure boundaries.

## Platform Scope

- **macOS**: This directory includes the native recording app, local daemon, browser provider, and AX collector.
- **Linux**: A single-desktop X11/Xorg AT-SPI service is included in [apps/linux_capture](apps/linux_capture/README.md). The Mac app records the remote desktop view; Linux supplies trees and operation evidence.

## Two Recording Modes

- **Normal app startup — Mac**: records local work and macOS AX evidence; remote probing is disabled, including previously saved enable settings.
- **Command startup — Linux**: `./.venv/bin/python scripts/start_linux_recording.py --ssh linux-desktop`. First start the [Linux AT-SPI service](apps/linux_capture/README.md) on the target desktop. This mode uses a separate daemon/data directory and disables host Mac AX and browser DOM collection.

Finish and export a recording, then quit the app before switching modes. Older external launchers need the new `WORKRECORDER_RECORDING_TARGET=linux` setting; use the launcher documented here for the AT-SPI-only workflow.

### Which files run on Linux and which run on Mac?

| Run on | Entry point | Purpose |
| --- | --- | --- |
| The Linux desktop being recorded | [`apps/linux_capture/service.py`](apps/linux_capture/service.py) | Collect AT-SPI trees, events, and click targets |
| Mac | [`scripts/start_linux_recording.py`](scripts/start_linux_recording.py) | Connect to the Linux collector and start WorkRecorder in Linux recording mode |

**First, on Linux:** clone or copy the repository, install the [Linux dependencies](apps/linux_capture/README.md), and run this in a terminal inside the desktop being recorded:

```bash
cd /path/to/Work2Skill/WorkRecorder
python3 apps/linux_capture/service.py
```

Replace `/path/to/Work2Skill` with the repository location on that machine. Run as the desktop login user and keep the terminal open. Keep the entire `apps/linux_capture/` directory together: `service.py` starts both programs under `collectors/` automatically.

**Then, on Mac:** build the app as described below, quit any existing app, and run this in a Mac terminal:

```bash
cd /path/to/Work2Skill/WorkRecorder
./.venv/bin/python scripts/start_linux_recording.py \
  --ssh linux-desktop
```

Replace `linux-desktop` with an SSH alias or `user@host` for the desktop being recorded. The launcher detects the Linux desktop resolution automatically; supply both `--width` and `--height` to override it. Open your remote desktop viewer, press `⌃⌥⌘R`, and select the remote desktop region to record. Keep both terminals running until recording and export finish. See the [Linux collector guide](apps/linux_capture/README.md) for all options.

## Quick Start

The package, daemon, Swift modules, scripts, and configuration use the WorkRecorder name. Run the following commands from the monorepo's `WorkRecorder/` directory.

### Build and Launch the macOS App

```bash
git clone https://github.com/china-qijizhifeng/Work2Skill.git
cd Work2Skill/WorkRecorder
uv sync --extra dev
./.venv/bin/python -m scripts.repair_uv_editable_install
npm --prefix apps/browser_extension install
./.venv/bin/python scripts/package_workrecorder_app.py --dev --verify
open dist/WorkRecorder.app
```

After opening the app:

1. Follow the permission guide for Screen Recording, Accessibility, and Input Monitoring for operation tracking.
2. For web evidence, build and load `apps/browser_extension` through Chrome/Edge's extension management page and confirm the provider is connected.
3. Press `⌃⌥⌘R` or choose **Start recording** in the menu bar.
4. Select the recording region, confirm, and perform your workflow.
5. Use the recording controls to pause, resume, or finish.
6. Open the recording center to review video and the operation timeline, then export to a folder as needed.

Build a self-contained package for distribution:

```bash
./.venv/bin/python scripts/package_workrecorder_distribution.py --dev --verify --archive both
```

### Development Setup

```bash
# Run from WorkRecorder/
uv sync --extra dev
./.venv/bin/python -m scripts.repair_uv_editable_install
npm --prefix apps/browser_extension install
npm --prefix apps/browser_extension run build
./.venv/bin/workrecorder-daemon
```

Start the native app in another terminal:

```bash
cd apps/macos_capture
swift run WorkRecorderCapture
```

Check the service and code from `WorkRecorder/`:

```bash
./.venv/bin/workrecorder daemon health --json
./.venv/bin/python -m scripts.quality_gate
```

After migrating an existing checkout to this layout, run `uv sync --extra dev` inside `WorkRecorder/` to create its virtual environment.

### Optional: Full Keystroke Recording

Full keystroke recording is disabled by default. When enabled, it stores physical key codes, characters, modifiers, and timestamps for each `key_down` / `key_up`, which may include passwords and other sensitive text. Set this before launching the app:

```bash
defaults write app.workrecorder.local WorkRecorder.ActiveCapture.RecordFullKeystrokes -bool true
```

Set the preference to `false` to disable it. The launch-time environment variable `WORKRECORDER_ACTIVE_CAPTURE_FULL_KEYSTROKES=1` also enables it; `0` disables it.

## Review and Export

Click **Export to Folder** and choose a destination to export one `normal` recording and automatically convert it to benchmark format. No separate script is needed. Raw exports are saved under `<destination>/<recording note>/video/`, with converted results in the sibling `benchmark/` directory, which opens in Finder on success. Conversion requires `uv` and `ffmpeg` (including `ffprobe`); Pillow is installed with the project dependencies. Basic task metadata is generated when no external task metadata is supplied. If conversion fails, the raw exports are preserved and the error is shown.

The recording center provides session review with video, actions, and keyframes. The exporter materializes a browsable directory; files depend on the evidence actually collected:

```text
<recording>/
  recording.json          # Session metadata and file index
  trajectory.json         # Ordered keyframe and action timeline
  summary.md              # Operation summary
  dom_hits.jsonl          # Available action-aligned DOM hits
  video.mp4 | video/      # Video, when available
  0000_<timestamp>/       # Keyframe evidence, when available
    screenshot.png
    actions.json
    meta.json
    ...
```

Additional OCR or VM accessibility files are generated only when corresponding evidence exists. The default local export omits some raw AX and web evidence; an exported folder is not a complete copy of the raw evidence store.

Exports can be used by [AgenticSkillInduction](../AgenticSkillInduction/README.md) and [DownstreamTasks](../DownstreamTasks/README.md). AgenticSkillInduction provides the NexAU example, and DownstreamTasks provides perturbed task definitions and grading criteria. See [WorkDemo-350 on Hugging Face](https://huggingface.co/datasets/yuqi777/WorkDemo-350) for the human operation demonstration dataset.

## Code and Documentation

| Directory | Responsibility |
| --- | --- |
| `apps/macos_capture/` | Native recording entry point, controls, review, and macOS AX provider |
| `apps/linux_capture/` | Linux AT-SPI trees, events, click targets, and a loopback service |
| `apps/browser_extension/` | Chrome/Edge web evidence provider |
| `services/context_daemon/` | Local service and collection orchestration |
| `packages/active_capture/` | Recording sessions, actions, keyframes, timelines, and export |
| `packages/capture/` | Underlying evidence collection and persistence |
| `packages/providers/` | Provider integration and routing |
| `packages/storage/` | Local ledger and artifact vault |
| `apps/cli/`, `apps/skill/` | Existing context retrieval and agent interfaces |

See the [documentation overview (Chinese)](docs/README.md) and [macOS development guide](apps/macos_capture/README.md). Earlier context-event and screenshot-entry documents remain as architecture references; the recording workflow described here defines the current product entry point.

## Updating an Existing Installation

Rebuild the app and browser extension together, and recreate the development environment with `uv sync --extra dev` followed by `python -m scripts.repair_uv_editable_install` using that environment. The daemon command is `workrecorder-daemon`; environment variables use `WORKRECORDER_`, and new local data defaults to `.workrecorder`. Updated clients and daemon must run together because their protocol identifiers also changed.

The CLI command is `workrecorder`; the agent skill wrapper is `scripts/workrecorder-cli`. Rebuild and reload the browser extension, then restart the app and daemon together to use the `workrecorder-token.` authentication protocol. Existing saved credentials are reused; newly generated credentials use the `workrecorder_` prefix.

Existing recording directories are not moved or deleted automatically. To open an existing app data directory, set `WORKRECORDER_APP_DATA_ROOT` and explicitly set `WORKRECORDER_DATABASE_PATH` to the existing database filename before launching the app. For a separately started daemon, also set `WORKRECORDER_ARTIFACT_STAGING_DIR` and `WORKRECORDER_ARTIFACT_VAULT_DIR` to the existing directories. Keep the database, vault, staging directory, and local credential files together; back them up before upgrading. Reapply app preferences using the new keys if needed. Do not run two daemons against the same database during the upgrade.
