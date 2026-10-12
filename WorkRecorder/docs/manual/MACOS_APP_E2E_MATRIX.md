# macOS App E2E Matrix

This is the release checklist for real local capture validation. It complements automated tests; it does not replace them.

## Preflight

1. Quit all old WorkRecorder instances before testing:

```bash
osascript -e 'tell application "WorkRecorder" to quit' || true
```

2. Build and verify the real app bundle:

```bash
./.venv/bin/python scripts/package_workrecorder_app.py --dev --verify
xattr -cr dist/WorkRecorder.app
codesign --verify --deep --strict --verbose=2 dist/WorkRecorder.app
```

If the checkout lives under a FileProvider-backed Desktop folder and macOS
immediately reattaches `com.apple.FinderInfo`, verify the same bundle from a
non-FileProvider staging path:

```bash
rm -rf /tmp/WorkRecorder-strict-verify.app
/usr/bin/ditto --norsrc --noextattr dist/WorkRecorder.app /tmp/WorkRecorder-strict-verify.app
codesign --verify --deep --strict --verbose=2 /tmp/WorkRecorder-strict-verify.app
```

3. Record the validation identity in the report: git SHA, `dist/WorkRecorder.app` mtime, codesign identifier, daemon pid, resolved daemon URL, and app launch time.
4. Open `dist/WorkRecorder.app` directly. Do not use `swift run`, `swift test`, or the package executable for this matrix.
5. Before claiming strict release readiness, run the release-lab preflight:

```bash
./.venv/bin/python scripts/check_macos_app_release_lab.py \
  --manifest .qa/reports/macos-e2e/run-manifest-final-hardening.json \
  --json-output .qa/reports/macos-e2e/release-lab-preflight.json
```

The preflight does not replace the matrix; it records whether the current
machine can run the strict rows that require physical multi-display, isolated
TCC state, Stable Chrome extension loading, a clean Notes target, and an
external shortcut-conflict helper.

6. Run the recording release matrix runner to collect all automated evidence
   into one timestamped folder:

```bash
./.venv/bin/python scripts/run_macos_recording_release_matrix.py \
  --run-id release-lab-$(date -u +%Y%m%dT%H%M%SZ) \
  --allow-blockers
```

The runner builds the real app bundle, runs the automated Swift/Python/UI
gates, records release-lab preflight state, and scrubs generated report files.
It does not replace physical observation. By default the runner exits non-zero
when strict blockers remain; use `--allow-blockers` only to collect an honest
evidence folder on a non-release workstation after all automated gates pass.
The flag must not be used to mask skipped gates, failed automation, or dry-run
output. If strict release still fails, complete the missing physical report rows
first instead of editing the manifest by hand.

Stable Chrome and Chrome for Testing must stay distinct in the manifest.
Chrome for Testing can prove provider routing, but the Stable Chrome row is
only complete when the Stable Chrome case is recorded with artifact-backed
evidence and `browser: "stable_chrome"`. Likewise, the external shortcut UI row
is only complete after the helper-driven Workbench flow is recorded, for
example by adding `external_helper_ui: "passed"` to the shortcut validation
case with a report artifact.

## How To Record A Case

For each row:

1. Open `dist/WorkRecorder.app`.
2. Use the shortcut named by the case: `⌃⌘2` for current-window capture, `⌃⌘3` for region capture, or `⌃⌥⌘R` for region recording. `⌃⌘R` is intentionally not the default because it collided with QQ screen-recording on the validation machine.
3. For capture cases, copy the event id from Workbench or CLI. For recording cases, record the active-capture session id, segment ids, keyframe event ids, and whether the final video artifacts were attached only after the completion sheet Save action.
4. For capture cases, run:

```bash
./.venv/bin/workrecorder events search "<case keyword>" --since 30m --json
./.venv/bin/workrecorder events inspect <event_id> --purpose e2e_validation --view system_appshot --view selection_text --view screenshot_ref --view evidence_refs --json
./.venv/bin/workrecorder agent replay --json
```

5. Save a redacted JSON report under `.qa/reports/macos-e2e/`.

