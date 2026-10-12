# Screenpipe 深读：主动采集设计借鉴

> 导航：[返回文档总览](../README.md) · 相关：[Active Context Capture：截图关键帧与记录片段](./USER_TRIGGERED_KEYFRAME_CONTEXT_CN.md) · [System Appshot](../architecture/SYSTEM_APPSHOT_CN.md)

这份文档记录对本地 `reference_code/screenpipe` 的代码和设计阅读结论，并把它转成 WorkRecorder 后续“主动录屏 / 关键帧上下文”的产品与架构建议。

一句话结论：

> screenpipe 值得学的不是“持续录视频”，而是“事件驱动地保存关键屏幕状态，并把截图、文字、App、窗口、触发原因和搜索入口绑定成同一个可回放证据单元”。

WorkRecorder 的定位不同。screenpipe 是长期个人活动记忆，WorkRecorder 是用户主动截图触发的可信上下文。我们应该保留主动、克制、可审计的心智，只借鉴它的采集管线和 Agent 使用方式。

## screenpipe 实际怎么做

#### 1. 它已经从固定 FPS 录屏走向事件驱动

核心入口在：

- `reference_code/screenpipe/crates/screenpipe-engine/src/event_driven_capture.rs`
- `reference_code/screenpipe/docs/EVENT_DRIVEN_CAPTURE_SPEC.md`

screenpipe 不再只靠固定帧率盲录，而是把这些信号当作 capture trigger：

| 触发 | 意义 |
| --- | --- |
| app switch | 用户切到新上下文，最高价值 |
| window focus | 新窗口、新 tab、新文档 |
| click | 用户刚操作，画面可能变化 |
| typing pause | 不记录每个按键，而是等用户停下来记录结果 |
| scroll stop | 等滚动停下后记录新内容 |
| clipboard | 复制动作本身有价值，但代码里会避免为 clipboard 单独跑完整截图 |
| visual change | 被动画、通知、自动刷新触发 |
| idle fallback | 长时间没事件，也周期性留锚点 |
| manual | 手动强制 capture |

几个细节很有价值：

- 有最小 capture 间隔，避免风暴。
- 有 idle fallback，避免时间线上长期没有锚点。
- app/window 切换时重置 dedup，避免新上下文被旧 hash 误杀。
- 非活跃显示器进入 Warm/Cold 状态，降低多屏 CPU。
- DRM、锁屏、时间计划、忽略窗口在截图前 gate，不是截图后再打码。

#### 2. Paired capture 是核心

核心入口在：

- `reference_code/screenpipe/crates/screenpipe-engine/src/paired_capture.rs`

它的关键思想是：

```text
同一个触发点
  -> 截图
  -> 走 accessibility tree
  -> 必要时 OCR
  -> 写同一个 frame row
```

这样搜索命中文字时，缩略图和文字不会错时。screenpipe 自己的设计文档里也说，之前最大问题是 OCR、a11y、UI event 各跑各的，用户搜到文字时对应截图不是同一刻，信任感会崩。

对 WorkRecorder 来说，这正好对应我们已经做的 `system.appshot` 思想：

```text
一次截图 event
  -> screenshot evidence
  -> a11y evidence
  -> OCR evidence
  -> appshot 聚合 refs + quality
```

主动关键帧也必须保持这个原则：每一帧都是 paired evidence，不允许“图片是 12:00:01，文字是 12:00:04，但看起来像同一帧”。

#### 3. a11y 优先，OCR 兜底，但要识别“薄 a11y”

screenpipe 不是无脑 OCR。它先看 accessibility tree：

- 如果 a11y 有可靠文本，就跳过 OCR。
- 如果 a11y 没文本，跑 OCR。
- 如果 a11y 只有工具栏/浏览器 chrome，而正文是 canvas / video / PDF / Google Docs/Figma/Miro 这类主内容不可见，它判断为 `thin a11y`，再跑 OCR 做 hybrid。

它还有一些 app/site heuristic：

- Google Docs / Sheets / Slides
- Figma / Miro / Canva / Excalidraw
- 视频会议类应用
- 终端类应用需要特殊节流

