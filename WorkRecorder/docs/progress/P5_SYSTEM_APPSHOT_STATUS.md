# P5 System Appshot 状态

> 本文是 P5 离线进度记录。设计说明见 [System Appshot：只读系统底片](../architecture/SYSTEM_APPSHOT_CN.md)。

## 当前完成

- 新增 `system.appshot` typed contracts：
  - `SystemAppshotSnapshot`
  - `AppshotSurfaceSnapshot`
  - `AppshotComponentRef`
  - `AppshotQualityReport`
  - `AppshotPermissionReport`
  - `AppshotWindowIdentity`
- 新增 enum：
  - `EvidenceKind.SYSTEM_APPSHOT`
  - `ArtifactType.SYSTEM_APPSHOT`
  - `ArtifactRole.SYSTEM_APPSHOT`
  - `ProviderCapability.COLLECT_SYSTEM_APPSHOT`
  - `EventInspectSection.SYSTEM_APPSHOT`
- 系统证据 provider SDK 已落地：
  - `SystemEvidenceProvider`
  - `SystemEvidenceProviderRegistry`
  - `SystemScreenshotProvider`
  - `SystemMacOSA11yProvider`
  - `SystemAppshotProvider`
- `CapturePersistenceService` 已改为：
  - system screenshot 作为 provider bundle 入库。
  - appshot 由 `SystemAppshotComposer` 在 screenshot/a11y 后补真实 evidence/artifact refs。
  - `EventCaptureEnvelope` 记录 `system_appshot_evidence_id` 和 `system_evidence_bundle_ids`。
- Disclosure / inspect：
  - `workrecorder events inspect --view system_appshot` 可以读取安全系统底片摘要。
  - raw screenshot、raw AX tree、vault path、本地 bundle path 不进入 appshot public view。
- Provider lifecycle：
  - Workbench/daemon definitions 中加入 `system.appshot`，作为内置只读系统证据。
- macOS runtime：
  - `WindowHint` 增加 bundle id、display id、window layer/order、visible ratio、frontmost。
  - a11y node/text block 增加短期 element id。
  - a11y snapshot 增加 extraction revision、max depth、max nodes、truncated。

## 已跑验证

- `./.venv/bin/python -m pytest tests/unit/test_system_evidence_registry.py tests/contract/test_system_appshot_contracts.py tests/integration/test_daemon.py::test_provider_cannot_pollute_system_appshot_refs tests/integration/test_daemon.py::test_provider_cannot_promote_forged_a11y_tree_into_selection_text tests/integration/test_daemon.py::test_capture_without_web_provider_is_accepted_system_only -q`
- `swift test --package-path apps/macos_capture`
- `./.venv/bin/python -m scripts.quality_gate`

## Reviewer 10 轮结论

| 轮次 | 关注点 | 结论 |
| --- | --- | --- |
| 1 | 架构边界 | `system.appshot` 放在 system evidence 层，不进入 source routing，边界清楚 |
| 2 | provider SDK | 截图、a11y、appshot 已统一为 system provider bundle；registry 校验 manifest/key/kind/evidence kind |
| 3 | typed contracts | App/window/permission/quality/component 都有 typed model，避免裸 JSON 漂移 |
| 4 | persistence / ledger | appshot composer 严格只引用 system provider 证据；source provider 伪造 appshot/a11y 不会污染系统底片 |
| 5 | disclosure / privacy | appshot 只返回 safe metadata + refs；public view 清空 artifact ids、bundle URL、path-like metadata |
| 6 | indexing / citation | appshot 默认不 index，后续只由 selection_text/OCR/canonical text 入索引 |
| 7 | macOS runtime | WindowHint 已补 bundle/display/frontmost 等事实，后续可继续加强 App icon artifact |
| 8 | Workbench UX | Workbench 已 decode system_appshot，并在证据栈中展示“系统底片”质量摘要 |
| 9 | E2E / reliability | system-only 和 desktop-only 已测试；仍需真实 macOS App/Preview/PDF E2E 报告 |
| 10 | release review | P5 核心只读链路通过；quality gate 0 warning |

## 剩余风险 / 后续

- 真实 macOS E2E 仍需覆盖 Preview/PDF、TextEdit/Notes/Finder、桌面、重叠窗口。
- `system.appshot` 目前记录 app icon ref 但不生成 icon artifact；后续可由 Swift runtime 补。
- a11y element id 是短期稳定 id，适合一次 capture 内复盘；跨 capture diff 需要专门的 AX identity strategy。
- OCR 状态已经在 appshot contract 预留，当前由事件 changes / OCR job 状态承接；后续可在 OCR job 完成后刷新 appshot summary 或追加 derived appshot revision。
