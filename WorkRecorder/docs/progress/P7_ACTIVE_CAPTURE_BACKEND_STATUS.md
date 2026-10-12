# P7 Active Capture Backend Status

## Scope

P7.1-P7.10 are implemented as backend capabilities only. No menu entry, HUD,
Workbench card UI, storyboard page UI, player, or UI trigger is included in
this stage. P7.5 is represented by safe backend card/storyboard projections
that future UI can consume without changing the existing screenshot flow. P7.8
adds an Agent-safe inspect projection, and P7.9 adds typed policy-before-index
projection for active-capture text.

2026-05-31 appshot follow-up: screenshot UX work is now layered outside the
active-capture backend. It adds configurable native shortcuts, current-window
capture, and a region-recording command placeholder without starting Active
Capture sessions or changing the existing region screenshot save/search/inspect
defaults.

## Architecture Decisions

- Active Capture is a separate bounded context under `packages/active_capture`.
- Existing screenshot capture remains the source of truth for screenshot
  evidence; Active Capture observes successful commits through a post-commit
  hook.
- Keyframes link existing event, capture run, evidence, and artifact rows. Raw
  screenshot/video bytes are not copied into keyframe tables.
- Recording video artifacts are promoted through a separate MP4 validator and
  remain metadata-only by default. The backend parses MP4 `mvhd` duration from
  copied bytes before vault commit; client duration is only a bounded hint.
- Timeline media time is derived only from trusted internal/native monotonic
  timestamps. The public capture and completion APIs still reject caller
  supplied media-time or monotonic-time fields; native timing receipts require
  the local install secret before the daemon will honor them.
- Pause/resume is modeled as segmented recording: pause closes the current
  segment and opens a pause interval; resume starts a new segment. Timeline
  alignment stitches segment-local media times when segment clocks are present
  and falls back to trusted recording anchors for legacy/continuous producers.
- Event-driven keyframes are represented as typed trigger candidates with
  priority bands, debounce status, keep/drop reasons, diff thresholds, and
  candidate-to-keyframe linking. The scheduler does not run a UI loop; trusted
  native/headless producers submit candidates through the daemon API.
- Human demonstration trace is stored as a separate low-sensitive action graph:
  action event, coordinates, target refs, evidence links, and result
  observations. It records semantic hotkey categories and explicit coordinates,
  but not ordinary raw keyboard text.
- Agent inspect and UI storyboard are separate projections. Storyboard remains
  product/UI-oriented under `/v1/active-captures/{session_id}/storyboard`;
  Agent inspect is exposed only when callers explicitly request active-capture
  `event_inspect` sections.
- Active-capture searchable text goes through typed policy-before-index
  projection. Feature code submits `IndexableTextSource` records and receives
  auditable `SafeIndexProjectionBatch` results instead of passing loose
  `dict[evidence_id, text]` into the index backend.
- Screenshot/Appshot shortcut handling is now command-driven. macOS registers
  typed `current_appshot`, `region_screenshot`, and `region_recording`
  bindings through a `ShortcutRegistry`; user overrides persist locally and are
  mirrored to daemon `/v1/settings/shortcuts` as non-secret typed settings.
- Current-window capture reuses the existing screenshot pipeline. The native shell
  resolves the frontmost window via Accessibility when possible and falls back
  to WindowServer hints, then submits a single primary `WindowHint` with
  `capture_strategy=os_window` plus a trusted native timing receipt. The daemon
  rejects `os_window` attempts unless the local install secret is present and
  the receipt identity matches the primary frontmost hint.

## Completed

- [x] P7.1 typed contracts, state machine, settings, repository, headless
      session API.
- [x] P7.2 ordinary screenshot anchor keyframe baseline via non-blocking
      post-commit hook.
- [x] P7.3 start/final keyframe binding and optional locked video artifact
      promotion.
- [x] P7.4 timeline manifest builder with monotonic-to-media-time alignment.
- [x] P7.5 backend-safe recording card and storyboard projection, without UI.
- [x] P7.6 pause/resume/user mark/stop/max-duration-ready control contract,
      segmented recording manifest, and headless APIs.
- [x] P7.7 event-driven keyframe trigger candidates with debounce, priority
      bands, keep/drop diagnostics, and candidate-to-keyframe capture linking.
- [x] P7.10 low-sensitive human demonstration trace ledger with exact screen,
      screenshot-relative, and scope-relative coordinates, semantic hints,
      target refs, evidence links, and result observations.
- [x] Screenshot UX follow-up: default shortcuts changed to `⌃⌘2` current-window
      screenshot, `⌃⌘3` region screenshot, and `⌃⌥⌘R` region-recording
      placeholder; Workbench Settings now exposes shortcut status/reset/re-recording.
- [x] Current-window capture captures the frontmost window only, flashes a lightweight
      blue-white target-window overlay, opens the existing Light Sheet, and
      submits through `/v1/captures` with typed `manual_os_frontmost_window_hotkey`
      and `os_window` values.
- [x] Screenshot UX reviewer hardening: current-window flash now runs after the
      screenshot bytes are captured, `OS_WINDOW` routing fails closed unless a
      valid primary frontmost hint is present, shortcut validation uses enum
      modifiers and safe no-input errors even for scalar JSON payloads, the
      region-recording placeholder cannot launch region screenshot, and the
      menu Settings item opens the unified Workbench Settings page.
- [x] Appshot hardening: `OS_WINDOW` attempts require local native authority,
      trusted receipt metadata is matched against the primary hint, public
      inspect appshot metadata hides process/window ids and exact frames, and
      daemon shortcut settings mirror the native UserDefaults source rather
      than overwriting local bindings at launch.
- [x] Explicit `keyframes` inspect section; default screenshot capture response
      remains accepted-compatible.
- [x] Unit and integration tests for repository, state machine, anchor,
      headless recording, timeline, and video raw gate denial.
- [x] Reviewer round 1 fixes: capture retry no longer replays active-capture
      side effects, completed sessions are idempotent, terminal sessions ignore
      later keyframes, and timeline manifests are server-built instead of
      caller-supplied.
- [x] Extra tests for feature-flag short-circuit, completion retry, client
      timeline rejection, terminal keyframe rejection, raw video policy denial,
      timeline ordering/alignment, keyframe policy drops, MP4 validation, and
      cascade delete.
