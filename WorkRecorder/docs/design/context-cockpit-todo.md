# WorkRecorder Context Cockpit Implementation Checklist

Reference image: `/Users/example/Downloads/9ba1bafb-e85d-4352-b361-70c438e66cd1.png`

## Product Narrative

- [x] Rename the primary surface from a Chrome/card library to an Agent context cockpit.
- [x] Make the first screen explain that each record is a searchable, inspectable local context event.
- [x] Move Chrome/web wording into source metadata and filters instead of making it the product headline.
- [x] Show Agent visibility boundaries on each card: default visible, on demand, locked.
- [x] Make the Inspector first screen answer what Agent sees, not a generic details form.

## Functional Mapping

- [x] Search uses the recent-captures projection and filters by title, source, note, selection text, URL, and status.
- [x] Filters map to real projection state: Agent ready, needs review, locked materials, safe summary, full evidence package.
- [x] Sort order uses parsed capture timestamps and has a deterministic fallback.
- [x] Storage display uses numeric copy such as `0 MB / 10 GB`, never `Zero KB`.
- [x] Raw DOM is not presented as clean page text.
- [x] Browser candidate selection text is explained when it exists but fails coordinate validation.

## Context Cards

- [x] Cards use a typed evidence stack instead of loose text badges.
- [x] Cards show default-visible / on-demand / locked counts.
- [x] Missing thumbnails are labeled honestly and do not pretend to be webpage screenshots.
- [x] Real thumbnails are used when the daemon provides them.
- [x] Card hover and selected states use a directional key shadow and a rounded shadow path.
- [x] Replace the remaining large missing-thumbnail blank area with a denser deterministic preview while keeping it visually distinct from real screenshots.
- [x] Validate 1440x900 snapshots show four card previews and no evidence-stack clutter on home cards.

## Inspector

- [x] Rename Summary to Agent View.
- [x] Rename Raw Materials to Locked Materials.
- [x] Add visibility mode switch: safe summary, working context, full evidence package.
- [x] Add default-visible / on-demand / locked summary rows.
- [x] Add a context stack panel with note, selection, OCR, page text, screenshot, raw.
- [ ] Tighten the first-screen scroll height so the Agent view reads as a cockpit panel rather than a form.

## Visual Material

- [x] Rework top trust capsule copy and material.
- [x] Improve search, filter, sort button vertical centering.
- [x] Increase app source icon size in cards.
- [x] Reduce sidebar status/storage card height and keep numeric storage copy.
- [x] Keep prism behind sidebar content.
- [ ] Continue refining sidebar prism into thin-film scattering instead of an obvious ellipse.
- [ ] Tune card shadows against the reference: visible right-bottom lift without global 360-degree haze.

## Tests

- [x] Workbench navigation copy test updated for Context Cockpit.
- [x] Search/filter/sort mapping test covers real projection behavior.
- [x] Storage copy test locks numeric zero.
- [x] Evidence stack model test locks Agent-visible and locked count mapping.
- [x] Snapshot smoke test renders primary pages and Inspector tabs.
- [ ] Add heuristic snapshot check for card shadow clipping and card/container padding.
