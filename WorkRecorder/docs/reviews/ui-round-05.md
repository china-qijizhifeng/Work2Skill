# UI Round 05 - Interaction Pass

Scope: Clickability, discoverability, and user-facing actions.

Reviewer findings:
- Visual: Primary actions were visible but not yet strongly connected to evidence inspection.
- UX: Card click should clearly open details; action labels should say what happens.
- Engineering: More interaction tests are needed for hover preview, keyboard navigation, and copy behavior.

Changes made:
- Card CTA changed from generic “查看详情” to “查看证据”.
- History subtitle and card copy now set expectation that clicking opens Agent-visible evidence.
- Search/filter scaffolding was added to the history page.

Artifacts:
- `.qa/workbench/history.png`

Remaining:
- Hover preview, Space to pin preview, `[`/`]` tab shortcuts, and `⌘C` evidence copy remain unimplemented.
