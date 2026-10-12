# UI Round 04 - Evidence Inspector

Scope: Right-side drawer, tabs, and Agent-visible summary.

Reviewer findings:
- Visual: Native segmented tabs looked bolted on and too default.
- UX: Drawer header exposed event IDs too early; it should answer “Agent 会看到什么？” first.
- Engineering: Diagnostic data should stay available, but only in the Diagnostics tab.

Changes made:
- Replaced native segmented control with custom light-glass tab buttons.
- Removed event ID from the normal drawer header.
- Reframed the summary tab around default visible, on-demand, and locked evidence.
- Expanded drawer width and spacing so the close button no longer hugs the edge.

Artifacts:
- `.qa/workbench/overview-selected.png`

Remaining:
- Copy actions and tab keyboard shortcuts need a runtime pass.
