# RFC 与当前实现对齐

早期 RFC 把 WorkRecorder 讲成“OS 截图入口 + Web source MVP”。现在主线已经往前走了一步：核心不再是“event + artifacts”，而是“一次可审计的上下文采集运行”。

## 已经对齐的设计

| 方向 | 当前实现 |
| --- | --- |
| 主对象是 Context Event，不是截图 | accepted capture 生成 ContextEvent 和 EventCaptureEnvelope |
| 截图只是证据之一 | screenshot 作为 system evidence artifact |
| provider 可插拔 | Provider session、manifest、routing、command service |
| Web 是第一个 App adapter | Chrome/Edge extension 通过 WebSocket 现场采集 |
| 系统证据独立 | screenshot、macOS a11y、system appshot 都是独立 system evidence provider |
| 本地优先 | SQLite ledger + local artifact vault |
| raw artifact 默认隔离 | full DOM、a11y tree、screenshot 默认不直接给 Agent |
| Agent 读取要安全 | Disclosure Policy SDK 构建 summary / inspect / raw view |
| 索引要可插拔 | `packages/indexing`，v1 SQLite keyword |
| Agent 使用要留痕 | Agent Run Ledger、Delivered Snapshot、Citation、Usage Event |

## 相比早期 RFC 的重要变化

### 1. 从短 TTL evidence 注册改成 event-driven command

早期想法里，extension 可以短 TTL 注册 context。现在成熟版是：

```text
extension 保持 session 和能力
截图发生时 daemon 选择 provider
daemon 下发 collect command
provider 现场采集 evidence bundle
```

这样更适合多 App，避免每个 App 一直轮询。

### 2. selection_text 成为正式 evidence

截图框内文本不是临时摘要。现在它是 daemon 从 a11y blocks 派生的正式 evidence，默认展示给 Agent。

### 3. Disclosure 独立于 Evidence Policy

入库时的 Evidence Policy 决定 artifact 的安全状态。读取时的 Disclosure Policy 决定这次 caller 能看到什么。

这让“存什么”和“给谁看什么”分开。

### 4. Search 变成 index layer

早期检索更多像 metadata list。现在有独立 indexing package，CLI/search/bundle 不直接绑某个 index 算法。

### 5. Agent Run Ledger 补齐可复盘

现在一次 Agent 回答不是无状态读取。系统能记录 query、inspect、bundle、citation、usage。

### 6. system.appshot 补齐系统底片

早期 RFC 主要关注“截图”和“网页补全”。现在多了 `system.appshot`：它不采新内容，而是把截图、窗口/App 事实、a11y/OCR 状态、权限和质量报告串成只读系统底片。这样非 Web、桌面区域、PDF/Preview 等 system-only event 也能被清楚复盘。

## 哪些早期表述已经过时

- “P0 不做 a11y”：已过时。当前 a11y 是系统 provider。
- “系统截图只是 persistence 特例”：已过时。当前截图、a11y、appshot 都走统一 system provider bundle。
- “extension 预推 DOM/text evidence”：已过时。当前截图时 daemon command 现场采集。
- “非 Web 完全不进入设计”：已过时。当前架构可支持系统-only 和多 App provider，只是产品验证先聚焦 Web。
- “search 返回裸 event”：已过时。现在默认返回安全摘要卡。
- “Context Bundle 可以从最近事件生成”：已过时。bundle 应走 search/index 候选和 disclosure/citation。

## 当前权威文档

- README：项目介绍和 quick start。
- `docs/TECHNICAL_OVERVIEW_CN.md`：总体技术简介。
- `docs/01_TRIGGER_CN.md` 到 `docs/06_AGENT_USAGE_CN.md`：六阶段设计。
- `docs/USER_GUIDE_CHROME_CASE_STUDY_CN.md`：用户手册式真实流程。
- 本文件：RFC 和代码对齐说明。
