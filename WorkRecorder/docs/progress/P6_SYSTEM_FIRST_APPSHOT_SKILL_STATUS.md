# P6 System-first Appshot Skill Pack Status

## Scope

- Keep Workbench timeline out of this round.
- Harden system-first capture so valid screenshots save even when app providers are offline.
- Treat Chrome/Web as enhancement.
- Make `system.appshot` the safe system bottom layer.
- Upgrade `workrecorder-context` skill pack and CLI contracts.

## Completed

- `main` quality baseline pushed with Pyright in quality gate.
- P6 branch created from latest `main`.
- Reviewer round 1 completed for capture/appshot, skill/CLI, and E2E coverage.
- CLI subprocess smoke added so `workrecorder --help` must import without `PYTHONPATH`.
- CLI expected-error path now returns a parseable JSON envelope instead of JSON plus Python traceback.
- Skill references now document same-run `screenshot_ref` before raw screenshot access.
- Workbench copied inspect command now uses real inspect views.
- Local Apple Vision OCR provider scaffold added; default auto OCR records `skipped/config_required` unless local OCR is explicitly enabled.
- `system.appshot` inspect view overlays runtime OCR status.
- System provider failure diagnostics now carry error code/message into provider outcomes.
- Live daemon + real `workrecorder` subprocess test added for the agent-facing flow:
  `agent begin -> events search -> events inspect(system_appshot/screenshot_ref/evidence_refs) -> agent replay`.
- Repository quality audit is clean: 0 violations, 0 warnings.
- Reviewer round 2 completed for appshot/OCR, CLI/skill packaging, and E2E reliability.
- Apple Vision OCR helper moved into the package and verified in the built wheel.
- Visual OCR settings/test flow now treats Apple Vision as local default instead of requiring a model API key.
- Manual OCR runs now respect provider availability; unavailable local OCR records `skipped/config_required`.
- Auto OCR scheduling now honors disabled settings before reporting provider configuration problems.
- Appshot/system diagnostics now sanitize local paths, vault references, and storage URIs before safe metadata exposure.
- macOS hidden editable `.pth` repair is now run by quality gate and tests, so `.venv/bin/workrecorder` works without `PYTHONPATH`.
- CLI module execution now preserves nonzero exit codes for JSON error envelopes.
- Apple Vision probe now executes the Swift helper against an in-memory probe image instead of only checking files.
- `WorkRecorder.app --verify` now checks the Apple Vision helper exists in the configured runtime.
- `system.appshot` contracts now recursively reject local file, vault, and raw artifact locators.
- Safe metadata now redacts whole sensitive URI/path tokens, including strings nested inside lists.
- CLI daemon errors now preserve daemon error code, details, and request id in the agent-facing JSON envelope.
- Skill single-question workflow now creates a bundle before recording usage against a bundle id.
- Disclosure priority now keeps daemon-derived `selection_text` ahead of OCR text in default search cards; OCR remains fallback/enrichment.
- P6 final quality gate passed with 0 repo quality warnings.

## Reviewer Round 1 Findings

- Capture/appshot reviewer: main architecture is correct; improve system provider failure reason, appshot OCR status, and raw/vault metadata guard.
- Skill reviewer: fix CLI importability, JSON error shape, stale command examples, and raw access flow.
- E2E reviewer: add real macOS app matrix docs/scripts, CLI subprocess replay test, OCR unavailable test, and release report structure.

## Reviewer Round 2 Findings

- Appshot/OCR reviewer:
  - P1: manual OCR bypassed provider availability. Fixed by checking provider readiness before claiming a run.
  - P1: provider diagnostics could carry local path-like details. Fixed by sanitizing system diagnostics and safe metadata.
  - P2: visual OCR provider test was still API-key gated. Fixed so Apple Vision can be probed as the local default.
  - P2: disabled auto OCR could be reported as a provider config failure. Fixed by reordering scheduling guards.
