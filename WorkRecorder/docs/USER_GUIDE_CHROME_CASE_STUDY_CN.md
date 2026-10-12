# 用户手册：一次 Chrome 截图到 Agent 回答

这份文档用一个 Chrome case 讲清楚 WorkRecorder 的完整体验。它不按字段大全展开，而是按用户、系统、Agent 的视角解释：每一步发生了什么，采了哪些真实数据，哪些默认给 Agent，哪些需要精查，哪些永远默认不给。

这个 case 对应仓库里的本地测试页面：

- 页面 fixture：[tests/fixtures/e2e/acme_pricing.html](../tests/fixtures/e2e/acme_pricing.html)
- hidden Chrome E2E：[tests/e2e/test_chrome_hidden_extension_e2e.py](../tests/e2e/test_chrome_hidden_extension_e2e.py)

> 为了便于阅读，下面的 id 使用固定示例，真实运行时每次都会不同。截图和 artifact map 展示的是这个 fixture 的真实内容结构，用来说明 WorkRecorder 如何保存、清洗和披露。

## 场景

你正在 Chrome 里看一个 ACME 报价页面。页面里有一张小表格：

```text
Account | Status | Risk
ACME    | Procurement delayed | Renewal risk medium
```

页面上还有预算提示：

```text
Budget variance +18%
```

测试页面里故意放了一些不应该泄漏的 sentinel，比如 hidden input、password、CSS hidden 文本、token-like 文本。这样 E2E 能验证 WorkRecorder 不是“把 DOM 全部洗白给 Agent”，而是按规则清洗、遮挡和披露。

用户目标是：以后让 Agent 能在准备续约讨论时找回这块上下文。

## 你看到的截图 artifact

用户按快捷键框住报价表区域。WorkRecorder 会保存 OS screenshot artifact。下面这张 SVG 是文档里的可视化复现，真实 E2E 中对应的是本地 vault 里的 PNG artifact。

![ACME 截图 artifact](assets/acme_capture_screenshot.svg)

用户还可以补一句 note：

```text
用于 ACME 续约风险分析
```

这句 note 会跟着 event 一起进入索引和摘要卡，因为它解释了用户为什么截这块。

## 第一步：触发

macOS shell 做的事情很少：

- 记录快捷键触发时间。
- 记录用户框选 bbox。
- 截一张系统 PNG。
- 记录当前窗口 hints：Google Chrome、窗口 id、pid、title。
- 收集用户 note。
- 把 capture attempt 发给 daemon。

它不读 DOM，不读 a11y tree，也不判断 Agent 能看什么。

示意数据：

```json
{
  "trigger": "macos_hotkey",
  "actor": "local_user",
  "workspace": "default",
  "selection_bbox": {"x": 386, "y": 246, "width": 418, "height": 128},
  "window_hint": {
    "app_name": "Google Chrome",
    "title": "ACME Pricing Dashboard"
  },
  "user_note": "用于 ACME 续约风险分析"
}
```

## 第二步：daemon 判断命中了 Chrome

daemon 收到 attempt 后，不会直接创建最终 event。它先做 surface detection：

- 这个 bbox 和哪个窗口重叠最多？
- 窗口对应哪个 App？
- 有没有在线 provider 可以处理这个 surface？
- 置信度够不够？

在这个 case 里，route plan 大概是：

| provider | 为什么运行 | 产出 |
| --- | --- | --- |
| `system.screenshot` | 每次 capture 都有系统截图 | screenshot PNG |
| `system.macos_a11y` | 跨 App 抽取框内文本和 UI 结构 | a11y tree、text blocks、coverage |
| `web.browser_extension` | bbox 命中 Chrome 页面，extension 在线 | URL、title、DOM、page text、selection map |

这里最重要的是：Chrome extension 不是一直上传 DOM。它只是保持 WebSocket session，等 daemon 在用户截图后现场下命令。

## 第三步：provider 现场采集

daemon 同时向系统 provider 和 Chrome provider 要证据。

### 系统采集到什么

系统侧采集：

- `screenshot`：用户框选区域对应的 PNG。
- `a11y_tree`：窗口可访问性树。
- `a11y_text_blocks`：带 frame、role、node path 的文本块。
- `a11y_coverage_report`：这次 a11y 抽取覆盖得怎么样。