对 WorkRecorder 的启发：

- `selection_text` 仍以 a11y 为主，但必须记录 coverage/quality。
- OCR 不应只是“失败兜底”，也应是 `thin_a11y` 和图像型 App 的默认增强。
- PDF/Preview、会议、Figma、Miro、图表、截图里的图片文字，应明确进入 OCR 优先策略。
- 每次选择 a11y/OCR/hybrid 都要落 `source_method` 和 diagnostics，不能让 Agent 误以为所有文字都同等可靠。

#### 4. 它存的是关键帧图片，不再依赖视频抽帧

screenpipe 文档明确说明：事件驱动后，不适合再写 H.265 视频 chunk，因为帧时间不均匀，读取还要 ffmpeg 抽帧。新路径直接写 JPEG snapshot，并把路径挂在 frame row。

对 WorkRecorder 的启发更明确：

> 主动采集第一版不要录视频，存关键帧截图就够了。

原因：

- 用户主动截图的频率低，不需要视频压缩来摊成本。
- Agent 更需要“哪几张关键画面 + 每张对应文字和来源”，不是一段视频。
- 关键帧天然适合 evidence/citation。
- 分享、导入、审计都比视频简单。

视频可以作为未来“用户显式记录 10 秒操作过程”的模式，但不应该是默认后台能力。

#### 5. 它有一个 frame 级 canonical full_text

screenpipe 过去有 OCR、a11y、UI monitoring 多套搜索入口，后来收敛到 `frames.full_text` 和 `frames_fts`。代码里 `insert_snapshot_frame_with_ocr` 会根据 `text_source` 合并出 `full_text`：

- accessibility
- OCR
- hybrid = a11y + OCR

结构化元素仍存 `elements`，但主搜索先走 frame 级 full_text。

对 WorkRecorder 的启发：

- 每个 `ContextKeyframe` 也应该有 `keyframe_full_text`。
- 每个 `ContextEvent` 应该有 `event_context_text`，由 anchor/settle/OCR/Web/canonical text 聚合。
- 搜索默认查 event 级安全文本；精查时才展开 keyframe/evidence。
- OCR、a11y、DOM 不要各自变成并列搜索真相源，否则结果重复且难解释。

#### 6. 元素树是补充，不是默认读取面

screenpipe 把 OCR word boxes 和 a11y nodes 写入统一 `elements` 表，带 role、bbox、parent、depth、confidence、on_screen 等字段。元素写入是 deferred：frame 先可搜，元素树后补。

这对 WorkRecorder 非常适合：

- event 先保存、先可搜。
- `selection_text` / OCR text 先入 index。
- a11y tree、OCR boxes、DOM selection map 后续补齐。
- Agent 默认不拿 raw tree；需要精查/citation/高亮时用 element refs。

#### 7. 它的 Agent 工具采用渐进式披露

screenpipe MCP 的 usage guide 很像我们想做的 skill：

1. `activity-summary`：先问“这段时间大概做了什么”。
2. `search-content`：需要具体内容时再搜。
3. `search-elements`：需要 UI 控件/结构时再查。
4. `frame-context`：有 frame id 后查完整时刻。
5. `update-memory`：把稳定事实/偏好/决定写回 memory。

这跟 WorkRecorder 已经设计的粗搜/精查/引用/usage record 是同一路线。区别是我们应该更严格：

- search card 更短，只给 note/time/app/title/url/selection_text/available_fields。
- inspect 才给 clean page text、OCR、screenshot ref、system_appshot summary。
- raw screenshot、raw DOM、raw a11y tree 仍走单独 raw endpoint 和 audit。
- agent run ledger 记录每次 query 拿到哪些字段。

#### 8. 它还有音频、输入事件、长期 memory，但 WorkRecorder 不应照搬默认开启

screenpipe 还采：

- 麦克风/系统音频
- VAD/STT
- speaker ID
- click/keyboard/clipboard/app switch
- meetings
- memories
- pipes 定时执行

这些给 WorkRecorder 的启发是“可选信号层”，不是默认范围。

WorkRecorder 可以未来支持：