- [x] Reviewer round 2 fixes: capture binding no longer accepts client media
      time, inspect disclosure audit is trimmed with the returned sections,
      active-session reads filter deleted/restricted secondary events, bundle
      and timeline views are sanitized from existing keyframes, and video
      completion retry reuses already promoted recording artifacts.
- [x] Reviewer round 3 fixes: recording videos are prepared as uncommitted
      metadata and inserted atomically with the active-capture graph, failed
      graph writes leave no public recording-video artifact and keep staging
      retryable, session routes enforce owner checks, scoped bindings are
      matched before keyframe write, disabled active capture rejects headless
      session creation, and legacy active-capture delete triggers protect old
      `SET NULL` tables from stale references.
- [x] Final strict-review fixes: public bindings and completion commands reject
      caller-supplied monotonic/media timeline inputs, workspace-scoped sessions
      require a matching workspace header, region scopes enforce selection
      overlap, and transient video copy failures remain retryable without
      terminalizing the session.
- [x] Final P2 tightening: public bindings no longer accept caller-supplied
      sequence indexes, region overlap uses expected-area coverage instead of
      smaller-area overlap, and retryable video copy errors return HTTP 503
      with `retryable=true`.
- [x] Native recording E2E hardening: added a dedicated
      `WorkRecorderRecordingE2E` Swift executable that opens a target AppKit
      window plus a magenta sentinel window, records the target with
      ScreenCaptureKit `desktopIndependentWindow`, extracts start/final PNG
      keyframes from real frames, and emits typed fixture metadata.
- [x] Backend E2E now verifies real MP4 bytes enter the vault, MIME/magic/hash
      metadata is preserved, staging cleanup happens after commit, keyframes
      include screenshot and system-appshot evidence, timeline entries align
      from trusted native monotonic receipts, and raw recording-video access is
      still denied.
- [x] Native timing receipt gate added: untrusted capture requests carrying
      timing receipts are rejected unless the local install secret is present.
- [x] Production-code hardening pass: keyframe repository lookups now use
      `KeyframeRole` and `KeyframeTriggerKind`, recording video MIME and failure
      reasons are enum-backed, workspace/session `auto` sentinels are centralized
      in contracts, timeline alignment now carries typed status reasons, and
      workspace-scoped active-capture bindings ignore body-only workspace spoofing.
- [x] Native E2E reviewer fixes: ScreenCaptureKit sample buffers must be complete,
      AVAssetWriter append failures are surfaced, MP4 duration is read from the
      container, and the sentinel window deliberately overlaps the target to prove
      the recording is window-only.
- [x] Production-code reviewer fixes: recording scopes now fail closed instead
      of optional-field match-all, active-capture routes return a safe public
      view instead of raw `ContextKeyframe` graphs, video completion requires
      the install secret, recording timing uses typed `RecordingTimingAnchor`,
      keyframe sequence allocation moved into the repository transaction, and
      terminal quality policy fails sessions with no usable keyframe/video.
- [x] Video artifact hardening: copied MP4 bytes are hashed after daemon-owned
      temp copy, MP4 duration is parsed server-side from the copied file,
      reserved producer metadata keys are rejected, duration spoofing leaves no
      committed recording-video artifact, and raw-denial audit rows include the
      typed disclosure error details.
- [x] Cohesion cleanup: public-view projection moved into
      `ActiveCaptureViewProjector`, terminal state decisions moved into
      `TerminalSessionQualityPolicy`, and evidence-kind to keyframe-role mapping
      is explicit instead of a catch-all fallback.
- [x] Final reviewer P2 follow-up: active-capture public APIs now use dedicated
      session/timeline/video summary contracts rather than internal graph
      models, copied MP4 temp files are size-checked before probe/hash, trusted
      recording timing anchors can be bound to the target session, and sequence
      index conflicts retry inside the SQLite repository adapter.
- [x] Outbox hardening follow-up: screenshot post-commit work now uses a typed
      durable `capture_post_commit_outbox` written with the capture ledger
      transaction, a pluggable post-commit dispatcher, FastAPI after-response
      drain, and a daemon retry worker. The screenshot hot path no longer calls
      the active-capture keyframe hook directly.
- [x] Outbox reviewer fixes: durable tasks now store compact typed refs instead
      of copying the full capture envelope, use `handler_id` for plug-in
      identity, validate duplicate handler registrations, guard transitions with
      claim leases so stale workers cannot overwrite newer state, and route plus
      daemon drains share a safe drain wrapper.
- [x] P7.5-P7.10 backend layering pass: contracts are split into
      `active_capture_controls`, `active_capture_triggers`,
      `active_capture_demonstration`, and `active_capture_storyboard`;
      application logic is split into recording control, trigger scheduler,
      demonstration trace, and storyboard services; SQLite tables persist each
      graph separately instead of burying them in session metadata.
- [x] P7.6-P7.10 APIs: added `/controls`, `/segments`, `/triggers`, `/actions`,
      and `/storyboard` backend endpoints. Trusted native writers for segments,
      triggers, and actions require the local install secret.
- [x] Segment video hardening: trusted segment updates can promote staged MP4
      files into the vault with session+segment metadata, atomically persist the
      segment/video graph, clean staged files after commit, and expose only a
      typed public segment/video summary without hashes, staged paths, or
      producer metadata.
- [x] P7.7/P7.10 E2E hardening: the real macOS ScreenCaptureKit E2E now also
      records a backend user mark, accepted event-driven trigger candidate,
      human click action with explicit coordinates, segment manifest, and
      storyboard projection.
- [x] Demonstration trace tightening: coordinate requirements are action-kind
      aware, so click actions still require coordinates/targets while semantic
      hotkeys can be recorded without leaking raw keyboard text.
- [x] Final P7.5-P7.10 reviewer fixes: recording-video public projection now
      also protects event `include=artifacts` responses, action evidence refs
      are validated against the same session graph, action media time is
      server-derived from trusted segment clocks, failed segment graph writes
      discard prepared vault blobs, trigger submissions return typed capture
      instructions, and `typing_pause` actions reject free-text target fields.
- [x] Final blocker-only reviewer re-check completed with the existing reviewer
      set: no remaining P1/P2 blockers.
- [x] Repository quality-warning cleanup: split active-capture keyframe
      recording, recording public projection, session completion, SQLite row
      writers, and daemon completion routes into focused modules; tightened the
      quality audit to avoid method-level duplicate noise and to ignore schema
      string literals in complexity counts; full repository audit now reports
      zero violations and zero warnings.
