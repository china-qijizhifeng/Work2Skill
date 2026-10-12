# Workbench Context Inspector 复刻进度

> 发布版说明：仓库中的文章 fixture 已替换为自编合成内容（`https://example.test`），不再包含第三方文章或真实采集标识。下文保留开发阶段的设计记录；历史截图名称仅用于兼容已有 QA 流程。

## 目标

按照 `.qa/workbench/展开.png` 的方向，重做 event 展开后的右侧 Agent Inspector。左侧和中间只做轻量对齐与选中态增强。

## 真实设计迭代记录

> 说明：这里的 Round 只记录“真实渲染图上能看到的设计变化”。测试循环、稳定性回归、工程修 bug 会单独记录，不能拿来冒充设计迭代。

### Round 00 · Baseline

- 当前 `.qa/workbench/overview-selected.png` 右侧像调试详情栏，内容过大，证据栈被截断。
- Reviewer 结论：最大问题是布局比例、首屏闭合和右侧信息结构，不是单点颜色。

### Round 01 · Inspector Skeleton

- 已完成：新增 `EventInspectorPresentation` 和右侧组件骨架。
- 差异：右侧从旧 tabs + 说明面板改成 Header → Agent 预览 → 材料矩阵 → 证据栈 → 共享模式 → 信任状态。
- Reviewer 记录：这只是结构落地，不算最终视觉完成。

### Round 02 · Agent Preview Hero

- 已完成：把“Agent 默认会看到什么”改成“Agent 预览”，并改成安全摘要主卡。
- 追加修正：第一版两个 field 像表单输入，已改成更紧凑的 bullet payload + 右侧文档预览。
- 真实数据检查：本地 `evt_DoKAKL5gFlRRB1uF` 的标题 44 字、`clean_page_text` 11608 字、`canonical_text` 11622 字；右侧只展示摘要，不内联长正文。

### Round 03 · Matrix / Evidence Draft

- 已完成：默认可见、按需加载、默认锁定三列矩阵已落地；证据栈已从日志列表改为产品化行。
- 对照问题：中间栏仍偏窄，搜索栏没有贴合内容主轴；右侧矩阵中文清单会被截断，看起来像工程表格。
- 截图：`.qa/workbench/overview-selected.png`

### Round 04 · Middle Rail Alignment

- 已完成：展开态中区从 `640-720` 加宽到 `760-840`，搜索栏左边线向内容主轴移动，选中卡片宽度从 `502` 调到 `548`。
- 对照结果：搜索栏比上一版舒服，但中区仍不够像主工作区；右侧 Inspector 仍偏宽。
- Reviewer 结论：搜索、标题、筛选、卡片必须形成同一主轴；筛选栏不能像主导航。
- 截图：`.qa/workbench/overview-selected.png`

### Round 05 · Workbench Weight Shift

- 已完成：右侧 Inspector 从 `500` 收窄到 `470`，中区从 `760-840` 加宽到 `820-900`，选中卡片宽度调到 `570`。
- 已完成：筛选 chip 和下拉按钮压低高度，主筛选只保留 `全部 / Agent 就绪`，`网页来源` 收进更多筛选。
- 已完成：右侧文案从“默认可见 / 默认锁定 / 证据栈”改成更用户化的“会直接看到 / 不会默认发 / 材料明细”。
- 对照结果：中区主工作感变强，搜索栏和选中卡片基本落在同一轴线；右侧仍缺少真正发送动作，但本轮按需求不做假按钮。
- 截图：`.qa/workbench/overview-selected.png`

### Round 06 · Material Restraint / Thumbnail Fill

- 已完成：右侧大容器边框从 Tiffany 青改为中性 hairline，只保留安全摘要和选中态使用青色。
- 已完成：真实缩略图从 aspect-fit 改为 aspect-fill，避免网页截图在宽卡片中缩成小图、两侧大面积空白。
- 对照结果：整体少了一层“浅青塑料感”，选中卡片的网页预览更像真实上下文卡片。
- 截图：`.qa/workbench/overview-selected.png`

## 工程修正记录

- 锁定材料不再从中文 label 反推，改为按 artifact type/role 归类；`browser_full_dom` 稳定映射为 `DOM 文本 / 完整页面 HTML`。
- 缺备注或缺可靠选区文本时，不再凭空显示 NOTE/TXT 行；新增单测覆盖真实缺失形态。
- 未知 artifact type 不再被吞掉，会归入“其他原料 / 默认锁定”，防止真实后端新增 evidence 时 UI 低报风险。
- 10 次重复渲染是稳定性回归，不是设计迭代；该回归曾暴露 `EvidenceTokenView` 等宽字体偶发 nil 崩溃，已加字体 fallback。
- 当前通过：`.qa/workbench` 快照事实校验、10 次稳定性回归、`scripts.quality_gate`。

## 当前真实轮次

- 当前已完成到 Round 15；Round 15 是 release dossier / reviewer 收口，不新增“假像素轮次”。
- 不把测试循环、snapshot facts 或 reviewer 轮次计入设计轮次。
- 每轮截图、side-by-side、diff、facts、real-data-check 和 review 存放在 `.qa/workbench-rounds/round-XX/`。