- 用户主动标记时，把最近会议转写片段作为可选上下文。
- 截图时记录 app/window switch 作为 metadata。
- 复制链接/选中文本时作为用户意图 signal。
- agent 回答后，把用户确认的结论写成 `memory`。

但不建议默认记录键盘内容和音频。它们隐私压力远高于主动截图。

## 对 WorkRecorder 的设计建议

### 1. 产品定位：不是后台录屏，是主动上下文记录

建议产品文案不要叫“持续录屏”。更准确的是：

> 当用户主动截图或主动开始记录时，WorkRecorder 把这段重要工作现场整理成 Agent 以后能安全使用的上下文。

这里有两种产品入口：

| 入口 | 用户心智 | 默认行为 |
| --- | --- | --- |
| 截图关键帧 | “这一刻很重要” | 保存 anchor，并在短窗口补少量关键帧 |
| 上下文录制片段 | “接下来这段操作很重要” | 用户开始/结束，期间只保留关键帧 |

截图关键帧的用户心智：

- 我主动按下快捷键。
- WorkRecorder 立即保存 anchor。
- 页面稳定、OCR 完成、provider 补全时，WorkRecorder 可能再补关键帧。
- Agent 默认只看安全摘要。
- 原图和原料仍锁定。

上下文录制片段的用户心智：

- 我主动点击“开始记录”。
- 我选择一个窗口、区域或当前 App。
- WorkRecorder 只在这段时间里保存关键变化。
- 我点击“结束记录”后，它生成一张可搜索、可精查、可分享的上下文卡片。

这比“后台一直看屏幕”更容易被用户接受，也比单张截图更适合流程演示、bug 复现、PDF/网页阅读和多页面比较。

### 2. 采集什么：默认存关键帧，不存视频

第一版建议只存图片关键帧：

| 数据 | 默认采集 | 说明 |
| --- | --- | --- |
| anchor screenshot | 是 | 用户截图那一刻，必须有 |
| settle screenshot | 条件触发 | 300-800ms 后页面稳定才留 |
| provider completion keyframe | 条件触发 | Web/OCR/a11y 明显补全时留 |
| recording start/end frame | 是 | 用户显式录制片段的开始和结束 |
| recording change frames | 条件触发 | 录制期间只留关键变化 |
| short video | 否 | 仅用户显式勾选“保存视频” |
| full screen video | 否 | 不适合 WorkRecorder 默认隐私心智 |

每张 keyframe 都应绑定：

- captured_at
- trigger
- selected bbox
- primary/secondary surfaces
- screenshot evidence
- appshot evidence
- a11y evidence refs
- OCR evidence refs
- provider outcome refs
- quality report
- keep/drop reason

### 3. 采集时机：四层触发

### A. 用户主动触发

这是 WorkRecorder 的核心：

```text
hotkey / menu / workbench
  -> 用户框选
  -> anchor keyframe
```

### B. 用户显式上下文录制

这是对“开始时间、结束时间、窗口”的正式支持。

```text
开始记录
  -> 选择窗口 / 区域 / 当前 App
  -> recording session started_at
  -> 关键帧事件循环
  -> 结束记录
  -> recording session ended_at
  -> 生成 ContextEvent / RecordingSummary
```

第一版优先做窗口录制：

- 绑定 window id。
- 记录 app name、bundle id、window title、display id。
- Chrome/Edge 命中时触发 Web provider。
- PDF/Preview 命中时先走 system-only + OCR，未来接 PDF provider。
- 窗口丢失、最小化、遮挡时写 quality diagnostics。

### C. 主动触发后的短窗口

截图模式默认 5 秒内观察；录制模式在整个 session 内用同一套 keep/drop 策略：

| 触发 | 默认策略 |
| --- | --- |
| settle delay | 500ms 后检查一次 |
| visual diff | bbox 内 diff 超阈值才留 |
| text diff | a11y/OCR/Web 文本新增明显才留 |
| provider completed | URL/DOM/OCR/clean text 完成且质量提升才留 |
| surface changed | 主窗口变更或弹窗覆盖才留 |

建议默认上限：

- `max_keyframes = 4`
- `window_ms = 5000`
- `min_frame_gap_ms = 250`

