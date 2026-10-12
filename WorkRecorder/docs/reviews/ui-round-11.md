# UI Round 11 · Evidence Workbench Closure

Date: 2026-05-20

## Scope

This round focused on moving the app from a capture utility toward a product-grade Agent Context Capture workflow:

- Workbench evidence cards and the right-side inspector.
- Capture HUD saved-state handoff.
- Screenshot preview affordances and keyboard actions.
- Shared Workbench design tokens and snapshot refresh.

## Reviewer Inputs

### Visual Reviewer

Findings:

- Evidence cards looked like large pale text containers rather than evidence objects.
- Missing thumbnails made the history page feel unfinished and empty.
- The right inspector was readable but too form-like; it needed a clearer "Agent sees this" hierarchy.
- The HUD was acceptable after the glass fixes, but saved-state actions needed a visible product loop.

Changes:

- Evidence cards now use larger screenshot thumbnails and a synthetic evidence preview when a thumbnail is missing.
- User note is visually promoted as the strongest human signal.
- Inspector default tab is now `摘要`, with explicit groups for default-visible, on-demand, and locked materials.
- Saved HUD state now exposes `查看证据` and `继续截图` instead of disappearing immediately.

Remaining:

- Workbench visual language is still too pale in some places; next pass should deepen card layering and reduce outline-only surfaces.

### UX Reviewer

Findings:

- The saved screenshot path lacked closure: user could save but not immediately inspect.
- `稍后` was misleading because P0 discards the current capture.
- Evidence details exposed too much system language by default.
- Search and keyboard affordances were missing in the evidence browser.

Changes:

- Confirming state now uses `不保存`; saved state uses `查看证据 / 继续截图`.
- Card click opens the inspector; `Esc` closes it.
- Added `⌘F` search focus, `⌘C` copy current evidence summary, and `[` / `]` tab movement.
- Added local search filtering over title, app, origin, URL, note, and text snippets.
- Added hover thumbnail preview plumbing for evidence cards.

Remaining:

- The hover preview should be runtime-tested with real thumbnails, not just snapshot-rendered cards.

### Engineering Reviewer

Findings:

- Workbench UI needs presentation models instead of raw daemon fields.
- Snapshot and runtime UI must drift less.
- Token usage was improving but still not deep enough.

Changes:

- Added `EvidenceInspectorPresentation` to normalize inspector copy and evidence states.
- Routed Workbench layout/material/typography through `HUDDesignTokens`.
- Updated Swift tests for the saved-state path.
- Regenerated HUD and Workbench snapshots and stored this round under `.qa/round-11`.

Remaining:

- Snapshot renderer still has a parallel HUD drawing path. It should be made to share more production layout/material primitives in a future engineering pass.

### HUD / Overlay Reviewer

Findings:

- Screenshot bbox is clearer than before, but should remain stronger than ordinary crop-box UI.
- Non-selection background and popup material are now separated enough in snapshots.
- Confirmation handles are hidden in confirming state, matching Light Lens intent.

Changes:

- Confirmed current HUD snapshots across 1440, 1024, and 390 widths.
- Preserved Light Lens overlay and saved-state product loop.

Remaining:

- Need runtime QA on a real Chrome/white-page background after this build.

## Artifacts

- Workbench snapshots: `.qa/round-11/workbench/`
- Capture HUD snapshots: `.qa/round-11/capture-hud/light/`

## Verification

- `swift test` passed: 50 tests.
- `WORKRECORDER_WRITE_WORKBENCH_SNAPSHOTS=1 swift test --filter WorkbenchRuntimeTests/workbenchSnapshotsRenderPrimaryPages` passed.
- `swift run WorkRecorderCaptureSnapshots --output .qa/capture-hud` regenerated 21 HUD snapshots and design reference.
- `uv run python scripts/verify_capture_hud_snapshots.py --root apps/macos_capture/.qa/capture-hud` passed.