After updating the run manifest, validate that every required row is either
proved by an existing report artifact under `.qa/reports/macos-e2e/` or
explicitly recorded as an environment limitation. Passing rows cannot rely on
free-text evidence alone; supporting reports and quality-gate strings are also
validated:

```bash
./.venv/bin/python scripts/verify_macos_app_e2e_manifest.py \
  --manifest .qa/reports/macos-e2e/run-manifest-final-hardening.json \
  --json-output .qa/reports/macos-e2e/manifest-validation-final.json
```

For a release-lab pass with physical multi-display, isolated TCC, Stable
Chrome extension loading, a dedicated external shortcut-conflict helper, and a
stable Notes target available, run the stricter mode. It must fail until every
environment-limited row and related release-lab caveat is replaced with passing
artifact-backed evidence. Strict mode also fails unless
`shortcut_validation.external_helper_ui` is explicitly `passed`; same-process
Carbon tests and helper stdout are not enough to prove Workbench's
external-conflict UI.

```bash
./.venv/bin/python scripts/verify_macos_app_e2e_manifest.py \
  --manifest .qa/reports/macos-e2e/run-manifest-final-hardening.json \
  --strict-release
```

## Required Cases

| Case | Expected |
| --- | --- |
| `⌃⌘2` Chrome current window | only frontmost Chrome window is captured; safe card/inspect/share hide process id, window id, and exact frame |
| `⌃⌘2` Finder current window | Finder window is captured; Finder desktop/no-window shows a neutral no-target message |
| `⌃⌘2` native App current window | Preview/TextEdit/Notes/System Settings save as current-window capture with system appshot present |
| `⌃⌘2` overlapping windows | frontmost target wins; background windows do not steal OS_WINDOW routing |
| `⌃⌘2` multi-display | left/negative-coordinate and mixed-Retina displays capture only the target window |
| `⌃⌘2` Accessibility denied | screenshot can save via WindowServer fallback; Light Sheet/diagnostics show degraded window recognition |
| `⌃⌘3` region screenshot | existing region selection, Light Sheet, save, search, and inspect behavior remain unchanged |
| `⌃⌥⌘R` region recording | enters region selection, shows confirmation, starts only after user clicks Start, records fixed region with HUD/boundary visible, and commits video only after completion-sheet Save |
| `⌃⌥⌘R` recording discard | after stopping, Discard cancels the active-capture session and deletes local staged video without completing/indexing the recording |
| Recording pause/resume/mark | HUD Mark creates a session keyframe; Pause stops video/input capture; Resume starts a new segment; segment close reasons are typed |
| Shortcut conflict settings | internal duplicate/weak chords are rejected; Carbon registration failures show a conflict status; arbitrary external app/event-tap conflicts require release-lab proof before they can be claimed |
| Chrome webpage + extension online | event saved, Web provider succeeded, appshot present |
| Chrome extension offline | event saved, Web skipped/stale, screenshot/appshot present |
| Preview PDF | event saved, primary app Preview, OCR/a11y status visible |
| Finder | event saved, primary app Finder |
| TextEdit or Notes | event saved, selection/OCR text if available |
| Desktop blank area | event saved as desktop/system-only |
| Overlapping windows | primary and secondary surfaces visible in appshot/manifest |
| Accessibility denied | event saved, a11y diagnostic/permission state visible |
| Accessibility granted | event saved, a11y evidence or quality report visible |
| OCR config missing | event saved, OCR skipped/config_required |
| OCR success | event saved, visual OCR text searchable |

## Per-Case Setup

