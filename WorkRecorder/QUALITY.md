# WorkRecorder Quality Gate

WorkRecorder 的质量门覆盖仓库卫生、静态站点、Python daemon/CLI 骨架，以及 macOS Capture HUD 的 Swift 测试和视觉快照。后续 extension tests、CLI contract tests 和 Playwright E2E 继续接入同一入口。

## Commands

```bash
# Run the full quality gate
uv run --extra dev python -m scripts.quality_gate

# Auto-format Python quality scripts, then run the full gate
uv run --extra dev python -m scripts.quality_gate --fix

# Equivalent npm-style shortcut
npm run quality
npm run quality:fix
```

## What It Checks Today

1. Python normalization with isort + Black.
2. NorthCUA-derived AST quality audit:
   - oversized modules
   - thin docstrings
   - public API docs
   - broad exception handling without logging
   - typing drift
   - TODO/FIXME debt
3. Static site audit:
   - missing local links/assets
   - duplicate HTML IDs
   - missing title/lang/viewport
   - legacy brand drift in public pages
4. Python bytecode compilation for `scripts/`.
5. JavaScript syntax check for `site/assets/app.js`.
6. macOS Capture HUD:
   - Swift unit tests
   - light-mode HUD snapshot generation
   - snapshot presence/dimension/design-reference verification

Reports are written to `.qa/reports/`.

## Design Notes

- The quality gate is intentionally strict for new Python scripts: the current baseline is `0 violation(s), 0 warning(s)`.
- Site auditing uses only the Python standard library so it can run before a Node frontend toolchain exists.
- Capture HUD snapshots are light-only by design. Dark-mode snapshot directories are treated as stale output.
- Future product code should be added behind this same command instead of introducing fragmented checks.

## Pre-commit

Install hooks with:

```bash
uv run --extra dev pre-commit install
```

The local hook runs the full WorkRecorder quality gate.