- CLI/skill reviewer:
  - P1: console script importability could fail when macOS hid editable `.pth` files. Fixed with a repair helper wired into quality gate/tests.
  - P1: Apple Vision helper was outside package data. Fixed by moving the helper into `packages.enrichment.visual_ocr`.
  - P2: `python -m apps.cli.main` returned zero for expected JSON errors. Fixed with explicit process exit code.
  - P2: Workbench visual OCR copy still implied model OCR by default. Fixed to describe Apple Vision as the local default.
- E2E reviewer:
  - P1: live CLI subprocess test inherited unstable environment. Fixed by scrubbing agent/OCR/PYTHONPATH env vars.
  - P2: free-port test helper still has a small TOCTOU race. Tracked as residual test hardening work.
  - P2: manual E2E report was missing trace ids. Fixed report shape with run, event, evidence, artifact, and replay ids.

## Reviewer Round 3 Findings

- App packaging/E2E reviewer:
  - P1: packaged App defaulted to Apple Vision but daemon launch path did not enable the old hidden opt-in flag. Fixed by removing the hidden opt-in gate; Apple Vision is local default when Swift/helper are present.
  - P2: app package verification did not cover the Apple Vision helper. Fixed with runtime helper verification and a packaging unit test.
- Appshot/OCR reviewer:
  - P1: Apple Vision `probe()` only checked file existence. Fixed by executing the Swift helper with `--probe`.
  - P1: appshot contract only scanned metadata keys/limited values. Fixed with recursive locator rejection over the whole appshot payload.
  - P2: direct `VisualOCRService.run()` did not check provider availability. Fixed by enforcing provider availability before image preparation.
  - P2: invalid OCR base64 could leak a low-level binascii error. Fixed and covered by unit test.
- CLI/skill reviewer:
  - P1: CLI JSON errors erased daemon error codes. Fixed by carrying `ErrorCode`, details, and request id through `DaemonClientError`.
  - P1: safe metadata URI replacement kept sensitive path tails. Fixed with whole-token URI/path redaction.
  - P2: workflow doc recorded usage against a bundle id that had not been created. Fixed by adding `bundle create`.

## Final Automated Verification

- `./.venv/bin/python -m scripts.quality_gate`
  - normalize, ruff, mypy, Pyright: passed
  - pytest: 191 passed, 1 skipped
  - repository quality audit: 0 violations, 0 warnings
  - static site audit: passed
  - browser extension typecheck/build/test: passed
  - Swift tests: passed
  - Workbench snapshots and verification: passed
  - Capture HUD snapshots and verification: passed
  - `WorkRecorder.app` package verify: passed

## Remaining

- Add opt-in manual macOS app matrix runner/report for Chrome, Preview/PDF, Finder, TextEdit/Notes, desktop, overlapping windows, a11y permission states, and OCR states.
- Run reviewer rounds 3-10 after implementation hardening.
- Reduce the live daemon test port race by moving the fixture to a server-managed port or retrying on bind conflict.

## Verification

- `./.venv/bin/python -m pyright -p pyrightconfig.json`
- `./.venv/bin/python -m pytest tests/contract/test_cli_contracts.py tests/contract/test_system_appshot_contracts.py tests/integration/test_cli_live_daemon.py tests/integration/test_daemon.py::test_visual_ocr_settings_are_typed_and_masked tests/integration/test_daemon.py::test_visual_ocr_unavailable_after_capture_is_skipped_not_blocking tests/integration/test_daemon.py::test_manual_visual_ocr_respects_provider_unavailable_reason tests/unit/test_visual_ocr.py -q`
- `./.venv/bin/python -m pytest tests/integration/test_cli_live_daemon.py -q`
- `uv build --wheel --out-dir /tmp/workrecorder-wheel-check`
- `./.venv/bin/python -m scripts.audit_repo_quality --strict --max-findings 80 --json-output .qa/reports/python-quality.json`
- `./.venv/bin/python -m scripts.quality_gate`
