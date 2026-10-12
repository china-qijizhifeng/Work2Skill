# WorkRecorder 录制功能 UI/UX 设计方案

> 导航：[返回文档总览](../README.md) · 相关：[大屏录制复盘工作区](RECORDING_LARGE_SCREEN_REVIEW_CN.md) · [Active Context Capture](USER_TRIGGERED_KEYFRAME_CONTEXT_CN.md) · [Screenpipe 深读](SCREENPIPE_ACTIVE_CAPTURE_LESSONS_CN.md) · [macOS App E2E Matrix](../manual/MACOS_APP_E2E_MATRIX.md)

## 设计结论

WorkRecorder Recording 不是“截图功能的加长版”，而是一个显式进入、边界清楚、持续可见、结束可审查的高信任录制模式。

最终建议快捷键：

| 快捷键 | 功能 | 心智 |
| --- | --- | --- |
| `⌃⌘2` | 当前窗口截图 | 捕捉当前窗口这一刻 |
| `⌃⌘3` | 区域截图 | 捕捉框选区域这一刻 |
| `⌃⌥⌘R` | 区域录制 | 进入录制准备态，记录一段过程 |

核心交互结论：

- `⌃⌥⌘R` 只负责进入录制准备态，或在录制中唤起控制，不直接开始、不偷偷暂停、不直接停止。
- 真正开始录制必须经过用户框选和确认。
- V1 录制对象是固定屏幕区域，不自动跟随窗口；窗口识别只作为 metadata、warning 和 timeline hint。
- 正在录制必须同时有菜单栏状态、Recording HUD 和轻量区域边框。
- Recording HUD 默认不得进入视频 artifact。
- 暂停、继续、完成必须发生在可见 UI 上。
- 完成后进入 staging review；用户可以预览临时回放，只有点击保存后才进入 Workbench 长期库。
- 录制过程中生成的关键帧和 action trace 默认归属于 recording session，不污染普通截图流。

## 当前已落地版本

截至 2026-06-02，`feature/p7-video-context-design` 已经落地的是 **区域录制 V1 + Workbench 录制库 + 安全复盘抽屉**。这部分不是概念稿，已经有真实 macOS app bundle、Swift/Python 自动化测试和若干真实/受控 E2E 报告支撑。

### 快捷键与入口

| 入口 | 当前行为 |
| --- | --- |
| `⌃⌘2` | 当前窗口截图；录制中作为当前窗口关键帧，归属当前 recording session |
| `⌃⌘3` | 区域截图；录制中作为区域关键帧 / 局部证据，归属当前 recording session |
| `⌃⌥⌘R` | 进入区域录制准备态；录制中唤起 Recording HUD，不暗中暂停或停止 |
| Workbench `开始录制` | 打开同一条区域录制准备流程 |

快捷键配置已经进入 Workbench `设置` 页，与视觉识别设置同属设置体系；`诊断` 页只保留权限、错误、日志和复制诊断。快捷键持久化以本机 `UserDefaults` 为事实源，daemon settings 只做镜像和诊断，避免启动时覆盖用户设置。

### 已实现的录制主流程

当前实现的主路径：

```text
按 ⌃⌥⌘R / 点击开始录制
→ 区域选择 overlay
→ 区域确认条
→ 倒计时，可 Esc 取消
→ 开始录制
→ 菜单栏状态 + Recording HUD + 轻量边框
→ 标记 / 暂停 / 继续 / 完成
→ completion sheet 本地复查
→ 保存到录制库，或显式丢弃
```

已实现的关键行为：

- 录制只在用户框选并确认后开始，不支持静默开始。
- ScreenCaptureKit 录制固定屏幕区域，WorkRecorder HUD/边框默认从视频流中排除。
- HUD 会显示录制时长、标记、暂停/继续、完成；Space 只在 HUD 聚焦时切换暂停/继续，Esc 打开停止确认。
- 录制中 `标记` 会写入 control event，并尝试生成 user mark keyframe。
- 录制中 `⌃⌘2` / `⌃⌘3` 不弹普通 Light Sheet，而是生成 recording keyframe，并在 HUD 中反馈成功、失败或缺少 trigger instruction。
- 暂停会停止视频片段和输入 producer；继续会重新开始新 segment，并写 typed control / segment close reason。
- 多段录制在保存前会拼接为一个可播放视频 artifact，同时每段 segment 仍作为后端证据保留。
- 录制完成先进入 staging review；保存前可以打开本地预览，也可以填写备注。
- 保存失败、丢弃失败、录制启动失败都会留在当前可恢复 UI 上，不用泛化的“截图失败”态吞掉上下文。
- 丢弃使用独立确认面板，`返回` 是安全主动作，`丢弃录制` 是显式 destructive 动作。
- App 退出时如果仍在录制或等待保存/丢弃，会阻止退出并聚焦现有录制控制，避免静默删除 staged media。

### 已实现的权限与降级

| 场景 | 当前行为 |
| --- | --- |
| Screen Recording denied | 不开始录制，打开录制专用权限说明面板 |
| Accessibility denied | 允许录制画面，但显示窗口/控件识别降级 |
| Input listener failure | HUD 和 completion sheet 标记操作线索可能不完整 |
| 后端启动失败 | 不误判为屏幕录制权限；按 backend/transport/manifest stage 显示错误 |
| 录制启动失败 | 清理 HUD、边框、倒计时、input trace 状态，并尝试取消后端 session |

