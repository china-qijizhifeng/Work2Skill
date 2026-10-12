# WorkRecorder Agent Workflows

Keep every command JSON-first and let the daemon enforce disclosure policy.
Activate the WorkRecorder virtual environment to use `workrecorder`, or use the bundled `scripts/workrecorder-cli` wrapper.

## Single Question

```bash
workrecorder agent begin --purpose answer_user_question --question "用户的问题" --json
workrecorder events search "关键词" --since 7d --explain --json
workrecorder events inspect evt_123 --purpose agent_deep_read --view selection_text --view canonical --view evidence_refs --json
workrecorder bundle create --query "用户的问题" --purpose answer_user_question --json
workrecorder citations resolve cit_123 --json
workrecorder usage record --bundle cb_123 --agent codex --purpose answer_user_question --output-ref arun_123 --used-citation cit_123 --json
workrecorder agent replay --json
```

## Visual Check

Only use this when the user explicitly asks to inspect the image.

```bash
workrecorder events inspect evt_123 --purpose user_requested_visual_check --view screenshot_ref --json
workrecorder artifacts raw art_screenshot_123 --event evt_123 --purpose user_requested_visual_check --output /tmp/workrecorder-screenshot.png --json
```

## Multi-Event Answer

```bash
workrecorder agent begin --purpose synthesize_context --question "跨多个截图整理结论" --json
workrecorder events search "项目名 风险" --since 14d --workspace ws_project --json
workrecorder bundle create --query "项目名 风险" --purpose synthesize_context --max-tokens 8000 --json
workrecorder bundle show cb_123 --json
workrecorder usage record --bundle cb_123 --agent codex --purpose synthesize_context --output-ref arun_123 --json
```

## Shared Context Link

Use this when the user pastes a WorkRecorder share link or asks you to use shared screenshot context.

```bash
workrecorder agent begin --purpose user_shared_context --question "用户让我读取这条分享上下文" --json
workrecorder shares import "https://example.feishu.cn/file/..." --json
workrecorder events inspect <data.imported_event_id> --purpose agent_deep_read --view selection_text --view canonical --view screenshot_ref --json
workrecorder usage record --agent codex --purpose user_shared_context --output-ref arun_123 --json
```

Import first when the user gives a Feishu/WorkRecorder share link. The command either creates a local imported event or returns the existing event when it was already imported.
Use the `data.imported_event_id` field from `workrecorder shares import` as the next `workrecorder events inspect` target.

Optional local import:

```bash
workrecorder shares import "workrecorder://share/shr_123" --json
```

## Replay

```bash
workrecorder agent replay --agent-run-id arun_123 --json
```

Replay should show what was searched, which events were inspected, which fields were delivered, and which citations or bundles were used.
