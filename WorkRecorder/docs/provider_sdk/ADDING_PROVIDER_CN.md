# 添加一个新的 WorkRecorder Provider

WorkRecorder 的 provider 不是“往主链路里加一个 if app == xxx”。它是一个可插拔的数据来源：daemon 负责 surface detection、routing、command、入库、策略、索引和披露；provider 只负责在被命中时现场采集自己最懂的数据。

## 最小接入路径

一个新 provider 至少需要完成六件事：

| 步骤 | 要做什么 |
| --- | --- |
| 1. Manifest | 声明 provider key、kind、source types、capabilities、输出 evidence kinds |
| 2. Route matcher | 根据 `DetectedSurface` 判断自己是否能处理这个 App/窗口/文档 |
| 3. Command handler | 收到 daemon 的 collect command 后现场采集 |
| 4. Evidence bundle | 返回 `ProviderEvidenceBundle`，只描述事实，不决定 agent 能看什么 |
| 5. Disclosure profile | 声明这个 provider 产出的数据如何默认摘要、精查、raw 锁定 |
| 6. Tests | contract fixture、routing test、provider unit test、至少一个 E2E |

## Provider 应该做什么

Provider 负责采事实层，例如：

- System appshot provider：主窗口、附属 surface、权限、质量和 evidence refs。
- Slack thread provider：thread id、channel、message text、作者、时间范围。
- PDF provider：document id、page number、text layer、selection map。
- IDE provider：file path、symbol、diagnostics、selected code range。
- Terminal provider：current command、visible buffer、exit status。

Provider 不应该决定：

- 这份数据是否默认给 Agent。
- 是否写入 index。
- 是否 DLP 通过。
- raw artifact 能不能读取。
- 事件是否保存。

这些都由 daemon 中央策略决定。

## Routing 怎么工作

一次截图会先做 surface detection：

1. 找到 bbox 压到哪些窗口/App。
2. 算 overlap、confidence。
3. 找能处理这些 surface 的 provider。
4. 生成 0..N 个 route。
5. 最高分 route 是 primary source，其余是 secondary source。

如果 provider 离线、超时或失败，event 仍会保存。失败信息进入 `ProviderCaptureOutcome`，不会丢截图。

系统 provider 也使用同样的 bundle/outcome 思路，但它不参与 App source routing。当前内置有 `system.screenshot`、`system.macos_a11y` 和 `system.appshot`。如果你要新增系统级公共能力，比如未来 OCR provider 或窗口 icon provider，应优先接入 `SystemEvidenceProvider` / `SystemEvidenceRegistry`，而不是在 persistence 里写特例。

## Evidence bundle 约定

Provider 返回的 bundle 需要包含：

- `provider_key`
- `provider_session_id`
- `command_id`
- `status`
- `evidence_kind`
- 可选 `source_binding`
- `EvidenceDraft` 列表
- diagnostics

`EvidenceDraft` 里要写清：

- kind / phase / artifact type / role。
- locator：source URI、bbox、text range、selector 等。
- provenance：provider、session、command、extractor。
- sensitivity / redaction claim。

注意：这些 sensitivity 只是 provider claim。daemon 会重新盖章。

## 新 provider 不应该改哪些地方

正常情况下，新增 provider 不应该改：

- `CaptureAttemptService`
- `CapturePersistenceService`
- `DisclosurePolicyService` 主逻辑
- Search CLI
- Workbench 主流程

它应该通过 registry、manifest、profile、adapter 接进去。

如果你发现必须在主链路里写 `if provider_key == "xxx"`，大概率是 SDK 边界还不够好，需要先补抽象。
