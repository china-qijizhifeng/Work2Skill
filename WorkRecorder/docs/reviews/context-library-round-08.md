# Context Library Round 08 Review

## Reference

- Reference: `.qa/context-library/reference.png`
- Current: `.qa/context-library/round-08/overview.png`
- Selected: `.qa/context-library/round-08/overview-selected.png`

## Changes In This Round

- Enlarged the two-column context cards and thumbnails so the page reads as a card wall rather than a text list.
- Reworked the sidebar prism layer from a hard conic rainbow ellipse toward softer radial + diagonal thin-film light.
- Added stronger glass/satin treatment to sidebar privacy and storage cards.
- Added a privacy glyph to the privacy status card.
- Increased card content contrast, thumbnail density, lock badge size, and card lift.
- Updated footer copy to the product promise: local by default, confirm before sending to Agent.
- Wired `⌘K` to focus search and added a card `shadowPath` to reduce large-card shadow cost.

## Reviewer Findings

### Visual

- P0: thumbnail realism is still the biggest mismatch. Current generated previews are denser, but still feel like illustrative skeletons rather than downscaled real pages.
- P0: material still relies too much on outlines. Reference uses softer glass, inner light, and diffused card shadows.
- P0: left prism is still not reference-grade. It needs diagonal thin-film refraction with subtle cyan/pink/violet, not a teal wash.
- P1: badges and lock buttons need to be smaller and more icon-led.
- P1: typography is slightly heavier than the reference in sidebar, filters, and card metadata.

### UX

- P1: Chrome-only boundary is ambiguous. Main title/search/sidebar still imply all context types.
- P1: filters mix dimensions: source type, review state, Agent readiness, and evidence level.
- P1: cards need one scan line answering: source/domain, capture type, visibility, and send behavior.
- P2: search placeholder should explain scope: title, domain, note, OCR/page text.

### Reference Match

- P0: reference filters and card subjects differ from the current Chrome-only implementation.
- P0: bottom trust copy and placement differ from reference; product copy was intentionally kept more explicit.
- P1: top spacing and canvas scale differ because snapshot viewport differs from the reference image.
- P1: sidebar prism and avatar remain too teal and not enough blue/pink/purple.

### Engineering

- P1: larger cards can exceed narrow workbench widths; future fix should derive columns from available width.
- P1: storage usage is currently computed synchronously while rendering sidebar.
- P2: prism layers use Core Image filters and string compositing filters; consider prerender/cache or a single renderer path.
- P2: sidebar glass sheen layer has fixed frame; should become a reusable view/layer updating in layout.

## Fixed From Reviewer Feedback

- Added `⌘K` handling to match the visible search shortcut.
- Added card `shadowPath` to reduce the rendering cost of large shadows.
- Generated Round 08 screenshots after changes.

## Remaining Priorities

1. Make thumbnails substantially more screenshot-like or use real captured fixture thumbnails.
2. Split filters into source/status/evidence-level groups or commit visually to the reference filters.
3. Refactor sidebar glass card into a reusable component with layout-updated sheen.
4. Move storage usage calculation out of render path.
5. Normalize the snapshot viewport or add a reference-scale comparison mode.
