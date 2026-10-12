# E2E Hardening Round 01

## Coverage Matrix

| Case | Automated | Manual / Opt-in | Gate |
| --- | --- | --- | --- |
| Chrome + extension online | hidden Chrome E2E | required before release | opt-in |
| Chrome extension offline | pending resilience E2E | manual app matrix | opt-in |
| Preview / PDF | synthetic integration | manual app matrix | manual |
| Finder | pending | manual app matrix | manual |
| TextEdit / Notes | pending | manual app matrix | manual |
| Desktop blank region | integration system-only | manual app matrix | quality + manual |
| Overlapping windows | synthetic integration | manual app matrix | quality + manual |
| a11y denied/granted | fixture integration | manual app matrix | manual |
| OCR config missing/success | integration | manual app matrix | quality + manual |
| CLI search/inspect/replay | live daemon + `workrecorder` subprocess E2E | n/a | quality |

## Evidence Checklist

- `trigger_id`
- `capture_run_id`
- `event_id`
- `system_appshot` evidence id
- screenshot artifact id
- provider outcomes
- CLI `events search` command
- CLI `events inspect` command
- `agent_run_id`
- replay snapshot id

## Privacy Checks

- No raw DOM in summary/search.
- No raw a11y tree in summary/search.
- No vault path or `storage_uri` in API payloads.
- No URL query/hash in agent-facing surfaces.
- Raw screenshot requires same-run `screenshot_ref`.
