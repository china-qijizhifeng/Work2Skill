# WorkRecorder CLI Reference For Agents

Always pass `--json` so outputs remain parseable.
Most agent-facing commands auto attach an `agent_run_id` from `--agent-run-id`,
`WORKRECORDER_AGENT_RUN_ID`, the local active session, or the daemon implicit run
fallback. Context-delivering responses include `agent_run_id`,
`retrieval_call_id`, and `snapshot_id`.

The examples below assume the WorkRecorder virtual environment is active. You can also use
`scripts/workrecorder-cli ...` or set `WORKRECORDER_CLI=/path/to/.venv/bin/workrecorder`.

## Discovery

```bash
workrecorder daemon health --json
workrecorder agent begin --purpose customer_brief --question "Generate ACME renewal brief" --json
workrecorder agent current --json
workrecorder agent replay --json
workrecorder events ls --since 24h --app Chrome --limit 10 --json
workrecorder sources ls --since 7d --domain example.test --json
workrecorder entities ls --query ACME --json
```

`--since` and `--until` accept RFC3339 timestamps or relative values like `24h` and `7d`.
`entities ls` is currently a safe degraded placeholder until entity extraction/indexing lands.

## Search

```bash
workrecorder events search "ACME renewal risk" \
  --mode keyword \
  --since 7d \
  --workspace ws_acme \
  --app Chrome \
  --domain example.test \
  --status agent_ready \
  --explain \
  --json

workrecorder events grep "Budget variance" --since 7d --app Chrome --json
```

Search is intentionally compact. Each result shows only `event_id`,
`captured_at`, `app`, `title`, sanitized Chrome/Web `url`, `user_note`,
bounded `selection_text`, `selection_text_truncated`, and `available_fields`. Use
`events inspect <event_id> --view ...` for webpage body text, screenshot refs,
full selection text, evidence refs, system appshot, screenshot refs, or artifact
metadata.

Useful filters: `--since`, `--until`, `--workspace`, `--app`, `--domain`, `--origin`, `--source`, `--provider`, `--event-type`, `--evidence-kind`, `--status`, `--sensitivity`, `--entity`, `--project`, `--limit`, `--cursor`, `--sort`, `--explain`.

## Inspect

```bash
workrecorder events inspect evt_123 \
  --purpose agent_deep_read \
  --view selection_text \
  --view canonical \
  --view clean_page_text \
  --view screenshot_ref \
  --view system_appshot \
  --json
```

Supported views: `selection_text`, `visual_ocr_text`, `canonical`, `clean_page_text`, `screenshot_ref`, `system_appshot`, `evidence_refs`, `artifact_metadata`.
Prefer returned `citation_id` values over hand-written event references.

## Bundles

```bash
workrecorder bundle create \
  --query "Generate ACME renewal brief with risks and evidence" \
  --purpose customer_brief \
  --entity ACME \
  --max-tokens 8000 \
  --json

workrecorder bundle show cb_123 --json
workrecorder bundle export cb_123 --format markdown --json
```

Bundle items include `citation_ids` when WorkRecorder can map claims back to evidence.

## Citations

```bash
workrecorder citations resolve cit_123 --json
```

Citation resolution returns safe citation metadata and bounded text only when disclosure policy allows it.

## Shares

```bash
workrecorder shares create --event evt_123 --target feishu_drive --copy-link --json
workrecorder shares resolve workrecorder://share/shr_123 --purpose user_shared_context --json
workrecorder shares import "https://example.feishu.cn/file/..." --json
workrecorder shares import workrecorder://share/shr_123 --json
workrecorder shares sync shr_123 --json
workrecorder shares revoke shr_123 --json
workrecorder shares ls --user "Alice" --json
workrecorder shares jobs shr_123 --json
```

`shares create` freezes the exact safe summary snapshot for agent use and includes a full screenshot in the generated human-readable share package. If Feishu publishing succeeds, `--copy-link` copies the Feishu URL. If publishing is still pending or failed, `copyable_url` is empty; do not share the local `workrecorder://share/<share_id>` with other people.

`shares resolve` returns a safe card, available fields, hidden material names, screenshot artifact id/ref, and share refs. It must not return screenshot bytes, raw DOM, raw a11y tree, vault paths, URL query/hash, cookies, localStorage, sessionStorage, or provider raw diagnostics.

`shares import` supports local WorkRecorder share ids/links and WorkRecorder-generated Feishu file URLs when the local daemon has Feishu Drive read access configured. Import creates a local event card or returns the existing one when the link was already imported.

## Artifacts

```bash
# Step 1: same agent run must first receive a screenshot ref.
workrecorder events inspect evt_123 \
  --purpose user_requested_visual_check \
  --view screenshot_ref \
  --json

# Step 2: only then request raw screenshot bytes/ref through the raw gate.
workrecorder artifacts cat art_text_123 \
  --event evt_123 \
  --purpose agent_deep_read \
  --agent-run-id run_123 \
  --redacted \
  --json

workrecorder artifacts raw art_screenshot_123 \
  --event evt_123 \
  --purpose user_requested_visual_check \
  --agent-run-id run_123 \
  --output /tmp/workrecorder-screenshot.png \
  --json
```

Use raw only for explicit user-requested visual checks. By default `workrecorder artifacts raw` prints audit metadata and omits base64; pass `--output <file>` to write bytes locally, or `--inline` only when the caller explicitly needs base64 in stdout. Raw screenshot access requires a prior same-run `screenshot_ref` disclosure; raw DOM, raw a11y tree, provider diagnostics, vault paths, cookies, localStorage, sessionStorage, hidden inputs, and URL query/hash are never normal agent context.

## Usage

```bash
workrecorder usage record \
  --bundle cb_123 \
  --agent codex \
  --purpose customer_brief \
  --output-ref run_123 \
  --used-citation cit_123 \
  --json
```

Usage records close the loop for the current agent run. They point to the run ledger, retrieval calls, delivered snapshots, bundles, citations, and final answer reference.
