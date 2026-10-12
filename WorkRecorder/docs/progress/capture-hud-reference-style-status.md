# Capture HUD Reference Style Progress

## Current Goal
Implement reference-inspired light optical HUD for real macOS capture overlay and Light Sheet.

## Iteration Log

### Round 00 · Baseline
- Existing HUD already has light glass direction, but non-selection veil is too dark, source line has no app icon, Light Sheet top row is compressed, snapshot renderer still duplicates visual code.
- Planned changes: app-only source row with icon, shallow frosted veil, visible Light Lens, no chips, no window title/URL.

### Round 01 · Reference Match
- Added offline design spec and started the reference-style HUD rewrite.
- Replaced unstable source/title promises with app + workspace only.
- Reworked the snapshot fixture around a Chrome/web capture instead of copying the Finder reference content.

### Round 02 · Reviewer Fixes
- Strengthened selection bbox and reduced confirmation-state resize-tool feeling.
- Increased Light Sheet opacity so background text is not readable through input/actions.
- Shifted veil from white fog toward cool frosted dim.
- Started moving Prism from decorative glow into edge/material language.

### Round 03 · User + Reviewer Follow-up
- Moved app icon/name/workspace onto the title row.
- Removed app icon background; real app icon is used when source confidence is high enough.
- Removed the large container behind input/buttons.
- Reduced shadow reliance; rim/highlight now carry more of the material depth.
- Aligned source display confidence with submission confidence and wired saved-state continue-capture in real mode.

## Latest Verification

- `swift test`: 51 tests passed.
- `swift run WorkRecorderCaptureSnapshots --output ../../.qa/capture-hud`: regenerated 21 snapshots.
- `uv run python scripts/verify_capture_hud_snapshots.py --root .qa/capture-hud`: passed.