- [x] Native input producer backend: added a typed producer-event bounded slice
      with `active_capture_producer_events` and
      `active_capture_producer_decisions`, plus `/producer-events` trusted
      ingestion that atomically derives P7.10 action traces and P7.7 trigger
      candidates for click, scroll, exact hotkey chord, typing pause, and
      focus/tab changes.
- [x] Keyboard privacy contract: shortcut/hotkey chords store physical key
      code, normalized label, modifiers, and semantic; ordinary typing is
      aggregate-only and rejects raw text/keystroke metadata at the contract
      boundary.
- [x] P7.11 preparation: added a safe `skill-distillation-input` projection
      over action sequence, exact shortcuts, trigger links, evidence keyframes,
      and review/sensitivity flags without exposing raw screenshots, video,
      DOM, a11y, or ordinary typed text.
- [x] macOS producer scaffolding: added an independent
      `ActiveCaptureInputEventProducer` with session-scoped CGEvent tap support,
      a privacy-preserving typing pause aggregator, classifier tests, and
      transport support for the `/producer-events` trusted endpoint. This does
      not alter the existing screenshot hotkey controller or UI.
- [x] Reviewer hardening pass for P7.7/P7.10:
      - validation errors no longer echo producer payload input values;
      - producer metadata rejects raw/typed/text/value/password/token-like keys
        including camelCase variants;
      - public producer ingestion rejects low-level `key_down/key_up`;
      - decision status now mirrors accepted/debounced/dropped trigger outcome;
      - debounced/dropped candidates no longer consume pending-trigger budget;
      - producer-driven accepted triggers now return native capture instructions
        that Swift parses and schedules through an injected handler;
      - captured producer candidates backfill `ProducerDecision.keyframe_id`,
        `ActionEvidenceLink(AFTER_KEYFRAME)`, and result observation for P7.11;
      - skill projection strips raw target fields and exposes only safe target
        refs plus typing aggregate.
- [x] Native timing/noise hardening: Swift producer now treats Enter/Escape as
      command hotkeys, coalesces scroll gestures before emitting `scroll_stop`,
      supports optional pointer scope bounds, re-enables disabled event taps,
      stops safely in `deinit`, logs transport failures, and no longer silently
      drops producer transport errors.
- [x] Final reviewer fix pass:
      - `/actions` validation errors now use the same no-input error formatting
        as `/producer-events`;
      - scoped sessions no longer silently replace missing producer-observed
        scope with the session scope for keyboard/scroll;
      - Swift producer events can carry a typed observed scope;
      - scheduled native capture instructions are tracked and cancelled on
        stop;
      - event tap callback ownership now uses a weak context object instead of
        self-retaining the producer;
      - `CaptureCoordinator` now exposes headless start/stop wiring and a real
        capture handler that submits `/v1/captures` with active binding and
        native timing receipt.
- [x] P7.8 Agent-safe inspect projection: added `ActiveCaptureInspectView`,
      `RecordingTimelineInspectView`, safe text blocks, video inspect refs,
      skill-readiness summaries, and typed active-capture citations under an
      explicit `EventInspectView.active_capture` section.
- [x] P7.8 batch loading: recording inspect loads session, keyframes, actions,
      controls, evidence links, producer decisions, timeline, and video refs in
      bounded repository calls, avoiding storyboard/inspect N+1 access patterns.
- [x] P7.8 citation hardening: `CitationRecord` can now carry typed
      active-capture target metadata for sessions, keyframes, action steps,
      text ranges, bboxes, and video time while raw image/video/DOM/a11y access
      remains behind the existing raw gate.
- [x] P7.9 safe index projection: added `packages/indexing/safety` with
      `IndexableTextSource`, `SafeIndexProjectionBatch`, sensitive-surface
      detection, redaction, fail-closed suppression, and a typed
      `IndexingService.index_safe_projection` entrypoint.
- [x] P7.9 active-capture indexing: session completion now builds a safe
      non-replacing active-capture index batch for summary, timeline captions,
      human demo summaries, and redacted event text. Suppressed sources produce
      audit decisions and are not indexed.
- [x] P7.8/P7.9 regression guard: default screenshot save, default search card,
      and default event inspect remain unchanged; active-capture inspect is
      returned only when explicitly requested with active-capture sections.
- [x] P7.8/P7.9 reviewer hardening: ordinary screenshot indexing now routes
      through a typed safe-projection compatibility adapter, active-capture
      index updates use scoped chunk-prefix replacement, inspect/search expose
      only coarse active-capture cards by default, hidden/restricted keyframes
      filter linked actions/producers, and storyboard/skill projections drop
      hidden-keyframe-backed steps while preserving safe hotkey/typing
      aggregate steps for P7.11 with review flags.
- [x] Final P7.8/P7.9 P2 fixes: active inspect now refuses to build when the
      session primary event is hidden even if a secondary keyframe event is
      visible; active-capture index chunk-prefix replacement escapes SQLite
      `LIKE` wildcards; skill-distillation projection uses session-level batch
      action evidence/observation readers; and skill-visible filtering also
      scrubs target keyframe/evidence/artifact refs that are not backed by
      visible keyframes.
- [x] Final P7.8/P7.9 blocker re-check with the fixed reviewer set: no
      remaining P1/P2 blockers.
- [x] P7.1-P7.10 final backend hardening pass:
      native producer-triggered `native_timing_receipt` keyframe capture now
      has an explicit trusted-secret transport path while ordinary screenshots
      still submit without the install secret.
- [x] Added a unified `RecordingSessionGraphReader` plus
      `ActiveCaptureVisibilityProjector` so inspect/storyboard/skill-safe
      projections can share one batch-loaded session graph and fail-closed
      reference cleanup.
- [x] Added typed projection budgets and truncation receipts for active
      inspect/storyboard/skill projections. Large sessions now expose bounded
      counts and cursors inside the active-capture projection without changing
      normal screenshot cards or default inspect output.
- [x] Split repository contracts into narrow active-capture ports while keeping
      the existing SQLite adapter and schema-compatible public API.
- [x] Producer input ingestion now plans an entire batch first and commits
      producer events, action trace rows, trigger candidates, and decisions in
      one repository transaction; graph-write failure leaves no partial
      producer/action/trigger rows.
- [x] Scoped keyboard/scroll/focus/tab producer events now require observed
      frontmost window/process/bundle identity. Pointer clicks can still use
      coordinate bounds as the fallback.
