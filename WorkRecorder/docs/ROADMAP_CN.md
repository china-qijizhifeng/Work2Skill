# 后续路线

WorkRecorder 当前的重点是把本地 Web capture infra 做扎实。后续工作按价值和风险分层推进。

## 近期

- 继续扩大 hidden Chrome E2E 页面类型：新闻、blog、长文档、表格、SaaS、iframe、shadow DOM、PDF-like。
- 更多真实 macOS GUI E2E，减少模拟。
- 改善 `selection_text` 对长文档、PDF、复杂表格的覆盖。
- 为 `risk_advisory_records` 增加更完整的公开 API。
- 把 provider SDK 文档和示例做成开发者可直接照抄的模板。
- 把 `Agent Context Firewall` 和 `Context Receipt` 做成 agent-facing 读取体验的第一卖点：默认安全摘要、精查留痕、最终引用可复盘。
- 设计 `ContextKeyframe` contracts：先把每次截图的 anchor frame 显式入账，为后续关键帧上下文铺路。

## 中期

- PDF text layer / OCR provider。
- 非 Web App provider：Terminal、IDE、Slack/飞书、文档 App。
- 更细的 citation range：chunk、bbox、DOM node、text range。
- semantic/vector index backend。
- 本地 Workbench UI，把 event、artifact、agent replay 可视化。
- Active Context Capture：截图后短窗口保存 settle/change/provider-completion 帧；用户主动记录片段时保存本地视频、关键帧 storyboard 和低敏操作线索。录制 UI/UX 以“显式准备态、可见 HUD、保存前预览、证据归属 session”为边界。
- Visual Bug Repro Capsule：用截图、关键帧、appshot、Web evidence 和用户 note 生成可复现 bug 证据包。

## 长期

- 团队共享和权限同步。
- 企业 DLP / KMS / retention policy。
- MCP server 或更标准的 agent tool 接口。
- 多设备和云端控制面，但 raw artifact 仍保持强权限边界。
- Provider Store：让 PDF、聊天、IDE、Terminal、CRM provider 可以用 manifest + adapter + disclosure profile 独立接入。
- Prompt Injection Lab：检测网页、DOM、OCR、PDF 里的隐藏 prompt/injection 风险，再进入 agent context。
- Local-first Team Vault：共享被裁剪后的 context pack，而不是共享 raw screenshot / DOM。

## 不变原则

- 用户主动、默认安全。
- 事实层可追溯，增强层可重算。
- provider 可插拔，不把 App 逻辑写死进 daemon。
- Agent 读取必须留痕。
- 关键帧只能围绕用户主动触发生成；如果未来做持续模式，必须单独授权、单独策略、单独披露。

## 创新方向索引

- [产品创新地图](PRODUCT_INNOVATION_IDEAS_CN.md)：更完整的产品想象空间和优先级。
- [Active Context Capture：截图关键帧与记录片段](design/USER_TRIGGERED_KEYFRAME_CONTEXT_CN.md)：借鉴 screenpipe 的事件驱动关键帧，但保持 WorkRecorder 的主动触发、视频默认锁定和可审计边界。
- [录制功能 UI/UX 设计方案](design/RECORDING_UI_UX_CN.md)：区域录制的快捷键、HUD、完成 sheet、Workbench、权限降级和验收标准。
