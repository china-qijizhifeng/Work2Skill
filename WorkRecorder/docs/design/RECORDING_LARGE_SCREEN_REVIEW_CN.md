# WorkRecorder 大屏录制复盘工作区设计方案

> 导航：[返回文档总览](../README.md) · 相关：[录制功能 UI/UX 设计方案](RECORDING_UI_UX_CN.md) · [Active Context Capture](USER_TRIGGERED_KEYFRAME_CONTEXT_CN.md) · [macOS App E2E Matrix](../manual/MACOS_APP_E2E_MATRIX.md)

## 一句话设计

**大屏复盘不是“大播放器”，而是一个 Recording Review Workspace：大视频播放器 + 章节时间线 + 当前步骤 Inspector。**

它的产品分工是：

```text
抽屉复盘 = 快速确认这条录制是什么
大屏复盘 = 认真回看这段过程发生了什么
系统播放器 = 仅播放视频本身
```

这个 feature 的核心不是把抽屉视频放大，而是让用户能在一个足够大的空间里对齐：

- video playback。
- keyframes。
- action trace。
- safe text。
- warnings。
- recording timeline。
- 后续可沉淀 workflow / skill 的步骤结构。

## 当前背景

WorkRecorder 已经完成区域录制 V1、录制库、复盘抽屉和显式视频播放：

- `录制库` 独立于 `截图库`。
- 录制卡片点击打开右侧复盘抽屉。
- 抽屉可加载 gated playback，并在视频下方显示轻量控制。
- 抽屉 timeline 支持 marker rail、filmstrip、上一步/下一步和 selected step detail。
- `用播放器打开` 会走同一条授权播放读取，再交给系统默认播放器。

当前缺口是：抽屉空间天然有限，适合快速确认，但不适合长时间观看、逐步复盘和细看证据。大屏复盘就是为了解决这个缺口。

## 设计原则

### 1. 同一份逻辑，两套布局

大屏复盘必须复用当前 recording inspect/read model，不重新发明一套数据解释逻辑。

```text
RecordingReviewCore
  selection
  playback
  timeline projection
  step projection
  safe evidence mapping

DrawerReviewLayout
  compact density

LargeReviewWindowLayout
  spacious density
```

这样可以避免：

- 抽屉看到 A，大屏看到 B。
- 抽屉 timeline 跳转和大屏 timeline 跳转行为不一致。
- 后续 P7.11 skill projection 要维护两套 evidence 映射。

### 2. 大屏是 Workspace，不是播放器

播放器只是主画面。真正的使用对象是一段过程：

```text
Recording Session
  video
  timeline steps
  current step evidence
  text snapshot
  screenshots/keyframes
  action trace
  warnings
```

因此大屏不能只做 video + transport controls。它必须让用户知道当前画面对应哪一步、这一步为什么被记录、有哪些证据、哪些地方需要复核。

### 3. 抽屉和大屏分工清楚

抽屉负责：

- 快速看一眼。
- 查看保存状态和备注。
- 点开录制库卡片后的轻量复盘。
- 快速播放 / 跳到 step / 打开系统播放器。
- 删除、复制链接、进入文件与材料。

大屏负责：

- 长时间观看。
- 逐步复盘。
- 视频、timeline、文字、截图、action trace 对齐。
- 查看 warning 和 needs-review step。
- 为后续 workflow / skill 整理做准备。

### 4. 内部复盘和系统播放器必须区分

产品文案需要形成两个动作：

| 动作 | 含义 |
| --- | --- |
| `打开复盘` | 在 WorkRecorder 内部打开大屏复盘：视频 + timeline + 证据 |
| `仅播放视频` / `用播放器打开` | 交给系统播放器，只看视频，不显示 timeline 和证据 |

这两个入口都要保留，但不能混用。

### 5. 不绕过安全披露

大屏复盘必须继续遵守现有 playback / raw gate：

- 视频读取走 dedicated playback route。
- 需要本机 trusted install secret。
- 需要明确 `session_id` / `event_id` / `artifact_id`。
- 需要 `read_raw_artifact` disclosure audit。
- generic raw artifact route 仍拒绝 `recording_video`。
- Agent inspect/search 不因为大屏打开而获得 raw video path。

## V1 产品决策

这些决策在 V1 实现前必须拍死，避免实现阶段反复摇摆。