- [x] Added durable `index_policy_decisions` audit rows for successful
      policy-before-index writes. Audit rows store field/status/reason/surface
      and text hashes only, never raw text.
- [x] Added configurable safe-index and active projection policy knobs plus an
      active-capture telemetry port with null and in-memory implementations.
- [x] Added `ActiveCaptureCitationResolver` as the safe replay entry for
      active-capture citations; it revalidates the visible session graph before
      resolving keyframe/action/text/video-time targets.
- [x] Capture and active-capture write routes now use no-input validation error
      formatting, so local paths, tokens, and typed text are not echoed in
      validation responses.
- [x] Final reviewer P1 hardening follow-up: producer trigger debounce now
      honors batch-local candidates, strict native keyboard/scroll/hotkey
      events require observed scope identity, producer/action/trigger budgets
      are rechecked inside the SQLite commit transaction, video producer
      metadata is dropped before artifact persistence, active-capture citation
      replay rechecks run actor/workspace, index policy audit is persisted as
      pending before index upsert and marked indexed/failed afterward, and
      projection reads use bounded repository reads plus batch event lookup.
- [x] Final blocker-only reviewer re-check: architecture/performance reviewer,
      privacy/security reviewer, and native/E2E reviewer all confirmed no
      remaining P1/P2 blockers after the `BEGIN IMMEDIATE` producer batch
      transaction fix, strict scope fail-closed fix, safe route-error cleanup,
      skill-target ref scrub, and storyboard cursor addition.

## Reviewer Notes To Re-check

- Verify `packages/active_capture` stays layered and does not import capture
  persistence internals.
- Verify raw video is not exposed by `/v1/artifacts/{id}/raw`.
- Verify policy-before-index remains typed and fail-closed; no keyframe text is
  indexed directly without safe projection.
- Verify ordinary screenshot save/idempotency tests remain green.
- Verify future UI can consume `/v1/active-captures` without changing the
  existing screenshot flow.
- Round 1, round 2, round 3, and final strict-review findings from
  architecture, contracts/security, and tests have been addressed.

## Latest Quality Gate

- `swift test` in `apps/macos_capture`: 92 passed.
- `uv run pytest tests/unit tests/integration -q`: 324 passed.
- Targeted post-review shortcut/settings regression:
  `uv run pytest tests/integration/test_daemon.py::test_shortcut_settings_validation_does_not_echo_input_values tests/integration/test_daemon.py::test_shortcut_settings_round_trip -q`:
  2 passed.
- `uv run pytest tests/unit/test_active_capture.py tests/integration/test_active_capture_backend.py -q`:
  85 passed.
- `uv run pytest tests/e2e/test_macos_active_recording_e2e.py tests/e2e/test_macos_active_input_listener_e2e.py -q`:
  2 skipped by default because the macOS recording/input-listener E2E harnesses
  are opt-in.
- `uv run python -m scripts.audit_swift_quality --root apps/macos_capture`:
  clean.
- `uv run --extra dev python -m scripts.audit_repo_quality --strict --max-findings 0 --json-output .qa/reports/python-quality-current.json`:
  0 violations, 0 warnings.
- `uv run ruff check packages services tests`: clean.
- `uv run black --check packages services tests`: clean.
- `uv run mypy packages services`: success.
- `uv run pyright packages services tests`: 0 errors, 0 warnings, 0
  informations.
- `git diff --check`: clean.
- Native macOS real recording verification retained from the earlier P7.7/P7.10
  pass:
- `WORKRECORDER_RUN_MACOS_RECORDING_E2E=1 uv run pytest tests/e2e/test_macos_active_recording_e2e.py -q`:
  1 passed on macOS with ScreenCaptureKit permission; the test performs a real
  3-5 second window-only recording, vault promotion, MP4 MIME/magic/hash/duration
  validation, start/final and producer-triggered keyframe evidence capture,
  segment/user-mark/action/producer ingestion, P7.10 action evidence linkage,
  P7.11 safe projection checks, and timeline alignment checks.
- `uv run pytest tests/e2e/test_macos_active_recording_e2e.py -q`:
  1 skipped by default because the macOS recording E2E is opt-in.
- Added `tests/e2e/test_macos_active_input_listener_e2e.py` and
  `--active-capture-input-listener-e2e` native harness for opt-in real input
  listener coverage. Safety correction: the harness must not use global
  `CGEvent.post(.cghidEventTap)` keyboard injection in a normal desktop
  session because focus ownership can change between guard and post. It now
  posts only to the harness process PID and returns `focus_not_owned`/`no_events`
  diagnostics instead of risking input into other apps. Full global HID
  automation should run only in a dedicated isolated macOS test user/runner.
- `uv run pytest tests/e2e/test_macos_active_input_listener_e2e.py -q`:
  1 skipped by default because the native input listener E2E is opt-in.
- Targeted checks for the new input listener test:
  `ruff`, `mypy`, and `pyright` all clean.

Historical P7.1-P7.4 gates retained below:

- `pytest tests/unit/test_active_capture.py tests/integration/test_active_capture_backend.py -q`:
  50 passed after adding post-commit outbox coverage.
- `pytest tests/unit/test_capture_post_commit_outbox.py tests/integration/test_active_capture_backend.py -q`:
  44 passed after compact-ref, lease hardening, restart-drain coverage,
  current-event drain, and default screenshot response-shape coverage.
- `WORKRECORDER_RUN_MACOS_RECORDING_E2E=1 pytest tests/e2e/test_macos_active_recording_e2e.py -q`:
  1 passed on macOS with ScreenCaptureKit permission after outbox hardening.
- `pytest tests/e2e/test_macos_active_recording_e2e.py -q`:
  1 skipped by default unless `WORKRECORDER_RUN_MACOS_RECORDING_E2E=1`.
- `pytest tests/unit tests/integration -q`: 282 passed after outbox hardening.
- `swift build --target WorkRecorderRecordingE2E`: clean.
- `swift test` in `apps/macos_capture`: 80 passed.
- `mypy packages/active_capture packages/contracts/active_capture.py packages/contracts/capture.py packages/contracts/enums.py packages/artifacts/vault.py services/context_daemon/routers/active_captures.py services/context_daemon/routers/captures.py services/context_daemon/routers/artifacts.py tests/unit/test_active_capture.py tests/integration/test_active_capture_backend.py tests/e2e/test_macos_active_recording_e2e.py`:
  success.