在这个 case 中，a11y text blocks 里会出现表格内的文字块，例如：

```json
[
  {"text": "Account", "role": "AXStaticText", "frame": {"x": 414, "y": 298, "w": 96, "h": 20}},
  {"text": "Status", "role": "AXStaticText", "frame": {"x": 526, "y": 298, "w": 112, "h": 20}},
  {"text": "Risk", "role": "AXStaticText", "frame": {"x": 660, "y": 298, "w": 88, "h": 20}},
  {"text": "ACME", "role": "AXStaticText", "frame": {"x": 414, "y": 338, "w": 96, "h": 20}},
  {"text": "Procurement delayed", "role": "AXStaticText", "frame": {"x": 526, "y": 338, "w": 150, "h": 20}},
  {"text": "Renewal risk medium", "role": "AXStaticText", "frame": {"x": 660, "y": 338, "w": 160, "h": 20}}
]
```

这些 raw blocks 默认不直接给 Agent。它们是后面生成 `selection_text` 的输入。

### Chrome provider 采集到什么

Chrome extension 在真实 tab 里现场读取：

```json
{
  "browser": "chrome",
  "title": "ACME Pricing Dashboard",
  "origin": "http://127.0.0.1:8877",
  "sanitized_url": "http://127.0.0.1:8877/acme_pricing.html",
  "viewport": {"width": 1280, "height": 900, "device_pixel_ratio": 2},
  "scroll": {"x": 0, "y": 0},
  "dom_capture_mode": "full_dom",
  "coverage": {
    "same_origin_iframes": "captured_when_available",
    "cross_origin_iframes": "diagnostic_only",
    "shadow_dom": "open_shadow_dom_attempted"
  }
}
```

Chrome provider 还会返回：

- full DOM artifact。
- visible text source。
- readability/page text source。
- selection map。
- diagnostics。

但 provider 不能自己决定“这些能给 Agent 看”。它只是上交证据，daemon 统一盖章。

## 第四步：存成本地案卷

采集完成后，WorkRecorder 会创建一条 context event，并把所有 evidence 和 artifact 写入本地 ledger/vault。

可以把这一步理解成“把现场材料整理成案卷”：

![ACME artifact map](assets/acme_artifact_map.svg)

这次案卷里大概有这些 artifact：

| artifact | 来源 | 默认可见性 | 内容示例 |
| --- | --- | --- | --- |
| `art_screen_acme` | `system.screenshot` | 默认不给 raw，只给 ref | PNG bytes，sha256 可验证 |
| `art_a11y_tree_acme` | `system.macos_a11y` | 默认不给 | AX tree JSON |
| `art_a11y_blocks_acme` | `system.macos_a11y` | 默认不给 | 带 bbox 的 text blocks |
| `art_dom_acme` | `web.browser_extension` | 默认不给 | full DOM HTML，本地隔离 |
| `art_page_text_source_acme` | `web.browser_extension` | daemon 清洗前不给 | 可读正文来源 |
| `art_selection_map_acme` | `web.browser_extension` | metadata/ref | screen/window/viewport/DOM 对齐信息 |
| `art_selection_text_acme` | `system.enrichment.selection_text` | 粗搜默认给 | 框内表格文字 |
| `art_clean_page_text_acme` | daemon enhancement | 精查可见 | 清洗后的网页正文 |
| `art_canonical_text_acme` | daemon enhancement | 搜索/精查/bundle | 用于召回和引用的统一文本 |

每个 artifact 都带：

- artifact id。
- evidence id。
- provider key。
- captured_at / observed_at。
- content type。
- sha256。
- sensitivity。
- policy version。
- parent evidence ids。

这就是“可追溯”的基础。

## 第五步：生成 selection_text

WorkRecorder 不把 raw a11y tree 直接给 Agent。daemon 会从 a11y text blocks 派生正式 evidence：`selection_text`。

这个 case 的 selection_text 是：

```text
Account
Status
Risk
ACME
Procurement delayed
Renewal risk medium
```

它的特点是：

