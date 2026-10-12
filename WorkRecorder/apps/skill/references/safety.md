# WorkRecorder Safety Rules For Agents

## Default Search Cards

Search returns safe cards only:

- `event_id`
- app/title/origin/sanitized URL
- capture time and selection bbox
- user note
- bounded screenshot selection text
- hidden artifact type names
- match reason and optional safe explain data
- preview citation id when available

Search can use canonical or clean text internally, but it must not echo that text in default cards unless disclosure policy allows it.
The daemon stores a replay snapshot of exactly these safe delivered fields for the current `agent_run_id`.

## Event Inspection

Use `workrecorder events inspect` only after choosing an `event_id`. Request narrow views:

- `selection_text` for screenshot-box text
- `canonical` for DLP/redacted agent-readable text
- `clean_page_text` for cleaned page text
- `screenshot_ref` for an audited raw screenshot reference
- `evidence_refs` for citation paths

`evidence_refs` is ref-only unless a text view such as `selection_text`, `canonical`, or `clean_page_text` is explicitly requested.

## Share Links

WorkRecorder share links are audited context packages. They may include a full screenshot for the human-readable HTML page, but `shares resolve` must still behave like coarse search: safe summary first, screenshot only as a ref. Treat the returned `safe_context` as the readable source of truth.

- Import Feishu/WorkRecorder share URLs with `workrecorder shares import ... --json`, then inspect the returned event id.
- Resolve only local share ids or links that already exist on this machine.
- Do not infer that a Feishu/Drive URL grants permission to raw event internals.
- Do not request raw DOM, raw a11y tree, vault paths, URL query/hash, cookies, storage, or provider diagnostics from a share.
- If a share has no external URL, treat it as not ready for sharing. `workrecorder://share/<share_id>` is local-only and should not be sent to another person.

## Raw Access

Raw bytes are not default context. Raw screenshot access requires:

- explicit user need
- `event_id`
- `purpose`
- `agent-run-id`
- a prior same-run `workrecorder events inspect <event_id> --view screenshot_ref --json`
- daemon policy approval

Never request raw full DOM, raw a11y tree, provider diagnostics, cookies, localStorage, network payloads, password values, hidden inputs, vault paths, or URL query/hash.
Raw access snapshots record only safe metadata, hashes, and byte counts. They do not duplicate raw bytes into the agent run ledger.
Prefer `workrecorder artifacts raw ... --output <file> --json` for screenshots; the CLI omits base64 from stdout by default. Use `--inline` only for an explicit caller that needs base64.