- `black --check packages/active_capture packages/contracts/active_capture.py packages/contracts/capture.py packages/contracts/enums.py packages/artifacts/vault.py services/context_daemon/routers/active_captures.py services/context_daemon/routers/captures.py services/context_daemon/routers/artifacts.py tests/unit/test_active_capture.py tests/integration/test_active_capture_backend.py tests/e2e/test_macos_active_recording_e2e.py`:
  clean.
- `ruff check packages/active_capture packages/contracts/active_capture.py packages/contracts/capture.py packages/contracts/enums.py packages/artifacts/vault.py services/context_daemon/routers/active_captures.py services/context_daemon/routers/captures.py services/context_daemon/routers/artifacts.py tests/unit/test_active_capture.py tests/integration/test_active_capture_backend.py tests/e2e/test_macos_active_recording_e2e.py`:
  clean.
- `pyright packages/active_capture packages/contracts/active_capture.py packages/contracts/enums.py packages/contracts/capture.py packages/artifacts/vault.py services/context_daemon/routers/active_captures.py services/context_daemon/routers/captures.py services/context_daemon/routers/artifacts.py tests/unit/test_active_capture.py tests/integration/test_active_capture_backend.py tests/e2e/test_macos_active_recording_e2e.py`:
  0 errors, 0 warnings.
- `ruff check packages/capture packages/storage packages/contracts services/context_daemon tests/unit/test_capture_post_commit_outbox.py tests/integration/test_active_capture_backend.py tests/conftest.py`:
  clean.
- `black --check packages/capture packages/storage packages/contracts services/context_daemon tests/unit/test_capture_post_commit_outbox.py tests/integration/test_active_capture_backend.py tests/conftest.py`:
  clean.
- `mypy packages/capture packages/storage packages/contracts services/context_daemon tests/unit/test_capture_post_commit_outbox.py tests/integration/test_active_capture_backend.py tests/conftest.py`:
  success.
- `pyright packages/capture packages/storage packages/contracts services/context_daemon tests/unit/test_capture_post_commit_outbox.py tests/integration/test_active_capture_backend.py tests/conftest.py`:
  0 errors, 0 warnings.

## 2026-06-01 Appshot + Shortcut Final E2E Hardening

- Built the real local app bundle with
  `./.venv/bin/python scripts/package_workrecorder_app.py --dev --verify`.
  `./.venv/bin/python scripts/package_verify.py` and
  `codesign --verify --deep --verbose=2 dist/WorkRecorder.app` pass. Strict
  codesign still fails directly in this Desktop/FileProvider worktree because
  FinderInfo xattrs are immediately reattached to `dist/WorkRecorder.app`. The
  same bundle contents pass strict codesign after staging outside FileProvider
  with `ditto --norsrc --noextattr dist/WorkRecorder.app
  /tmp/WorkRecorder-strict-verify.app`, so the manifest records the direct
  dist-path xattr issue separately from bundle signature validity.
- Launched `dist/WorkRecorder.app` directly. `/health` returned
  `service=workrecorder-local-daemon`, and
  `/v1/auth/native-capture-authority` accepted only the native capture secret.
  Adaptive daemon port resolution remains expected behavior when the resolved
  endpoint passes both health identity and native authority checks.
  `run-manifest-final-hardening.json` records git SHA, bundle mtime, resolved
  daemon URL, daemon pid, screen topology, quality gates, manual cases, and
  remaining environment-limited gaps.
- Real shortcut E2E reports written under `.qa/reports/macos-e2e/`:
  - `textedit-window-object-final.json`: `⌃⌘2` saved a TextEdit
    `screen.window.captured` event through `screencapture_window_object`.
  - `chrome-window-object-final.json`: `⌃⌘2` saved a Chrome current-window
    capture with `source.app_name=Google Chrome`.
  - `finder-window-object-final.json`: `⌃⌘2` saved a Finder current-window
    capture with `source.app_name=访达`.
  - `region-screenshot-final.json`: `⌃⌘3` preserved the existing region
    screenshot flow and saved `screen.region.captured` / `os_region`.
  - `recording-placeholder-final.json` and
    `recording-placeholder-final.png`: `⌃⌥⌘R` displayed the neutral
    “区域录制即将支持” placeholder and did not create a new event.
  - `workbench-settings-final.png`: Workbench settings page contains shortcut
    settings and visual OCR together in the unified “设置” page.
  - `chrome-provider-online-cft-final.json`: Chrome-provider online path passed
    with Chrome for Testing. The materialized browser extension registered as
    `web.browser_extension`, reported tab title `ACME Pricing Dashboard`, saved
    `evt_yp3EzrsirJNpwfNQ`, produced clean/canonical page text, and raw
    screenshot verification shows only the target browser window.
  - `final-bundle-textedit-smoke-final.json`: after the final sanitizer and
    packaging pass, the rebuilt `dist/WorkRecorder.app` handled `⌃⌘2` against a
    TextEdit frontmost window, saved `evt_x4E1uBmRxOnDZOTM` as
    `screen.window.captured` / `os_window`, used
    `screencapture_window_object`, and produced a system appshot inspect view.
  - `final-bundle-post-review-smoke-final.json`: after reviewer follow-up
    fixes and a final rebuild, the true `dist/WorkRecorder.app` handled `⌃⌘2`
    against TextEdit again, saved `evt_-9llFtvlh3Mp0DR-` as
    `screen.window.captured` / `os_window`, used
    `screencapture_window_object`, and produced a system appshot inspect view.
  - Startup-order hardening moved adaptive endpoint probing and browser
    extension materialization out of synchronous `RuntimeConfig.load()`. The
    app now loads a fast local/bootstrap config first, registers menu/hotkeys,
    then resolves the daemon endpoint and materializes the browser extension in
    a background startup task. If the resolved endpoint changes, runtime
    components are rebuilt against the final config before daemon start and
    provider registration.
  - `final-bundle-fast-startup-smoke-final.json`: after the startup-order
    refactor and final rebuild, the true `dist/WorkRecorder.app` handled
    `⌃⌘2` against TextEdit, saved `evt_JIBlOP3nmnb3wuq3` as
    `screen.window.captured` / `os_window`, used
    `screencapture_window_object`, and produced a system appshot inspect view.
  - `adaptive-port-blocker-current-window-strong.json`: with the persisted
    local endpoint intentionally written to stale `127.0.0.1:8765` and a
    recorded `workrecorder-port-blocker` process (`pid=80520`) listening on
    `127.0.0.1:8765`, the true `dist/WorkRecorder.app` resolved the daemon
    endpoint to `127.0.0.1:8766`, passed `/health` and native-capture authority
    on the resolved endpoint, and still handled `⌃⌘2` against TextEdit. The
    saved event `evt_0nbsL4A7KNsBkLFo` is `screen.window.captured` /
    `os_window`, has a delivered system appshot, public OS_WINDOW
    geometry/process/window/bundle identity redacted, and the raw screenshot
    verification shows only the TextEdit window object.
  - `stable-chrome-load-extension-only-retry.json`,
    `stable-chrome-open-n-extension-load-retry.json`, and
    `stable-chrome-provider-online-strong-retry.json`: stable Chrome 148 was
    retried with isolated profiles, the materialized extension path, local
    ACME fixture, and DevTools enabled. Chrome itself launched and DevTools was
    reachable, but the isolated profile never registered a WorkRecorder extension
    entry after `--load-extension`, and `/v1/providers/sessions` never reported
    `web.browser_extension`.
  - `stable-chrome-extension-load-diagnostics-v3.json`: follow-up Chrome-side
    diagnostics connected through DevTools/CDP with proxy disabled. The target
    list contained the ACME page plus built-in Google Hangouts and Google
    Network Speech extension targets only; `Target.getTargets` returned no
    WorkRecorder extension target, and Chrome Preferences/Secure Preferences had
    no WorkRecorder extension entry. The Chrome for Testing path remains the
    passing browser-extension evidence for provider routing and web text
    capture.
  - `ShortcutSettingsTests.registryReportsCarbonConflictForPreexistingHotKey`
    exercises same-process Carbon hotkey registration by pre-occupying
    `⌃⌥⌘9`; WorkRecorder reports the binding as `.conflict` with the
    “已被系统或其他 App 占用” message. This proves the UI/status path for
    Carbon registration failures, not arbitrary external app/event-tap
    conflicts. Separate-process conflict proof remains a release-lab case.