### 已实现的 Workbench 录制体验

Workbench 已经把录制作为一级内容类型处理：

- `截图库` 只展示普通截图 / 当前窗口截图。
- `录制库` 只展示录制 session，视频、关键帧复盘、action trace 和备注单独成库。
- 普通录制中的 secondary keyframe material 不会混入截图库。
- 录制卡片使用视频式预览图、时长、状态、视频/时间线/action chips 和保存备注。
- 没有视频的录制显示为 `关键帧复盘`，不承诺播放 raw video。
- 空录制库不是大片空白：当前实现有紧凑说明、开始录制入口和“保存后会出现什么”的预览结构。

录制详情当前是安全复盘抽屉，不是普通截图详情页：

```text
录制 header
→ 视频 / 关键帧播放面
→ timeline marker rail + step filmstrip + 上一步/下一步
→ 当前 step 详情：动作、证据、文字快照、原始材料入口
→ warning / 保存备注
```

当前详情页 tabs 是：

| Tab | 用途 |
| --- | --- |
| `复盘` | 用户默认看的安全复盘：视频/关键帧、timeline、step evidence、safe text |
| `原始材料` | 需要用户显式查看的录制 raw materials 摘要，不直接泄漏 raw video/path/DOM/a11y |

### 已实现的播放与回看

录制视频播放已经从“看缩略图”推进到“显式播放”：

- 用户点击录制详情的播放预览后，Workbench 通过 dedicated playback route 请求视频。
- 后端要求本机 trusted install secret、明确的 `session_id` / `event_id` / `artifact_id` 和 `read_raw_artifact` disclosure；普通 raw artifact route 仍拒绝 `recording_video`。
- 播放响应使用 `Cache-Control: no-store`，只返回 typed playback payload。
- Workbench 把视频写入权限收窄的本机临时文件，选择变更、关闭 drawer 或销毁 controller 时清理。
- 内嵌播放器不使用 macOS 浮动大控制栏，避免遮住视频。
- 视频下方有轻量控制：`播放/暂停`、`跳到当前步骤`、`用播放器打开`。
- 还没加载视频时，也提供 `用播放器打开`，会走同一条授权播放读取，准备完成后交给系统默认播放器。
- timeline step 选择会 seek 到对应 `media_time_ms`；marker rail、filmstrip、上一步/下一步走同一条 selection path。

### 已实现的后端与安全契约

UI 已经对齐 Active Capture 后端能力：

- 录制 session、control、segment、trigger、completion、cancel 都走 typed transport。
- start/final/user mark/keyframe trigger 可以绑定到 recording session。
- video artifact 进入 vault 后做 MIME、magic、duration、hash、byte size 校验。
- Timeline manifest 使用 media time 对齐 keyframe/action/control/video。
- 录制 inspect projection 是 agent-safe/read-model，不把 UI storyboard 直接暴露给 Agent。
- safe index projection 只允许 safe summary、safe timeline caption、redacted text 和 user note 入索引。
- 用户备注作为 safe `USER_NOTE` field 持久化、inspect 展示、索引，并可用于后续 skill-friendly projection。
- raw video、raw keyframe image、raw DOM、raw a11y tree、OCR boxes 默认不进入 search/inspect/replay。

### 已验证的工程状态

当前功能已有这些验证资产：

- Swift 录制 UI snapshot：trigger/menu、区域确认、倒计时、HUD、暂停、降级、完成、保存失败、丢弃确认、权限拒绝等状态。
- Workbench 录制库/录制详情 snapshot：普通卡片、长标题、无视频、dense timeline、narrow drawer。
- 大屏复盘窗口 snapshot：视频复盘、无视频关键帧复盘、材料面板、dense timeline、narrow layout、loaded playback 预览。
- Native recording backend E2E：真实 ScreenCaptureKit 3-5 秒 MP4、start/final keyframes、producer events、vault promotion、timeline alignment、raw denial。
- Controlled packaged-app save E2E：真实 `dist/WorkRecorder.app` 启动，自动录制、完成、保存、录制库展示、playback route 验证。
- 质量门禁覆盖 Swift tests、Python tests、ruff、mypy、pyright、Swift quality audit、repo quality audit、`git diff --check`。

### 尚未落地

这些仍是后续 feature，不应误读为当前已实现：

- 自动生成 skill / workflow。
- Follow Window Recording。
- 默认录音。
- 视频剪辑、裁剪、导出编辑器。
- 自动上传或云同步。
- 24/7 后台录屏。

## 关键产品决策

这些决策是工程实现和评审的硬边界。后续如果要改变，必须显式更新文档和测试。

