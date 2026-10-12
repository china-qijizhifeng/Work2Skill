# 阶段 3：事件入库

> 导航：[返回文档总览](README.md) · 上一篇：[阶段 2：采集](02_COLLECTION_CN.md) · 下一篇：[阶段 4：增强与去噪](04_ENRICHMENT_CN.md)

入库阶段回答：

> provider 采回来的材料，如何变成一条可审计、可验证、可复盘的上下文事件？

WorkRecorder 不把采集结果简单塞进一个 JSON 字段。它会把一次截图拆成 event、evidence、artifact、ledger、audit 多层记录。这样后面才能回答：这段文本从哪里来？谁采的？什么时候采的？有没有改过？Agent 什么时候看过？

## 一次 accepted capture 会生成什么

一次成功截图会产生一份本地案卷，核心对象包括：

| 对象 | 用途 |
| --- | --- |
| `ContextEvent` | 产品层和 Agent 层看到的事件 |
| `EventCaptureEnvelope` | daemon 内部权威案卷，串起触发、路由、采集、增强、索引 |
| `EvidenceRecord` | 每条证据的来源、时间、provider、command、父证据 |
| `Artifact` | 实际内容：PNG、HTML、JSON、Markdown、文本块等 |
| `artifact_provenance` | artifact 之间的来源关系 |
| `provider_command_runs` | provider command 的开始、结束、状态、错误 |
| `provider_capture_outcomes` | 每个 provider route 的成功、失败、跳过、超时 |
| `evidence_bundle_records` | 每个系统/App/派生 bundle 产出了哪些 evidence |
| `capture_run_source_bindings` | 一次截图命中的 primary/secondary 来源 |
| `enrichment_runs` | 增强任务的输入、输出、extractor version |
| `index_records` | 哪些 projection 被写入哪个 index backend |
| `audit_log_events` | 谁读过、怎么读、为什么读 |

这个结构看起来比“一个 events 表 + 一堆 payload”复杂，但它换来的是可追溯性。

这里的 primary/secondary 很重要。`ContextEvent.source_binding` 只代表这次截图的主来源，比如“Preview 的 PDF 窗口”或“Google Chrome 的网页”。其他被同一 bbox 压到的窗口、App provider 成功补到的材料，会进入 `capture_run_source_bindings`、`provider_capture_outcomes` 和 `evidence_bundle_records`，不会偷偷替换主来源。这样用户回看卡片时，主 App icon、标题和来源不会因为某个附属 provider 成功而漂移。

P5 之后，`system.appshot` 也会作为独立 evidence 入库。它不是 raw 截图，也不是 raw a11y tree，而是这次截图的系统底片目录：主 App、窗口事实、surface 列表、screenshot evidence id、a11y evidence ids、OCR 状态、权限和质量报告。它让 system-only event 也有清楚的“当时系统看到了什么”的复盘入口。

## EventCaptureEnvelope 是什么

`EventCaptureEnvelope` 可以理解为这次截图的“总案卷目录”。它包含：

- capture run id。
- event id。
- trigger 和 selection geometry。
- detected surfaces。
- route plan。
- provider outcomes。
- source bindings。
- evidence bundle records。
- provider command runs。
- system evidence。
- app evidence。
- enrichment records。
- artifact records。
- index manifest。
- policy snapshot。
- audit refs。

它不是给 Agent 直接消费的大对象，而是 daemon 入库、诊断和复盘的权威 IR。

## EvidenceRecord 为什么重要

Agent 看到一句话时，系统必须能反查这句话从哪来。

一条 `selection_text` evidence 应该能追到：

- 它是 daemon 增强生成的，不是 provider 伪造的。
- 输入来自哪些 a11y text blocks。
- 对应哪个 screenshot bbox。
- extractor 是哪个版本。
- 生成时间是什么。
- artifact id 是什么。
- policy 如何盖章。

这就是 EvidenceRecord 的价值。它把“文本”变成“有出处的证据”。

## Artifact Vault

artifact 是实际内容。WorkRecorder 用本机 content-addressed vault 存 artifact，而不是只存随手生成的路径。

每个 artifact 记录：