| Case | Setup |
| --- | --- |
| `⌃⌘2` Chrome current window | Bring Chrome frontmost, press `⌃⌘2`, confirm save, then inspect/search/share the saved event. |
| `⌃⌘2` Finder current window | Open a Finder window and capture it; repeat with no Finder window focused/desktop foreground. |
| `⌃⌘2` native App current window | Repeat with Preview PDF, TextEdit/Notes, Calendar or System Settings. |
| `⌃⌘2` overlapping windows | Stack two app windows and keep the target frontmost before pressing `⌃⌘2`. |
| `⌃⌘2` multi-display | Repeat on left negative-coordinate display, right display, and vertical display arrangement when available. |
| `⌃⌘2` Accessibility denied | Revoke Accessibility, restart WorkRecorder, capture a frontmost window, then confirm degraded-window copy. |
| `⌃⌘3` region screenshot | Press `⌃⌘3`, drag a region, save, and compare with previous region screenshot behavior. |
| `⌃⌥⌘R` region recording | Press `⌃⌥⌘R`, drag a region, confirm the selection summary, click Start, wait for countdown, record 3-5 seconds, click Finish, then Save from the completion sheet. Confirm start/final keyframes and a recording segment video artifact. |
| `⌃⌥⌘R` recording discard | Repeat the recording flow, click Finish, then Discard. Confirm the session is cancelled and no completed recording appears in Workbench/search. |
| Recording pause/resume/mark | During a recording, click Mark, Pause, Resume, then Finish. Confirm the manifest contains typed control events, a paused segment close reason, and a new resumed segment. |
| Shortcut conflict settings | In Settings, try duplicate commands, weak Shift-only chords, reset defaults, and restart persistence. |
| Chrome webpage + extension online | Load the unpacked extension from Workbench, wait until browser capture shows online, then capture a visible webpage region. |
| Chrome extension offline | Quit Chrome or disable the WorkRecorder extension, then capture the same page area; the event should still save with Web skipped/stale. |
| Preview PDF | Open a local PDF in Preview, capture text and margin, then inspect `system_appshot` and OCR status. |
| Finder | Open a Finder window with several visible filenames and capture the list area. |
| TextEdit or Notes | Open a document/note with known text and capture only the text area. |
| Desktop blank area | Hide windows or capture a blank desktop region; expect a system-only event with low/no text. |
| Overlapping windows | Put two app windows under the same bbox; verify primary is the larger/frontmost overlap and secondary is retained. |
| Accessibility denied | Revoke WorkRecorder Accessibility in System Settings, restart the app, capture a text window, and confirm a typed permission diagnostic. |
| Accessibility granted | Re-enable Accessibility, restart the app, capture the same window, and confirm a11y evidence or a quality report. |
| OCR config missing | Temporarily make `swift` unavailable or force a local OCR unavailable test setting; event should save with OCR skipped. |
| OCR success | Keep `swift` available, capture visible text, and confirm `visual_ocr_text` appears in inspect/search once processing finishes. |

## External Shortcut Conflict Helper

Use this helper only in the release lab when validating that Workbench shows an
external Carbon hotkey conflict, not an internal duplicate. The helper is a
diagnostic, not proof by itself: on some macOS versions a separate process can
hold the same Carbon chord while WorkRecorder can still register it. Mark this
row passed only when Workbench itself shows the external-conflict state.

```bash
swift scripts/macos_hotkey_conflict_helper.swift \
  --key-code 26 \
  --modifiers control,option,command \
  --display-name "Control+Option+Command+9"
```

Leave the helper running, set one WorkRecorder command to the occupied chord in
Settings, verify the conflict state and copy, then stop the helper with
`Control-C`. If Workbench still shows the shortcut as enabled, record that as a
release-lab limitation instead of a pass.

## Expected JSON Assertions

- `events search` returns only safe summary fields and never returns raw DOM, raw a11y tree, vault path, or URL query/hash.
- `events inspect --view system_appshot` includes `primary_app`, provider outcomes, OCR status, and screenshot ref metadata.
- `events inspect --view screenshot_ref` returns a ref only; raw bytes still require the audited raw artifact endpoint.
- `agent replay` includes the search/inspect calls, delivered fields, snapshot ids, and citation ids when present.

## Report Shape

```json
{
  "case": "preview_pdf",
  "trigger_id": "trg_...",
  "capture_run_id": "caprun_...",
  "event_id": "evt_...",
  "captured_at": "2026-05-23T...",
  "primary_app": "Preview",
  "provider_outcomes": [],
  "system_appshot": {
    "present": true,
    "evidence_id": "evd_appshot_...",
    "ocr_job_status": "skipped"
  },
  "screenshot_artifact_id": "art_screen_...",
  "cli_commands": {
    "search": "workrecorder events search ... --json",
    "inspect": "workrecorder events inspect ... --json"
  },
  "agent_run_id": "arun_...",
  "replay_snapshot_id": "snap_...",
  "search_ok": true,
  "inspect_ok": true,
  "privacy_checks": {
    "no_storage_uri": true,
    "no_raw_dom": true,
    "no_raw_a11y_tree": true
  }
}
```