| 决策 | V1 结论 | 原因 |
| --- | --- | --- |
| 录制对象 | `fixed_screen_region` | 用户框选的是屏幕固定矩形，窗口移动后不自动跟随，边界最清楚 |
| 窗口绑定 | `best_effort_hint` | App/window/title 用于确认条、warning、timeline，不作为自动追踪依据 |
| 录制快捷键 | `⌃⌥⌘R` 进入准备态 / 唤起 HUD | 快捷键不暗中改变录制状态 |
| 开始录制 | 必须经过框选和确认 | 避免 silent recording |
| HUD 入镜 | 默认不得进入 video artifact | 保持录制专业性，避免遮挡证据 |
| 完成语义 | 进入 staging review | `打开回放` 查看临时录制，`保存` 才 commit 到 Workbench |
| staging 保留 | 默认 24 小时或 App 退出时提示处理 | 防止用户误关完成 sheet 后找不到临时录制 |
| 录制中截图 | 归属 recording session | 不制造普通截图列表噪声 |
| 输入线索 | 分级启用，永不保存普通输入原文 | 支持 P7.11，同时避免 keylogger 心智 |
| raw video | 默认不进 Agent inspect/search | raw video 属于高敏 artifact |
| scope lost | 不自动停止，但必须显式 warning | 让用户决定继续、重新选择或完成 |
| Workbench | 录制作为独立内容类型 | session/timeline/video/action 与截图 event 不同 |

V1 不做 Follow Window Recording。后续如果需要，可以作为高级模式单独设计：

```text
V1: fixed_screen_region + window_hint
V1.1+: optional follow_window_recording
```

## 产品原则

WorkRecorder Recording 的第一原则是可信任，不是炫技。

```text
WorkRecorder Recording Principles

1. No silent recording.
2. No ambiguous boundary.
3. No hidden ongoing state.
4. No irreversible save.
5. No background input capture without visible recording state.
6. No upload before local review, unless user explicitly enables auto-save/sync.
7. Recording evidence belongs to the recording session by default.
```

对应中文产品约束：

- 不静默录制。
- 不让用户猜测录制范围。
- 不隐藏正在录制状态。
- 不做不可逆保存。
- 不在没有可见录制状态时采集输入事件。
- 不在用户本地审查前自动上传。
- 录制证据默认属于录制片段，而不是散落成普通截图。

## 目标与非目标

### 目标

- 给用户一个明确、安全、克制但高级的录制体验。
- 让用户随时知道录制范围、录制状态、录制时长和可用控制。
- 支持暂停、继续、手动标记、完成、丢弃。
- 结束后能快速确认“录到了什么”，再决定是否保存。
- 在 Workbench 中把录制作为独立类型呈现，同时复用截图证据、关键帧、timeline 和安全披露能力。
- 为后续 P7.11 skill distillation 提供可理解的 action trace 和 keyframe timeline，但第一版不自动生成 skill。

### 非目标

- 不做后台 24/7 录屏。
- 不做默认全屏录制。
- 不默认录音。
- 不记录普通键盘输入文本。
- 不把录制变成复杂视频剪辑器。
- 不在第一版自动生成 workflow/skill。
- 不把录制中的关键帧默认展示成普通截图卡片。

## 信息架构

Workbench 已经把录制作为一级内容类型，而不是塞进截图详情里。当前导航命名以用户可理解的内容库为主：

```text
Workbench
  截图库
  录制库
  开始使用
  保存范围
  设置
  隐私与可见性
  帮助与诊断
```

设计理由：

- 截图是一个瞬间；录制是一段 session。
- 截图卡片的主对象是 event；录制卡片的主对象是 recording session。
- 录制详情需要 video、keyframes、actions、warnings、timeline，不适合挤进普通截图详情。
- 搜索和跨库入口后续可以混排，但类型必须一眼可辨。
- 当前实现中，录制卡片不会进入 `截图库`；录制中的 keyframe material 也不会伪装成普通截图卡片。

## 状态模型

录制 UI 应该围绕状态机设计，避免快捷键和弹窗变成隐式分支。

| 状态 | 用户看到什么 | 允许操作 | 不允许操作 |
| --- | --- | --- | --- |
| `idle` | 无录制状态 | `⌃⌥⌘R` 进入准备态 | 后台采集输入 |
| `selecting_region` | 区域选择 overlay | 框选、取消 | 开始保存视频 |
| `confirming_region` | 轻量确认条 | 开始录制、重新选择、取消 | 静默开始 |
| `countdown` | 3/2/1 小倒计时 | 取消 | 编辑区域 |
| `recording` | 菜单栏红点、HUD、边框 | 标记、暂停、完成、唤起 HUD | 隐藏所有状态 |
| `paused` | 灰/琥珀 HUD、虚线边框 | 继续、完成、取消 | 继续采集视频/输入 |
| `soft_scope_change` | 小 warning | 继续录制 | 假装 metadata 完全准确 |
| `scope_lost` | 琥珀边框、warning | 继续、重新选择区域、完成 | 自动跟随窗口 |
| `capture_invalid` | 暂停态 + 错误说明 | 重新选择区域、完成、丢弃 | 继续写无效视频 |
| `finalizing` | 正在整理片段 | 等待、取消保存请求 | 二次开始录制 |
| `reviewing_completion` | staging 完成 sheet + preview | 保存、丢弃、临时回放、备注 | 自动提交到长期库 |
| `completed` | 进入 Workbench/列表 | 打开详情、搜索、分享受控摘要 | 默认暴露 raw video |
| `discarded` | 清理临时数据 | 关闭 | 保留半成品 artifact |

状态转换必须记录 control event，方便审计和后续 bug 复盘。

### Scope 语义

V1 的录制对象是固定屏幕矩形：

```text
recording_scope = fixed_screen_region
window_binding = best_effort_hint
```

这意味着用户框选的是屏幕上的一块区域。即使 WorkRecorder 识别出 Chrome、Finder 或某个窗口标题，窗口移动后录制区域也不会自动跟随。识别结果只用于：

