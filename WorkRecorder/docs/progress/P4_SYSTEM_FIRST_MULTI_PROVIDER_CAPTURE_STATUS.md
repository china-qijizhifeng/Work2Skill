# P4 System-First Multi-Provider Capture 状态

> 分支：`feature/p4-system-first-multi-provider-capture`

## 目标

这轮把截图链路改成 system-first：

- 只要系统截图合法，就保存 accepted event。
- `system.screenshot` 每次必有。
- `system.macos_a11y` 每次尝试，失败写诊断。
- App provider 只做增强，不再是保存前置条件。
- 一次截图可以命中 0..N 个 provider。
- 每个 provider 的成功、失败、跳过、超时都写进 `EventCaptureEnvelope`。

## 已完成

- `ProviderRoutePlan` 升级为 multi-route，新增 `routes`、`primary_route_id`、`selected_route_ids`。
- 新增 `ProviderRoutePolicy`，把主来源/附属来源的选择策略从 router 中拆出来；当前策略按 bbox overlap + detection confidence 评分，并支持最小附属 overlap 与最大 fanout 数。
- 新增 `ProviderCaptureOutcome`，记录 route/provider/surface/role/status/command/evidence/diagnostics。
- 新增 `EvidenceBundleRecord`，记录系统/App bundle 与 evidence ids 的关系。
- `EventCaptureEnvelope` 升到 v2，增加 provider outcomes、source bindings、evidence bundles。
- `ProviderRoutingService` 不再因为 non-Web、低置信、多窗口 ambiguous 直接 unsupported。
- Swift `WindowResolver` 真实快捷键路径现在会提交多个重叠窗口 hint，包括真实 window frame、window id、pid、overlap ratio；不再只提交一个“最大窗口”，也不再把选区框伪装成窗口 frame。
- 新增 `AppProviderFanoutService`，并发触发 selected app routes；单 provider 失败不阻塞 event。
- `CaptureAttemptService` 改成 system-first：route -> system evidence -> app fanout -> persistence。
- `CapturePersistenceService` 支持 `app_bundles=()`，system-only event 使用 fallback source binding。
- SQLite ledger 增加 provider outcomes、evidence bundle records、source bindings 查询表。
- `/v1/search` summary card 增加 provider contribution 和 source kind 信息。
- Workbench 首页不再把 Chrome 连接当截图硬门槛；卡片状态支持“已保存 / 已增强 / 部分增强”。
- Workbench 卡片以 primary app 作为主 icon/source；event inspect 增加 Sources strip，用于展示主来源、附属来源、system evidence/provider outcome。
- Event inspect 的 `source_contributions` 增加 `source_kind`、rank、overlap、confidence，Workbench 可解释“为什么它是主来源 / 附属来源”。
- 修复 primary 非 Web、secondary Web 成功时的归因：事件主来源保持 primary surface，Web 只作为附属来源贡献，不会因为 provider 成功而抢主 App。
- 修复 system-only source contribution 语义：`system.surface_detection` 显示为系统定位/已保存，不冒充 App provider 成功。
- Provider route policy 已接入 daemon settings，可通过环境变量调整 provider confidence、secondary overlap、max fanout、confidence/overlap 权重。
- Source provider registry 强制要求 `capture_evidence_kind`，fanout 不再把未知 provider 静默 fallback 成 Web evidence。
- no-window-hints / desktop-only 会显式保存为“桌面区域”，不再只是模糊 fallback。
- Visual OCR 对每个 accepted event 留下 job 状态；未配置时 `skipped/config_required`，不上传、不阻塞。
- 更新采集、入库、总体技术文档。
- hidden Chrome E2E 测试夹具改为优先使用 Chrome for Testing，并使用 generated-style install secret，避免普通 Chrome 忽略 unpacked extension 或 dev secret 无法申请 elevated scope。

## 已验证

- `./.venv/bin/pytest tests/unit tests/contract tests/integration/test_daemon.py -q`
  - 152 passed。
- `swift test --package-path apps/macos_capture -q`
  - 64 Swift tests passed。
- `./.venv/bin/python -m mypy`
  - no issues。
- `./.venv/bin/python -m scripts.audit_repo_quality --strict --max-findings 80 --json-output /tmp/workrecorder-quality.json`
  - 0 warnings, 0 violations。
- `WORKRECORDER_RUN_CHROME_E2E=1 ./.venv/bin/pytest tests/e2e/test_chrome_hidden_extension_e2e.py -q`
  - 1 passed，覆盖普通页、新闻/blog、长页、表格、文档站、SaaS、iframe、shadow DOM、PDF-like 页面。
- `./.venv/bin/python -m scripts.quality_gate`
  - passed；包含 Python、Swift、extension、Workbench snapshot、HUD snapshot、WorkRecorder.app package verify。
- `./.venv/bin/pytest tests/unit/test_capture_routing.py tests/integration/test_daemon.py::test_capture_without_window_hints_saves_desktop_system_only_event tests/integration/test_daemon.py::test_primary_non_provider_surface_keeps_primary_source_when_secondary_web_succeeds -q`
  - 22 passed。
- `swift test --package-path apps/macos_capture --filter WorkbenchRuntimeTests/eventInspectorSourceRowsExplainPrimaryAndSecondarySources -q`
  - 1 passed。
- `./.venv/bin/python -m ruff check packages/capture packages/providers packages/disclosure packages/shared services/context_daemon tests/unit/test_capture_routing.py tests/integration/test_daemon.py`
  - passed。

## 还需要做的验收

- 手动 GUI E2E：
  - Chrome + extension 成功增强。
  - 非 Chrome native app system-only 保存。
  - Preview/PDF system-only + OCR job 状态。
  - Chrome extension 离线仍保存，Web outcome 为 stale/timeout/skipped。
  - 多窗口 overlap 记录 primary/secondary route。

## Reviewer 摘要

- 架构 reviewer：P4 的关键不是“支持更多 provider”，而是保存链路不能被单个 App provider 卡住；system evidence 要先入库。
- storage/index reviewer：route id 必须全局稳定或复合唯一；provider outcome 和 bundle record 要进入 ledger，便于复盘。
- Workbench reviewer：Chrome 应是增强来源，不应是首页截图门槛；卡片状态要表达 system-only、enhanced、partial。
- Round 08-10 reviewer 复审结论：
  - P0：已补主来源非 Web、附属 Web 成功的归因测试；已补 system-only contribution 不冒充 App provider 成功。
  - P1：已补 route policy settings 注入、provider evidence kind 注册校验、Sources strip overlap/confidence 展示。
  - P1/P2 保留：index source-level provenance、typed `ProviderRouteTarget`、provider manifest app alias/session matcher、Swift window z-order/display/space 仍是后续硬化项。

## 当前风险

- OCR 真实 provider 需要用户显式配置；当前默认只记录 skipped/config_required。
- PDF/Slack/飞书 provider 还是 future adapter；P4 只完成通用路由和 system-only 骨架。
- Index 当前仍以 event primary source 为主归因；multi-provider search hit 的 `route_id/source_binding_id/bundle_id` typed provenance 需要后续补强。
- Provider route target 仍是 JSON target 字段，后续应升级为 typed `ProviderRouteTarget` contract。
- Swift window hints 已包含多个窗口和 overlap，但尚未包含 z-order/display/space/layer；复杂遮挡窗口的 primary 选择还可继续提高。