录制模式默认参数可以更长、更保守：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `max_duration_minutes` | 10 | 防止用户忘记停止 |
| `max_keyframes` | 60 | 保留关键帧，不保存连续视频 |
| `min_frame_gap_ms` | 500 | 降低噪声和资源消耗 |
| `idle_anchor_interval_sec` | 30 | 长时间静止时留一个时间锚点 |

### D. 显式长一点的“记录接下来 10 秒”

未来可以有：

- 记录接下来 10 秒关键变化。
- 适合复现 bug、动态图表、下拉菜单、网页 loading。
- 仍然只存关键帧，不存视频。

### 4. 除了屏幕还采什么

默认围绕截图或录制 scope 保存：

| 类别 | 内容 | 是否默认给 Agent |
| --- | --- | --- |
| system.screenshot | 原始截图 / keyframe 图片 | 否，raw gate |
| system.appshot | 主 App、窗口、surface、权限、质量 | 精查摘要可见 |
| system.macos_a11y | AX tree、text blocks、coverage | 只派生 selection_text |
| system.ocr | OCR text、boxes、engine、confidence | 派生 text 可见 |
| app provider | Chrome URL、title、DOM、clean page text、selection map | 只给 clean/canonical |
| user intent | note、触发方式、workspace、actor | 粗搜可见 |
| activity signal | app/window switch、provider outcome、quality improvement | 精查摘要可见 |
| recording metadata | started_at、ended_at、duration、scope、keyframe_count | 粗搜/精查摘要可见 |

默认不采：

- 全局键盘输入内容。
- 全局音频。
- clipboard 原文。
- cookies/localStorage/sessionStorage/network response。
- raw DOM / raw a11y tree 给 Agent。

### 5. 存下什么：event + keyframes + evidence refs

建议新增或强化这些对象：

```text
ContextEvent
  一次用户意图和最终 Agent 可引用上下文

ContextKeyframe
  一张关键帧，属于某个 event

KeyframeEvidenceLink
  keyframe -> screenshot/a11y/OCR/appshot/Web evidence

KeyframeContextBundle
  多帧聚合后的安全上下文包

KeyframeFullText
  帧级 canonical searchable text

ActiveCaptureSession
  用户主动开始/结束的一段截图关键帧或记录片段

RecordingTimeline
  录制片段里的关键帧顺序、角色和保留原因
```

不要把 raw 图片 bytes、vault path、raw tree 复制进 keyframe JSON。只存 refs 和 hash。

### 6. 单个 event 给 Agent 暴露什么

建议保持渐进式披露：

### 粗搜 summary card

只给：

- event_id
- captured_at
- recording started_at / ended_at / duration，如果是录制片段
- primary app
- title
- sanitized URL
- user note
- selection_text
- recording_summary，如果是录制片段
- OCR/clean text 是否可精查
- hidden materials summary
- keyframe_count

不直接给：

- screenshot
- full DOM
- raw a11y tree
- OCR boxes
- vault path

### 精查 event inspect

按 view 给：

- `summary`
- `selection_text`
- `clean_page_text`
- `visual_ocr_text`
- `system_appshot`
- `keyframes`
- `recording_timeline`
- `evidence_refs`
- `screenshot_ref`

### raw

单独 endpoint：

- raw screenshot
- raw keyframe image
- raw DOM
- raw a11y tree

必须带 purpose / agent_run_id / audit。

录制片段的 Agent 默认视图应更像“过程摘要”，而不是一堆帧列表：

```text
这段记录持续 2 分 14 秒，主 App 是 Chrome。
用户备注：比较三个套餐的价格差异。
关键变化：
1. 打开定价页
2. 滚动到套餐表格
3. 切换企业版
4. 停在对比结论
可精查材料：OCR 文本、网页正文、关键帧截图引用
锁定材料：原始截图帧、DOM、a11y tree、可选视频
```

### 7. 数据能不能预处理

可以，而且应该分层预处理：

### 写入时轻处理

目标是 1 秒内可搜：

