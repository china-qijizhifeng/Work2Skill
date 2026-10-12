# P7 Context Share + Feishu Upload Status

> 本文记录“保存并复制上下文链接”的实现进度。完成后会并入正式设计文档。

## 当前决策

- 本地 event 先保存，分享不影响本地保存成功。
- 默认 share scope 是 `agent_context_with_screenshot`。
- Agent 默认只看到安全摘要：note、时间、app、title、sanitized URL、selection text、available fields、hidden materials。
- 分享包会上传完整截图，方便人在飞书链接里查看；Agent 需要精查/视觉检查才读取截图内容。
- raw DOM、raw a11y tree、vault path、URL query/hash、cookies、localStorage、sessionStorage、provider raw diagnostics 不进入分享包。
- 飞书 MVP 使用应用自有目录 + tenant token + `tenant_readable` 权限。

## 已完成

- 新增 `packages/context_share` 独立层：share 创建、冻结快照、HTML package、resolve、sync、revoke、import。
- 新增 `packages/integrations/feishu`：tenant token、Drive upload、权限设置、URL 查询和错误映射。
- 分享发布通过 `SharePublisher` / `SharePublisherRegistry` 适配器接入；context share 核心层不直接依赖飞书实现。
- 新增 share contracts / SQLite ledger / repository。
- `ContextEvent.user` 和 `UserRef` 已接入事件、索引和 search user filter。
- Daemon 新增 `/v1/shares` API。
- CLI 新增 `workrecorder shares create/resolve/import/revoke/ls/sync/jobs`。
- Light Sheet 支持“保存并复制链接 / 仅保存”。
- Workbench 卡片和详情页支持“复制上下文链接”。
- `workrecorder-context` skill 已加入 share resolve/import 工作流。
- 单元/集成测试覆盖：snapshot 冻结、raw 泄漏防护、Feishu 错误映射、API create/resolve/import、`READ_TEXT` 授权、share URL resolve、sync revision。
- `scripts.quality_gate` 已通过，包含 Pyright、pytest、Swift tests、Workbench snapshots、extension build/test、App 打包验证。

## 真实验证

- live Feishu E2E 已做成 opt-in：`WORKRECORDER_RUN_FEISHU_E2E=1`，需要本机安全注入 `WORKRECORDER_FEISHU_APP_ID`、`WORKRECORDER_FEISHU_APP_SECRET`、`WORKRECORDER_FEISHU_FOLDER_TOKEN`。不要把 secret 写入仓库、日志或命令历史。
- 2026-05-25 使用 Keychain 注入 secret 后，live Feishu E2E 通过：
  - tenant token 成功
  - `upload_all` 成功
  - `tenant_readable` patch 成功
  - metas URL 成功
  - revoke 成功
- 同日使用用户指定的原始文件夹 token 跑 live E2E，飞书返回 `feishu_1061004: forbidden`。说明当前应用仍不能向该用户文件夹上传；已验证 app-owned / app-created 分享目录路径可用。

## 还需验证

- macOS GUI 手测：
  - 截图后“保存并复制链接”关闭弹窗并复制 URL
  - Workbench 卡片链条按钮不触发卡片展开
  - 分享失败时 event 不丢失，日志有清晰中文错误

## Reviewer 迭代记录

### Round 01：架构边界

- 结论：分享层独立于 capture、Workbench 和 agent_runs；只通过 disclosure/vault/repository 获取安全数据，边界合理。
- 修正：
  - share 状态改为“本地快照 ready”和“外部发布状态”分离，飞书失败不让本地链接失效。
  - 引入 `SharePublisher` 端口，避免核心层写死 Feishu。

### Round 02：默认披露

- 结论：分享包可以携带截图，但 agent 默认 resolve 不应暴露截图 bytes。
- 修正：
  - `available_fields` 使用 `screenshot_ref`，文档/skill 明确截图需要精查。
  - `shares resolve` 返回安全摘要、可用字段和截图 ref，不返回截图 bytes。
  - `share.html` 可包含完整截图，作为用户主动复制链接后的可视分享页。

### Round 03：Feishu 安全

- 结论：secret 只能来自 Keychain/env，不入库、不进日志；飞书 URL 是分发载体，不替代 WorkRecorder 审计。
- 修正：
  - Feishu adapter 增加 retry、错误映射、URL 去 query/hash 和 best-effort revoke。
  - token hash / provider URL / copyable URL 等字段经过 safe public payload 清洗。
- 验证：live Feishu E2E 已通过 app-owned / app-created 分享目录；用户原始文件夹仍因飞书权限返回 `feishu_1061004`。

### Round 04：CLI / Skill

- 结论：skill 应先 `shares resolve`，仅在需要本地检索时 `shares import`；不能让 agent 解析 raw HTML。
- 修正：
  - skill references 已更新。
  - `shares import` 从默认分享流程移到可选 local import。

### Round 05：UI / UX

- 结论：Light Sheet 默认主按钮可以是“保存并复制链接”，但保存成功后应直接消失；Workbench 使用 icon-only link button，减少卡片噪声。
- 待做：真实 App 手测截图链路。

### Round 06：E2E release readiness

- 结论：自动化覆盖已经包含 contract/unit/integration/CLI/Swift/package；真实飞书链路需要用本机 secret 和目标 folder token 跑 opt-in E2E。
- 修正：
  - `/v1/shares` create/sync 同时检查 `CREATE_SHARE` 和 `READ_TEXT`。
  - share URL resolve 能通过已发布的 Feishu URL 找回本地 share 记录。
  - revoked / expired / deleted event 不可 resolve。