- 确认条里的低敏说明。
- Workbench 卡片标题。
- timeline step 的 target summary。
- provider routing 的 best-effort hint。
- scope warning 的判断依据。

V1 不承诺“录这个窗口对象”。这可以避免第一版被 AX 追踪、CGWindow 重建、Spaces、全屏、多屏和窗口误识别拖垮。

### Scope 异常分级

| 分级 | 含义 | UI 行为 | 录制行为 |
| --- | --- | --- | --- |
| `soft_scope_change` | app/window/title metadata 变化，但固定区域仍可录 | 小 warning，不打断 | 继续录制 |
| `scope_lost` | 原窗口不可识别或目标明显变化，但固定区域仍有效 | 琥珀边框，显示继续/重新选择/完成 | 继续录制，标记 needs review |
| `capture_invalid` | 显示器、权限或区域失效，无法可靠采集 | 暂停并要求重新选择或完成 | 停止写入当前片段 |

推荐文案：

```text
录制区域仍在继续，但窗口识别已变化
继续录制    重新选择区域    完成
```

## 快捷键行为

### 默认快捷键

| 场景 | 行为 |
| --- | --- |
| 未录制时按 `⌃⌥⌘R` | 进入区域录制准备态 |
| 选择区域时按 `Esc` | 取消准备态 |
| 确认条出现时按 `Enter` | 开始录制 |
| 录制中按 `⌃⌥⌘R` | 唤起 / 聚焦 Recording HUD，不改变状态 |
| 录制中按 `Esc` | 弹出停止确认，不直接结束 |
| 录制中按 `Space` 且 HUD 聚焦 | 暂停 / 继续 |
| 录制中按 `⌃⌘2` | 添加当前窗口关键帧，归属当前 recording session |
| 录制中按 `⌃⌘3` | 添加区域关键帧 / 局部证据，归属当前 recording session |

### 为什么不让 `⌃⌥⌘R` toggle 暂停

录制快捷键在用户心里更像“开始或控制录制”，不是“安全地暂停”。如果它在不同状态下偷偷改变 recording state，风险很高：

- 用户以为停止了，其实只是暂停。
- 用户以为暂停了，其实恢复录制。
- 用户不知道当前状态改变有没有成功。

因此，`⌃⌥⌘R` 在录制中只做一件事：唤起可见控制。

## 主流程

### 1. 进入录制准备态

用户按 `⌃⌥⌘R` 后，屏幕进入区域选择 overlay。

视觉：

- 背景轻微降噪，不做大面积暗罩。
- 光标变为精确框选形态。
- 顶部小提示：`WorkRecorder · 选择录制区域 · ⌃⌥⌘R`
- 多屏时每个屏幕显示独立坐标安全区。
- reduced motion 下关闭动态扫光，只保留静态边界。

设计语气：冷静、精确、像专业仪器进入测量模式。

### 2. 区域确认条

框选结束后不直接录制，而是在区域边缘显示确认条。

推荐文案：

```text
将录制此区域
1280 × 720 · Chrome · API 文档

开始录制    重新选择    取消
```

如果 Accessibility 权限不足：

```text
将录制此区域
1280 × 720 · 窗口识别已降级

开始录制    重新选择    取消
```

确认条规则：

- 必须显示录制范围尺寸。
- 能识别 app/window/title 时显示低敏摘要。
- 不能显示 process id、window id、精确本机路径。
- `开始录制` 是主按钮。
- `重新选择` 是次级按钮。
- `取消` 是弱按钮。

### 3. 倒计时

点击开始后进入短倒计时。

推荐：

```text
3
2
1
Recording
```

视觉规则：

- 倒计时小而清楚，贴近选区中心或 HUD 将出现的位置。
- 不做游戏化大动画。
- 允许可选轻提示音，但默认静音。
- reduced motion 下只做数字切换，不做缩放。

### 4. 正在录制

开始后同时出现三层状态：

| 层 | 作用 | 设计 |
| --- | --- | --- |
| 菜单栏 | 全局状态 | WorkRecorder 图标进入录制态，显示小红点 / timer |
| Recording HUD | 局部控制 | 贴在录制区域边缘外侧，显示时长和控制 |
| 录制边框 | 范围确认 | 细线、低亮度、持续存在 |

HUD 推荐布局：

```text
● 00:12      标记      暂停      完成
```

层级：

- `完成` 最右侧，最明确，危险但常用，使用清晰文字。
- `暂停` 次级，不和完成同等视觉权重。
- `标记` 最弱，用于插入 user mark keyframe。
- 录制点和 timer 是状态，不是按钮。

HUD 详细状态：

| 状态 | HUD | 边框 |
| --- | --- | --- |
| recording | 红点 + running timer | 细微红/蓝白边框 |
| paused | `已暂停 00:12` | 虚线边框 |
| soft scope change | `窗口信息变化` | 轻 warning |
| scope lost | `窗口识别变化` | 琥珀边框 |
| capture invalid | `录制区域不可用` | 暂停态 / 错误态 |
| permission degraded | warning icon + tooltip | 边框旁小 warning |
| finalizing | `正在整理录制...` | 边框淡出 |

HUD 不能抢输入焦点。只有用户点击 HUD 或按 `⌃⌥⌘R` 唤起控制时，HUD 才进入可键盘操作状态。

