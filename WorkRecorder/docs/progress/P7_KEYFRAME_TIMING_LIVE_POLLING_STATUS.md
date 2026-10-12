# P7 Keyframe Timing Live Polling Status

Last updated: 2026-06-07T05:33:00+08:00

## Scope

This document tracks the Active Capture adaptive-settle live polling V1 work. The goal is to replace immediate fixed-delay result keyframe capture with a backend-owned polling decision layer for accepted adaptive-settle candidates.

Non-goals for this pass:

- No P7.11 skill generation.
- No default screenshot behavior changes.
- No raw text, selector, AX path/name/value, OCR lines, local paths, storage URIs, or temporary probe image bytes in logs, audit rows, public projections, or index input.
- No continuous background monitoring outside an explicit active recording session.

## Completed

- Added typed live polling contracts:
  - `KeyframeTimingConfig` live polling fields.
  - `SettlePollingPlan`, `SettleSample`, `VisualDiffSummary`, `TextDiffSummary`, `ProviderReadinessSnapshot`, `SettleDecision`, `SettleAuditRecord`.
  - `SettleSignalKind`, `SettleSampleStatus`, `SettleDecisionStatus`, `SettleStopReason`, `ProviderReadinessState`, `VisualProbeMode`, `TextDiffMethod`.
- Added `packages/active_capture/keyframes/polling/` with contracts-facing ports, domain policies, degraded provider adapter, and application service.
- Kept `KeyframeTimingOrchestrator` write-free and `KeyframeTriggerScheduler` as the persistence/de-dupe boundary.
- Changed adaptive result trigger behavior:
  - Candidates with `settle_live_polling_state=pending|observing` no longer return a capture instruction in producer ingest responses.
  - Trusted native producers poll `POST /v1/active-captures/{session_id}/capture-instructions/pending`.
  - Polling finalizes candidates to `ready` before returning the final paired keyframe instruction.
- Added durable `active_capture_settle_audits` storage for safe sample/decision metrics.
- Added Swift producer support:
  - `CaptureTransport.pollPendingCaptureInstructions(sessionId:probeSnapshot:allowDegradedSample:)`.
  - `ActiveCaptureInputEventProducer` background polling loop during active recording.
  - Two-stage native polling: first ask for due work without a probe, then hide recording chrome and sample only when the backend reports observed candidates.
  - Claim-id de-dupe before scheduling native capture instructions, so a failed capture can retry after the backend lease creates a new claim.
- Added backend capture-claim hardening:
  - Pending polling requires bearer auth, install secret, and native capture secret.
  - SQLite claim uses an immediate transaction and CAS-style state checks.
  - Stale settle finalization cannot overwrite an unexpired `capturing` claim.
  - Capture binding metadata is restricted to a settle-safe whitelist with value-level validation for enum strings, counters, booleans, and claim ids.
- Added safe projection of settle explainability:
  - Final paired keyframes receive `settle_*` safe metrics in `KeyframeQualityReport.metrics`.
  - Public inspect/session views can explain stop reason, sample count, and needs-review state through existing quality fields.
- Added pre-due probe guard:
  - Pending poll responses expose `probe_required_candidate_count`.
  - Native Swift only hides recording chrome and samples when a candidate is actually due for a sample.
- Added native visual live probe support:
  - `ScreenCaptureService.probeRegionFingerprint(...)` samples the recording scope in memory via `CGDisplayCreateImage`.
  - Probe downsamples to a 16x16 buffer and stores only a luminance fingerprint plus safe diagnostics.
  - No temporary PNG, storage URI, raw image bytes, or vault artifact is created for probe samples.
  - Pending poll requests can carry `probe_snapshot.visual.sample_fingerprint`; backend binds it to due candidates as typed `SettleSample` rows.
- Updated controlled E2E harnesses to consume both immediate and pending capture instructions.

## V1 Provider State

Current runtime provider is hybrid:

- Native macOS recording sessions provide low-res in-memory visual fingerprints during pending instruction polling.
- Backend converts consecutive probe fingerprints into `observed -> changed -> stable` samples and only releases the final keyframe after the configured stability window.
- `DegradedSettleSampleProvider` remains the null-object fallback when the native probe is unavailable or permission/scope state prevents sampling.
- Provider readiness and text fingerprint providers are still conservative in V1; they remain typed ports and do not expose raw text or selectors.

## Remaining V1 Limitations

- Text/provider readiness adapter:
  - Redacted text fingerprint and length/source-count metrics.
  - Web/a11y/OCR/appshot readiness split by provider.
  - No raw text, OCR lines, AX names/values, DOM selectors, URL query/hash.
- Quality comparison E2E:
  - Controlled fixture with fixed strategy vs live polling.
  - Metrics: loading frames down, duplicate/no-change frames down, result-observed frames up.

## Tests Run

- `./.venv/bin/python scripts/quality_gate.py --skip-swift`
  - Result: passed; Python pytest 510 passed, 5 skipped; mypy/pyright/ruff/quality audit/site/browser-extension gates passed; repository audit 0 warnings.
- `swift test --package-path apps/macos_capture`
  - Result: 162 passed.
- `./.venv/bin/python -m pytest -q tests/unit/test_active_capture_keyframe_timing.py tests/integration/test_active_capture_timing_integration.py tests/integration/test_active_capture_backend.py`
  - Result: 86 passed.
- `git diff --check`
  - Result: passed.

## Review Notes

- Architecture boundary is intentionally split:
  - Ingest records user action facts.
  - Trigger scheduler persists candidates.
  - Polling service owns adaptive settle decisions.
  - Native producer only consumes finalized instructions.
- Privacy boundary is fail-closed:
  - Audit rows store only safe metrics and typed decisions.
  - Public capture instruction polling requires install-secret trusted writer access plus native capture authority.
- Reviewer blocker fixes completed:
  - Native probe no longer runs every 180ms when there is no due candidate.
  - Native probe also does not run for pre-due pending candidates.
  - Capture instruction claim is no longer a plain unconditional upsert.
  - Swift local de-dupe no longer permanently blocks lease retry after a failed capture.
  - Opt-in macOS recording/input E2E harnesses now include native capture secret for pending polls.
  - Crafted `/v1/captures` active-capture binding metadata with raw text/selectors/local paths is rejected before keyframe persistence, including dangerous values hidden under allowed settle keys.
- Final reviewer status:
  - Architecture/concurrency reviewer: no P0/P1/P2 findings; RC approved.
  - Privacy/security reviewer: no P0/P1 findings; RC approved.
  - Keyframe quality/E2E reviewer: no P1 blocker; RC approved.
- Known V1 limitation:
  - Native visual stability is implemented using a 16x16 luminance fingerprint; small localized or hue-only changes can still be false-stable.
  - Text/provider-readiness polling still uses typed ports plus conservative fallback and needs a later provider adapter pass.