| 决策 | V1 结论 |
| --- | --- |
| 窗口实例 | 全局单例 `RecordingReviewWindow` |
| 卡片默认点击 | 仍打开 Workbench 抽屉 |
| 大屏入口 | 卡片 footer/hover、抽屉主按钮、抽屉展开 icon |
| 初始状态 | 打开时继承抽屉 `selectedStepId` / `currentMediaTimeMs` |
| 状态回写 | 关闭或切换 session 时回写 `selectedStepId` / `currentMediaTimeMs` |
| 播放授权 | 继续走 dedicated gated playback route |
| 系统播放器 | `仅播放视频` 只打开系统播放器，不显示 timeline/evidence |
| 材料入口 | `文件与材料` 使用右侧 slide-over panel |
| Follow / Pin | V1 支持轻量 Follow / Pin |
| Esc 行为 | 普通窗口态不直接关闭；只退出 full-window/full-screen 或关闭临时 overlay/menu/focus |
| 关闭窗口 | 使用 `⌘W` 或窗口关闭按钮 |
| Dense timeline | 默认隐藏低价值 timer/no-change/repeated frame |
| Session 切换 | 复用单例窗口，先暂停当前播放，再切换 recording |
| 材料面板 | V1 以右侧 slide-over 临时覆盖 Inspector，关闭后回到当前 step |
| Follow 选步 | 使用当前播放时间之前最近 step，跨过下一个 marker 后再切换 |
| Timer 折叠 | representative timer frame 默认每 8 秒最多 1 个，可通过 density config 调整 |

## 产品目标与非目标

### 目标

- 给录制提供一个真正适合回看的主工作区。
- 让用户能在大画面中看清视频细节。
- 让 video time、timeline step、keyframe、文字和 action trace 始终对齐。
- 让用户能逐步审查操作过程，而不是在卡片和抽屉里来回找材料。
- 支持键盘高频操作，形成专业复盘手感。
- 支持 no-video / no-text / warning / degraded 等降级状态。
- 为后续 workflow summary / skill draft 做交互铺垫，但本阶段不自动生成 skill。

### 非目标

- 不做视频剪辑器。
- 不做复杂多轨时间线。
- 不做音频轨。
- 不做 annotation 弹幕。
- 不做自动 skill 生成。
- 不做跨录制 compare。
- 不做抽屉和大屏的实时双向同步 V1。
- 不暴露 raw video/path/DOM/a11y。

## 入口设计

### 入口位置

大屏复盘入口最多保留三个，避免按钮过多：

| 位置 | 推荐文案 | 行为 |
| --- | --- | --- |
| 录制库卡片 footer / hover action | `复盘` 或 `打开复盘` | 直接打开大屏复盘 |
| 抽屉视频区主按钮 | `打开复盘` | 从当前 selected step 打开大屏 |
| 抽屉 header icon | `展开` | 从当前 selected step 打开大屏 |

同时保留系统播放器入口：

| 位置 | 推荐文案 | 行为 |
| --- | --- | --- |
| 抽屉视频控制行 | `用播放器打开` | 仅打开视频 |
| 大屏 header / 更多菜单 | `仅播放视频` | 仅打开视频 |

### 默认点击行为

不建议把录制卡片的整卡点击改成直接进入大屏。当前卡片点击打开抽屉更轻，适合扫很多条录制。

推荐：

```text
卡片点击 = 打开右侧抽屉
卡片 footer/hover 的“复盘” = 打开大屏复盘
抽屉里的“打开复盘” = 打开大屏复盘
```

### 从抽屉打开大屏

如果用户在抽屉里已经选中了某个步骤：

```text
抽屉 selected step = 00:19 输入暂停
点击 打开复盘
→ 大屏直接选中 00:19 输入暂停
→ 视频 seek 到 00:19
→ 右侧 Inspector 显示 00:19 的文本 / action / warning
```

这是“大屏不是另一套页面”的关键体验。

## 窗口模型

### 推荐形态

V1 使用独立 `RecordingReviewWindow`，不要先做 Workbench 内 overlay。

原因：

- 视频需要大面积空间。
- 用户可以把复盘窗口拖到第二块屏幕。
- 不污染 Workbench 主布局。
- 快捷键焦点更清楚。
- 后续做 workflow preview / tutorial / compare 更容易扩展。

### 窗口尺寸

| 项 | 尺寸 |
| --- | --- |
| 最小尺寸 | `1100 × 720` |
| 推荐默认 | `1280 × 820` |
| 宽屏理想 | `1440 × 900` |
| Header 高度 | `60-68` |
| 右侧 Inspector | `min 340 / ideal 400 / max 480` |
| 底部 Timeline | `collapsed 140-160 / expanded 220` |
| 主区域 padding | `20-24` |
| 栏间距 | `12-16` |

