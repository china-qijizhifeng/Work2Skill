# Context Library Round 18 Review

Reference: `/Users/example/Desktop/projects/workrecorder/.qa/context-library/reference.png`

Snapshots:

- `/Users/example/Desktop/projects/workrecorder/.qa/context-library/round-18/overview.png`
- `/Users/example/Desktop/projects/workrecorder/.qa/context-library/round-18/overview-selected.png`

## Hard Checklist

- [x] Search is backed by `ContextLibraryRecordProjection.filteredCards`.
- [x] Filters are backed by model state, not decorative chips.
- [x] `安全摘要 / 完整上下文 / 待复核` map from real evidence quality, visibility, and hidden material state.
- [x] Sort handles malformed dates with nil dates last.
- [x] Storage uses numeric copy (`0 MB / 10 GB`) and real local artifact usage.
- [x] App logo increased in card title row.
- [x] Search field and badge text vertical centering adjusted.
- [x] Secondary status filters moved into a real dropdown to reduce crowding.
- [x] Trust capsule restyled as a glass/satin control.
- [x] Sidebar privacy/storage cards reduced from the earlier oversized state.
- [ ] Card elevation reaches the reference image's floating physicality.
- [ ] Sidebar prism reaches the reference image's natural thin-film refraction.
- [ ] Thumbnails feel like real saved webpages rather than rendered placeholders.

## Reviewer Findings

### Visual

- Cards still read flatter than reference because the cast shadow and contact shadow are too weak relative to the large outer glass canvas.
- The sidebar prism is present but still looks like a faint graphic treatment, not a natural rainbow film scattering through glass.
- Chrome thumbnails are more differentiated than before, but the two text-heavy cards still lean synthetic.

### UX

- Collapsing secondary filters into `更多筛选` reduces crowding, but the active secondary state must stay visible in the button label.
- Selected detail drawer is useful, but its presence changes the grid to one column; the selected state must remain obvious.
- Chrome-only language is clearer after the search placeholder update.

### Engineering

- Functional mapping tests now cover search, filters, sort, visibility states, and storage copy.
- Still need stronger snapshot drift checks beyond the current smoke snapshots.

## Round 18 Fixes Applied

- Added a stricter clean-page-text mapping test so raw DOM does not claim `网页正文可补齐`.
- Added a dropdown control for secondary filters.
- Increased app logo size and corrected chip/search/dropdown vertical text alignment.
- Added card ambient/contact shadow layers.
- Reworked sidebar prism layers toward conic thin-film + diagonal beam refraction.
- Reduced sidebar status/storage card height.

## Remaining Round 19 Targets

- Make card elevation visibly stronger, especially in the 2x2 grid on the main canvas.
- Make sidebar prism colorful enough to be readable while staying glassy and not sticker-like.
- Improve thumbnail realism further if the next snapshot still reads like placeholders.
