# UI Round 03 - Evidence Card

Scope: Evidence card scanability and multi-card states.

Reviewer findings:
- Visual: A single ideal card hid layout problems; multi-card states were needed.
- UX: User note should be promoted; status should be readable as product state, not backend state.
- Engineering: Preview fixtures needed noisy, missing, pending, and locked examples.

Changes made:
- Rebuilt card structure around thumbnail, title/source, user note capsule, evidence state, and primary “查看证据” action.
- Added multiple preview capture fixtures: normal webpage, noisy selection, missing selection, sync/pending-like source.
- Shortened status tokens to `Agent 可见` / `可补齐` / `原料锁定` style language.

Artifacts:
- `.qa/workbench/overview.png`
- `.qa/workbench/history.png`

Remaining:
- Hover preview and keyboard inspection shortcuts are still planned for a deeper interaction pass.