右侧 Inspector 不用固定百分比。它应该使用固定范围，剩余空间给播放器：

```text
Playback Pane: flexible
Inspector: 340-480 px
Timeline: bottom fixed/expandable
```

### 响应式布局

宽屏：

```text
┌──────────────────────────────────────────┬───────────────┐
│ Playback Pane                            │ Step Inspector │
│                                          │ 340-480 px     │
├──────────────────────────────────────────┴───────────────┤
│ Timeline / Filmstrip                                      │
└──────────────────────────────────────────────────────────┘
```

窄屏或较小窗口：

```text
┌──────────────────────────────────────────┐
│ Playback Pane                            │
├──────────────────────────────────────────┤
│ Timeline / Filmstrip                     │
├──────────────────────────────────────────┤
│ Step Inspector                           │
└──────────────────────────────────────────┘
```

V1 可以先不做复杂断点，但需要保证最小窗口下不挤压文字、不遮挡播放器、不出现无法点击的控制。

### 窗口生命周期

V1 推荐：

- 使用全局单例 `RecordingReviewWindow`。
- 打开同一 recording 时，聚焦已有窗口，并 seek 到传入 step/time。
- 打开另一条 recording 时，复用同一个大屏窗口切换 session。
- 切换 session 前，如果当前正在播放，先暂停再切换。
- 切换 session 或关闭窗口时，把 `selectedStepId` / `currentMediaTimeMs` 回写给 Workbench 抽屉。
- 关闭大屏窗口使用 `⌘W` 或窗口关闭按钮。
- 普通窗口态下 `Esc` 不直接关闭窗口，只退出 full-window/full-screen 或关闭临时 overlay/menu/focus。

V1 不做实时双向同步。打开时继承，关闭时回写，足够稳定。

如果窗口正在展示 `文件与材料`、更多菜单、快捷键帮助、临时 toast 或其他 overlay：

```text
Esc
→ 优先关闭最上层临时界面
→ 不关闭复盘窗口

⌘W
→ 关闭 RecordingReviewWindow
→ 回写 selectedStepId/currentMediaTimeMs
→ 清理临时播放文件
```

## 信息架构

大屏复盘由四块组成：

```text
RecordingReviewWindow
  Header
  Playback Pane
  Step Inspector
  Chapter Timeline
```

### Header

Header 的任务是告诉用户“正在复盘哪段录制”和提供低频动作。

推荐内容：

```text
录制复盘：API 文档里完成密钥轮换流程
Google Chrome · 00:46 · 4 步 · 视频 · 需要复核

[返回 Workbench] [仅播放视频] [文件与材料] [更多]
```

Header 字段：

- title：用户备注优先，其次 source title。
- app/source：低敏 app/window/source summary。
- duration。
- steps count。
- readiness / warning chips。
- video state。

Header 不展示：

- process id。
- window id。
- precise frame。
- local path。
- raw artifact id。

### Playback Pane

Playback Pane 是主画面，但它必须和 timeline/inspector 联动。

默认打开：

- 不自动播放。
- 不自动全屏。
- 显示 representative frame / start frame / selected step frame。
- 选中传入的 initial step；没有则选 start 或第一条 action/warning。

播放器控件：

```text
播放/暂停
当前时间 / 总时长
marker scrubber
速度：0.5x / 1x / 1.25x / 1.5x / 2x
适应窗口 / 原始尺寸
仅播放视频
```

Scrubber 不应该只是普通进度条，而要带 marker：

```text
00:00 ━●━━━━●━━━━●━━━━●━━━━●━━ 00:42
       Start  Click  Hotkey  Mark  End
```

点击 marker：

- seek 视频。
- 选中 timeline step。
- 刷新右侧 Inspector。
- 如果 Inspector 之前处于 follow mode，则继续 follow；如果用户点了具体 step，则进入 pinned mode。

### Chapter Timeline

底部 timeline 是横向章节时间线 + filmstrip，不是竖向表格。

V1 默认显示高价值 step，排序以 `mediaTimeMs` 为主，`sequenceIndex` 为辅：

- Start。
- End。
- Warning。
- Manual Mark。
- Click。
- Hotkey。
- Scroll。
- Typing Pause。
- Scope Change。
- 重要 timer frame。

默认折叠低价值 step：

- 普通 timer frame。
- 无变化 frame。
- 重复 frame。

