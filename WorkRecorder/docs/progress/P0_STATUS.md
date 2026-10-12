# P0 Status

Updated: 2026-05-20

## Current Focus

WorkRecorder macOS app UI/UX polish for a product-grade local capture workflow:

1. Capture HUD: clear screenshot bbox, readable Light Capsule, no overlay residue.
2. Workbench: evidence cards, multi-record states, and Agent-visible inspector.
3. QA: Swift tests, HUD snapshots, Workbench snapshots, and reviewer logs.

## Completed In This Pass

- Reworked Workbench visual tokens toward restrained macOS light glass.
- Improved Evidence Card layout: larger thumbnail, promoted user note, shorter status tokens, clearer `查看证据` action.
- Added multi-state preview records for normal, noisy, missing, and locked/pending evidence.
- Reworked Evidence Inspector tabs into custom light-glass controls and removed event IDs from the normal drawer header.
- Strengthened screenshot Light Lens visibility: stronger bbox, clearer non-selection veil, more visible corner bloom.
- Regenerated Workbench and Capture HUD snapshots.
- Added review logs `docs/reviews/ui-round-01.md` through `docs/reviews/ui-round-10.md`.
- Round 11: added saved-state handoff from HUD to evidence review (`查看证据 / 继续截图`), promoted evidence inspector summary, added search/filter/copy/tab keyboard affordances, improved missing-thumbnail previews, and recorded reviewer findings in `docs/reviews/ui-round-11.md`.
- Round 12: tightened Workbench control alignment and padding. Filter chips now use a custom centered control, status pills/evidence tokens share corrected baselines, and evidence-card right rails align `Agent 可见 / 需要复核` with `查看证据` as one action column. Findings are recorded in `docs/reviews/ui-round-12.md`.
- Round 13: used the real Meituan event shape (`selection_text` missing, `clean_page_text` available) to redesign the Evidence Inspector text flow. The Text tab now explains missing selection text, shows a local “网页正文已准备好” load panel, keeps loading feedback inside the tab, and renders loaded page text as selectable wrapping text. Added local-case snapshots and reviewer notes in `docs/reviews/ui-round-13.md`.
- Web extraction hardening: fixed browser page-text extraction for div-only SPA pages and ChatGPT-style `text-token-*` class names, added safe per-node fallback filtering, added ARIA grid markdown extraction, and documented capability boundaries in `docs/design/WEB_PAGE_EXTRACTION_STRATEGY_CN.md`.
- Selection evidence hardening: browser region candidates now remain hidden unless page text, selection map, and independent system evidence all agree. Workbench diagnostics explicitly distinguish verified selection text, browser candidate without map, map without candidate, and candidate+map that failed coordinate/evidence validation.
- Clean page text visibility: Workbench treats derived `clean_page_text` / readability evidence as loadable page-text sources, so the Text tab no longer reports “empty” when the daemon can provide webpage context on demand.
- Coordinate validation coverage: added pixel-region tests for `screen_px` selection maps, including a negative case where a browser map tries to pass macOS-global coordinates as pixels.
- Reviewer follow-up: tightened browser selection promotion so independent system evidence must cover the full candidate text, not merely a substring anchor. `screen_px` maps now fail closed without a `pixel_region` reference, and unsupported `screen_region.coordinate_space` values are rejected.
- Workbench follow-up: raw DOM is no longer presented as a loadable clean-page source by itself; clean-page availability now means actual derived `clean_page_text` / readability evidence. The Summary tab separates default Agent-visible fields from Workbench-only page text, and selection diagnostics use user-facing copy instead of exposing `selection_map` as normal UI language.

## Verified

