# WorkRecorder Linux AT-SPI Collector

[English](README.md) | [简体中文](README.zh-CN.md)

[WorkRecorder product guide](../../README.md)

This service collects evidence from a remote Linux desktop. WorkRecorder on Mac records the remote desktop view and local input; the Linux service supplies AT-SPI trees, focus and selection events, and controls resolved from actual pointer clicks.

Requires **Linux X11/Xorg and Python 3.10+**. Pointer monitoring uses X RECORD; Wayland is unsupported. Accessibility coverage depends on the target application, and tree traversal and click resolution have depth, node-count, and time limits.

## Entry Points and Where to Run Them

| File | Run on | How it starts |
| --- | --- | --- |
| [`service.py`](service.py) | The Linux desktop being recorded | Run `python3 apps/linux_capture/service.py` in its desktop terminal |
| [`collectors/a11y_daemon.py`](collectors/a11y_daemon.py), [`collectors/event_watch.py`](collectors/event_watch.py) | The same Linux desktop | Started automatically by `service.py`; keep these files with the service |
| [`scripts/start_linux_recording.py`](../../scripts/start_linux_recording.py) | Mac | Run the launcher after the Linux service is ready |

Run the commands below from `Work2Skill/WorkRecorder/` on each machine. Start in this order: **Linux service → Mac launcher → recording**. Keep both terminals open until recording and export finish.

## 1. Start the Service on the Linux Desktop

Clone or copy the repository to Linux. Run the service in a terminal inside the desktop being recorded, using the desktop login user rather than the server's root account.

Example dependencies for Ubuntu/Debian:

```bash
sudo apt-get install python3 python3-gi gir1.2-atspi-2.0 python3-xlib xdotool x11-utils
# Enable accessibility for GNOME/GTK; existing applications may need restarting.
gsettings set org.gnome.desktop.interface toolkit-accessibility true
# Optional: install the GTK accessibility bridge when recording LibreOffice.
sudo apt-get install libreoffice-gtk3
```

From `WorkRecorder/`, run:

```bash
python3 apps/linux_capture/service.py
```

The service inherits `DISPLAY`, `DBUS_SESSION_BUS_ADDRESS`, and `XAUTHORITY` from the desktop session. When starting through SSH, set these to the target session's actual values; user IDs and authentication paths from another machine are not interchangeable.

The service listens on Linux loopback at `127.0.0.1:7073`; its internal tree collector uses port `7070`. Override these with `--port` and `--tree-port`. Ctrl+C stops the collector processes started by this service.

Each launch creates a separate evidence directory under `~/.local/share/workrecorder/linux/<run>/`:

- `raw-events.jsonl`: raw AT-SPI events and click-resolution records.
- `events.jsonl`: sequentially numbered events with the latest available `a11y_snapshot`.
- `trees.jsonl`: independent tree snapshots and sampling start/end timestamps.
- Collector process logs.

Tree sampling defaults to once every 2 seconds, with a maximum depth of 6 and 400 nodes. Adjust these with `--tree-interval`, `--tree-depth`, and `--tree-max-nodes`. Each event carries the latest completed tree sample, **not necessarily the tree at the exact click time**. Events without an available tree omit the snapshot. The full tree sequence remains on Linux; the Mac export preserves snapshots received with events. The legacy export fields `dom_hit` and `dom_hits.jsonl` carry AT-SPI control information in this mode.

## 2. Start Linux Recording Mode on Mac

Install dependencies and build `dist/WorkRecorder.app` using the [product guide](../../README.md). Quit any existing recording app, then run from `WorkRecorder/`:

```bash
./.venv/bin/python scripts/start_linux_recording.py \
  --ssh linux-desktop
```

Replace `linux-desktop` with your SSH alias or `user@host`. It must reach the loopback service on the Linux desktop being recorded. For a virtual machine, connect SSH to that guest, using your own ProxyJump configuration if needed; reaching the physical host alone does not reach the guest service.

- Resolution is detected automatically through the Linux service using `xdpyinfo` from `x11-utils`. Optional `--width` and `--height` overrides must be supplied together. Detection failures prompt you to fix the desktop environment or provide both values. Keep the resolution unchanged during recording; restart the Mac launcher after changing it.
- `--title-bar` specifies the non-desktop area at the top of the Mac viewer window in points. The default is 28; use `0` for a borderless view.
- Use `--app /path/to/WorkRecorder.app` to select the app and `--remote-port` to select the service port.
- The launcher creates an isolated SSH tunnel and local daemon with dynamic ports, separate credentials, and a data directory at `~/.workrecorder/linux/<host-id>/`.
- It verifies the remote service profile, health, and clock difference. Keep both machines' clocks synchronized.
- Open your VNC or remote desktop client separately; the launcher establishes the evidence channel.
- Press `⌃⌥⌘R` (Control+Option+Command+R), align the recording region to the remote desktop content, record and export, then quit the app. Keep the terminals and SSH tunnel running throughout.

Normal app startup selects `macos` mode. The launcher sets `WORKRECORDER_RECORDING_TARGET=linux`, selects Linux AT-SPI evidence, and disables host Mac AX and browser-provider collection. Full keystroke content is disabled by default.

## Endpoints (Development and Debugging Reference)

The application calls these endpoints automatically during recording. Users do not need to enter these URLs or supply coordinates manually. Numbers in the table are example request values, not fixed recording settings.

| Endpoint | Contents |
| --- | --- |
| `/health` | `linux_atspi_v1` profile, collector status, service time, and current desktop pixel dimensions in `display` |
| `/events?n=100` or `/events?since_seq=42` | Event polling; up to the latest 5,000 events are buffered for transport |
| `/clicks?n=100` | Pointer clicks and click-resolution records |
| `/a11y?depth=6&max_nodes=400` | On-demand AT-SPI tree snapshot |
| `/at_point?x=100&y=200` | Query the accessibility control at Linux desktop pixel coordinates `(100, 200)` |

`/at_point` associates a click location with a specific control, such as a Save button. `x` and `y` are Linux desktop coordinates in pixels, measured from the top-left corner: the example `x=100&y=200` means 100 pixels to the right and 200 pixels down. The application maps the click position in the Mac recording region to Linux desktop coordinates before querying the control's available name, role, bounds, and other accessibility information.

The service binds to loopback and is accessed over SSH. Output can contain interface text; manage it as local recording data and keep recording logs and credentials out of the source repository.

## Provenance and Validation

`collectors/a11y_daemon.py` comes from MyPCBench's persist-introspection. `collectors/event_watch.py` comes from OSWorld's general AT-SPI watcher and retains its application-level control-resolution logic. See [NOTICE](NOTICE.md) and [licenses](licenses/) for provenance and retained licenses.

Automated tests cover HTTP cursors, snapshot transport, Mac probe integration, recording-mode isolation, and resolution detection. The complete Linux desktop → SSH → Mac video recording workflow still requires acceptance testing on the target desktop.
