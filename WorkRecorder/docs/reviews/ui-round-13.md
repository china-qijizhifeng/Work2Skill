# UI Round 13 · Evidence Inspector Local Case Review

> 发布版说明：仓库中的文章 fixture 已替换为自编合成内容（`https://example.test`），不再包含第三方文章或真实采集标识。下文保留开发阶段的设计记录；历史截图名称仅用于兼容已有 QA 流程。

Date: 2026-05-20

## Local Case Under Review

- Event: `evt_GuSGyWRVrWxpxRp-`
- Source: `Google Chrome · https://tech.meituan.com`
- User note: `EvoCUA`
- Observed data shape:
  - selection text: missing
  - clean page text: available, 11,646 characters
  - canonical text: available, 11,660 characters
  - readable evidence: `canonical_text`, `clean_page_text`

## Reviewer Findings

### Visual Reviewer

- The Text tab looked like a blank or broken state when selection text was missing.
- The long page text did not visually appear in the loaded state because the previous full-text view behaved like an empty embedded scroll area.
- The unloaded state needed a clearer task panel instead of a lone button.

### UX Reviewer

- “加载网页全文” had weak feedback: clicking it replaced the whole drawer with loading, so it felt like the tab did nothing or got stuck.
- Missing selection text should not read like a failure. The user needs to know the screenshot and page body are still usable.
- Tabs need task-specific copy: Summary says what Agent sees; Text says what text evidence is available; Raw explains why materials are locked.

### Engineering Reviewer

- The previous snapshot set only covered a happy-path ACME fixture with good selection text. It did not lock the real failure shape.
- `textBlock(truncate: false)` still used truncating line behavior and an embedded text view that could render blank in snapshots.
- Clean-page loading should be local to the Text tab, not reuse the whole-inspector loading state.

### HUD / Overlay Reviewer

- No HUD changes in this round. Keep the focus on Workbench observability and inspector behavior.

## Changes Made

- Added local-case inspector snapshots:
  - `.qa/workbench/inspector-meituan-summary.png`
  - `.qa/workbench/inspector-meituan-text-unloaded.png`
  - `.qa/workbench/inspector-meituan-text-loaded.png`
  - `.qa/workbench/inspector-meituan-raw.png`
  - `.qa/workbench/inspector-meituan-diagnostics.png`
- Added a realistic Meituan fixture with missing selection text and available clean page text.
- Reworked the Text tab:
  - Missing selection text now shows an amber explanation panel.
  - Clean page text now has a clear “网页正文已准备好” task panel.
  - Clicking load uses a local loading state instead of blanking the whole drawer.
  - Loaded long text now uses wrapping selectable text, not a blank embedded scroll view.
- Updated the Evidence Card fixture so the selected card matches the open local-case inspector.

## Verification

- `swift test` passed.
- `WORKRECORDER_WRITE_WORKBENCH_SNAPSHOTS=1 swift test --filter WorkbenchRuntimeTests/workbenchSnapshotsRenderPrimaryPages` passed.
- CLI verified the real event has empty selection text but full clean page/canonical text.

## Remaining Issues

- The Workbench snapshot test now covers the local-case shape, but the app still needs deeper model extraction from `WorkbenchWindow`.
- The full-text reader is now reliable and visible, but could later gain a copy button and in-text find.
- Snapshot verification is still structural; perceptual diff remains future work.