- `swift test` passed for the macOS package.
- `WORKRECORDER_WRITE_WORKBENCH_SNAPSHOTS=1 swift test --filter WorkbenchRuntimeTests/workbenchSnapshotsRenderPrimaryPages` passed and regenerated Workbench snapshots.
- `swift run WorkRecorderCaptureSnapshots --output .qa/capture-hud` regenerated HUD snapshots.
- `uv run python scripts/verify_capture_hud_snapshots.py --root apps/macos_capture/.qa/capture-hud` passed.
- Round 12 also reran `swift test` and regenerated Workbench snapshots with `WORKRECORDER_WRITE_WORKBENCH_SNAPSHOTS=1 swift test --filter WorkbenchRuntimeTests/workbenchSnapshotsRenderPrimaryPages`.
- Round 13 verified the real event via CLI: selection text length `0`, clean page text length `11646`, canonical text length `11660`.
- Round 13 reran `swift test` and regenerated Workbench snapshots, including local-case inspector tabs.
- Browser extension `npm test` now covers div-only SPA text, benign token-named CSS classes, sensitive/hidden/nav fallback filtering, and ARIA grid extraction.
- `uv run pytest tests/integration/test_daemon.py tests/integration/test_selection_text_batch_e2e.py tests/unit/test_selection_text_realistic_cases.py -q` passed with 68 tests.
- `swift test --package-path apps/macos_capture` passed with 55 tests.
- `npm test --prefix apps/browser_extension && npm run typecheck --prefix apps/browser_extension` passed.
- Reviewer follow-up verification: `uv run pytest tests/integration/test_daemon.py tests/integration/test_selection_text_batch_e2e.py tests/unit/test_selection_text_realistic_cases.py -q` passed with 73 tests, and `swift test --package-path apps/macos_capture` passed with 56 tests.


## Visual OCR Enrichment Pass

- Added typed Visual OCR contracts and enums for provider kind, API profile, status, job type, and `visual_ocr_text` artifacts.
- Added settings and secret-store layers: local SQLite stores non-secret model settings, macOS Keychain/env fallback stores API keys.
- Added a pluggable enrichment package with provider protocol, OpenAI-compatible provider, prompt builder, service orchestration, and async job runner.
- Added daemon endpoints for Visual OCR settings, test, manual run, and event change long-polling.
- Capture save now schedules Visual OCR jobs only when explicitly enabled, without blocking screenshot save.
- Completed OCR output is persisted as derived selection-bound evidence, refreshes canonical/index data, and participates in disclosure/Agent-visible inspect views.
- Workbench now includes a “模型与视觉识别” settings page, manual OCR run/retry from the Text tab, pending/running/failed/completed status copy, and event-driven refresh.
- Prompt v1 constrains the model to visible screenshot content only, treats screenshot text as evidence not instructions, preserves reading order and GUI controls, and returns strict JSON for validation.
- Reviewer hardening pass:
  - Keychain writes now use Security.framework directly instead of passing API keys through `security -w` process arguments.
  - Capture hot path uses non-secret runtime flags and no longer touches Keychain just to decide whether OCR should be queued.
  - Auto/manual OCR runs are gated to selected-region screenshots or explicit upload-allowed screenshots, with sensitive app names skipped before provider upload.
  - Duplicate pending/running/completed OCR jobs are de-duplicated so repeated clicks do not repeat model calls.
  - OpenAI-compatible provider now tries schema-first structured output, falls back to JSON mode for incompatible endpoints, and retries once with a repair prompt when parsing fails.
  - OCR markdown is prefixed as untrusted observed evidence, while full typed OCR JSON is stored as a locked `visual_ocr_result` sidecar for diagnostics.
  - Workbench manual OCR failures now surface as failed state in the Text tab, and event polling is canceled when switching captures.

## Visual OCR Verified

- `swift test` passed for the macOS package with 56 tests.
- `uv run pytest tests/unit/test_visual_ocr.py tests/integration/test_daemon.py::test_visual_ocr_settings_are_typed_and_masked tests/integration/test_daemon.py::test_visual_ocr_job_appends_selection_text_and_refreshes_inspect -q` passed.
- `uv run pytest tests/unit/test_contracts.py tests/unit/test_capture_vault.py tests/unit/test_visual_ocr.py tests/integration/test_daemon.py -q` passed with 74 tests.
- Reviewer hardening verification:
  - `uv run pytest tests/unit/test_visual_ocr.py tests/integration/test_daemon.py::test_visual_ocr_settings_are_typed_and_masked tests/integration/test_daemon.py::test_visual_ocr_job_appends_selection_text_and_refreshes_inspect -q` passed with 7 tests.
  - `uv run pytest tests/unit/test_contracts.py tests/unit/test_capture_vault.py tests/unit/test_visual_ocr.py tests/integration/test_daemon.py -q` passed with 77 tests.
  - `swift test` passed for the macOS package with 56 tests.
