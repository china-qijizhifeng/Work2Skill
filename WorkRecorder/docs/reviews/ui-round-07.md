# UI Round 07 - Material / Prism Pass

Scope: Light glass, satin rim, and prism restraint.

Reviewer findings:
- Visual: Earlier versions looked plasticky because cyan was used everywhere at the same strength.
- UX: Prism should support hierarchy, not decorate every surface.
- Engineering: Snapshot renderer and real HUD must continue converging on the same material language.

Changes made:
- Workbench controls now use softer glass shadows, inner highlights, and lower-contrast Tiffany fills.
- Thumbnail and selection lens receive only localized prism edge accents.
- HUD selection alpha was strengthened while keeping the prism effect on corners and edges.

Artifacts:
- `.qa/workbench/overview-selected.png`
- `.qa/capture-hud/light/design-reference.png`

Remaining:
- Capture HUD snapshot renderer still has independent drawing code and should be unified with the real view path.
