# 阶段 4：增强与去噪

> 导航：[返回文档总览](README.md) · 上一篇：[阶段 3：事件入库](03_EVENT_LEDGER_CN.md) · 下一篇：[阶段 5：索引与披露](05_INDEX_DISCLOSURE_CN.md)

增强阶段回答：

> 原始截图、DOM、a11y tree 这些材料，怎样变成 Agent 更容易读、更安全读、还能追溯来源的文本？

Provider 采回来的 raw evidence 很有价值，但不能直接丢给 Agent。它们通常太大、太乱、太敏感，也不一定正好对应用户框选区域。增强层的任务就是把事实层加工成可读的、受控的、能引用的上下文。

## 事实层和增强层分开

事实层是现场采集到的材料：

- OS screenshot。
- a11y tree。
- a11y text blocks。
- Web full DOM。
- Web visible text。
- Web page metadata。
- selection map。

增强层是 daemon 后处理出来的材料：

- `selection_text`。
- `clean_page_text`。
- `canonical_text`。
- 未来的 OCR text、PDF text layer、entity extraction、table extraction、message thread extraction。

这个分层非常重要。事实层是证据，增强层是解释和投影。增强算法可以升级、重跑、比较版本；事实层不能被随便覆盖。

## selection_text：截图框内文字

`selection_text` 是 WorkRecorder 当前最重要的默认 evidence。它回答：

> 用户框住的这一块里面，能读到哪些文字？

它不是 raw a11y text，也不是 full DOM 片段，而是 daemon 从 a11y blocks 中派生出来的正式 evidence。

### 为什么以 a11y 为主

截图框内文本应该跨 App 可用。Chrome 可以用 DOM，但原生 App、PDF viewer、Terminal、IDE、聊天窗口不一定有 DOM。

macOS Accessibility 是一个更通用的起点：

- 能覆盖很多原生控件。
- 能拿到 role、value、label、frame。
- 能和用户 bbox 做几何匹配。
- 能为未来非 Web provider 复用。

DOM 仍然有价值，但在当前设计里主要作为 Web 增强材料，不是默认框内文本的唯一来源。

### selection_text 怎么生成

大致流程：

1. 读取已入库的 a11y text blocks。
2. 计算每个 block 和截图 bbox 的 overlap。
3. 过滤浏览器工具栏、菜单、窗口标题栏等 chrome 噪音。
4. 只优先接受 leaf text block，避免把整页父节点 value 塞进去。
5. 做小范围 edge recovery，补用户框选略小导致的文字边缘。
6. 按阅读顺序排序。
7. 去重，但不误删两个不同控件里相同的文字。
8. 生成 strict text、diagnostics、confidence、parent evidence refs。

### 多控件和表格怎么办

如果用户框住一个表格，系统不会简单按字符串去重。两个按钮都叫 “Edit” 时，如果位置不同，就应该保留。

排序规则也不是只看 a11y tree order：

- 普通文本按空间行列顺序。
- 表格按 row-major。
- 多栏长文档尽量先左栏从上到下，再右栏从上到下。
- AX tree order 只作为 tie-breaker。

### 长文档 / PDF 怎么办

长文档最危险的问题是：a11y 有时只给一个很大的父节点，里面塞了整页甚至整篇文本。

WorkRecorder 当前策略是保守的：

- 只信任 bbox overlap 的 leaf text blocks。
- 如果只有巨大父节点有整页文本，不直接塞进 `selection_text`。
- 这种情况会产出低置信度、短文本或空文本，并在 diagnostics 中标记。
- 未来可以补 OCR、PDF text layer、AX range，但不会把整页误当“框内文本”。

这比“看起来拿到了很多字”更安全，因为默认摘要卡不能泄漏用户没框住的大段内容。

## clean_page_text：网页可读正文

`clean_page_text` 面向 Web 精查。它表示“当前 Chrome tab 已加载文档的 agent 可读网页正文”。

第一版由 Chrome extension 在真实 tab 中读取 live DOM/readability source，然后 daemon 做清洗、redaction、DLP。

它会尽量保留：

- 标题。
- 段落。
- 列表。
- 表格。
- 代码块。
- 链接文本。
- 可见正文结构。

它会过滤或降权：

- script/style/template。
- hidden/password/token-like controls。
- cookie/storage/network response。
- URL query/hash。
- raw DOM attributes 中的敏感值。

对于 iframe、shadow DOM、无限滚动、PDF text layer 缺失，系统会写 coverage diagnostics，不假装完整。

## canonical_text：搜索和 bundle 的统一文本

`canonical_text` 是为了搜索、bundle、citation 准备的统一文本。

它通常按 section 组织：

- `Selection`：来自 selection_text。
- `Page Text`：来自 clean_page_text。
- `Other Context`：来自 note、metadata 或未来增强。

每段都保留 parent evidence ids。这样 Agent 回答时引用一段 canonical text，仍然能追到它来自 selection_text 还是 clean_page_text，最后能回到截图、DOM 或 a11y blocks。

## DLP / Redaction 是什么

这里的 DLP 可以理解成“进入 Agent 可读层之前的敏感内容检查和遮挡”。

当前重点处理常见高风险内容：

- token。
- authorization header。
- password。
- secret。
- 邮箱、密钥样式字符串等。

例如页面里出现：

```text
Authorization: Bearer SHOULD_NOT_LEAK_VISIBLE_BEARER
```

清洗后的 agent-readable 文本应该变成类似：

```text
Authorization: Bearer [redacted]
```

raw evidence 仍在本地 vault 里，但默认不会给 Agent，也不会进入 agent-facing index。

## 增强结果也要可审计

每个增强结果都要记录：

- 输入 evidence ids。
- 输出 evidence id。
- extractor name/version。
- policy version。
- captured_at / observed_at。
- redaction 状态。
- confidence / diagnostics。
- artifact id。

这样以后如果 selection_text 出错，可以知道是 a11y provider 问题、projection 规则问题，还是 disclosure 显示问题。

## 设计亮点

- **默认给框内文字**：粗搜卡优先展示 `selection_text`，不是整页 DOM。
- **Web 全文可精查**：需要深入 event 时再读 `clean_page_text`。
- **增强可重算**：算法升级不破坏事实层。
- **敏感内容先处理再索引**：raw DOM/a11y tree 不进 agent-facing index。
- **未来扩展自然**：OCR、PDF text layer、App-specific extractor 都能作为新的 enhancement provider 加进来。

---

导航：[返回文档总览](README.md) · 上一篇：[阶段 3：事件入库](03_EVENT_LEDGER_CN.md) · 下一篇：[阶段 5：索引与披露](05_INDEX_DISCLOSURE_CN.md)
