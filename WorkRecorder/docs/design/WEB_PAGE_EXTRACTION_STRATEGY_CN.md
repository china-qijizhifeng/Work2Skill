# WorkRecorder Web 全文抽取策略

Updated: 2026-05-20

## 目标

WorkRecorder 的网页全文抽取不是 OCR。截图内文字可以用 OCR/Vision 兜底；网页全文应优先从浏览器侧的页面结构、DOM、可见文本、同源 iframe、open shadow root 和应用语义中提取。

核心原则：

- 用户主动截图只决定“这个网页上下文值得保存”。
- 全网页文本来自浏览器扩展的 source evidence，再由 daemon 做 clean page text / canonical text。
- 扩展不读取 cookie、localStorage、sessionStorage、网络响应体或 Chrome cookies。
- full DOM 继续是 quarantined/raw evidence，不直接暴露给 Agent。
- 能抽就标明方法；不能完整抽就标明 omitted reason，不伪装成完整。

## 抽取层级

1. **Selection / region text**
   - 目标：服务用户框选区域。
   - 来源：DOM text nodes 与 viewport bbox 相交；失败时以后走 OCR。
   - 状态：必须带 source、confidence、selection map。

2. **Semantic readable blocks**
   - 目标：普通 HTML、文章、文档、表格、代码块。
   - 来源：`main/article/h/p/li/pre/code/blockquote/table`、同源 iframe、open shadow root。
   - 结构：heading/list/table/code 尽量保留 markdown 形态。

3. **Application visible text fallback**
   - 目标：React/SPA/SaaS/ChatGPT-style 页面，正文不是 `p/li`，而是 div/span。
   - 来源：`main`、`[role=main]`、`article`、`#thread`、`[data-scroll-root]`、body 兜底。
   - 重要限制：逐 text node 做 visible / sensitive / nav-noise 过滤，禁止直接整棵 `innerText` 入库。

4. **ARIA table/grid**
   - 目标：SaaS dashboard 常见的 `role=grid/table`。
   - 来源：`role=row/columnheader/cell/gridcell`，转成 markdown table。

5. **Partial / future providers**
   - 虚拟列表、无限滚动、跨域 iframe、真实 PDF viewer、canvas/scanned PDF、图表图片，不应声称完整。
   - 后续需要 bounded scroll、frame aggregation、PDF text provider、OCR/VLM provider 或 source API。

## 当前明确支持

- 普通文章和文档 HTML。
- 长 HTML 页面。
- 原生 `<table>`。
- `pre/code` 基础文本。
- 同源 iframe。
- open shadow root。
- div-only SPA fallback。
- `text-token-*` 这类正常 CSS class 不再被误判为敏感。
- `data-auth-token` / `data-api-key` / `data-session-id` 等敏感子树会被过滤。
- hidden/nav/footer/search/aside 噪声不会进入 fallback 文本。
- ARIA grid/table 基础 markdown。

## 当前边界

- 真实 PDF：如果浏览器暴露 text layer，可以部分抽取；canvas/scanned PDF 需要 OCR/PDF provider。
- arXiv HTML 页面：当作普通 HTML/文章/表格处理；arXiv PDF 走 PDF 边界。
- ChatGPT/Slack/Linear 这类虚拟列表：只能拿当前已渲染 DOM。未 mounted 的历史消息不能凭空恢复。
- 跨域 iframe：当前只记录 partial reason；后续需要 all-frames aggregation。
- Canvas/SVG 图表：DOM 文本可取则取；纯视觉内容需要 OCR/VLM/chart extractor。

## 回归测试基线

浏览器扩展现在有 required Node/jsdom 测试，覆盖：

- div-only SPA 文本。
- `text-token-*` 不误杀。
- hidden/nav/sensitive descendant 不泄漏。
- ARIA grid dashboard。

隐藏 Chrome E2E 仍保留为 opt-in，用来验证真实扩展 provider 链路；但它在本机可能受 headless Chrome 扩展限制影响，所以不能作为唯一保护。