如果一段录制只有 timer/keyframe，没有 action，则至少显示：

- Start。
- End。
- representative timer frames，默认每 8 秒最多 1 个，具体间隔由 timeline density config 决定。
- 如果总时长很短但没有 action，至少保留一个中段 representative frame，避免 timeline 看起来像空录制。

Filter：

```text
全部
动作
关键帧
警告
标记
```

开关：

```text
显示全部关键帧
```

Timeline item 推荐结构：

```text
[thumbnail]
00:08
快捷键
按下 ⌘K 打开命令面板
[after] [text] [warning?]
```

### Step Inspector

右侧 Inspector 只展示当前 step，不展示整段录制的所有材料。

固定结构：

```text
当前步骤
  00:08 · 快捷键
  按下 ⌘K 打开命令面板

证据
  当前帧 / Before / After / Compare

文本
  safe text snapshot
  来源：OCR / AX / browser provider

Action Trace
  hotkey: ⌘K
  confidence: high

Warning
  needs review / provider unavailable / scope changed

材料
  打开当前帧
  复制文本
  更多...
```

不同 step 只替换内容，不改变整体结构。这样用户学一次就会用。

## Follow / Pin 模式

大屏复盘需要一个重要状态：Inspector 是否跟随播放。

### 默认逻辑

```text
用户直接播放视频
→ Inspector 跟随当前播放时间之前最近 step

用户点击 timeline step
→ Inspector 锁定到该 step

用户点击“恢复跟随”
→ Inspector 继续跟随播放
```

右侧顶部状态：

```text
跟随播放中
```

或：

```text
已锁定到 00:08 · 快捷键
[恢复跟随]
```

为什么需要它：

- 播放时自动跟随很适合快速浏览。
- 用户认真看某一步的文字或截图时，Inspector 不应该随着视频播放突然变化。

V1 可以先做：

- 点击 step 后进入 pinned。
- 点击 `恢复跟随` 后回到 follow。
- 播放时间变化只在 follow mode 下自动选 step。
- Follow 不使用“距离最近”的策略提前跳到未来 step，而是保持上一 step，直到播放时间跨过下一个 marker。

## 键盘操作

大屏复盘必须支持键盘，否则不像专业回看工具。

V1 必做：

| 快捷键 | 行为 |
| --- | --- |
| `Space` | 播放 / 暂停 |
| `←` | 上一个 step |
| `→` | 下一个 step |
| `Shift ←` | 后退 5 秒 |
| `Shift →` | 前进 5 秒 |
| `Esc` | 退出 full-window/full-screen；普通窗口态只关闭临时 overlay/menu/focus，不关闭复盘窗口 |

V1.1 可选：

| 快捷键 | 行为 |
| --- | --- |
| `J` | 后退 5 秒 |
| `L` | 前进 5 秒 |
| `F` | 适应窗口 / 全屏播放器 |
| `⌘F` | 搜索 timeline / safe text |

所有快捷键都必须有菜单或按钮路径，不能只依赖隐藏键盘操作。

## State 与数据模型

### Review State

建议抽出共享状态，而不是把状态散在抽屉和大屏里：

```text
RecordingReviewState
  sessionId
  eventId
  selectedStepId
  currentMediaTimeMs
  playbackArtifactId
  playbackLoaded
  isPlaying
  playbackRate
  followMode
  timelineFilter
  showAllKeyframes
```

V1 同步规则：

```text
打开大屏
  从抽屉读取 selectedStepId/currentMediaTimeMs

大屏内部
  独立维护 state

关闭大屏
  将 selectedStepId/currentMediaTimeMs 写回 Workbench
```

### Core / Layout 分层

推荐组件架构：

```text
RecordingReviewCore
  RecordingReviewState
  RecordingReviewProjection
  RecordingPlaybackController
  RecordingStepSelectionController
  RecordingTimelineFilter

DrawerReviewView
  compact layout

RecordingReviewWindow
  spacious layout
```

### Review Projection

大屏不直接读数据库，也不直接理解 raw artifacts。它消费 safe projection：

```text
RecordingReviewProjection
  recordingSummary
  videoPlaybackRef
  steps[]
  warnings[]
  safeTextBlocks[]
  visibleArtifacts[]
  skillReadiness
```

Step 结构：

```text
ReviewStep
  id
  timestamp
  mediaTimeMs
  sequenceIndex
  type: start | click | scroll | hotkey | typing_pause | timer | mark | warning | end
  triggerReason
  actionSummary
  textSnapshot
  beforeFrameRef
  afterFrameRef
  currentFrameRef
  videoTime
  warnings
  artifactRefs
  needsReview
```

