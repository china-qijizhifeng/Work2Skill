# Context Cockpit Round 24 Review

Reference image: `/Users/example/Desktop/9ba1bafb-e85d-4352-b361-70c438e66cd1.png`

## User Direction

- Home grid should go back to the older cleaner card-wall style.
- Do not put the full Agent evidence stack inside every home card.
- Keep improving the right drawer as the Agent-facing Inspector.

## Reviewer Findings Applied

### Engineering

- P0: Workbench called recent captures with `limit: 500`, while the daemon search API caps requests at `100`.
  - Fixed by adding `recentCaptureLimit = 100` and using it for refresh/search.
- P1: Search debounce spawned stale tasks.
  - Fixed by retaining and cancelling `captureSearchTask`.
- P1: Thumbnail loading could fan out over every filtered record.
  - Fixed by limiting prefetch to the first visible set and generation-guarding stale batches.
- P1: `⌘K` jumped to the history page instead of the current context library search.
  - Fixed by focusing the active overview/history search field instead of forcing History.

### Visual

- P0: Home card visual was too much like an evidence-control panel.
  - Fixed by removing Agent evidence stack chips and default/on-demand/locked count blocks from home cards.
- P0: Missing-thumbnail state looked like an unfinished blank/debug panel.
  - Fixed by restoring deterministic content previews for missing thumbnails and reserving real screenshots when available.
- P1: Agent visibility belongs in the Inspector, not in the card grid.
  - Kept Agent View / on-demand / locked sections in the drawer.

## Current Outcome

- Home cards are back to: large preview, title, source, one purpose line, status badge, more menu.
- Inspector keeps the stronger Agent View: default visible, on-demand, locked, and context stack.
- Workbench runtime tests pass.

## Remaining Issues

- Sidebar prism still needs more reference-grade thin-film scattering.
- Drawer tabs still look heavier than the reference and should be softened in the next pass.
- Search/filter state is functional, but canonical snippet matching still depends on the current API shape.