HUD 默认不得进入 video artifact。实现必须满足至少一个条件：

- HUD 始终吸附在录制区域外侧。
- HUD 是可被 capture compositor 排除的独立 overlay window。
- 如果没有安全外侧空间，也不能覆盖核心内容；必须进入最小化控制点或移动到屏幕安全边缘。

如果某个平台无法保证 HUD 不入镜，必须在确认条或设置里明确提示，并默认选择“区域外 HUD”策略。

### 5. 暂停与继续

暂停必须是显式操作。

暂停后：

- 停止写视频片段。
- 停止生成输入 action trace。
- 停止自动关键帧触发。
- 写入 `paused` control event。
- HUD 显示 `已暂停`。
- 边框变虚线。

继续后：

- 写入 `resumed` control event。
- 重新校验 scope。
- 重新建立 keyframe baseline。
- HUD 回到 running timer。

如果暂停超过配置上限，HUD 提示：

```text
录制已暂停较久
继续    完成    丢弃
```

### 6. 手动标记

`标记` 不是截图按钮，而是“这个时刻重要”的录制内动作。

点击后：

- 写入 `user_mark` control event。
- 生成一个 keyframe candidate。
- 如果视频开启，记录 media time。
- HUD 短暂显示 `已标记`。

后续 Workbench timeline 中显示为：

```text
00:18 手动标记
```

### 7. 完成录制与 staging review

用户点击 `完成` 后：

1. HUD 进入 `正在整理录制...`。
2. 录制边框淡出。
3. 视频 artifact、start/final keyframe、timeline manifest 完成校验。
4. 进入 staging review，并弹出完成 sheet。

完成 sheet 不应该直接跳大 Workbench，也不应该自动提交到长期库。

推荐结构：

```text
录制完成

[首帧 / 末帧 / 关键帧 preview]

时长 00:42
12 keyframes · 8 actions · video included

保存     丢弃     打开回放

添加备注...
```

如果存在 warning：

```text
录制完成，但有 2 个需要注意的地方
窗口识别曾降级 · 结束前未捕获 final keyframe
```

按钮规则：

- `保存` 是主按钮。
- `丢弃` 要明确，但不做成恐吓色。
- `打开回放` 查看临时回放，不等于保存到长期库。
- 备注默认折叠或轻量输入，不强迫用户填写。

保存语义必须固定：

```text
打开回放 = 查看 staging 临时录制
保存 = commit to Workbench
丢弃 = delete staging artifact
```

Staging 默认保留 24 小时，或在 App 退出前提示用户处理。未保存录制不能悄悄进入 Workbench；被丢弃的录制必须清理临时视频、关键帧和未提交 timeline，只保留最小审计记录。

### 8. 丢弃录制

丢弃是用户信任的一部分。

规则：

- 丢弃前显示一次确认，说明会删除临时视频和未保存 keyframes。
- 丢弃后清理 staging artifact。
- 可以保留最小审计日志：用户开始过一次录制并主动丢弃，但不保留 raw content。

推荐文案：

```text
丢弃这段录制？
临时视频和关键帧会被删除。此操作不会保存到 Workbench。

丢弃录制    返回
```

## 视觉语言

### 方向

WorkRecorder 的未来感应该来自精确、轻盈、可信的状态反馈，而不是厚重科幻装饰。

关键词：

- 专业
- 克制
- 精确
- 本地优先
- 安全可见
- 低噪声未来感

避免：

- 大面积霓虹遮罩。
- 持续闪烁。
- 游戏化倒计时。
- 夸张玻璃卡片堆叠。
- 用动画掩盖状态不清。

### 色彩建议

| 语义 | 用色方向 | 用法 |
| --- | --- | --- |
| recording | 深红 / 珊瑚红点 | 只用于红点、完成按钮强调、状态徽标 |
| boundary | 蓝白低亮细线 | 表示 WorkRecorder 正在精准绑定范围 |
| paused | 中性灰 + 琥珀 | 表示暂时停止，不是错误 |
| warning | 琥珀 | 权限降级、scope lost |
| success | 低饱和绿色 | 保存完成 |
| surface | satin / prism neutral | HUD、sheet、Workbench 卡片 |

录制边框应低亮度、持续可见，但不干扰被录内容。边框动画只在状态变化时出现，录制中保持安静。

### 动效

| 动效 | 时长 | 目的 |
| --- | --- | --- |
| 进入框选 overlay | 120-180ms | 让用户感知 mode 切换 |
| 确认条出现 | 160ms | 轻量确认 |
| 倒计时数字 | 250-350ms | 清楚，不戏剧化 |
| HUD 吸附 | 180ms | 让控制位置可追踪 |
| 边框状态切换 | 180-240ms | 表示 recording/paused/scope lost |
| 完成 sheet | 200ms | 收束任务 |

必须支持 `prefers-reduced-motion` / macOS Reduce Motion：

- 关闭扫光、缩放、持续动画。
- 保留静态边框、状态文字和 icon。

## Workbench 录制区

### 当前实现结构

当前 Workbench 录制区已经落地为独立 `录制库`，不和 `截图库` 混放。用户点击录制卡片后打开右侧复盘抽屉，默认进入 `复盘` tab；需要查看更底层材料时再切到 `原始材料` tab。

