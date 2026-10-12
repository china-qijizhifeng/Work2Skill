# UI Round 12 · Control Alignment Pass

Date: 2026-05-20

## Scope

This round focused on a narrow but important product-quality issue: controls and repeated UI elements were not sharing the same alignment rules. The visible symptoms were:

- Filter chips such as `全部来源 / 最近 7 天 / Agent 可见` had text sitting too high.
- Evidence status tokens such as `默认可见 / 网页正文 / 原料锁定` did not share a consistent baseline.
- Card right-rail controls (`Agent 可见 / 需要复核`, `查看证据`, helper text) were visually related but aligned as separate fragments.
- Sidebar labels and custom buttons used different vertical centering math from Workbench pills and tokens.

## Reviewer Inputs

### Visual Reviewer

Findings:

- The app had improved materially, but controls still felt assembled rather than designed.
- Repeated pills and chips were close in style but not close enough in height, baseline, and padding.
- Right-side card action content felt detached because the status pill and link did not start from the same x-axis.

Changes:

- Standardized Workbench button, status pill, evidence token, filter chip, and sidebar text vertical centering.
- Replaced toolbar filter labels with a real custom `WorkbenchFilterChip` so text centering is deterministic.
- Changed evidence-card right rails to leading alignment so `Agent 可见 / 需要复核`, `查看证据`, and helper copy form one clean column.

Remaining:

- The history page is still visually spacious. A future density pass should decide whether card height should shrink or whether cards should carry richer preview content.

### UX Reviewer

Findings:

- Click targets were visible, but repeated status controls did not feel like the same family.
- `查看证据` needed to read as connected to the card status, not as a separate floating link.
- Toolbar filters should feel tappable without becoming heavy buttons.

Changes:

- Filter chips now use a consistent 28px height, predictable horizontal padding, and custom centered text.
- Evidence-card right rail is now grouped as a single action stack.
- Status tokens keep short user-facing labels while avoiding noisy details in the default card view.

Remaining:

- Filter chips are still static in P0; when they become interactive, selected/hover/disabled states should be modeled explicitly.

### Engineering Reviewer

Findings:

- Baseline drift came from mixing `NSTextField` layer-backed labels with custom-drawn controls.
- New control metrics should be centralized instead of each component carrying independent magic numbers.

Changes:

- Added `WorkbenchControlMetric` values for action buttons, status pills, evidence tokens, and filter chips.
- Moved filter chips to a custom control instead of styling `NSTextField` directly.
- Ran Swift tests and regenerated Workbench snapshots after the alignment pass.

Remaining:

- `WorkbenchControlMetric` should eventually move into the shared design-token package so snapshot and runtime paths cannot diverge.

### HUD / Overlay Reviewer

Findings:

- This pass did not materially change HUD rendering.
- Workbench alignment fixes should not force HUD snapshot churn unless shared tokens change.

Changes:

- HUD snapshots were copied into `.qa/round-12` for review continuity; runtime HUD code was left untouched.

Remaining:

- HUD still needs separate runtime QA on a real white webpage after the next release build.

## Artifacts

- Workbench snapshots: `.qa/round-12/workbench/`
- Capture HUD snapshots: `.qa/round-12/capture-hud/light/`

## Verification

- `swift test` passed: 50 tests.
- `WORKRECORDER_WRITE_WORKBENCH_SNAPSHOTS=1 swift test --filter WorkbenchRuntimeTests/workbenchSnapshotsRenderPrimaryPages` passed and regenerated Workbench snapshots.