- Fixed findings from real E2E and reviewer pass:
  - Current-window Appshot now captures by WindowServer window id via
    `screencapture -l`, instead of display-cropping the window bounds.
  - `OS_WINDOW` routing now requires complete native identity
    (`process_id`, `window_id`, `bundle_id`, `display_id`, frame, frontmost)
    before trusting a primary hint.
  - Public OS_WINDOW payloads sanitize selection geometry, window/process/bundle
    identity, provider route ids, artifact storage handles, and macOS a11y
    source URIs such as `macos://a11y/<pid>/<window>`.
  - A11y provider token issue now uses the provider registration secret, not the
    install secret.
  - Browser provider routing no longer accepts generated app-name-only browser
    titles as a strong tab/window match.
  - Workbench runtime helpers were split into focused files to clear Swift
    structure audit warnings.
  - Daemon endpoint resolution now validates `/health`, install-secret token
    issuance, and native-capture authority without putting secrets in `curl` or
    process argv.
  - Browser extension connection config now prefers the materialized app config
    over stale Chrome storage, clears stale storage keys, and invalidates its
    runtime cache after token/websocket failure so adaptive port changes can
    recover.
  - Public projections now share `packages/safety.safe_metadata`: source cards,
    provider sessions, share snapshots, agent replay snapshots, artifact
    projections, and event inspect sanitize local paths, token-like text,
    provider/session ids, process/window ids, frame/display identity, and raw
    storage handles consistently.
  - Reviewer follow-up tightened the shared sanitizer for camelCase and
    query/header secret variants such as `apiKey`, `bearerToken`,
    `authToken`, `clientSecret`, `Authorization: Bearer ...`, bare
    `Bearer ...`, and `api_key=...` values.
  - Provider session diagnostics now sanitize `display_name` and `app_name`,
    not only tab metadata, and `/v1/events` create responses now return the
    same safe public event projection as list/get responses.
  - Final privacy review follow-up added unsafe-key sanitization, generic
    embedded HTTP URL query/hash stripping, and safe projection for
    agent-run replay, context bundle create/get/export, search entity query
    echoes, event change watches, and delete responses.
  - Browser extension connection handling now detects materialized daemon
    endpoint or provider-secret changes during heartbeat and reconnects, so an
    already-running MV3 worker does not silently stay attached to a healthy old
    adaptive port.
  - macOS runtime secret precedence is now consistent across install,
    provider-registration, and native-capture secrets:
    environment override, then local `~/.workrecorder/app-dev` secret store, then
    bundle fallback.
  - Public `system_appshot` projection no longer exposes process id, window id,
    frame, display id, bundle id, route id, command id, provider session id, or
    artifact ids for either current-window or region screenshots.