```text
录制库
  录制卡片
    大缩略图 / 视频预览感
    标题、来源、日期、备注
    视频 / 时间线 / 动作轨迹 chips
    复制链接 / 删除

录制复盘抽屉
  复盘
    session header
    视频或关键帧播放面
    timeline marker rail
    step filmstrip
    当前 step 证据与文字快照
    warnings / note
  原始材料
    视频状态
    keyframe/source artifact 摘要
    gated disclosure 入口
```

当前实现的几个约束：

- 卡片点击是“打开复盘”，不会静默读取 raw video。
- 复盘抽屉中点击播放才会读取 gated playback payload。
- `原始材料` 不直接暴露本机路径、process id、window id、raw DOM、raw a11y tree。
- no-video 录制显示 `关键帧复盘`，继续展示 timeline、safe text 和关键帧证据。
- 录制备注显示在卡片和复盘详情中，作为用户保存时的意图补充。

### 录制列表卡片

录制卡片需要和截图卡片有共同语言，但信息结构不同。

当前卡片内容：

```text
[preview thumbnail]

录制复盘：API 文档里完成密钥轮换流程
Google Chrome · 5 月 18 日

演示从文档定位 API key 页面、打开命令面板、完成轮换并验证请求。

[视频] [时间线] [动作轨迹]           复制链接  删除
```

卡片字段：

- preview：优先显示代表性关键帧；没有视频也可显示 keyframe。
- title：app/window/title 的安全摘要或用户备注。
- duration：录制时长。
- evidence chips：keyframes、actions、video、warnings。
- readiness：`ready` / `needs review` / `blocked`，当前以状态 pill 和 warning chip 进入卡片 / 抽屉。

不要在卡片上展示：

- process id。
- window id。
- 精确 frame。
- raw video path。
- raw OCR boxes。
- 普通输入文本。

### 录制详情页当前版

当前版本不是复杂 trace IDE，而是一个以视频 / 关键帧为锚点的安全复盘抽屉：

```text
┌──────────────────────────────┐
│ 录制标题 / 来源 / 状态 chips  │
├──────────────────────────────┤
│ 视频 / 关键帧播放面           │
│ 播放/暂停 · 跳到当前步骤 · 外部打开 │
├──────────────────────────────┤
│ Timeline marker rail          │
│ 上一步 · 当前时间 · 下一步     │
│ 横向 step filmstrip           │
├──────────────────────────────┤
│ 当前 step 的动作 / 证据 / 文字 │
├──────────────────────────────┤
│ Warning / 保存备注            │
└──────────────────────────────┘
```

播放面：

- 有 video artifact 时，先显示 video-style preview；点击后读取 gated playback payload 并在抽屉里播放。
- 没有 video artifact 时，显示 keyframe-only preview 和 timeline，不承诺播放。
- 内嵌播放器不使用 macOS 浮动大控制栏，避免遮住视频。
- 视频下方有轻量控制行：`播放/暂停`、`跳到当前步骤`、`用播放器打开`。
- `用播放器打开` 会复用同一条授权播放读取，然后交给系统默认播放器打开本机临时文件。

Timeline：

- 按 media time 排序。
- 事件类型使用 icon + 文本。
- 支持点击定位到视频时间或 keyframe。
- `needs review` 事件用小 warning 标记。
- 当前实现有 marker rail、横向 step chip filmstrip、上一步/下一步按钮。
- Dense timeline 下会保持选中步骤附近的上下文，避免出现半张无意义 chip。

当前 step：

- 展示 action type、target summary、keyframe 链接、safe text、confidence / needs review。
- 复制文字只复制当前 step 显式链接的 safe text，不会 fallback 到无关文字。
- `原始材料` 按钮切到 recording-specific raw materials tab，而不是普通截图 raw material 文案。

底部和尾部：

- 用户保存备注。
- warning / truncation / readiness。
- 未来可以接 skill readiness summary 和大屏复盘入口。

### Timeline Step 展开

点击一个 step 后显示：

```text
00:18 点击

目标：Chrome · API 文档
置信度：高
证据：before keyframe / after keyframe
结果：页面出现 Settings panel
状态：可用于后续 skill，但需要用户确认目标语义
```

不同事件展示不同字段：

| 事件 | 展示 |
| --- | --- |
| click | button、scope-relative point、target summary、before/after |
| scroll | direction、distance bucket、duration、after keyframe |
| hotkey | exact chord、semantic、after keyframe |
| typing_pause | 输入摘要、字符数量 bucket、是否 Enter 提交、不显示原文 |
| window_focus | app/window safe title、scope change |
| manual_mark | 用户标记、keyframe |
| pause/resume | control event、时长 |

## 与截图功能的关系

录制过程中可以复用截图能力，但要改变归属关系。

| 操作 | 非录制状态 | 录制中 |
| --- | --- | --- |
| `⌃⌘2` | 当前窗口截图，进入 Light Sheet | 添加当前窗口 keyframe 到 recording session |
| `⌃⌘3` | 区域截图，进入 Light Sheet | 添加区域 keyframe / 局部证据到 recording session |
| Light Sheet | 保存普通截图 event | 不默认弹出，避免打断录制 |

录制中使用截图快捷键时，HUD 必须短暂提示：

```text
已添加当前窗口关键帧
```

或：

```text
已添加区域关键帧
```

这些关键帧默认只出现在录制详情 timeline，不在截图列表里制造噪声。后续可以提供“导出为独立截图”的显式操作。

## 权限与隐私

