# Context Library Round 13 Hard Checklist

Reference: `/Users/example/Desktop/projects/workrecorder/.qa/context-library/reference.png`
Current target snapshot: `/Users/example/Desktop/projects/workrecorder/.qa/context-library/round-13/overview.png`

## Functional Gates

- [x] Search/filter/sort are backed by `ContextLibraryRecordProjection`, not decorative-only UI.
- [x] `安全摘要 / 工作上下文 / 完整上下文 / 待复核 / 处理中` are typed `ContextLibraryVisibilityMode` values derived from record state.
- [x] `Zero KB` copy is removed; storage uses numeric `0 MB / 10 GB`.
- [x] Grid fetches up to 100 recent records and does not silently cap at 8.
- [x] List view no longer caps at 10.
- [x] Unit tests cover search, sort, safe summary, full context, needs review, processing, and numeric storage copy.

## Reference-Match Gates

- [ ] Sidebar prism reads as natural thin-film refraction, not a hard ellipse or blue fog.
- [ ] Privacy/storage cards feel like floating glass-metal cards, not flat setting tiles.
- [ ] Privacy status card height matches reference proportions without looking squat or oversized.
- [ ] Main cards have strong physical floating depth: edge, inner highlight, shadow, hover/selected response.
- [ ] Thumbnails have real content weight and distinct page types, not generic skeleton placeholders.
- [ ] Main canvas and search/status controls align closer to the reference image.

## Expert Notes To Keep In View

- High-end light UI is not “everything pale.” It needs clear anchors: dark title text, real thumbnail density, crisp component edges, and visible but soft depth.
- Prism is a material signature, not decoration. It should live under the sidebar content and behind the lower cards, with blurred thin-film arcs and diagonal beams.
- WorkRecorder should read as a context control console: saved context objects, visibility state, local-first trust, and Agent readiness must be visible and true.