## Physical Recording Report Shape

The recording rows (`recording_region`, `recording_discard`, and
`recording_controls`) are strict release cases. They must be recorded with the
real `dist/WorkRecorder.app`, the default physical shortcut `⌃⌥⌘R`, visible region
selection, HUD, boundary, and completion sheet. The manifest verifier rejects a
passed recording row unless its report proves the user-visible flow.

Use the report helper after the physical run so every confirmation is explicit:

```bash
./.venv/bin/python scripts/create_macos_recording_physical_report.py \
  --case recording_region \
  --output .qa/reports/macos-e2e/recording-region-physical-release.json \
  --session-id acs_... \
  --started-at 2026-06-02T08:03:00Z \
  --ended-at 2026-06-02T08:03:05Z \
  --operator-note "Observed HUD, boundary, completion sheet, save, and library placement on the release-lab machine." \
  --opened-via-physical-shortcut \
  --region-selection-confirmed \
  --hud-visible \
  --recording-boundary-visible \
  --completion-sheet-visible \
  --privacy-check-no-storage-uri \
  --privacy-check-no-local-path \
  --save-clicked \
  --completion-final-status completed \
  --video-state available \
  --appears-in-recording-library \
  --event-id evt_... \
  --video-artifact-id art_... \
  --duration-ms 3500 \
  --segment-count 1 \
  --keyframe-count 3
```

The helper's proof flags default to `false`. A generated draft will not pass the
manifest verifier until every observed UI state and case-specific result is
explicitly recorded.

Before editing the run manifest, validate the single report directly:

```bash
./.venv/bin/python scripts/validate_macos_recording_physical_report.py \
  --case recording_region \
  --report .qa/reports/macos-e2e/recording-region-physical-release.json
```

Common required fields:

```json
{
  "case": "recording_region",
  "app_bundle": "dist/WorkRecorder.app",
  "trigger_shortcut": "⌃⌥⌘R",
  "opened_via_physical_shortcut": true,
  "region_selection_confirmed": true,
  "hud_visible": true,
  "recording_boundary_visible": true,
  "completion_sheet_visible": true,
  "session_id": "acs_...",
  "started_at": "2026-06-02T08:03:00Z",
  "ended_at": "2026-06-02T08:03:05Z",
  "privacy_check_no_storage_uri": true,
  "privacy_check_no_local_path": true
}
```

`recording_region` additionally requires:

```json
{
  "save_clicked": true,
  "discard_clicked": false,
  "completion_final_status": "completed",
  "video_state": "available",
  "appears_in_recording_library": true,
  "appears_in_screenshot_library": false,
  "event_id": "evt_...",
  "video_artifact_id": "art_...",
  "duration_ms": 3500,
  "segment_count": 1,
  "keyframe_count": 3
}
```

`recording_discard` additionally requires:

```json
{
  "save_clicked": false,
  "discard_clicked": true,
  "completion_final_status": "cancelled",
  "appears_in_recording_library": false,
  "appears_in_screenshot_library": false,
  "completed_event_created": false,
  "staged_video_deleted": true
}
```

`recording_controls` additionally requires:

```json
{
  "pause_clicked": true,
  "resume_clicked": true,
  "mark_clicked": true,
  "pause_stopped_capture": true,
  "resume_started_new_segment": true,
  "mark_created_keyframe": true,
  "save_clicked": true,
  "completion_final_status": "completed",
  "video_state": "available",
  "appears_in_recording_library": true,
  "appears_in_screenshot_library": false,
  "event_id": "evt_...",
  "video_artifact_id": "art_...",
  "manual_mark_keyframe_id": "kf_...",
  "duration_ms": 5200,
  "segment_count": 2,
  "keyframe_count": 4
}
```
