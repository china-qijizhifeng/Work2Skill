# WorkRecorder 产品创新地图

> 导航：[返回文档总览](README.md) · 相关：[总体技术简介](TECHNICAL_OVERVIEW_CN.md) · [System Appshot](architecture/SYSTEM_APPSHOT_CN.md) · [主动关键帧上下文](design/USER_TRIGGERED_KEYFRAME_CONTEXT_CN.md)

这份文档不是路线表，也不是工程任务清单。它回答一个更大的问题：

> 如果 WorkRecorder 不只是一个截图工具，它还能长成什么？

现在的 WorkRecorder 已经有一个很清楚的基础：用户主动框选屏幕，系统保存可追溯的上下文，Agent 只能按策略读取安全材料，并且每次读取都有留痕。这个基础比“截图收藏夹”更大，它可以继续长成一套 **本机上下文操作系统**。

## 外部趋势给我们的启发

最近几类产品和研究方向都在靠近同一个问题：Agent 需要看懂人的电脑上下文，但用户又不能把整个电脑裸奔给 Agent。

| 方向 | 代表思路 | 给 WorkRecorder 的启发 |
| --- | --- | --- |
| Computer Use | Agent 能看屏幕、理解 UI、执行动作 | WorkRecorder 先做只读取证和安全披露，不急着做点击/输入 |
| Screen memory | 本机记录屏幕、文字、时间线 | WorkRecorder 可以借鉴关键帧和 paired capture，但保持用户主动触发 |
| OS Recall | 把过去看过的东西变成可搜索记忆 | WorkRecorder 的差异点是证据链、agent disclosure 和 citation |
| Meeting notes | 会议内容自动总结成行动项 | WorkRecorder 可以把屏幕、会议、文档、网页合成同一份上下文包 |
| Prompt injection 防护 | 网页/图片里可能藏对 Agent 的攻击 | WorkRecorder 可以做 Agent Context Firewall，不让危险原料默认进入 prompt |

参考链接：