## 隐私与 Gated Playback

大屏复盘必须沿用当前 Workbench 播放约束。

### 视频读取

```text
用户显式点击播放 / 打开复盘
→ Workbench 请求 dedicated playback route
→ daemon 校验 install secret + disclosure purpose
→ 校验 session/event/artifact link
→ 返回 typed playback payload
→ Workbench 写入本机临时播放文件
→ 关闭/切换/销毁时清理
```

### 外部播放器

`仅播放视频` 或 `用播放器打开`：

- 仍先走 gated playback。
- 仍生成本机临时播放文件。
- 交给系统默认播放器。
- 不把文件加入默认搜索。
- 不上传。

首次使用可以有轻提示：

```text
将在本机播放器中打开此录制视频。
这不会把文件加入默认搜索，也不会上传。
```

不建议每次强确认。

### 文件与材料

大屏 Header 不建议直接叫 `原始材料`，普通用户可能觉得吓人。V1 使用 `文件与材料`，打开右侧 slide-over panel，而不是 Header 下拉菜单。

原因：

- 材料内容可能包含视频、关键帧、文本快照、timeline manifest 和受限原始材料，不适合放在短下拉里。
- Slide-over panel 可以承载说明、分组、warning 和 disclosure gate。
- 用户不会误以为点一个菜单项就直接暴露 raw data。

点开后分层：

```text
安全材料
  视频
  关键帧
  文本快照
  timeline manifest

受限原始材料
  raw video
  raw OCR boxes
  raw accessibility tree
```

受限原始材料必须走 disclosure gate。

V1 交互形态：

```text
点击 文件与材料
→ 右侧 slide-over 从 Inspector 区域进入
→ 暂时覆盖 Step Inspector
→ 播放器和底部 timeline 保持可见
→ Esc 或关闭按钮收起材料面板
→ 回到原 selected step Inspector
```

不使用 header 下拉承载材料列表；材料内容会变长，且包含 disclosure 状态、说明和受限材料入口，下拉承载力不够。

## 空状态与异常状态

### 没有视频，只有关键帧

```text
此录制没有可播放视频
你仍然可以通过关键帧复盘。

[Start] [Click] [Timer] [End]
```

播放器区域切换为 storyboard/keyframe viewer。

### 没有可用文本

```text
这一帧没有可用文本
可能原因：OCR 未命中、辅助功能权限不足或画面过小。
```

### 视频文件不可用

```text
视频文件不可用
关键帧和时间线仍可查看。

[查看关键帧] [重新检查]
```

### 权限降级

右侧 Inspector 和 Header 都可以显示降级 chip：

```text
窗口识别降级
操作线索不完整
视频可用，文本证据缺失
```

### Warning marker

Timeline 和 Inspector 都要显示 warning：

```text
⚠ 00:12 scope changed
```

点击 warning marker 直接跳到对应 step。

## 视觉语言

大屏复盘需要比普通 Workbench 更“影院化”，但仍然保持 WorkRecorder 的克制、精确、本机私有气质。

### 总体方向

- 播放器区域使用深色 media well，减少视频周围眩光。
- Inspector 和 timeline 保持 satin/prism light surface，延续 Workbench 语言。
- 不做全窗口黑色娱乐网站风格；这是复盘工作区，不是 streaming app。
- 不使用大面积霓虹、bokeh、orb 或过强 gradient。
- 状态色必须语义清楚：warning 使用琥珀，selection 使用 tiffany/blue，error 使用 restrained red。

### 推荐视觉结构

```text
Window background: satin / prism neutral
Playback pane: dark graphite / black media well
Controls: translucent low-height bar below video
Inspector: light panel with restrained border
Timeline: low-density cards + marker rail
Selection: tiffany / blue
Warning: amber
```

### 字体与密度

- 使用 macOS system font，不引入外部字体。
- 标题 `15-17 pt semibold`。
- Step title `13-14 pt semibold`。
- Body `12-13 pt regular`。
- Metadata `10.5-11.5 pt medium`。
- 按钮高度 `30-32`。
- Timeline item 宽 `120-160`，高 `96-130`。

## 可访问性

必须支持：

- VoiceOver 可读：当前录制、当前 step、播放状态、warning、follow/pin 状态。
- Keyboard-only 操作。
- Focus ring 明确。
- Reduce Motion。
- High contrast。
- 不只用颜色表达 `needs review` 或 warning。