- Final reviewer closeout:
  - Exported `VisualOCRElementRole` and `EventChangeType` through the contracts public boundary, fixing Visual OCR import/runtime.
  - Prompt now renders untrusted source metadata as fenced JSON and includes the strict generated schema in extraction and repair prompts.
  - Repair retries no longer resend the screenshot image; they repair the previous text output only.
  - OCR evidence markdown now blockquotes observed text and warnings so screenshot content remains evidence, not instructions.
  - Manual OCR requires both `run_enrichment` and `read_raw_artifact`; default dev install secrets cannot mint elevated scopes.
  - Workbench now decodes `skip_reason`, avoids retry loops for terminal skipped states, and disables OCR run copy when an API key is not configured.
  - OCR job claim now uses an atomic pending/failed/skipped to running transition to avoid duplicate model calls from repeated clicks.
  - Repository quality audit is down to three legacy warnings: `selection_text_enrichment.py` module/class length and `contracts/enums.py` module length.
- Final quality gate:
  - `uv run --extra dev python -m scripts.quality_gate` passed.
- Remote provider follow-up:
  - Visual OCR settings now support explicit remote HTTP OpenAI-compatible endpoints through `allow_insecure_remote_base_url`; localhost HTTP remains allowed, credentialed/query/fragment URLs remain rejected.
  - Prompt text moved out of Python literals into Jinja templates under `packages/enrichment/visual_ocr/templates/`.
  - Image preparation is now shared by daemon runtime and QA tooling through `VisualOCRImagePreparer`, so remote GPT-5.5 QA no longer bypasses resize/transcode behavior.
  - `scripts/run_visual_ocr_qa.py` can read the NorthCUA remote API config, run OCR against local screenshot artifacts, and write per-event markdown plus JSON reports without printing secrets.
  - Live GPT-5.5 QA with `/Users/example/Desktop/projects/nexcua/code/NorthCUA/config/agent.local.yaml` was run against all local screenshot events in `~/.workrecorder/workrecorder.db`: one valid PNG succeeded (`evt_Xq53foPLgh82Vjx_`, confidence 0.87), and the older `evt_qCVLEait67-rO7Ah` screenshot artifact is a 21-byte truncated PNG that correctly fails in image preparation before any model call.
  - Prompt tuning now discourages false table conversion for dashboard cards and enforces stable `[truncated: visible fragment]` formatting for clipped text.
  - App-dev E2E Visual OCR QA now uses the same NorthCUA remote GPT-5.5 config against `~/.workrecorder/app-dev/workrecorder.db`: settings update and provider probe succeeded, manual OCR completed for `evt_P2p4vxQqPp93cQTq`, and auto-run-on-capture completed for `evt_lRYiqHEIW9De2XKB`.
  - The E2E run verified the full daemon path `POST /v1/captures` → manual or auto OCR job → `/v1/events/{id}/changes` completed state → `event_inspect` disclosure containing `visual_ocr_text`, canonical text, and clean page text. Reports are saved in `.qa/visual-ocr-e2e/`.

## Visual OCR Remaining Work

- Add Workbench snapshots for Visual OCR pending/completed/failed inspector states.
- Add provider variants beyond OpenAI-compatible Responses/Chat profiles when needed.
- Add a daemon startup OCR job reconciler with leases/stale-running recovery, and make OCR append/job-completion fully idempotent in one transaction.
- Add per-capture external VLM upload consent/audit and stricter unknown-source auto-run policy before enabling auto-run broadly.

## Known Remaining Work

- Snapshot renderer and real HUD still have separate drawing paths; token sharing should be deepened.
- Workbench controller remains large; `EvidenceCard`, `EvidenceInspector`, and scene rendering should be extracted next.
- Hover preview needs runtime testing with real thumbnails.
- `CaptureCoordinator` and `WorkbenchWindow` still need extraction into smaller state-machine / renderer / presentation modules.
- Snapshot verifier still checks structure and basic image properties, not perceptual diffs.
- Hidden Chrome E2E remains opt-in and currently depends on local Chrome extension session registration; required coverage now includes browser extension unit-style content extraction tests in the quality gate.
