# WorkRecorder Documentation

[English](README.md) | [简体中文](README.zh-CN.md)

WorkRecorder organizes human operations into recording sessions: select a recording region, confirm, perform the workflow, finish recording, then review and export in the recording center. The default shortcut is `⌃⌥⌘R` (Control+Option+Command+R).

Keyframe images are saved as operation evidence. Refer to the [product guide](../README.md) for installation and the current user workflow.

## Current Entry Points and Implementation

| Entry | Contents |
| --- | --- |
| [WorkRecorder guide](../README.md) | Recording workflow, platforms, installation, permissions, review, and export |
| [macOS development](../apps/macos_capture/README.md) | Running and verifying the native recording app |
| [Linux AT-SPI collector](../apps/linux_capture/README.md) | Desktop service, SSH startup, evidence formats, and recording modes |
| [Browser provider](../apps/browser_extension/README.md) | Web evidence interface and development setup |
| [Recording module](../packages/active_capture/) | Sessions, actions, keyframes, timelines, and export implementation |

## Design and Historical Architecture References

These documents preserve design work and the earlier context-event architecture. Some describe older capture entry points, UI, or planned functionality. The current code and project README define the current behavior. The design references below are in Chinese unless indicated otherwise.

- [Recording UI/UX](design/RECORDING_UI_UX_CN.md)
- [Large-screen recording review workspace](design/RECORDING_LARGE_SCREEN_REVIEW_CN.md)
- [Active Context Capture](design/USER_TRIGGERED_KEYFRAME_CONTEXT_CN.md)
- [Technical overview](TECHNICAL_OVERVIEW_CN.md)
- [System evidence and System Appshot](architecture/SYSTEM_APPSHOT_CN.md)
- [Earlier Chrome workflow case study](USER_GUIDE_CHROME_CASE_STUDY_CN.md)
- Six-stage architecture: [trigger](01_TRIGGER_CN.md), [collection](02_COLLECTION_CN.md), [event ledger](03_EVENT_LEDGER_CN.md), [enrichment](04_ENRICHMENT_CN.md), [indexing and disclosure](05_INDEX_DISCLOSURE_CN.md), and [agent usage](06_AGENT_USAGE_CN.md)
- [RFC and implementation alignment](RFC_CODE_ALIGNMENT_CN.md)
- [Agent skill](../apps/skill/SKILL.md) and [CLI reference](../apps/skill/references/cli.md) (English)

## Documentation Maintenance

Organize product documentation around recording sessions, operation evidence, review, and export. Distinguish implemented capabilities, optional collection, and planned integrations. Use English for every `README.md`, place Chinese translations in `README.zh-CN.md`, and provide language-switch links. Keep both versions synchronized.
