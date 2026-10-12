# Context Share：可分享的上下文链接设计

> 导航：[返回文档总览](../README.md) · 相关：[阶段 5：索引与披露](../05_INDEX_DISCLOSURE_CN.md) · [阶段 6：Agent 使用与复盘](../06_AGENT_USAGE_CN.md) · [System Appshot](../architecture/SYSTEM_APPSHOT_CN.md)

## 一句话

Context Share 让用户在截图保存后，可以复制一条“上下文链接”，发给同事或贴给 Agent。别人打开链接后看到的不是裸截图文件，而是一份经过 WorkRecorder 策略裁剪、可追溯、可引用的上下文视图。

它的目标不是做网盘，也不是做截图外链，而是把 WorkRecorder 的核心能力分享出去：

> 这次截图发生在什么 App / 网页里，用户备注是什么，框内文字是什么，哪些材料默认可见，哪些原始材料被锁住，后续 Agent 可以怎么精查。

## 有价值吗

有，而且价值很明确。

普通截图分享只能传达“我看到了一张图”。Context Share 传达的是：

- **发生了什么**：时间、主 App、网页 title、URL、窗口/截图区域。
- **用户为什么截**：用户主动填的 note。
- **Agent 默认能读什么**：框内文本、网页标题、安全摘要。
- **还有什么材料**：截图、网页全文、DOM、a11y、OCR、appshot 等，但按策略锁住或按需读取。
- **证据链在哪里**：每段文本、每张图、每个来源都能追到 event / evidence / artifact。

几个高频场景：

| 场景 | 普通截图的问题 | Context Share 的价值 |
| --- | --- | --- |
| 给同事解释一个网页/产品问题 | 对方只能看图，不能复制文字，也不知道来源 | 链接里有 note、时间、URL、框内文字和截图 |
| 给 Agent 一个任务背景 | Agent 容易拿到过多 raw 材料，或者拿不到关键文字 | 默认只给安全摘要，需要时按 event/share id 精查 |
| Bug report / PR review | 截图和上下文散落在聊天里 | 一条链接就是一份可复盘上下文包 |
| 客服 / 销售交接 | 只转发截图很难让下一个人继续工作 | 可以分享“用户当时看到的页面 + 摘要 + 可引用证据” |
| 安全审计 | 不知道 Agent 到底看了什么 | share resolve / inspect / raw 请求全部写入 usage trace |

这个功能和 WorkRecorder 的定位很贴：把一次截图变成可信上下文，而不是把图片丢出去。

## 当前 MVP 决策

这轮实现采用更贴近用户动作的方案：

- 用户点击“保存并复制链接”时，WorkRecorder 先照常保存本地 event。
- 保存成功后，daemon 冻结一份 `agent_context_with_screenshot` 分享快照。
- 快照里包含 Agent 默认能读取的安全摘要；分享包另外携带一张完整截图，供人打开链接查看。
- daemon 生成一个 HTML 分享页，里面嵌入给人看的内容、机器可读 `safe_context` 和截图。
- 如果飞书配置可用，HTML 上传到飞书应用自有目录，并设置为“组织内获得链接的人可阅读”。
- 如果飞书上传失败，本地 event 和本地 share 不回滚；Workbench/CLI 会复制 `workrecorder://share/<share_id>` 作为本机可解析链接。

MVP 默认上传到分享包：

- user note
- 时间
- 主 App / title
- Chrome sanitized URL
- selection_text
- canonical / clean_page_text
- OCR text
- available fields
- hidden materials summary
- 完整 screenshot PNG（不进入 agent 粗搜/resolve 默认文本）

MVP 不上传：

- raw DOM
- raw a11y tree
- vault path / storage URI
- URL query/hash
- cookies / localStorage / sessionStorage
- provider raw diagnostics

## 设计原则

Context Share 必须遵守几条底线。

1. **链接不是裸 event_id**

   `event_id` 是索引和引用 id，不应该当分享权限。分享链接应该指向一个独立的 `share_id / grant_token`，里面有作用域、过期时间、创建者、审计记录。

2. **分享不绕过 disclosure**

   粗搜、精查、raw artifact 现在都有渐进式披露。Context Share 也必须走同一套规则，不能因为“复制链接”就绕过截图、DOM、a11y 的默认锁定。

3. **Agent 默认只读摘要，分享包携带截图**

   第一版默认给 Agent 读的字段：

   - event_id / share_id
   - 时间
   - 主 App
   - title
   - Chrome sanitized URL
   - user note
   - selection_text
   - 可精查字段清单
   - hidden materials 清单

   完整截图会随 HTML 分享包上传，方便人点开链接查看；Agent 粗搜/resolve 默认只拿 `screenshot_ref`，需要明确精查/视觉检查才读取截图。

   不默认分享 raw DOM、raw a11y tree、vault path、URL query/hash、cookies、localStorage、provider diagnostics。

