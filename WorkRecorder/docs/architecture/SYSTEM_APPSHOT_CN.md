# System Appshot：只读系统底片

> 导航：[返回技术总览](../TECHNICAL_OVERVIEW_CN.md) · 相关：[阶段 2：采集](../02_COLLECTION_CN.md) · [阶段 3：事件入库](../03_EVENT_LEDGER_CN.md)

`system.appshot` 是 WorkRecorder 的系统快照层。它借鉴 Codex Appshot / Computer Use 里“看清当前 App 状态”的思想，但只做 **只读取证**：把一次截图当时的画面、窗口/App 事实、a11y 状态、OCR 状态、权限和质量诊断串起来，成为一份可以审计、可以复盘、默认不暴露 raw 内容的系统底片。

它不是新的 App provider，也不是用来点击、输入、滚动的自动化层。它只回答：

> 这次截图当时，系统侧知道了什么？这些事实来自哪里？质量如何？哪些权限影响了采集？

## 为什么需要 system.appshot

P4 之后，WorkRecorder 已经做到“截图先保存，App provider 只是增强”。但如果只看 screenshot、a11y、OCR、Web evidence 这些独立材料，用户和 Agent 很难一眼理解这次截图的系统事实。

`system.appshot` 做的是归档目录：

- 这次选区是什么。
- 主 App / 主窗口是谁。
- 还压到了哪些 secondary App。
- screenshot evidence id 是哪个。
- a11y evidence ids 是哪些。
- OCR 当前是 pending、skipped、completed 还是 failed。
- Screen Recording / Accessibility 权限状态如何。
- 质量诊断：有没有截图、有没有 a11y、surface 置信度怎么样。

换句话说，它像一张系统底片的索引卡。它让一次 capture 的系统证据变得更好解释，但不复制高敏感原料。

## 借鉴 Codex Appshot 的部分

WorkRecorder 借鉴的是产品心智和取证结构：

- 一次只读调用拿到当前 App/window 的视觉和 AX 状态。
- screenshot 与 AX tree/text 同一次 capture 入账，避免错时。
- 记录 frontmost/key window、bundle id、pid、window id、bounds、display scale 等窗口事实。
- 给 AX tree/text block 稳定的短期 element identity，方便后续 diff 和复盘。
- 权限状态明确入账：Screen Recording、Accessibility、目标 App policy。
- 质量报告明确入账：coverage、truncation、permission denied、stale surface。

WorkRecorder 不照搬的是动作层：

- 不点击、不输入、不滚动。
- 不解锁屏幕。
- 不后台持续录屏。
- 不把 raw screenshot / raw AX tree 默认给 Agent。
- 不让 appshot 决定搜索、bundle 或 disclosure。

## 和系统 provider 的关系

P5 之后，系统证据走统一的 provider SDK：

| provider | 做什么 | 输出 |
| --- | --- | --- |
| `system.screenshot` | 使用 macOS shell 已暂存的截图，不重复截图 | screenshot evidence / PNG artifact |
| `system.macos_a11y` | 命令本机辅助功能 provider 采 UI tree、text blocks、coverage | a11y tree / a11y text / coverage diagnostics |
| `system.appshot` | 聚合截图、窗口事实、a11y refs、OCR 状态、权限和质量 | system_appshot JSON artifact |

`system.appshot` 不是把截图和 a11y 内容复制一份。它只保存引用和安全元数据：

- `screenshot_evidence_id`
- `a11y_evidence_ids`
- `components`
- `surfaces`
- `permissions`
- `quality`

这样既能复盘，又不会把 raw 内容扩大泄漏面。

## 一次截图里的顺序

1. macOS shell 提交 capture attempt：bbox、note、staged screenshot、window hints。
2. daemon 做 surface detection：识别主窗口和附属窗口。
3. system providers 运行：
   - `system.screenshot` 复用 staged screenshot。
   - `system.macos_a11y` 尝试采框内文字和 UI tree。
   - `system.appshot` 生成系统底片草稿。
4. persistence 先保存 screenshot/a11y，再把真实 evidence id 和 artifact id 填回 appshot。
5. app providers 按 route plan 补强，比如 Chrome Web provider 返回 URL、DOM、网页正文。
6. daemon 继续跑 selection_text、OCR、canonical text、index。

最终一条 event 里会同时看到：

- 独立 screenshot evidence。
- 独立 a11y evidence。
- 独立 appshot evidence。
- 可能存在的 Web/PDF/其他 App evidence。
- 每个 provider 的成功/失败/跳过/超时 outcome。

## Agent 能看到什么

默认粗搜不会直接展示 `system.appshot`。Agent 看到的是安全摘要卡：主 App、标题、时间、用户 note、selection_text、hidden artifacts。

带 `event_id` 精查时，可以请求：

```bash
workrecorder events inspect <event_id> --view system_appshot --json
```

返回的是系统底片的安全摘要：surface、provider refs、权限和质量诊断。它不会返回：

- raw screenshot bytes。
- raw AX tree。
- full DOM。
- vault path。
- URL query/hash。

如果确实要看原图，仍然要走 raw artifact endpoint，并写 usage/audit trace。

## 为什么这层对未来重要

很多 App 没有第一方 provider。比如 Preview、Finder、TextEdit、Notes、PDF 阅读器、老旧企业系统窗口。`system.appshot` 让这些截图至少都有一份清楚的系统事实：

- 截了哪个 App。
- 窗口在哪里。
- 文字采得怎么样。
- OCR 有没有排队。
- 哪些权限影响了质量。

以后加 PDF provider、Slack provider、飞书 provider、IDE provider 时，它们不是替代 appshot，而是在 appshot 的系统底片上追加 App 专属增强。

这就是 WorkRecorder 的分层：系统底片负责“当时电脑上发生了什么”，App provider 负责“这个 App 内部还能补什么”。