### 权限降级

录制中权限状态必须可见，但不能制造恐慌。

| 场景 | UI |
| --- | --- |
| Screen Recording denied | 不开始录制，显示权限说明 |
| Accessibility denied | 允许录制视频，但窗口识别降级 |
| Input Monitoring denied | 不采集输入事件和快捷键 chord，只保留视频/keyframes/manual mark |
| Browser provider unavailable | 不阻断录制，timeline 标记 provider unavailable |

AX 降级推荐文案：

```text
窗口识别已降级
仍可录制画面；开启辅助功能权限后，WorkRecorder 可以更准确地识别窗口和控件。
```

Input Monitoring 降级推荐文案：

```text
操作线索未启用
这段录制会保存视频和关键帧，但不会记录点击、滚动和快捷键线索。
```

### 输入采集边界

输入线索按权限分级，不把“记录快捷键”伪装成“不需要键盘监听”。

| Level | 能力 | 需要权限 | 说明 |
| --- | --- | --- | --- |
| 0 | video + manual keyframes | Screen Recording | 只保存视频、start/final、手动标记 |
| 1 | mouse / scroll / focus | Accessibility / event observation | 记录点击、滚动、窗口焦点等低敏 action |
| 2 | shortcut chord summaries | Input Monitoring | 记录 exact shortcut chord，不记录普通输入原文 |

Input Monitoring disabled 时，不记录 hotkey chord，只记录视频、关键帧和手动标记。

录制中在对应权限开启时可以记录：

- click。
- scroll。
- exact shortcut chord。
- typing pause summary。
- submit-by-enter signal。
- focus/window change。

不能记录：

- 普通输入的原文。
- raw keydown stream。
- password / sensitive field 内容。
- 本机文件路径。
- raw DOM / raw a11y tree。

普通输入应该被表达为：

```text
输入暂停 · 约 20-40 个字符 · 可能提交
```

而不是：

```text
用户输入了 "..."
```

## 后端契约对齐

UI 不应该直接理解数据库细节，但需要和后端能力对齐。

| UI 概念 | 后端概念 |
| --- | --- |
| 录制片段 | `ActiveCaptureSession` |
| 开始/暂停/继续/完成 | control event / session transition |
| 手动标记 | `user_mark` keyframe trigger |
| HUD warning | typed warning / producer decision |
| 视频回放 | `VideoArtifactRef`，raw gate 控制 |
| Timeline step | keyframe/action/control/timeline manifest projection |
| 保存前 preview | start/final/representative keyframe bundle |
| Workbench 录制卡片 | Agent-safe inspect / public projection |
| Skill readiness | `SkillReadinessSummary` |

UI 必须遵守：

- raw video 默认受 gate 控制。
- raw keyframe image、raw DOM、raw a11y tree、OCR boxes 不进入默认 inspect/search。
- sensitive surface fail closed。
- 普通截图默认展示不因录制功能改变。

## 空状态与异常状态

### 没有可录制目标

```text
没有找到可录制区域
请选择屏幕上的一个窗口或区域。

重新选择    取消
```

### 录制区域太小

```text
区域太小，无法稳定录制
请选择至少 320 × 180 的区域。
```

### 磁盘空间不足

```text
空间不足，无法开始录制
请释放本地磁盘空间后再试。
```

### 超过最长时长

```text
录制已达到最长时长
WorkRecorder 正在整理这段录制。
```

### Scope Lost

```text
录制区域仍在继续，但窗口识别已变化

继续录制    重新选择区域    完成
```

### Capture Invalid

```text
录制区域不可用
显示器、权限或区域状态发生变化，WorkRecorder 已暂停录制。

重新选择区域    完成    丢弃
```

### 视频失败但关键帧可用

```text
视频保存失败，但关键帧已保留
你仍然可以查看 timeline 和关键帧证据。
```

## 设置页

设置页应统一管理截图和录制快捷键。

推荐结构：

```text
设置

截图快捷键
  当前窗口截图     ⌃⌘2      已启用
  区域截图         ⌃⌘3      已启用
  区域录制         ⌃⌥⌘R     已启用

录制
  默认保存视频     开
  默认记录操作线索  开
  最大录制时长      10 分钟
  完成后先预览      开

视觉识别
  OCR / Web / Accessibility settings
```

录制设置第一版可少，但必须能解释隐私：

- `记录操作线索` 不等于记录输入文本。
- 关闭后仍可录视频和关键帧。
- 敏感输入默认永不保存原文。

快捷键设置必须延续截图快捷键的冲突检测能力：

- WorkRecorder 内部重复绑定必须阻止保存。
- 系统/Carbon 注册失败必须显示冲突状态。
- 弱快捷键或 modifier-only 快捷键必须拒绝。
- 当前 App 常见快捷键冲突可以提示 warning 和替代建议，但不建议硬拒绝。
- 保存后立即刷新注册状态，daemon mirror 失败只能作为诊断 warning，不能覆盖本机 UserDefaults。

## 可访问性

必须支持：

- 键盘操作 HUD。
- VoiceOver 可读状态：recording、paused、warning、finalizing。
- Reduce Motion。
- 高对比模式。
- 清晰 focus ring。
- 不只用颜色表达状态。

HUD 的 VoiceOver 标签示例：

```text
WorkRecorder 正在录制，时长 12 秒。按钮：标记、暂停、完成。
```