VoiceOver 示例：

```text
WorkRecorder 录制复盘，Chrome API 文档，时长 46 秒，当前步骤 00:08 快捷键。
```

Follow mode：

```text
Inspector 正在跟随播放。
```

Pinned mode：

```text
Inspector 已锁定到 00:08 快捷键。按钮：恢复跟随。
```

## 实现分期

### V1：大屏复盘 MVP

V1 要做到可发布、可用、低风险：

- 独立 `RecordingReviewWindow`。
- 全局单例窗口；切换 session 前暂停当前播放。
- 从录制卡片 / 抽屉打开。
- 打开时继承当前 selected step 和 media time。
- 关闭或切换 session 时回写 selected step 和 media time。
- 大视频播放器 / no-video keyframe viewer。
- 右侧当前 Step Inspector。
- 底部 marker rail + filmstrip。
- 默认隐藏低价值 timer/no-change/repeated frame；无 action 时保留 representative timer frames。
- 上一步 / 下一步。
- `Space` 播放暂停，`←/→` 跳 step。
- `Esc` 不关闭普通复盘窗口；`⌘W` 关闭窗口。
- 轻量 Follow / Pin Inspector。
- 播放速度。
- `仅播放视频` / `用播放器打开`。
- `文件与材料` 右侧 slide-over panel。
- dedicated playback route，不绕过 raw gate。
- Snapshot mocks 覆盖：有视频、无视频、长标题、dense timeline、warning、无文本、窄屏。

### V1.1：复盘体验增强

- Timeline filter。
- 显示全部关键帧开关。
- Before / After / Compare。
- Warning marker jump。
- 搜索 timeline / safe text。
- 播放器 full-window / fit mode。

### V2：Workflow / Skill 前置

- Workflow summary preview。
- 用户确认每一步的目标和参数。
- 生成 tutorial / skill draft。
- 标记 needs-review 的 step。
- 导出复盘摘要，而不是导出 raw trace。

## 验收清单

### 产品体验

- 录制卡片点击仍打开抽屉，不强制进入大屏。
- 用户能从卡片 footer / 抽屉主按钮 / 抽屉展开 icon 打开大屏。
- 大屏打开后继承抽屉当前 step 和时间点。
- 大屏关闭后回写 selected step。
- `打开复盘` 和 `仅播放视频` 语义清楚。
- 没有视频时仍可通过关键帧复盘。

### 播放与时间线

- 点击 timeline marker 会 seek 视频并更新 Inspector。
- 点击 filmstrip step 会 seek 视频并更新 Inspector。
- `Space` 播放/暂停。
- `←/→` 上一步/下一步。
- Dense timeline 不默认展示大量低价值 timer frames。
- Warning marker 可见并可跳转。

### Inspector

- 右侧只展示当前 step 的文本、截图、action、warning。
- 不展示整段录制所有文本。
- 复制文字只复制当前 step 的 safe text。
- no-text 状态可解释。
- needs-review 不被隐藏。

### 隐私安全

- 大屏播放仍走 dedicated playback route。
- 外部播放器打开不绕过 playback gate。
- 不展示 raw video path。
- 不展示 process id / window id / precise frame。
- 不展示 raw DOM / raw a11y tree / OCR boxes。
- 临时播放文件会在切换、关闭或销毁时清理。

### 视觉与可访问性

- 播放器控件不遮住视频主体。
- 窄窗口不挤压 Inspector 文本。
- Focus ring 清楚。
- VoiceOver 可读当前 step 和播放状态。
- Reduce Motion 下无持续动画依赖。
- 颜色语义一致：selection 不像 warning，warning 不像 destructive。

## 开放问题

这些不阻塞 V1，不能推翻上面的 V1 产品决策：

- Timeline filter 是否在 V1 露出 UI，还是先只内置低价值 frame 折叠策略。
- `仅播放视频` 首次轻提示是否需要用户可关闭的 “以后不再提示”。
- 大屏窗口是否参与 macOS state restoration；建议 V1 不恢复，后续再看用户是否需要。

## 最终原则

大屏复盘的目标不是让 WorkRecorder 看起来像视频播放器，而是让用户放心地理解一段真实操作过程：

```text
我看到了录制内容。
我知道当前时间点发生了什么。
我能看到这一步对应的文本、截图和动作。
我知道哪些证据可信，哪些需要复核。
我可以只播放视频，也可以在 WorkRecorder 里完整复盘。
```
