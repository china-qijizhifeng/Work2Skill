# WorkRecorder Browser Extension

Development-only MV3 provider for Web-source capture evidence.

The extension is intentionally an adapter. It keeps a local WebSocket provider
session with the daemon and never writes the event ledger, vault, audit log, or
retrieval index directly.

## V1 Responsibilities

- Register a provider session on `/v1/providers/sessions/ws`.
- Wait for daemon-issued `CollectEvidenceCommand` messages.
- Return typed `ProviderEvidenceBundle` records for URL, origin, title, viewport
  geometry, selected text, visible text, page text/readability markdown,
  selection map, and full DOM.
- Avoid cookies, localStorage, hidden secret fields, passwords, and network/API
  response payloads.
- Full DOM is collected by default but is quarantined by daemon policy and is
  not directly indexed or exposed to agents.
- Page text/readability markdown is still source evidence. The daemon runs
  redaction/DLP and creates `clean_page_text` / `canonical_text`; the extension
  never upgrades raw DOM or source text into agent-readable final context.
- Page text v1 walks the live DOM, includes same-origin iframe text and open
  shadow-root text when readable, and records coverage gaps for cross-origin
  frames, unloaded documents, truncation, and other partial-capture cases.
- PDF-like tabs are marked partial unless the browser exposes readable DOM text;
  PDF raw DOM is never treated as complete page context by the extension.
- Use routed tab/window metadata from the daemon; do not collect from whichever
  tab happens to be active at response time.

## Local Setup

```bash
cd apps/browser_extension
npm install
npm run build
```

Set `workrecorderInstallSecret` in extension local storage before opening a
provider session. The scaffold deliberately does not ship a production install
secret in the bundle.

## Deferred

- Native Messaging install attestation.
- Generated TypeScript contracts from Python JSON Schema.
- Browser viewport screenshots except QA alignment.