暂停状态：

```text
WorkRecorder 录制已暂停，录制时长 12 秒。按钮：继续、完成。
```

## 分阶段落地状态

### UI V1a：可信录制最小闭环（已落地）

- `⌃⌥⌘R` 进入区域录制准备态。
- 区域选择 overlay。
- 区域确认条。
- 倒计时。
- HUD + 边框 + 菜单栏状态。
- 完成 / 丢弃。
- 完成 sheet + preview。
- Staging review：打开临时回放、保存、丢弃。
- 保存到 Workbench 录制列表。
- Fixed region scope，不自动跟随窗口。
- App 退出 / daemon endpoint refresh / 录制启动失败都有 session-state 保护和清理路径。
- Completion sheet 已包含保存备注输入框。
- 丢弃确认已改成专用 WorkRecorder 面板，安全返回是主动作。

V1a 的目标是让用户敢用。它优先证明“不会静默录、边界清楚、结束前可审查”。

### UI V1b：录制控制与 trace 增强（已落地）

- 暂停 / 继续。
- 手动标记。
- `⌃⌘2` / `⌃⌘3` 添加 recording keyframe。
- action trace：click、scroll、focus、shortcut chord summary、typing pause summary。
- Timeline 初版。
- 录制 keyframes/actions 不污染普通截图流。
- 暂停/继续会切 segment，保存时可拼接为单个 playback video。
- 输入 producer 的降级会进入 HUD 和 completion warning。
- 快捷键触发 keyframe 时 HUD 显示 typed feedback，不再假成功。

### UI V1.1：证据与回放增强（部分已落地）

- Timeline step 展开。
- before/after keyframe。
- safe caption。
- warning / needs review。
- 视频时间与 keyframe/action 对齐。
- Workbench 安全复盘抽屉。
- 显式内嵌视频播放。
- 视频下方轻量播放控制。
- `用播放器打开` 外部播放器入口。
- recording-specific `原始材料` tab。
- 手动导出关键帧为独立截图仍未落地。

### UI V1.2：大屏复盘工作区（已落地，继续验收）

抽屉复盘负责快速确认，大屏复盘负责专注回看。V1 已按 [大屏录制复盘工作区设计方案](RECORDING_LARGE_SCREEN_REVIEW_CN.md) 落地为独立窗口，并与抽屉复用同一份 safe inspect/read model：

- 大视频播放器作为主画面。
- 下方章节 timeline 和 marker rail。
- 右侧显示当前 step 的文字、截图、action、warning。
- 空格播放/暂停，左右箭头跳 step。
- 继续复用 dedicated playback route 和 safe inspect projection。
- 不引入 raw video 自动暴露，不绕过 disclosure audit。

已补齐 packaged app 保存录制后自动打开大屏复盘并加载 dedicated playback route 的 controlled smoke 证据；仍需继续补齐的是物理快捷键/HUD/manual focus 矩阵，以及真实视频帧播放 readiness 的更强自动化检查。这些属于发布验收，不改变 V1 产品结构。

### UI V2：Skill-friendly 工作流

- Skill readiness summary。
- 将录制转成教程 / 操作步骤。
- 用户确认目标和参数。
- 生成 workflow draft。
- 不自动发布 skill。

## 验收清单

### 基础流程

- `⌃⌥⌘R` 只进入准备态，不直接录制。
- 框选后必须出现确认条。
- V1 录制固定屏幕区域，不自动跟随窗口。
- 点击开始后有倒计时。
- 录制中有菜单栏状态、HUD 和边框。
- HUD 默认不得进入 video artifact。
- `⌃⌥⌘R` 录制中只唤起 HUD，不暂停、不停止。
- `Esc` 弹确认，不直接停止。
- 完成后进入 staging preview sheet，不自动进入长期库。
- 丢弃会清理 staging artifact。

### 安全与隐私

- 没有 silent recording。
- 没有隐藏录制状态。
- 没有 raw keyboard text。
- Input Monitoring disabled 时不记录 exact shortcut chord。
- AX/Input Monitoring 降级状态可见。
- raw video 不进入默认 Agent inspect。
- 录制关键帧默认不变成普通截图卡片。

### Workbench

- 录制有独立列表入口。
- 卡片显示 duration、keyframes、actions、video、warning。
- 详情页能看视频或 keyframe storyboard。
- Timeline step 可定位到 video/keyframe。
- `needs review` 不被隐藏。
- `截图库` 不混入录制 session，也不展示录制 secondary keyframe material。
- 点击录制卡片打开复盘，不静默读取 raw video。
- 播放视频必须通过显式点击和 dedicated playback route。
- 内嵌播放器控制不得遮住视频主体。
- 详情中必须有 `用播放器打开` 入口，便于小窗看不清时使用系统播放器。
- no-video 录制显示 `关键帧复盘`，不能承诺视频播放。

### 质量

- Reduced Motion 下可用。
- 多屏坐标正确。
- HUD 不遮挡录制主体，必要时自动吸附到区域外。
- 全屏/Spaces 行为可预测。
- 权限 denied 不崩溃。
- 录制失败时保留可解释状态。

## 最终一句话

WorkRecorder Recording 的体验目标不是让用户惊叹“它能录屏”，而是让用户放心：“我知道它什么时候开始、录哪里、现在还在不在录、录到了什么，以及我能不能安全地保存。”