- 来自截图框内的 leaf text blocks。
- 过滤掉浏览器工具栏和菜单。
- 按空间阅读顺序合并。
- 不把整页 DOM 或整页 a11y 父节点塞进来。
- 有 parent evidence refs，可以追到原始 blocks。

这就是粗搜默认给 Agent 的核心文本。

## 第六步：生成 clean_page_text 和 canonical_text

Chrome provider 给的 DOM/page text source 需要 daemon 清洗。

测试页面里故意包含这类内容：

```text
API token: SHOULD_NOT_LEAK_VISIBLE_TOKEN
Authorization: Bearer SHOULD_NOT_LEAK_VISIBLE_BEARER
```

清洗后的 `clean_page_text` 应该类似：

```markdown
# ACME Pricing Dashboard

Budget variance +18%

API token: [redacted]
Authorization: Bearer [redacted]

| Account | Status | Risk |
| --- | --- | --- |
| ACME | Procurement delayed | Renewal risk medium |
```

而这些 sentinel 不应该进入 agent-readable text：

```text
SHOULD_NOT_LEAK_HIDDEN_INPUT
SHOULD_NOT_LEAK_PASSWORD
SHOULD_NOT_LEAK_CSS_HIDDEN
SHOULD_NOT_LEAK_VISIBLE_TOKEN
SHOULD_NOT_LEAK_VISIBLE_BEARER
```

`canonical_text` 会把 selection、page text、note、metadata 组织成更适合搜索和引用的结构：

```markdown
## Selection
Account
Status
Risk
ACME
Procurement delayed
Renewal risk medium

## Page Text
ACME Pricing Dashboard
Budget variance +18%
API token: [redacted]
Authorization: Bearer [redacted]

## User Note
用于 ACME 续约风险分析
```

## 第七步：Agent 粗搜

Agent 通过 `workrecorder-context` skill 调 CLI：

```bash
./.venv/bin/workrecorder events search "ACME 续约风险" \
  --workspace default \
  --app "Google Chrome" \
  --json
```

返回的不是完整 event，而是安全摘要卡：

```json
{
  "ok": true,
  "agent_run_id": "arun_demo_20260518_001",
  "retrieval_call_id": "rcall_search_001",
  "snapshot_id": "snap_search_001",
  "items": [
    {
      "event_id": "evt_acme_pricing_001",
      "captured_at": "2026-05-18T10:23:31+08:00",
      "source": {
        "app_name": "Google Chrome",
        "title": "ACME Pricing Dashboard",
        "origin": "http://127.0.0.1:8877",
        "sanitized_url": "http://127.0.0.1:8877/acme_pricing.html"
      },
      "user_note": "用于 ACME 续约风险分析",
      "selection_bbox": {"x": 386, "y": 246, "width": 418, "height": 128},
      "selection_text": "Account\nStatus\nRisk\nACME\nProcurement delayed\nRenewal risk medium",
      "selection_text_truncated": false,
      "hidden_artifacts": [
        {"role": "screenshot", "reason": "raw visual requires audited raw endpoint"},
        {"role": "full_dom", "reason": "raw source is quarantined"},
        {"role": "a11y_tree", "reason": "raw UI tree is not agent-facing"}
      ],
      "preview_citation_id": "cit_acme_selection_preview"
    }
  ]
}
```

这张卡已经足够让 Agent 判断“ACME 续约风险”相关，但它还没有拿到 full DOM、raw screenshot 或 raw a11y tree。

## 第八步：Agent 带 event_id 精查

如果 Agent 需要更多上下文，它带 event id 精查：

```bash
./.venv/bin/workrecorder events inspect evt_acme_pricing_001 \
  --view selection_text \
  --view canonical \
  --view clean_page_text \
  --view screenshot_ref \
  --purpose agent_deep_read \
  --json
```

返回示例：