### Round 07 · QA Baseline

- 已完成：Workbench review viewport 改为接近参考图的 `1586x992` 比例，修正之前展开态过宽过矮的问题。
- 已完成：新增 `scripts/create_workbench_round_report.py`，每轮产出 side-by-side、diff、facts、review。
- Reviewer 结论：这轮是基准修正，不等同于视觉完成。

### Round 08 · Context Library Filters

- 已完成：筛选行恢复为 `全部 / 网页 / 文档 / 聊天 / 已锁定 / Agent 就绪`。
- 已完成：搜索框改为“搜索上下文库…”，页面标题改为“最近上下文”。
- 对照结果：非展开结构更接近参考图，但卡片和 sidebar 材质仍需继续抛光。

### Round 09 · Sidebar Prism

- 已完成：sidebar prism 抽出 `SidebarPrismFilmRecipe`，增强底部彩虹膜层、斜向 glint 和薄光束。
- 对照结果：左下角折射更接近参考图，但仍保持大面积珍珠白，避免变成渐变背景。

### Round 10 · Floating Cards

- 已完成：中间卡片未选中态改为中性 hairline，选中卡才保留 Tiffany rim。
- 已完成：卡片 lift plate、ambient shadow、contact shadow 重新分配层级。
- 对照结果：卡片更像漂浮在工作台上，而不是被青色边框圈住。

### Round 11 · Inspector Action Hierarchy

- 已完成：summary 首屏底部从开发式 tab 按钮改为非执行的“发送前确认”区域。
- 已完成：保持“当前仅预览，真实发送会再次确认”的文案，避免制造假功能。
- 对照结果：右侧更接近参考图的 Agent Preview / Visibility Control 心智。

### Round 12 · Real Data Loop

- 已完成：`.qa/workbench/real-inspect.json` 接入 snapshot 链路，额外生成 `inspector-real-meituan-summary.png`。
- 已完成：真实数据检查覆盖 `tech.meituan.com`、clean text `11608` 字、canonical text `11622` 字、hidden artifacts `12` 项、raw artifacts `1` 项。
- 对照结果：右侧能展示真实长网页材料，不只依赖 synthetic fixture。

### Round 13 · Real Text Polish

- 已完成：Inspector 展示层清理 OCR 内部说明，不再把 `Visual OCR evidence` / untrusted-system wording 直接显示给用户。
- 已完成：新增单测确认真实 Meituan selection preview 是用户可读中文片段，并展示 HTML `11608 字`。
- 对照结果：真实数据不再暴露采集管线里的技术说明，右侧更像产品。

### Round 14 · Visual QA Gate

- 已完成：视觉 verifier 增加真实 fixture 检查，覆盖 origin、clean text 长度、hidden artifacts 数量。
- 已完成：新增多窗口尺寸非空渲染测试。
- 已完成：修正 verifier 的 Inspector 取样区域，避免新 review 高度下误抓空白。
- 对照结果：视觉验证更贴近当前布局，不再用旧横向视口假报警。

### Round 15 · Release Dossier

- 目标：汇总 Round 07-14 产物、最终 reviewer 结论和验证命令。
- 已完成：真实 Meituan fixture 从 `.qa` 可选数据迁到 `tests/fixtures/workbench/synthetic-inspect.json`，缺失时测试直接失败。
- 已完成：`inspector-real-meituan-summary.png` 的左侧选中记录和右侧 Inspector 都来自同一个真实 event，避免“右侧真实、左侧 mock”的假闭环。
- 已完成：右侧 summary 首屏补回轻量“按需查看”导航，用户能进入截图、文本、原料、诊断，不再只有静态摘要。
- 已完成：Workbench 默认窗口上调到 `1500x920`，最小窗口上调到 `1280x720`，减轻展开态搜索和筛选挤压。
- 已完成：`scripts.quality_gate` 已接入 Workbench snapshot 生成和 `scripts.verify_workbench_snapshots`。
- Reviewer 结论：Pascal 的三个 P0 已修复；James 对导航缺失的 P0/P1 已补齐。`WorkbenchWindow.swift` 仍偏大，作为后续 P2 拆分工作保留。
- 状态：完成。

## 本轮验证

- `WORKRECORDER_WRITE_WORKBENCH_SNAPSHOTS=1 swift test --package-path apps/macos_capture --filter WorkbenchRuntimeTests/workbenchSnapshotsRenderPrimaryPages`
- `./.venv/bin/python -m scripts.verify_workbench_snapshots --root .qa/workbench --json .qa/workbench/facts.json`
- `swift test --package-path apps/macos_capture`
- `./.venv/bin/python -m scripts.quality_gate`

## Reviewer 重点

- 右侧是否完整闭合。
- 默认首屏是否还像开发调试页。
- 颜色职责是否清楚。
- 字体和控件是否拥挤或廉价。
- 新组件是否减少 `WorkbenchWindow.swift` 的继续膨胀。
