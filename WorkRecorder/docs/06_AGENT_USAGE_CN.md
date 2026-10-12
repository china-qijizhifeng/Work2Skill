# 阶段 6：Agent 使用与复盘

> 导航：[返回文档总览](README.md) · 上一篇：[阶段 5：索引与披露](05_INDEX_DISCLOSURE_CN.md) · 下一篇：[Chrome 真实流程 Case Study](USER_GUIDE_CHROME_CASE_STUDY_CN.md)

Agent 使用阶段回答：

> Agent 为了回答用户问题，到底搜了什么、看了哪些 event、拿到了哪些字段、最后引用了哪些证据？

WorkRecorder 不只关心采集，也关心使用。因为真正的产品目标是给 Agent 提供可信上下文。如果 Agent 读上下文的过程不可追踪，最后答案就很难复盘。

## 三层入口

Agent 读取 WorkRecorder 走三层：

```text
workrecorder-context skill
        |
        v
workrecorder CLI
        |
        v
daemon API
```

三层职责不同：

| 层 | 责任 | 不做什么 |
| --- | --- | --- |
| skill | 教 Agent 怎么调用 CLI，说明安全边界和推荐流程 | 不实现搜索、不保存策略、不 import 主仓库 |
| CLI | 稳定本地客户端，处理参数、JSON 输出、token、run id | 不绕过 daemon policy |
| daemon | 搜索、披露、审计、快照、citation、usage ledger | 不相信客户端自称已审计 |

这保证 skill 和主仓库解耦，同时又不会让安全边界落在 skill 文档上。

## 推荐 Agent 工作流

一次标准回答大概是：

1. `workrecorder agent begin`：创建一次 agent run。
2. `workrecorder events search`：粗搜安全摘要卡。
3. `workrecorder events inspect <event_id>`：精查相关事件。
4. `workrecorder bundle create`：需要时打包多条上下文。
5. `workrecorder citations resolve`：需要引用时解析 citation。
6. `workrecorder usage record`：回答完后记录使用了哪些证据。
7. `workrecorder agent replay`：需要复盘时查看完整读取链路。

Agent 最好主动 begin，但系统不能依赖 Agent 永远守纪律。

## agent_run_id 不传怎么办

很多 Agent 调工具时不会主动传 run id。WorkRecorder 做了兜底：

1. 显式 `--agent-run-id` 优先。
2. 没传则用 `WORKRECORDER_AGENT_RUN_ID`。
3. 再没有就用 CLI 本地 active session。
4. 还没有则 daemon 创建 implicit run。

这意味着“忘了 begin”也不会变成无痕读取。daemon 仍然会给这次 search/inspect 建 run，并在 response 里返回 `agent_run_id`。

## Retrieval trace：每次读取都留痕

每次 agent-facing API 调用都会记录 retrieval call。

例如：

- search：记录 query hash、过滤器、命中 event ids、返回字段。
- inspect：记录 event id、请求 view、实际披露字段、citation ids。
- bundle create：记录候选 event、bundle item、citation ids。
- artifact raw：记录 raw gate 决策、artifact hash、byte count，不复制 raw bytes。
- citation resolve：记录解析了哪个 citation、返回了哪些安全字段。

这些记录让人能回答：Agent 为了回答这个问题，具体看了什么。

## Delivered snapshot：保存实际返回给 Agent 的内容

仅记录“调用过 inspect”还不够。我们还要知道当时返回给 Agent 的 JSON 里到底有什么。

Delivered snapshot 保存的是 policy-delivered safe payload：

- 字段名。
- event/evidence/artifact refs。
- 文本 hash。
- 字符数/字节数。
- truncation。
- disclosure policy version。
- citation ids。

它不复制：

- raw full DOM。
- raw a11y tree。
- raw screenshot bytes。
- vault path。
- URL query/hash。

这样既能复盘 Agent 看到了什么，又不会把危险原料复制到另一个目录造成二次泄漏。

## Citation 是标准证据单位

Agent 最终回答里应该引用 citation id，而不是自己写“来源是某网页”。

一个 citation 可以追到：

- event id。
- evidence id。
- artifact id。
- chunk id。
- text range 或 bbox。
- provider key。
- command id。
- source URI。
- captured_at。

这让答案里的每个关键判断都能回到证据。

## Usage event：回答结束后的封面

`workrecorder usage record` 会生成 usage event。它不是把所有内容再复制一遍，而是引用前面已经存在的 run、query、snapshot、citation、bundle、answer。

usage event 记录：

- agent run。
- 用户问题或 query hash。
- 用了哪些 citation。
- 用了哪些 bundle。
- 最终答案 ref/hash。
- 是否提出高风险建议。
- 高风险建议记录 ids。

如果 Agent 做了医疗、法律、金融、生产操作建议等高风险建议，应该单独写 `risk_advisory_records`，usage event 引用它们。这样普通上下文使用和高风险建议不会混在一起。

## 删除或限制事件后的复盘

复盘不应该成为绕过权限的后门。

如果 event 后来被删除或 restricted：

- 新的 search 不应返回它。
- bundle show/export 需要重新走可见性检查。
- replay 可以显示“当时曾返回过某字段的摘要/哈希/引用”，但不应泄漏现在已经禁止的文本。
- raw artifact 仍然必须重新过 raw gate。

这让系统既能审计过去，又尊重当前权限。

## 设计亮点

- **无痕读取兜底消失**：Agent 不传 run id 也会被 daemon 建 implicit run。
- **能复盘真实返回**：snapshot 记录的是实际交付给 Agent 的安全 payload。
- **citation 串起答案**：回答里的证据不是散文描述，而是可解析引用。
- **高风险建议单独留痕**：便于审计和后续策略升级。
- **skill 与主仓库解耦**：skill 是使用说明，真正策略都在 daemon。

---

导航：[返回文档总览](README.md) · 上一篇：[阶段 5：索引与披露](05_INDEX_DISCLOSURE_CN.md) · 下一篇：[Chrome 真实流程 Case Study](USER_GUIDE_CHROME_CASE_STUDY_CN.md)
