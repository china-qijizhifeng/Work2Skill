# UI Round 01 - Design System Foundation

Scope: Workbench and Capture HUD visual foundations.

Reviewer findings:
- Visual: The app still read as a pale settings utility. Cards, drawer, and HUD used similar white/cyan surfaces without enough hierarchy.
- UX: User-facing pages exposed too much system wording and did not make “what Agent can see” obvious enough.
- Engineering: Workbench and HUD tokens were drifting; screenshots could pass while real views differed.

Changes made:
- Tightened Workbench design tokens around a restrained macOS light glass palette.
- Reduced duplicated color usage by routing Workbench surfaces, text, borders, and shadows through shared Workbench tokens.
- Kept engineering terms out of user-facing card/drawer copy; diagnostics remain the place for IDs and raw references.

Artifacts:
- `.qa/round-02/workbench/*.png`
- `.qa/round-02/capture-hud/light/*.png`

Remaining:
- Full token unification with `WorkRecorderCaptureDesign` is not complete; several drawing paths still use low-level color constants.
