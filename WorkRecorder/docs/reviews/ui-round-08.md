# UI Round 08 - Empty / Error / Permission States

Scope: Non-happy paths.

Reviewer findings:
- Visual: The app needs to look intentional when there is no image, no text, pending enrichment, or low confidence.
- UX: Noisy selection should be a gentle warning, not a scary error.
- Engineering: Fixtures should keep these states visible in snapshots.

Changes made:
- Added preview records for low-confidence selection, missing selection text, and pending/locked materials.
- Evidence cards now show an amber warning row for noisy selection text.
- Missing thumbnails use a calmer frosted placeholder with Light Lens styling.

Artifacts:
- `.qa/workbench/overview.png`
- `.qa/workbench/history.png`

Remaining:
- Real daemon failure modes still need end-to-end Workbench snapshots with live data.