- Quality gates after the hardening pass:
  - `swift test --package-path apps/macos_capture`: 106 passed.
  - `WorkbenchRuntimeTests.runtimeConfigLoadDoesNotProbeOrMaterializeBrowserExtension`:
    proves the app-launch config fast path does not write daemon endpoint config
    or copy/materialize the browser extension.
  - `swift test --package-path apps/macos_capture --filter ShortcutSettingsTests`:
    11 passed, including same-process Carbon registration-denial coverage.
  - `./.venv/bin/python -m pytest tests/integration/test_daemon.py tests/unit/test_capture_routing.py tests/contract/test_system_appshot_contracts.py tests/unit/test_package_workrecorder_app.py tests/unit/test_verify_macos_app_e2e_manifest.py -q`:
    155 passed.
  - Targeted sanitizer regression:
    `tests/contract/test_system_appshot_contracts.py`,
    `test_provider_sessions_diagnostic_redacts_native_and_tab_identity`, and
    `test_event_metadata_views_sanitize_url_query`: 11 passed.
  - Final replay/bundle/search sanitizer regression:
    `tests/contract/test_system_appshot_contracts.py`,
    `test_agent_run_replay_redacts_caller_query_and_user_text`,
    `test_bundle_routes_redact_query_and_purpose_echoes`,
    `test_search_entities_redacts_echoed_query`,
    `test_agent_run_replays_search_inspect_bundle_usage_and_raw_snapshot`, and
    `test_bundle_show_and_export_hide_deleted_event_items`: 15 passed.
  - Targeted privacy/share/system-appshot checks:
    `tests/unit/test_context_share.py`, selected daemon provider/session tests,
    and `tests/contract/test_system_appshot_contracts.py`: 28 passed.
  - `./.venv/bin/ruff check apps packages services scripts tests`: clean.
  - `./.venv/bin/python -m mypy`: success.
  - `./.venv/bin/python -m pyright -p pyrightconfig.json`: 0 errors,
    0 warnings.
  - `./.venv/bin/python -m scripts.audit_repo_quality --strict --max-findings 80`:
    0 violations, 0 warnings.
  - `./.venv/bin/python -m scripts.audit_swift_quality --root apps/macos_capture --max-file-lines 700 --max-type-lines 450 --max-function-lines 120`:
    passed.
  - Browser extension `npm run typecheck` and `npm test`: passed, 9 tests.
  - `./.venv/bin/python scripts/verify_macos_app_e2e_manifest.py --manifest .qa/reports/macos-e2e/run-manifest-final-hardening.json --json-output .qa/reports/macos-e2e/manifest-validation-final.json`:
    passed with explicit warnings for release-lab/environment-limited rows.
    `--strict-release` fails as intended while release-lab caveats remain for
    Stable Chrome unpacked extension loading, external shortcut-conflict UI,
    physical multi-display, isolated AX-denied, and Notes visible-target
    evidence.
  - Manifest verifier hardening follow-up: passed cases now require existing
    report artifacts under the manifest report directory; `supporting_reports`
    are checked; free-text-only pass evidence is rejected; quality gates use
    explicit pass predicates and unknown gates fail closed; `--strict-release`
    errors if a passed row still has a matching open risk.
  - `./.venv/bin/python -m pytest tests/unit/test_verify_macos_app_e2e_manifest.py -q`:
    17 passed, including negative cases for nonexistent reports,
    missing supporting reports, free-text-only pass evidence, failed quality
    gates, unknown quality gates, and strict-release risk conflicts.
  - `./.venv/bin/python scripts/check_macos_app_release_lab.py --manifest .qa/reports/macos-e2e/run-manifest-final-hardening.json --json-output .qa/reports/macos-e2e/release-lab-preflight.json`:
    completed the current-machine release-lab profile. It reports one blocker
    (`multi_display`: only one display detected), two manual setup requirements
    (`isolated_ax_denied`: needs isolated TCC state, and
    `external_shortcut_conflict_ui`: needs Workbench-visible external conflict
    proof), and two ready-to-validate rows (`stable_chrome` and
    `notes_visible_target`).
  - Release-lab preflight follow-up: Stable Chrome readiness now uses
    case-specific proof (`browser: "stable_chrome"` on a passed Stable Chrome
    row), so Chrome for Testing pass evidence cannot satisfy the Stable Chrome
    release row. External shortcut UI readiness now requires helper-driven UI
    proof (`external_helper_ui: "passed"` or a dedicated passed case), so
    deleting the open risk cannot mark it complete.
  - `swiftc -typecheck scripts/macos_hotkey_conflict_helper.swift`: passed. The
    helper is available only as a release-lab diagnostic; helper output alone
    must not mark external shortcut-conflict UI complete.
  - `./.venv/bin/python -m pytest tests/unit/test_check_macos_app_release_lab.py tests/unit/test_verify_macos_app_e2e_manifest.py -q`:
    22 passed, including regressions that Chrome for Testing cannot satisfy
    Stable Chrome readiness and removing the external shortcut open risk cannot
    satisfy helper-driven Workbench conflict UI proof.
  - Reviewer release-lab preflight follow-up: no P0/P1 blockers after the
    Stable Chrome and external shortcut UI proof fixes.
  - `git diff --check`: clean.
- Environment limitations:
  - This machine exposes one built-in Retina display only, so real negative
    coordinate / mixed Retina multi-display cases could not be executed here;
    geometry remains covered by Swift tests.
  - Screen Recording denied was validated with an isolated temporary bundle and
    produced the expected macOS permission prompt/no-event behavior.
  - Accessibility-denied while Screen Recording is granted still needs an
    isolated QA user or TCC fixture; this developer machine was not mutated into
    that state.
  - Stable Chrome 148 did not register the unpacked extension in an isolated
    profile on this machine even when DevTools was reachable and
    `--load-extension` was passed; DevTools/CDP and Chrome Preferences confirm
    no WorkRecorder extension target/entry. Chrome for Testing did register and
    validate the same extension/daemon/web evidence route.
  - Notes did not produce a stable visible target in this session; TextEdit,
    Preview, Finder, System Settings, Chrome, overlap, fullscreen/Spaces, and
    no-target cases are covered.
  - External Carbon shortcut conflict was not reproduced with a dedicated helper
    app in this pass; internal duplicate, weak shortcut, reset, and persistence
    were validated.

### 2026-06-01 App Bundle E2E Stabilization Follow-up

- Real `dist/WorkRecorder.app` was rebuilt and relaunched with the Settings page
  opened through the app bundle (`--open-settings`) instead of `swift run` or a
  package executable. The daemon resolved to the adaptive endpoint
  `http://127.0.0.1:8766` and `/health` returned `ok`.
- Real Workbench Settings refresh exposed a backend regression: the page showed
  "未能读取数据，因为它的格式不正确。" because its refresh fetched recent captures
  with `limit=100`; search returned a non-JSON 500 once a delivered snapshot
  contained malformed URL-like text (`ValueError: Invalid IPv6 URL` in
  `safe_public_payload`).
- Fixed `packages/safety/safe_metadata.py` so malformed embedded HTTP URLs and
  malformed URL-valued fields fail closed to `[url:redacted]` instead of
  raising. Regression added in
  `tests/contract/test_system_appshot_contracts.py`.
- Verification:
  - `./.venv/bin/pytest tests/contract/test_system_appshot_contracts.py -q`:
    11 passed.
  - `./.venv/bin/pytest tests/unit/test_package_workrecorder_app.py -q`:
    13 passed.
  - `swift test --package-path apps/macos_capture --filter ShortcutSettingsTests/workbenchLaunchPageResolverSupportsSettingsAndDiagnosticsE2EEntrypoints`:
    passed.
  - In-process daemon using the real app-dev database returned 200 for
    `/v1/search?limit=45`, `limit=50`, and `limit=100`.
  - Relaunched true `dist/WorkRecorder.app`; Workbench Settings AX text no longer
    includes the stale "格式不正确" error, and the live daemon returned 200 with
    70 results for `/v1/search?limit=100`.