```json
{
  "ok": true,
  "agent_run_id": "arun_demo_20260518_001",
  "retrieval_call_id": "rcall_inspect_001",
  "snapshot_id": "snap_inspect_001",
  "event_id": "evt_acme_pricing_001",
  "readable_evidence": [
    {
      "kind": "selection_text",
      "citation_id": "cit_acme_selection_full",
      "text": "Account\nStatus\nRisk\nACME\nProcurement delayed\nRenewal risk medium"
    },
    {
      "kind": "clean_page_text",
      "citation_id": "cit_acme_clean_page_text",
      "text": "# ACME Pricing Dashboard\n\nBudget variance +18%\n\nAPI token: [redacted]\nAuthorization: Bearer [redacted]\n\n| Account | Status | Risk |\n| --- | --- | --- |\n| ACME | Procurement delayed | Renewal risk medium |"
    }
  ],
  "artifact_refs": [
    {
      "role": "screenshot",
      "artifact_id": "art_screen_acme",
      "content_type": "image/png",
      "sha256": "sha256:demo_screenshot_hash",
      "raw_endpoint_required": true
    }
  ],
  "denied": [
    {"role": "full_dom", "reason": "raw source is not exposed in event_inspect"},
    {"role": "a11y_tree", "reason": "raw UI tree is not exposed in event_inspect"}
  ]
}
```

精查能拿到更多可读文本和 screenshot ref，但 raw DOM / raw a11y tree 仍然不给。

## 第九步：Agent 生成回答

Agent 可以基于 citation 回答：

```text
ACME 的续约风险主要来自采购延期和预算偏差。页面中 ACME 的状态是 “Procurement delayed”，风险是 “Renewal risk medium”；同一页面还显示预算偏差为 +18%。建议会前准备预算偏差解释和采购延期的替代方案。
```

答案里的关键判断可以对应 citation：

- `cit_acme_selection_full`：表格里的 ACME / Procurement delayed / Renewal risk medium。
- `cit_acme_clean_page_text`：页面里的 Budget variance +18%。

## 第十步：usage record 和复盘

回答结束后，Agent 调：

```bash
./.venv/bin/workrecorder usage record \
  --bundle cb_acme_001 \
  --agent codex \
  --agent-run-id arun_demo_20260518_001 \
  --purpose customer_brief \
  --used-citation cit_acme_selection_full \
  --used-citation cit_acme_clean_page_text \
  --output-ref local_answer_acme_001 \
  --json
```

以后用户或开发者可以复盘：

```bash
./.venv/bin/workrecorder agent replay --agent-run-id arun_demo_20260518_001 --json
```

复盘能看到：

- 用户问题或 query hash。
- Agent 搜了什么。
- 搜索返回了哪些 event。
- 精查了哪个 event。
- 每次 API 实际返回给 Agent 的 snapshot。
- 哪些 citation 被创建和使用。
- 最终 usage event 指向哪个 answer。

这就是 WorkRecorder 的核心价值：不仅能给 Agent 上下文，还能说明上下文怎么来的、怎么被读取、怎么被引用。

## 这个 case 证明了什么

这个 case 把 WorkRecorder 的几个关键设计串起来了：

| 设计点 | 在 case 里的体现 |
| --- | --- |
| 用户主动触发 | 快捷键 + bbox + note 定义上下文 |
| event-driven provider | daemon 截图后才命令 Chrome extension 现场采集 |
| 系统/App 双层采集 | screenshot/a11y + DOM/page metadata/selection map |
| 可追溯 artifact | 每个 artifact 有 provider、evidence、sha256、policy |
| 默认安全摘要 | 粗搜只给 app/title/origin/time/note/selection_text |
| 精查渐进披露 | event_id inspect 才给 canonical/clean_page_text/screenshot ref |
| raw 默认不给 | full DOM/a11y tree/raw screenshot bytes 不直接给 Agent |
| agent usage 留痕 | search、inspect、citation、usage 都能 replay |

## 还能测哪些页面

当前 hidden Chrome E2E 覆盖了多种页面形态：

- 普通网页。
- 新闻/blog。
- 长网页。
- 表格页面。
- 文档站。
- SaaS-like 页面。
- same-origin iframe。
- cross-origin iframe diagnostics。
- open shadow DOM。
- PDF-like 页面。

PDF 和文档类页面有一个现实限制：如果 a11y 或 DOM 只能给巨大的父节点，而不能给精确 leaf text，WorkRecorder 会保守处理，宁可产出低置信度/partial diagnostics，也不会把整页文本冒充“截图框内文本”。未来可以补 OCR、PDF text layer、AX range 作为新的 provider/enrichment。
