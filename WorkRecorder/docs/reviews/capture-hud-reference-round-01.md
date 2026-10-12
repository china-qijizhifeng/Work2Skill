# Capture HUD Reference Review · Round 01

## Scope

Establish the reference direction using the desktop image supplied by the user:
light frosted veil, Tiffany Light Lens selection frame, app-only source row,
and a lightweight Context Capsule that does not overlap the selected region when
space allows.

## Reviewer Roles

- Visual: reference match, material, Prism, typography.
- UX: source confidence, note flow, placement, action labels.
- Engineering: token reuse, snapshot drift, tests.
- HUD/Overlay: selection contrast, non-selection veil, popup separation.

## Findings

- The old HUD was too much like a generic screenshot utility: source and note
  were present, but the selection did not feel like an activated Light Lens.
- The old non-selection layer either read too dark or too translucent depending
  on background; it needed a more controlled frosted veil.
- The Light Sheet content needed to be reduced to app + workspace, note, and
  actions. No chips or unstable page/window title promises at capture time.

## Implemented

- Added reference-style design spec at
  `docs/design/capture-hud-reference-style.md`.
- Reworked the Light Sheet into an app-only source row and context note flow.
- Reworked snapshot fixtures to use a Chrome-like app fixture instead of Finder
  progress copy from the reference.