- Added a tiny launch test entrypoint for E2E automation:
  `--open-settings`, `--open-diagnostics`, and `WORKRECORDER_WORKBENCH_OPEN_PAGE`.
  This only controls the initial Workbench page and does not alter user
  capture behavior.
- External shortcut conflict helper follow-up: real testing showed a separate
  helper process can register `⌃⌥⌘9` while WorkRecorder can still register the
  same Carbon chord and display "已启用". The helper/preflight/manual docs now
  state that helper output is diagnostic only; this row can be marked passed
  only if Workbench itself reports an external conflict. The release-lab gap
  remains open rather than being overclaimed.
- Release-lab verifier follow-up: `--strict-release` now directly fails when
  `shortcut_validation.external_helper_ui != "passed"`, even if the textual
  open risk is removed. The legacy
  `passed_automated_carbon_conflict_plus_manual_internal_validation` status is
  no longer accepted as a pass.
- Release-lab preflight follow-up: if the manifest records a known failed helper
  diagnostic such as `not_passed_helper_diagnostic_only`, the external shortcut
  row is `MANUAL_SETUP_REQUIRED`, not `READY_TO_VALIDATE`; helper output alone
  cannot advance the release checklist.
- Reviewer follow-up found the first malformed URL fix still allowed
  `https://[broken]/path?token=...` to leave the query-like suffix behind.
  `HTTP_URI_RE` now consumes bracketed malformed URL-like tokens through the
  next safe delimiter, and tests cover both direct sanitizer and
  `DeliveredSnapshotBuilder.safe_payload(SearchResponse(...))`.
- Post-review verification:
  - `./.venv/bin/pytest tests/unit/test_check_macos_app_release_lab.py tests/unit/test_verify_macos_app_e2e_manifest.py tests/contract/test_system_appshot_contracts.py -q`:
    34 passed.
  - Targeted `ruff`, `ruff format --check`, `mypy`, and `pyright` on the
    changed sanitizer/preflight/verifier/tests: clean.
  - Live true-bundle daemon after restart returned 200 with 70 results for
    `/v1/search?limit=100`, and the Workbench Settings AX text no longer shows
    the previous "格式不正确" refresh error.

### 2026-06-01 Stage Closeout Quality Gate

- Re-ran the closeout quality gates for the current Appshot/shortcut release
  candidate:
  - `./.venv/bin/ruff check packages/safety/safe_metadata.py scripts/check_macos_app_release_lab.py scripts/verify_macos_app_e2e_manifest.py tests/unit/test_check_macos_app_release_lab.py tests/unit/test_verify_macos_app_e2e_manifest.py tests/contract/test_system_appshot_contracts.py`:
    clean.
  - `./.venv/bin/ruff format --check ...`: clean.
  - `./.venv/bin/mypy -m packages.safety.safe_metadata -m scripts.check_macos_app_release_lab -m scripts.verify_macos_app_e2e_manifest -m tests.unit.test_check_macos_app_release_lab -m tests.unit.test_verify_macos_app_e2e_manifest -m tests.contract.test_system_appshot_contracts`:
    success, no issues.
  - `./.venv/bin/pyright packages/safety/safe_metadata.py scripts/check_macos_app_release_lab.py scripts/verify_macos_app_e2e_manifest.py tests/unit/test_check_macos_app_release_lab.py tests/unit/test_verify_macos_app_e2e_manifest.py tests/contract/test_system_appshot_contracts.py`:
    0 errors, 0 warnings.
  - `./.venv/bin/pytest tests/unit/test_check_macos_app_release_lab.py tests/unit/test_verify_macos_app_e2e_manifest.py tests/contract/test_system_appshot_contracts.py -q`:
    38 passed.
  - `./.venv/bin/python scripts/audit_repo_quality.py --strict --max-findings 80`:
    0 violations, 0 warnings.
  - `swift test --package-path apps/macos_capture --filter ShortcutSettingsTests/workbenchLaunchPageResolverSupportsSettingsAndDiagnosticsE2EEntrypoints`:
    passed.
  - `swiftc -typecheck scripts/macos_hotkey_conflict_helper.swift`: passed.
  - `git diff --check`: clean.
- Re-ran manifest release-lab checks:
  - Normal manifest verifier passed with explicit environment-limited warnings.
  - `--strict-release` intentionally fails on the remaining release-lab gaps:
    multi-display, isolated AX-denied TCC, Stable Chrome extension registration,
    Notes visible target, and external shortcut-conflict UI proof.
  - Release-lab preflight now reports multi-display as blocked, AX-denied and
    external shortcut UI as manual setup required, and Stable Chrome / Notes as
    ready-to-validate on a suitable lab setup.
- Rebuilt the real app bundle with
  `./.venv/bin/python scripts/package_workrecorder_app.py --dev --verify`.
  `dist/WorkRecorder.app` was rebuilt and signed; `codesign --verify --deep
  --verbose=2 dist/WorkRecorder.app` reports the bundle is valid on disk and
  satisfies its designated requirement. `scripts/package_verify.py
  dist/WorkRecorder.app` also passed.

## Known Follow-ups

- Split video probing/validation out of `LocalArtifactVault` into an
  active-capture `VideoProbe`/`VideoValidator` port; keep the generic vault
  focused on staging, atomic copy, hashing, and content-addressed storage.
- Add a repository-level aggregate append that refreshes keyframe bundles in the
  same transaction as keyframe append; sequence allocation now has unique-index
  retry protection, but bundle refresh still happens immediately after append.
- Continue splitting `ActiveCaptureService` into smaller session/keyframe/video
  finalizer services as the backend grows.
- Replace per-keyframe evidence-count lookups in `ActiveCaptureViewProjector`
  with a batch repository projection if active sessions grow large.
- Productize the native ScreenCaptureKit recording producer after UI/trigger
  design; current Swift executable is an opt-in E2E harness, not a user entry.
- Add Workbench/card/storyboard UI in a later design pass.
- Add native producer wiring for real app click/scroll/hotkey event streams once
  UI/permission design is decided; the daemon-side contracts, storage, and
  trusted ingestion gates are now in place.
- Decide the product permission/UX for enabling the native input event tap in
  user-facing recording sessions. The backend and native producer module are
  ready, but this work intentionally avoids menu/HUD/Workbench UI wiring.
- Add P7.11 `SkillDistillationService` over the persisted demonstration trace;
  current code intentionally stores the reviewable IR and does not auto-publish
  skills.