4. **分享内容要可冻结**

   链接创建时应该保存一份“实际允许展示的安全快照”。这样之后可以回答：

   > 这个链接创建时到底让对方/Agent 看到了哪些字段？

   如果原始 event 后续被删除或权限收紧，旧链接不能偷偷泄漏新规则下不允许看的内容。

5. **可以撤销和过期**

   分享链接默认有过期时间，用户可以在 Workbench 里撤销。撤销后不能继续 resolve。

6. **本机优先，飞书只是发布通道**

   WorkRecorder 当前是本机优先产品。飞书链接只是组织内分发入口；真正的分享事实、revision、审计和导入仍由 WorkRecorder share ledger 记录。

## 三种分享形态

当前实现按“两层链接 + 一个包”落地：本地链接保证可复盘，飞书链接负责组织内传播，分享包负责让人和 Agent 都能读懂。

### 1. 本机上下文链接

适合：同一台电脑上的 Workbench、CLI、Agent。

形式：

```text
workrecorder://share/shr_xxx
```

或开发态：

```text
http://127.0.0.1:8765/v1/shares/shr_xxx/view?token=...
```

特点：

- 只在本机 daemon 可用时打开。
- 最安全，最容易落地。
- Agent 可以用 CLI resolve：

```bash
workrecorder shares resolve workrecorder://share/shr_xxx --purpose agent_context_read --json
```

这是飞书发布失败、离线或本机 Agent 使用时的兜底路径。只要本地 share snapshot 已经冻结，这个链接就应该能被 `workrecorder shares resolve` 解析。

### 2. 飞书组织内链接

适合：用户点“保存并复制链接”后，把上下文发给同组织的人。

形式：

```text
https://*.feishu.cn/drive/file/...
```

本质是 WorkRecorder 生成 HTML 分享包，然后上传到飞书应用自有目录：

```text
workrecorder-share-{share_id}-r{revision}.html
```

特点：

- HTML 内嵌完整截图和 `safe_context`。
- 飞书权限设置为组织内获得链接的人可阅读。
- 飞书只是分发入口；WorkRecorder 本地 ledger 仍记录 share、revision、audit。
- raw DOM / raw a11y tree / vault path / URL query/hash 不进入包。

### 3. `.nlctx` 离线包

适合：不用飞书，或者需要导入到另一台机器。

这一阶段还没实现。计划中的包结构：

```text
manifest.json
safe_context.json
screenshot.png
share.html
```

## 用户体验

### 截图弹窗里

用户截图后，保存弹窗可以有两个动作：

```text
[保存] [保存并复制上下文链接]
```

保存成功后，弹窗直接关闭，控制中心或系统提示轻量告知：

```text
已保存，并复制上下文链接。
链接里包含安全摘要和完整截图；Agent 默认只读摘要，截图需要精查确认。
```

如果用户点“更多分享选项”，打开一个小面板：

```text
分享范围

(•) 安全摘要 + 截图包
    备注、App、网页标题、URL、框内文字；HTML 包里带完整截图

过期时间：24 小时 / 7 天 / 永不过期
```

第一版只开放 `agent_context_with_screenshot`，后续再加更细的分享范围。

### Workbench 卡片里

右键或卡片详情页增加：

```text
复制上下文链接
复制 Agent 命令
管理分享
```

“复制 Agent 命令”可以输出：

```bash
workrecorder shares resolve workrecorder://share/shr_xxx --purpose agent_context_read --json
```

这比直接复制一大坨 JSON 更干净。

### 接收方打开链接

本机 viewer 页面应该像一个轻量 context card：

```text
网页内容抽取策略
Google Chrome · chatgpt.com · 2026-05-22 20:41

用户备注
测试

框内文字
最小可行版本可以这样做

可深入查看
网页正文、OCR 正文、系统底片、截图引用、证据引用

默认锁定
原始截图、DOM、a11y tree
```

底部给两个按钮：

```text
[复制给 Agent 的命令] [在 WorkRecorder 中打开]
```

如果是离线包，则是：

```text
[导入到 WorkRecorder] [复制安全摘要]
```

## Agent 怎么用

Agent 不应该直接解析链接背后的 raw 内容。标准流程是：

1. 用户把链接贴给 Agent。
2. Agent 调用：

```bash
workrecorder shares resolve <context_link> --purpose user_shared_context --json
```