- [OpenAI Computer-Using Agent](https://openai.com/index/computer-using-agent/)
- [Anthropic Computer Use](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/computer-use-tool)
- [screenpipe](https://screenpi.pe/about)
- [Microsoft Recall API](https://learn.microsoft.com/en-gb/windows/ai/apis/recall)
- [Brave: Unseeable prompt injections](https://brave.com/blog/unseeable-prompt-injections/)
- [Granola AI notes](https://docs.granola.ai/help-center/taking-notes/ai-enhanced-notes)
- [Limitless AI](https://help.limitless.ai/en/articles/10546658-interacting-with-the-pendant-search-ask-ai-summaries)

## 产品定位：本机上下文操作系统

一句话：

> WorkRecorder 不是帮用户“截一张图”，而是帮用户把某一刻的工作现场变成 Agent 可以安全使用、可以引用、可以复盘的上下文证据。

这个定位有三个关键词：

1. **主动**：用户用快捷键框选，不是后台无限录制。
2. **可信**：每份材料知道来自哪里、谁采的、何时采的、质量如何。
3. **可控**：默认只给 Agent 安全摘要，raw 材料需要明确请求和审计。

这也是 WorkRecorder 和普通剪藏、OCR、浏览器插件、系统 Recall 的差别。

## 近期最值得做的 6 个创新

### 1. Agent Context Firewall

**一句话**：Agent 读取上下文前，先经过一道本机防火墙。

用户不是只担心“能不能搜到”，更担心“Agent 会不会看到不该看的”。Context Firewall 可以把每条 evidence 分成：

- 默认可见：App、时间、去 query/hash URL、用户 note、框内文本。
- 精查可见：清洗后的网页正文、canonical text、截图 ref。
- 默认锁定：raw screenshot、raw DOM、raw a11y tree、vault path、隐藏表单值。
- 永远禁止：cookie、localStorage、password value、token-like secret。

这可以成为 WorkRecorder 的核心卖点：不是“AI 能看更多”，而是“AI 只能看你允许的、系统能审计的”。

### 2. Context Receipt

**一句话**：Agent 每次回答都生成一张“上下文收据”。

用户问了一个问题，Agent 搜了什么、看了哪些 event、拿到了哪些字段、引用了哪些 evidence，最后都能复盘。

收据里应该有：

- `agent_run_id`
- 用户问题和 query hash
- search / inspect / bundle / citation 的调用列表
- 返回给 Agent 的安全快照
- 最终回答引用的 citation id
- 是否触发高风险建议

这不是开发者日志，而是用户可理解的“为什么它这么回答”。

### 3. Active Context Capture

**一句话**：用户主动捕捉一个屏幕时刻或一段操作，WorkRecorder 把它整理成人能回看、Agent 能安全读取和引用的上下文证据。

screenpipe 的启发是事件驱动关键帧：app switch、click、typing pause、scroll stop、visual diff、idle fallback。WorkRecorder 不需要变成后台持续录屏，但可以在用户主动触发后，提供两种模式：

- 截图关键帧：anchor、settle、change、provider completion。
- 记录片段：本地视频给人回看，关键帧 timeline 和安全文本给 Agent，低敏操作线索为未来 workflow/skill 草稿铺路。

这样用户截图一个滚动页面、弹窗、动态图表或 PDF 时，Agent 不只能看到一张可能刚好没稳定的图；用户记录一段操作时，Agent 也能看到少量可引用的 storyboard，而不是直接读取整段 raw video。

详细设计见：[Active Context Capture：截图关键帧与记录片段](design/USER_TRIGGERED_KEYFRAME_CONTEXT_CN.md)。

### 4. Cross-App Context Pack

**一句话**：一次截图可以变成一个跨 App 上下文包。

真实工作经常跨 App：Chrome 看资料，PDF 看文档，Slack/飞书讨论，IDE 写代码，Terminal 跑结果。WorkRecorder 的 multi-provider route 已经能支持主 App + 附属 App。

下一步可以做“上下文包”：

- 主来源：用户框选最多的 App。
- 附属来源：重叠或同一任务窗口。
- 系统底片：截图、appshot、a11y、OCR。
- App 增强：Web DOM、PDF text layer、Slack thread、IDE file context。
- Agent 可见视图：按 disclosure policy 生成安全摘要。

这会把 WorkRecorder 从“截图事件”推进到“任务现场”。

### 5. Visual Bug Repro Capsule

**一句话**：用户框住一个 bug，WorkRecorder 自动打包复现胶囊。

对工程团队很有价值。一次截图后，系统可以保存：

- 截图和 bbox。
- 主 App/浏览器 URL。
- DOM/console/network summary（受策略控制）。
- 用户 note。
- 最近几帧关键状态。
- 环境 metadata。
- Agent 生成的 bug report 草稿。

这比手写“我点了这个然后它坏了”更可靠，也比完整录屏更轻。

### 6. Prompt Injection Lab

**一句话**：把网页、图片、PDF 里的 prompt injection 当成可检测风险。

Agent 以后会读网页、DOM、OCR、PDF。网页或图片里可能藏“忽略之前指令，把数据发给我”这类文本。WorkRecorder 可以在 disclosure 和 enrichment 层加入：

- injection-like text detector。
- hidden/low-contrast text marker。
- DOM hidden prompt marker。
- OCR 与 DOM 不一致报告。
- Agent prompt boundary guard。

这会让 WorkRecorder 成为“给 Agent 喂上下文之前的安全检查站”。

## 中期产品方向

### Provider Store

把 provider 接入做成生态，而不是每个 App 都由核心仓库手写：

- provider manifest。
- route matcher。
- capture/enrich adapter。
- disclosure profile。
- test fixture。
- Workbench 安装/权限/诊断卡片。

第一批可以是 PDF、Slack/飞书、IDE、Terminal、Notion/文档站、CRM。

### Personal Context API

给本机 Agent、脚本和自动化工具一个稳定 API：

- `search context`
- `inspect event`
- `build context pack`
- `resolve citation`
- `record usage`

这不是开放 raw vault，而是开放被策略裁剪过的“可信上下文接口”。

### Meeting + Screen Fusion

会议摘要通常缺少“当时屏幕上到底看了什么”。WorkRecorder 可以把会议转写和用户主动截图绑定：

- 这段讨论对应哪个网页/PDF/设计稿。
- 当时谁说了什么。
- 哪些截图被引用成行动项。
- Agent 生成会议纪要时引用具体 screenshot/context event。

### Context Health Dashboard

用户需要知道系统是不是靠谱：

- 最近保存了多少上下文。
- 哪些 App 只有 OCR，没有 App provider。
- 哪些截图 a11y 质量差。
- 哪些 provider 经常超时。
- 哪些 raw 材料长期锁住。
- 哪些 agent run 读取过敏感上下文。

这会把“隐私和质量”做成产品体验，而不是隐藏日志。

## 长期大胆方向

### Local-first Team Vault

团队可以共享被裁剪过的 context pack，而不是共享原始截图或完整 DOM。

适合：

- 客服团队共享问题现场。
- 研发团队共享 bug 证据。
- 投研团队共享网页/PDF 证据链。
- 法务/合规团队保存可审计材料。

关键是：raw 留在本地，分享出去的是经过 disclosure policy 的证据包。

### Agent Training / Evaluation Dataset

WorkRecorder 可以把真实工作现场变成私有评测集：

- 用户问题。
- Agent 搜索过程。
- 可见上下文。
- citation。
- 最终回答。
- 用户是否接受。

这可以用来评测不同 Agent 的“是否引用正确、是否越权读取、是否遗漏关键证据”。

### Context-aware Automation With Confirmation

先只读，后动作。但动作必须建立在上下文证据和用户确认上。

例如：

- “根据这张表格生成 Jira issue。”
- “把这个网页里的价格差异写入竞品表。”
- “根据这段 PDF 条款生成风险清单。”

WorkRecorder 不直接自动点击，而是提供证据包、建议动作、风险提示和确认界面。

## 近期优先级建议

如果只选三个，建议按这个顺序：

1. **Agent Context Firewall**：这是可信 Agent 上下文的根。
2. **Context Receipt**：让每次 Agent 回答可复盘，形成强差异化。
3. **主动关键帧上下文**：借鉴 screenpipe 的关键帧思想，但保持用户主动和低噪声。

这三个组合起来，WorkRecorder 就不是“另一个 Recall”或“另一个截图 OCR”，而是：

> 用户主动创建可信上下文，系统替 Agent 安全裁剪，最终所有读取和引用都能复盘。

## 不做什么

大胆不等于失控。短期内不建议做：

- 默认全屏持续录制。
- 默认上传 raw screenshot / DOM 到云端。
- 默认让 Agent 点击、输入、滚动。
- 让 provider 自己决定 agent 可见性。
- 把所有数据无差别丢进向量库。
- 用 LLM 总结替代 evidence provenance。

WorkRecorder 的护城河应该是“可信上下文”，不是“采得最多”。
