# UI Round 09 - QA Hardening

Scope: Tests and snapshot generation.

Reviewer findings:
- Engineering: Snapshot QA previously checked file presence rather than perceptual drift.
- Visual: Workbench snapshots were stale unless the environment variable was set.
- UX: Test fixtures should cover real usage, not only ideal ACME data.

Changes made:
- Regenerated HUD snapshots through `WorkRecorderCaptureSnapshots`.
- Regenerated Workbench snapshots with `WORKRECORDER_WRITE_WORKBENCH_SNAPSHOTS=1`.
- Swift tests confirm Workbench user-facing copy, card metadata, source line behavior, and HUD state behavior.

Artifacts:
- `.qa/workbench/*.png`
- `.qa/capture-hud/light/**/*.png`

Remaining:
- Pixel/perceptual diff is still not implemented; current verifier is structural.