3. CLI 返回一张安全摘要卡，字段和 `events search` 粗搜保持一致。它不内联截图，只返回可精查的 `screenshot_ref`：

```json
{
  "share_id": "shr_123",
  "event_id": "evt_123",
  "captured_at": "2026-05-22T12:41:24Z",
  "app": "Google Chrome",
  "title": "网页内容抽取策略",
  "url": "https://chatgpt.com/c/abc",
  "user_note": "测试",
  "selection_text": "最小可行版本可以这样做",
  "available_fields": [
    "selection_text",
    "canonical",
    "clean_page_text",
    "system_appshot",
    "screenshot_ref"
  ]
}
```

4. 如果需要深入，Agent 再带 `share_id` 或 `event_id` 精查：

```bash
workrecorder shares inspect shr_123 --view clean_page_text --purpose agent_deep_read --json
```

或者同机事件：

```bash
workrecorder events inspect evt_123 --view clean_page_text --purpose agent_deep_read --json
```

5. 所有 resolve / inspect / raw 请求写入 agent run ledger。

这样 share link 不会破坏之前“先粗搜，再精查，危险原料默认不给”的设计。

## 后端模型

建议新增一组独立 contracts，不要把分享状态塞进 `ContextEvent`。

### SharedContextGrant

表示用户创建过的一条分享授权。

字段示意：

```text
share_id
event_id
created_by_actor
created_at
expires_at
revoked_at
share_scope
allowed_views
audience
token_hash
snapshot_id
policy_version
metadata
```

### ShareScope

当前枚举：

```text
agent_context_with_screenshot
```

后续可以增加 `safe_summary_only`、`offline_export`、`debug_manifest`，但默认不会绕过 daemon disclosure policy。

### SharedContextSnapshot

保存“创建分享时实际可见的内容”。

字段示意：

```text
snapshot_id
share_id
event_id
payload_hash
payload_ref
delivered_fields
redaction_policy_version
disclosure_policy_version
created_at
```

payload 只能包含 disclosure 允许的安全字段，不复制 raw DOM、raw a11y tree、vault path。

### ShareAuditEvent

记录分享链路里的动作：

```text
share_created
share_resolved
share_inspected
share_exported
share_revoked
share_expired
raw_denied
```

每条记录至少包含：

```text
share_id
event_id
actor
agent_run_id
purpose
requested_view
decision
delivered_fields
created_at
```

## API / CLI 设计

### API

建议新增：

```text
POST /v1/shares
GET  /v1/shares/{share_id}
POST /v1/shares/{share_id}/resolve
POST /v1/shares/{share_id}/inspect
POST /v1/shares/{share_id}/revoke
POST /v1/shares/{share_id}/export
POST /v1/shares/import
```

第一版可以更简单：

```text
POST /v1/shares
GET  /v1/shares/{share_id}
POST /v1/shares/resolve
POST /v1/shares/{share_id}/resolve
POST /v1/shares/{share_id}/sync
POST /v1/shares/{share_id}/revoke
POST /v1/shares/import
GET  /v1/shares/{share_id}/jobs
```

Resolve 返回 frozen safe summary context、可见字段、隐藏材料清单、截图 artifact id/ref 和飞书 URL；不返回截图 bytes、raw DOM/a11y/vault path。

### CLI

建议新增：

```bash
workrecorder shares create --event evt_123 --target feishu_drive --copy-link --json
workrecorder shares resolve workrecorder://share/shr_123 --purpose agent_context_read --json
workrecorder shares revoke shr_123 --json
workrecorder shares sync shr_123 --json
workrecorder shares import workrecorder://share/shr_123 --json
workrecorder shares jobs shr_123 --json
```

Agent skill 里只推荐：

```bash
workrecorder shares resolve <link> --purpose user_shared_context --json
```

只有用户明确要求深入时，再用 returned event id 走 `events inspect`。

## 当前还缺什么

当前 WorkRecorder 已经有很多基础能力可以复用：

- event / evidence / artifact ledger。
- disclosure policy。
- agent run / retrieval snapshot / citation。
- raw artifact gate。
- Workbench 卡片和截图弹窗。
- CLI / skill。

但要做 Context Share，还缺这些：

1. **Share grant 表**

   现在没有 `share_id`、token、过期、撤销、audience、scope 的存储。

2. **Share snapshot**

   现在 agent run 会记录“给 Agent 返回了什么”，但没有专门记录“创建分享链接时允许别人看到什么”。

3. **Share-specific disclosure view**

   现在有 `summary_card` 和 `event_inspect`，但缺一个 `share_summary` / `share_inspect` 视图，用来表达“别人通过链接看”。