- screenshot artifact
- system_appshot
- selection_text
- OCR text 如果本机快
- event_context_text
- recording metadata / keyframe timeline
- FTS/index receipt

### 后台异步处理

不阻塞保存：

- OCR retry
- keyframe diff
- clean page text
- canonical text
- redaction/DLP
- caption
- entity/action-item extraction
- recording summary
- per-keyframe caption
- session-level canonical text
- day/session/project rollup

### 读取时压缩

按 Agent query 动态生成：

- search card
- inspect view
- context bundle
- citation pack

不要把每次截图都提前 LLM 总结成一段“永久真理”。更稳的是保留证据，按问题生成摘要。

### 8. 能不能变成 Agent 参考的“人类演示 skill”

可以，这是很有价值的一层。screenpipe 的 MCP guide 给了很强启发：让 Agent 知道“先看概要，再精查证据”。

WorkRecorder 可以做一个 `workrecorder-context` skill 升级版：

### Skill 给 Agent 的工作流

```text
1. workrecorder events search --since ... --json
2. 选 event_id
3. workrecorder events inspect <event_id> --view summary,keyframes,selection_text --purpose ...
4. 必要时 workrecorder artifacts raw <artifact_id> --purpose visual_check
5. 回答里引用 citation_id
6. workrecorder usage record --used-citation ...
```

### Skill 里的“人类演示”

不要只写命令，可以给 Agent 一个行为范式：

- 用户主动截图通常代表“这块内容重要”。
- `note` 是用户意图，比网页全文更优先。
- `selection_text` 是默认框内文字。
- `visual_ocr_text` 是视觉兜底，置信度要看 diagnostics。
- `clean_page_text` 是网页全文增强，不代表用户框选内容。
- raw screenshot 只在需要视觉判断时请求。
- keyframe 里 anchor 是用户截图时刻，settle/provider frame 是补强，不要混为一谈。
- recording 里 start/end 是用户主动边界，中间关键帧是过程证据，不是连续视频。

这比裸 CLI 手册更像真正的 agent 使用技能。

## 推荐落地路线

### P8.1：主动关键帧 schema

- `ContextKeyframe`
- `KeyframeRole`
- `KeyframeTrigger`
- `KeyframeKeepReason`
- `KeyframeQualityReport`
- keyframe ledger tables
- golden fixtures

### P8.2：anchor-only

每次截图都生成 anchor keyframe，引用已有 screenshot/appshot/a11y/OCR/Web evidence。

### P8.3：短窗口 settle

截图后 500ms 检查一次：

- visual diff
- text diff
- provider quality

只有质量明显提升才保留第二帧。

### P8.4：provider completion keyframe

OCR/Web provider 后台完成后，如果新增了 Agent 可用材料，生成 provider completion keyframe 或更新 keyframe bundle。

### P8.5：Skill / Agent 展示

- search card 增加 keyframe_count / available_fields。
- inspect view 增加 keyframes。
- citation 支持 keyframe_id。
- agent replay 展示某次回答用了哪一帧。

### P8.6：可选 10 秒关键变化

做成显式按钮，不是默认后台：

- “记录接下来 10 秒”
- 只保留关键帧
- 默认 max 8 帧
- Workbench 可回放为轻量 storyboard

### P8.7：Context Recording Session

做成正式入口：

- “开始记录” / “结束记录”。
- 第一版支持窗口 scope。
- 录制中有轻浮层和计时。
- 每个 session 生成 start/end keyframe 和若干 change/provider keyframe。
- 结束后生成 recording summary、event_context_text 和 citation refs。
- Agent 粗搜看到摘要，精查看到 timeline，raw 帧仍锁定。

## 最重要的边界

WorkRecorder 不该变成“无感监控”。它应该是：

> 用户主动标记重要时刻，或主动记录一段重要操作；系统只保存关键证据，让 Agent 以后能安全、可信、有引用地使用这段上下文。

所以默认策略应该是：

- 不持续录屏。
- 不默认录音。
- 不默认记录键盘内容。
- 不默认暴露 raw。
- 不在用户没开始录制时长期观察。
- 不把“录制片段”伪装成完整视频。
- 不为了“完整记忆”牺牲用户信任。
