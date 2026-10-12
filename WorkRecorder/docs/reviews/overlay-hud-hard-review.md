# Overlay / HUD Strict Review Pass

## Scope
Reviewed the real macOS Capture HUD after the four-reviewer pass. This review focused on the specific foreground/background hierarchy problem: the popup did not separate enough from the non-selection veil and busy desktop text.

## Confirmed Issues
- The non-selection area used pale cyan-white veil, too close to the popup material. The selected area and popup did not read as distinct layers.
- The selection rectangle relied on glow and a uniform cyan stroke, so it looked like a soft annotation rather than a precise capture lens.
- The selected interior carried too much haze/refraction, reducing capture fidelity.
- The Light Sheet had glass styling, but not enough local backing/contact shadow to float above high-contrast desktop text.
- Snapshot rendering still duplicates drawing logic and remains a structural drift risk, although this pass re-synced the edited visual values.

## Fixes In This Pass
- Changed non-selection veil from pale cyan-white to a cooler graphite dim layer with only a very light blue sheen.
- Added a dark precision keyline behind the Tiffany selection stroke, making the bbox visible on light UI and dense text.
- Reduced selection interior haze/refraction so selected content remains the clearest part of the screen.
- Increased Light Sheet spatial separation with a subtle local backing, stronger cool environment shadow, and stronger contact shadow.
- Re-generated snapshots from the updated snapshot renderer after syncing the same values used by the real HUD.

## Remaining Risks
- Snapshot renderer is still not the real AppKit HUD. The proper fix is to share a renderer/material layer or introduce golden perceptual snapshots from real views.
- Source confidence remains a product risk: app-only source copy is safer, but selection-window validation still needs a follow-up.
- Workbench Evidence Card polish is out of this pass; it still needs a separate product UI round.