- artifact id。
- artifact type / role。
- content type。
- sha256。
- byte size。
- ingest state。
- sensitivity。
- redaction state。
- allowed scopes。
- sidecar manifest。

例如：

- screenshot 是 PNG artifact。
- full DOM 是 HTML artifact。
- a11y tree 是 JSON artifact。
- selection_text 是文本/JSON artifact。
- canonical_text 是 Markdown/text artifact。

## 为什么要 sha256 和 sidecar

因为 WorkRecorder 要能回答这些问题：

- 这张截图是不是当时那张？
- 这份 DOM 后来有没有被改过？
- bundle 里的 citation 能不能追到原始 evidence？
- agent replay 里的 snapshot 是不是当时实际返回的内容？

sha256 让 artifact 可以验证，sidecar manifest 让 artifact 的元信息离线也能读懂。

## 原子保存和失败处理

入库阶段必须避免“事件写了一半”的状态。

理想流程是：

1. 写 capture run 和 route diagnostics。
2. 保存 provider command 结果。
3. 写 evidence records。
4. 写 artifacts 和 vault sidecars。
5. 写 enrichment/index jobs。
6. 提交 transaction。

如果中间失败，系统需要留下可诊断状态，并通过 orphan sweeper 清理没有入库成功的 vault blob。

## system-only 也要清楚

P4 之后，WorkRecorder 不再把“App provider 没有补到内容”当成截图失败。

只要 staged screenshot 合法，这次截图就会生成 event：

- `system.screenshot` evidence 必有。
- `system.macos_a11y` 每次尝试，失败也写 diagnostic bundle。
- `system.appshot` 每次生成，只保存 refs、surface、permission、quality，不复制 raw bytes。
- OCR 对 accepted event 进入 job 状态；没配置时记录 skipped/config_required，不阻塞保存。
- App provider 成功就追加 app evidence；失败、超时、离线就写 provider outcome。
- 如果 bbox 只覆盖桌面背景，source binding 会是“桌面区域”；这仍然是一条可复盘 event，只是没有 App 深度增强。

真正不会生成 event 的情况应该非常少，例如截图文件非法、token/权限校验失败、staging 文件丢失。这些仍然会记录 rejected/failed diagnostics，但不是“非 Chrome”这种产品场景。

## provider outcome 怎么看

一次 capture 里，每个 provider route 都有 outcome：

| outcome | 大白话 |
| --- | --- |
| `succeeded` | 这个 provider 补到了证据 |
| `stale` | provider 存在但当前 session 不新鲜 |
| `skipped` | 策略或置信度导致本次不采 |
| `timeout` | 下发了命令，但 provider 没在期限内返回 |
| `failed` | provider 返回失败或结果不能入库 |
| `unsupported` | provider 明确说这个 surface 不支持 |

Workbench 里的“已保存 / 已增强 / 部分增强”，就是从这些 outcome 和 evidence bundle 推出来的。

## 入库后的默认权限

入库不是披露。artifact 先被 daemon 统一盖章。

默认策略大致是：

| artifact | 默认状态 |
| --- | --- |
| screenshot | raw visual，高敏感，只给 ref，raw 读取需审计 |
| full DOM | raw source，高敏感，默认隔离 |
| a11y tree | raw UI tree，高敏感，默认隔离 |
| provider diagnostics | debug provenance，默认不给 raw |
| selection_text | daemon 派生，DLP/redaction 后可做摘要 |
| clean_page_text | daemon 派生，精查可读 |
| canonical_text | daemon 派生，可索引、可 bundle、可 citation |

## 设计亮点

- **每条数据有来源**：provider、command、时间、父证据都记录。
- **每份内容可验证**：sha256 和 sidecar 防止“后来变了还不知道”。
- **事实和增强分层**：原始 evidence 不被增强逻辑覆盖。
- **入库和读取分离**：存下来了不等于 agent 能看。
- **失败也可解释**：unsupported/partial/failure 不再靠猜。

---

导航：[返回文档总览](README.md) · 上一篇：[阶段 2：采集](02_COLLECTION_CN.md) · 下一篇：[阶段 4：增强与去噪](04_ENRICHMENT_CN.md)
