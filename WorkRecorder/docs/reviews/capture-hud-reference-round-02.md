# Capture HUD Reference Style · Round 02 / 03

## Scope

Round 02 implements the first reviewer pass after the reference-style rewrite:

- Non-selection veil moved away from white fog toward cool frosted dim.
- Selection frame strengthened with higher contrast Tiffany line and fewer handles in confirmation state.
- Light Capsule material made more opaque and separated with stronger rim/shadow.
- Snapshot renderer aligned on the most visible state strings and placement order.
- Overlay Escape cancellation moved back to coordinator/window level after the
  engineering reviewer flagged stale global-monitor risk.
- User follow-up: app icon/name/workspace now share the same top row; the real
  HUD detects app name/icon when confidence is high enough.

## Snapshots

- `.qa/capture-hud/light/1440x900/confirming.png`
- `.qa/capture-hud/light/1440x900/dragging.png`
- `.qa/capture-hud/light/390x844/confirming.png`
- `.qa/capture-hud/light/1440x900/permission-needed.png`

## Self Review Before Reviewer Round

### Improved

- Selection bbox reads faster than Round 01; confirmation state no longer shows side resize handles.
- Popup is less transparent and bottom text no longer dominates through the sheet in generated snapshots.
- App source line remains app/workspace only.

### Still Weak

- Overall palette still reads too uniformly mint/cyan; needs more neutral silver/graphite hierarchy.
- The floating sheet still feels more like a light acrylic card than true macOS material.
- Snapshot renderer is still a parallel drawing path and must be tightened further.

## Round 02 Reviewer Findings

### Visual

- Popup separation improved, but the shadow/backplate was too rectangular.
- Selection still felt like a screenshot annotation tool, especially handles.
- Overall palette was too one-note aqua; veil/background needed more neutral
  silver-gray hierarchy.
- Buttons were polished but not premium enough; primary and quiet were still too
  close in weight.
- Mobile bottom HUD was readable but heavy.

### UX

- Source line looked too confident when source confidence was below submission
  threshold.
- `稍后` remains semantically risky because P0 behavior is discard, but the
  product decision for this round keeps it as softer user-facing copy.
- Input looks optional in behavior but not fully optional in copy; a later pass
  should revisit label copy.
- Permission copy should say the user must re-capture after opening settings.

### Engineering

- Snapshot renderer still duplicates real HUD layout and material logic.
- Source display threshold drifted from daemon submission threshold.
- Real saved-state `继续截图` path was not wired outside preview mode.
- App icon lookup was too fuzzy; it should prefer process/bundle identity.

### HUD / Overlay

- Side edges of the selection bbox were still weaker than top/bottom.
- Handles were visible by position but not by contrast.
- Non-selected veil was better but still modest; outside should step back more.
- Popup contact shadow needed to be tighter but not heavier overall.

## Round 03 Fixes

- Top row revised to `status + title + app icon + app/workspace` in one line.
- App icon background removed; real HUD now shows a real app icon only when the
  source confidence matches the submission threshold.
- Source display threshold aligned to `0.75`, matching window-hint submission.
- App icon detection now prefers process id, known bundle id, then exact app name
  match; fuzzy contains no longer wins first.
- Saved state now wires `继续截图` in the real capture path, not only preview.
- Selection frame gained a stronger continuous dark keyline and stronger handle
  rim.
- Non-selection veil shifted more neutral/graphite and less mint.
- Removed the large clean-zone container behind input/actions; input and buttons
  now sit directly on the capsule material.
- Reduced shadow dependence: far/contact/reflection shadows are lighter; depth
  is primarily expressed through rim, satin edge, and glass fill.
- Button text now uses font-measured vertical centering; action font is slightly
  smaller and cleaner.

## Latest Snapshots

- `.qa/capture-hud/light/1440x900/confirming.png`
- `.qa/capture-hud/light/1440x900/dragging.png`
- `.qa/capture-hud/light/390x844/confirming.png`
- `.qa/capture-hud/light/1024x768/confirming.png`

## Latest Verification

- `swift test`: 51 tests passed.
- `swift run WorkRecorderCaptureSnapshots --output ../../.qa/capture-hud`: 21
  light snapshots regenerated.
- `uv run python scripts/verify_capture_hud_snapshots.py --root .qa/capture-hud`:
  passed.

## Remaining Debt

- Snapshot renderer remains parallel to real AppKit drawing. This is acceptable
  for this iteration but should be addressed before release hardening.
- Need snapshot variants for long app names, low-confidence source fallback,
  `captureError`, and `unsupported` states.