4. **Workbench 分享 UI**

   现在卡片可以打开详情，但没有“复制上下文链接 / 管理分享”。

5. **CLI share 命令**

   现在 agent 可以 search / inspect / bundle，但没有 `workrecorder shares resolve`。

6. **本机 URL scheme**

   需要注册 `workrecorder://share/...`，让系统能从链接打开 WorkRecorder.app。

7. **离线导出格式**

   如果要跨机器分享，需要 `.nlctx` 格式和 import/export 流程。

8. **安全测试**

   需要证明 share 不泄漏 raw DOM、raw a11y tree、vault path、URL query/hash；完整截图只通过用户主动分享动作进入 HTML 包。

## MVP 建议

当前 MVP 是“飞书组织链接 + 本地 fallback”：

### P0：Feishu Context Share

- Workbench 卡片详情增加“复制上下文链接”。
- 截图保存成功后增加“复制上下文链接”。
- 新增 share grant 存储。
- scope 只支持 `agent_context_with_screenshot`。
- 链接 7 天过期。
- 支持撤销。
- 上传 HTML 包到飞书应用自有目录。
- 设置为组织内获得链接的人可阅读。
- CLI 支持：

```bash
workrecorder shares create --event <event_id> --json
workrecorder shares resolve <link> --json
workrecorder shares revoke <share_id> --json
```

- Agent resolve 返回 compact card + safe_context；截图只作为 ref/HTML 包材料，不作为默认文本暴露。
- resolve 写入 agent run ledger。

### P1：User OAuth / Import Feishu URL

- 接收方从飞书 URL 下载 `safe_context`。
- 校验 manifest/hash。
- 导入成本地 imported event。

### P2：Offline `.nlctx`

- 导出安全摘要包。
- 可选低敏 thumbnail。
- 接收方可导入。
- 可包含完整截图，但 raw DOM/a11y tree 继续 hard deny。

### P3：Team / Cloud Share

- 账号、权限、E2EE、访问审计、团队策略。
- 适合企业协作，但不应阻塞本机版。

## 安全边界

Context Share 最容易出问题的地方是：链接一旦复制出去，就像 capability。一些规则必须写死：

- 链接 token 只存 hash，不明文入库。
- 默认过期。
- 可以撤销。
- 每次打开都审计。
- 不允许 URL query/hash 进入默认分享。
- 不允许 raw DOM / raw a11y tree / vault path。
- 完整截图只在用户主动点击“保存并复制链接/复制上下文链接”时进入分享包。
- share scope 只能收紧，不能扩大 daemon disclosure policy。
- provider 自己不能声明“我产出的内容可分享”；最终由 daemon policy 盖章。

## 测试计划

### Contract

- `SharedContextGrant`
- `SharedContextSnapshot`
- `ShareScope`
- `ShareResolveResponse`
- `ShareAuditEvent`

### Unit

- 创建 share 时生成 token hash。
- 过期 share 被拒绝。
- revoked share 被拒绝。
- `agent_context_with_screenshot` 不含 raw DOM、a11y、vault path、URL query/hash。
- workspace override 不能把 hard-deny raw source 变成可分享。
- share snapshot 和 event 当前状态不一致时，仍按安全策略输出。

### Integration

- capture -> create share -> resolve -> agent replay。
- Chrome event share resolve 返回 title / sanitized URL / note / selection text。
- system-only event share resolve 返回 app / time / note / OCR/selection text。
- share inspect 能读 selection_text，但不能读 raw DOM。
- 分享包里的截图必须来自用户主动分享动作，且写 share audit。

### Workbench

- 截图保存后“复制上下文链接”可用。
- 卡片详情“复制上下文链接”可用。
- revoked/expired share 给用户友好提示。
- 长 title、长 note、长 selection text 不撑爆分享预览。

## 设计评审结论

从产品角度：值得做。它能把 WorkRecorder 从“个人截图上下文库”推进到“可协作、可交接、可给 Agent 使用的上下文证据系统”。

从工程角度：应该独立成 share layer，不要把 share token 塞进 event，不要让链接绕过 disclosure。

从安全角度：本轮明确允许用户主动分享完整截图，但 raw DOM、raw a11y tree、vault path 和 URL query/hash 继续 hard deny；飞书只是组织内分发通道，不替代 WorkRecorder 的 ledger 和审计。

从 Agent 角度：非常有用。用户可以直接把 context link 贴给 Agent，Agent 用 `workrecorder shares resolve` 读安全摘要；需要更深材料时，再按 share scope 和 event id 精查。这个流程和 WorkRecorder 现有渐进式披露完全一致。
