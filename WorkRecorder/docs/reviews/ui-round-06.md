# UI Round 06 - HUD / Overlay Pass

Scope: Screenshot selection visibility and Light Capsule readability.

Reviewer findings:
- Visual: Screenshot bbox was too subtle against real pages.
- UX: Non-selection area and HUD panel color were too close, making the active area harder to perceive.
- Engineering: Closing paths must reliably remove overlay, anchor, and sheet together.

Changes made:
- Increased selection outline strength, corner bloom, and outer glow.
- Darkened the non-selection veil into a more legible frosted graphite tint.
- Kept confirming state handles hidden while retaining the Light Lens border.

Artifacts:
- `.qa/capture-hud/light/1440x900/confirming.png`
- `.qa/capture-hud/light/390x844/confirming.png`

Remaining:
- Runtime close-path validation against real overlay windows still needs manual QA on the active app.
