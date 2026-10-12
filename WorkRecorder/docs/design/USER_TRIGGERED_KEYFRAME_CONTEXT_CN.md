# Active Context Capture：截图关键帧与记录片段

> 导航：[返回文档总览](../README.md) · 相关：[Screenpipe 深读](SCREENPIPE_ACTIVE_CAPTURE_LESSONS_CN.md) · [System Appshot](../architecture/SYSTEM_APPSHOT_CN.md) · [阶段 2：采集](../02_COLLECTION_CN.md)

这份文档把之前两份设计合并成一个统一能力：

> **Active Context Capture**：把用户主动捕捉的屏幕时刻和操作片段，转化为可回放、可搜索、可审查、可引用的上下文证据。

它下面有两种模式：

| 模式 | 用户心智 | 默认产物 |
| --- | --- | --- |
| 截图关键帧 | “这一刻很重要” | 当前截图 + 少量稳定/增强关键帧 |
| 记录片段 | “接下来这段操作很重要” | 人可回看的视频 + Agent 可用的关键帧/文本/证据 |

这不是后台无限录屏，也不是简单视频文件夹。它的核心是：**用户主动、范围明确、证据成链、Agent 渐进式读取**。

## 一句话产品定义

WorkRecorder 现在已经能把一次截图保存成可审计 event。Active Context Capture 要进一步解决两个问题：

1. 一张截图有时不够。页面可能还在加载，菜单可能马上消失，OCR/Web provider 可能稍后才补全。
2. 用户有时想记录一段操作过程。比如复现 bug、浏览 PDF、比较网页、演示一个后台流程。传统录屏能回看，但 Agent 很难安全、可引用地使用。

所以我们把“屏幕记录”拆成两层：

- **给人看的回放层**：记录片段默认保存一段本地视频，方便用户日后打开查看。
- **给 Agent 用的证据层**：关键帧、OCR/a11y/Web 文本、system.appshot、provider outcome、citation、audit。

视频不默认给 Agent。Agent 默认消费的是安全摘要、文本、关键帧引用和 citation。

录制部分的核心边界可以压成一句话：

> 视频是 raw memory，关键帧是 evidence，时间线是 interface，citation 是壁垒，privacy gate 是底线。

### P7.8/P7.9 后端边界

P7.8/P7.9 先做后端能力，不做 Workbench UI、播放器、storyboard 页面、菜单入口或录制触发 UI。

- UI storyboard 和 Agent inspect 是两个 projection。`/v1/active-captures/{session_id}/storyboard`
  继续服务未来产品 UI；Agent 只通过显式请求
  `/v1/events/{event_id}?view=event_inspect&inspect_views=active_capture_summary,recording_timeline,...`
  获取 `EventInspectView.active_capture`。
- Agent-safe inspect 只暴露 session/status、timeline step、低敏 action caption、
  bounded redacted text block、safe video ref、citation target 和 skill readiness。
  raw keyframe image、raw video、raw DOM、raw a11y tree、OCR boxes、producer metadata
  继续走 raw gate，不在默认 inspect/search 中出现。
- active-capture 新文本必须走 typed policy-before-index projection，先生成
  `IndexableTextSource -> SafeIndexProjectionBatch -> IndexDocument`。敏感 surface
  fail closed，只保留 hidden/coarse 说明，不猜测放行。
- 普通截图保存、默认 search card、默认 event inspect 不依赖 Active Capture inspect/index 成功，
  也不因为本阶段变更而改变展示形态。

## 从 screenpipe 借鉴什么

这轮阅读了本机 `reference_code/screenpipe` 的关键实现和文档：

- `crates/screenpipe-engine/src/event_driven_capture.rs`
- `crates/screenpipe-engine/src/paired_capture.rs`
- `docs/EVENT_DRIVEN_CAPTURE_SPEC.md`
- `docs/VISION_PIPELINE_SPEC.md`
- `docs/TIMELINE_VIDEO_SPEC.md`
- `crates/screenpipe-core/assets/skills/screenpipe-api/SKILL.md`

值得借鉴的是这些原则。

### 1. 事件驱动，而不是固定 FPS 盲录

screenpipe 的新路径不再只靠固定帧率，而是用 app switch、window focus、click、typing pause、scroll stop、visual change、idle fallback 等事件触发 capture。

WorkRecorder 不应该把这些事件变成后台常驻监控。更适合的做法是：只有用户主动开始截图/记录后，这些触发才在限定窗口、限定范围内生效。

### 2. Paired capture 是可信度核心

screenpipe 的 `paired_capture` 把截图、a11y、OCR 写在同一个 frame 上，避免“搜到的文字和缩略图不是同一刻”。

WorkRecorder 已经有 `system.appshot`，所以每个关键帧也必须是 paired evidence：

```text
ContextKeyframe
  -> screenshot evidence
  -> system.appshot evidence
  -> a11y evidence refs
  -> OCR evidence refs
  -> App provider evidence refs
  -> quality / permission diagnostics
```

每帧都要能解释：画面来自哪里，文字来自哪里，质量如何，是否同一时刻。

### 3. a11y 优先，OCR 兜底，但要识别 thin a11y

screenpipe 不是无脑 OCR。它先看 accessibility tree，如果 a11y 有可靠文本就跳过 OCR；如果只有工具栏、浏览器 chrome、会议按钮、canvas 外壳，就认为是 thin a11y，再跑 OCR 或 hybrid。

WorkRecorder 可以沿用这个策略：

- Chrome 普通网页：优先 Web provider / clean page text。
- 原生 App：优先 a11y，再 OCR。
- PDF、Preview、远程桌面、图片、会议、Figma/Miro/Canva：默认偏 OCR。
- 所有来源都记录 `source_method`、confidence 和 diagnostics。

### 4. 关键帧图片比视频抽帧更适合 Agent 热路径

screenpipe 的 timeline 设计说明过：从 MP4/H.265 里抽单帧慢、复杂，还容易让回放和搜索错时。事件驱动后，直接写 JPEG/PNG snapshot 更适合搜索和证据引用。

WorkRecorder 的取舍是：

- 关键帧截图是 Agent 证据热路径。
- 视频是用户回看材料。
- 不从视频里抽帧作为主要 evidence。
- 如果用户要视频，视频作为 raw artifact 保存和播放。

## 两种模式

### 模式一：截图关键帧

用户按快捷键框选屏幕。WorkRecorder 立即保存 anchor frame，然后在很短窗口里补少量关键帧。

适合：

- 网页还在 loading。
- 下拉菜单或 tooltip 很快消失。
- OCR 或 Web provider 稍后补全文字。
- 图表或页面在短时间内稳定。

默认策略：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| observation window | 5 秒 | 截图后的短观察窗口 |
| max keyframes | 4 | anchor + settle/provider/ocr 等少量辅助帧 |
| settle delay | 500ms | 页面稳定后检查一次 |
| min frame gap | 250ms | 防止风暴 |
| visual diff threshold | 0.06 | 过滤光标闪烁、小动画 |
| text diff threshold | 0.12 | 文字新增/变化才留 |

关键帧角色：

- `anchor`：用户框选那一刻。
- `settle`：页面稳定后的状态。
- `provider_completion`：Web/OCR/App provider 补全后。
- `change`：画面或文字发生有意义变化。

### 模式二：记录片段

用户主动点击“开始记录”，选择窗口或区域，然后主动结束。WorkRecorder 默认同时保存：

1. **本地视频**：给用户日后回看。
2. **关键帧证据流**：给 Agent 搜索、精查、引用。
3. **可选 human demonstration trace**：给未来 skill/workflow 沉淀使用。

适合：

- 复现 bug。
- 演示后台操作。
- 比较几个网页或文档。
- 阅读 PDF/长网页并希望 Agent 之后理解过程。
- 录一段“我是怎么做的”，以后变成自动化流程。

第一版建议优先支持 window scope。

| Scope | 优先级 | 原因 |
| --- | --- | --- |
| window | P0 | 最清楚，能绑定 window id、App、title，也方便 provider routing |
| region | P1 | 适合图表、远程桌面、视频区域，但遮挡和多屏坐标更难 |
| current_app | P1 | 适合同一 App 内多窗口切换，但语义不如 window 稳 |
| full screen | 不默认 | 隐私压力大，噪声高 |

录制默认参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| max duration | 10 分钟 | 防止忘记关闭 |
| max keyframes | 60 | 关键帧，不是视频帧 |
| min keyframe gap | 500ms | 防止风暴 |
| idle anchor interval | 30 秒 | 长时间静止时留时间锚点 |
| save video | true | 给人回看，默认锁住不给 Agent |
| capture audio | false | 不默认录音 |
| capture raw keyboard text | false | 不记录普通文本输入 |

第一版不建议叫“智能录屏”，也不要承诺“自动学会你的流程”。更准确的产品定义是：

> 窗口级上下文记录：用户选择一个窗口，WorkRecorder 保存视频回放，并生成 Agent 可读的 storyboard 关键帧时间线。

P0 只保留：

- 选择窗口。
- 开始记录 / 暂停 / 结束。
- 本地视频 artifact。
- start / end / user mark keyframe。
- scroll_stop / click_settle / provider completion / OCR completion 关键帧。
- Workbench 记录卡片。
- 详情页 storyboard。
- Agent inspect `recording_timeline` / OCR / clean page text / evidence refs。
- raw video 默认锁定。

P0 暂不做：

- full screen scope。
- 默认 region scope。
- audio。
- raw keyboard text。
- 自动 workflow candidate UI。
- 自动生成 skill。
- 复杂剪辑器。
- 视频语义理解。

## 采集时机

### 必留帧

- start：录制起点。
- end：录制终点。
- user mark：用户点“标记此刻”。

### 条件保留帧

| 触发 | 什么时候保留 |
| --- | --- |
| window title / URL 变化 | 新页面、新文档、新任务 |
| scroll stop | 新内容稳定进入视野 |
| click settle | 点击后弹窗、菜单、详情出现 |
| provider completed | Web/PDF/App provider 补到重要材料 |
| OCR completed | OCR 让文本质量明显提升 |
| visual diff | 画面变化超过阈值 |
| text diff | OCR/a11y/Web 文本变化明显 |
| surface change | 主窗口、遮挡、secondary surface 变化 |
| idle fallback | 长时间没变化，留时间锚点 |

### 关键帧优先级

关键帧不能退化成“低 FPS 录屏”。录制期间要先按事件价值分档，再按预算保留。

| 档位 | 例子 | 策略 |
| --- | --- | --- |
| A. 必留帧 | start、end、user_mark、scope_lost、sensitive_skip_placeholder、major_navigation | 不参与普通预算竞争 |
| B. 高价值帧 | URL/title 变化、新 dialog/popover/menu、scroll_stop 带来新文本、click_settle 命中新 surface、provider evidence improved、error/toast/alert | 优先保留 |
| C. 普通变化帧 | visual_diff、text_diff、surface_change | 超过阈值才保留 |
| D. 时间锚点 | idle_anchor 每 30-60 秒 | 只在长时间没变化时保留 |

这样 Workbench 的 timeline 会像 storyboard，而不是一堆重复截图。

### 丢弃原因也要入账

不保存的帧也要有诊断，至少采样入账：

- duplicate。
- low_delta。
- too_soon。
- budget_exceeded。
- scope_lost。
- sensitive_surface。
- permission_denied。

这能解释为什么某段录制只有 8 张关键帧，而不是 600 张。

## Recording Session 状态机

录制是长生命周期对象，不能只用 `recording/completed/failed` 三个状态。建议状态机：

```text
created
  -> selecting_scope
  -> recording
  -> paused
  -> scope_lost
  -> stopping
  -> finalizing
  -> completed
  -> completed_with_warnings
  -> failed
  -> cancelled
```

`completed_with_warnings` 很重要。真实录制里经常出现“主结果可用，但增强不完整”：

- 视频保存成功，但 OCR 失败。
- keyframe 成功，但 Web provider skipped。
- 用户关闭了窗口。
- a11y 权限中途不可用。
- 结束时还有 provider 没完成。
- raw video encoding 失败，但 storyboard 可用。

这些不应该都算 `failed`。用户关心的是“这段记录还能不能用”，不是所有后台增强是否完美完成。

录制结束也要分阶段：

```text
T0：用户点击结束
T1：session closed，start/end/keyframes ledger 写完
T2：summary / OCR / provider evidence 持续补全
T3：video artifact finalized
```

Workbench 应该尽快显示：

```text
记录已保存
正在整理文字和关键帧
视频处理中 / 已可回放
```

Agent 也可以先搜到粗卡，不必等视频最终编码完成。

## Human Demonstration Trace

这是新增的一层，目标不是监控用户，而是为未来“从人类演示沉淀 skill/workflow”打基础。

Human Demonstration Trace 应该是 Active Context Capture 的一等接口，但第一版不要把它包装成“自动学会你的流程”。用户侧先表现为“操作线索”，底层先把可语义化的中间表示铺好。

第一版建议只记录低敏、结构化、可解释的操作事件，不记录原始键盘内容。

默认可记录：

| 事件 | 记录什么 | 不记录什么 |
| --- | --- | --- |
| mouse click | 时间、窗口、坐标、命中的 UI element ref | 不推断敏感字段值 |
| scroll | 方向、幅度、窗口、前后关键帧 | 不记录网页外内容 |
| hotkey | copy/paste/submit/search 这类语义分类，外加 exact chord：物理 key code、normalized label、modifier enum | 只用于快捷键/热键，不记录普通文字按键 |
| typing pause | “用户输入后停顿”这个事实、事件数、字符数、删除键数、IME/composition/submit-by-enter 摘要 | 不记录输入内容，不存 raw keystrokes |
| window/tab switch | App、title、sanitized URL | 不记录 URL query/hash |
| user mark | 用户手动标记的重要时刻 | 不自动生成动作脚本 |

建议合约：

- `HumanDemonstrationTrace`
- `HumanActionEvent`
- `HumanActionKind`
- `ActionTargetRef`
- `ActionEvidenceLink`
- `ProducerEventEnvelope`
- `ProducerDecision`
- `KeyChord`
- `TypingSessionSummary`
- `WorkflowCandidate`

一个有价值的 human action 不能只是鼠标键盘日志。它应该分三层：

| 层 | 例子 | 用途 |
| --- | --- | --- |
| `raw_signal` | click、scroll、hotkey、typing_pause | 低敏事实 |
| `target_ref` | DOM selector、a11y element、OCR bbox、appshot component、keyframe ref | 能追溯命中了什么 |
| `semantic_hint` | 用户点击了 Enterprise tab；页面切到企业套餐详情 | 后续由 Agent/LLM 生成，可被用户审查 |

示例：

```text
raw_signal: click
target_ref: button[text="Enterprise"] / DOM selector / OCR bbox / keyframe_07
semantic_hint: 用户在 Chrome 定价页点击了 Enterprise tab
result_hint: 页面切到企业版套餐详情
```

后续流程应该是：

```text
录制片段
  -> human demonstration trace
  -> SkillDistillationService 后处理成 workflow candidate
  -> 用户确认
  -> 补充输入参数和泛化范围
  -> 生成 SkillDraft
  -> dry-run / 测试
  -> 用户发布成 skill / automation recipe
```

不要录制时直接生成自动化脚本。鼠标坐标和 UI 状态不稳定，必须先转成语义步骤，再让用户确认。

推荐文案也要克制：

```text
WorkRecorder 已记录这段操作线索。
你可以让 Agent 将它整理成一个可审查的 workflow 草稿。
```

不要写成：

```text
已自动生成 skill。
```

## 架构设计

### 新增模块

建议新增 `packages/active_capture/`，承载两种模式的共同逻辑。

```text
packages/active_capture/
  contracts.py
  session_service.py
  keyframe_service.py
  recording_service.py
  demonstration_service.py
  distillation_service.py
  policy.py
  trigger_buffer.py
  diff.py
  dedup.py
  summary.py
  repositories.py
```

职责：

| 组件 | 职责 |
| --- | --- |
| `ActiveCaptureSessionService` | start / pause / stop / cancel / finalize |
| `ActiveCaptureScopeResolver` | 绑定 window / region / current_app，处理窗口丢失和多屏坐标 |
| `TriggerBuffer` | 接收 click、scroll、visual、provider、OCR、user mark 等触发 |
| `KeyframeCapturePolicy` | 判断 keep/drop，给出 reason |
| `KeyframeCaptureService` | 调用现有 capture pipeline 生成一帧 evidence bundle |
| `VideoArtifactService` | 管理用户回看的本地视频 artifact |
| `HumanDemonstrationService` | 记录低敏操作事件，生成 workflow candidate 输入 |
| `SkillDistillationService` | 从 demonstration trace 生成 WorkflowCandidate / SkillDraft，不直接发布 |
| `ActiveCaptureSummaryService` | 生成过程摘要和 event_context_text |
| `ActiveCaptureRepository` | 写 session/keyframe/timeline/demo ledger |

### 和现有 P6 链路的关系

Active Context Capture 不绕过现有主链路。每个关键帧都像一次轻量 capture attempt：

```text
ActiveCaptureTrigger
  -> KeyframeCaptureService
  -> SurfaceDetectionService
  -> ProviderRoutingService
  -> SystemEvidenceOrchestrator
  -> AppProviderFanoutService
  -> CapturePersistenceService
  -> Enrichment / OCR / Index
```

区别是：

- 普通截图 event 有一张主截图。
- Active capture event 可以挂 1..N 个 `ContextKeyframe`。
- 记录片段还有一个用户回看的 video artifact 和可选 demonstration trace。

## 合约与枚举

核心 enum：

| Enum | 值 |
| --- | --- |
| `ActiveCaptureMode` | `screenshot_keyframes`, `recording_session` |
| `ActiveCaptureStatus` | `created`, `selecting_scope`, `recording`, `paused`, `scope_lost`, `stopping`, `finalizing`, `completed`, `completed_with_warnings`, `failed`, `cancelled` |
| `RecordingScopeKind` | `window`, `region`, `current_app` |
| `KeyframeRole` | `anchor`, `settle`, `change`, `provider_completion`, `user_mark`, `idle_anchor`, `start`, `final` |
| `KeyframeTriggerKind` | `manual_start`, `manual_stop`, `manual_screenshot`, `user_mark`, `visual_change`, `text_change`, `surface_change`, `scroll_stop`, `click_settle`, `provider_completed`, `ocr_completed`, `idle_fallback` |
| `KeyframeKeepReason` | `required_boundary`, `user_marked`, `visual_delta`, `text_delta`, `provider_evidence_added`, `quality_improved`, `primary_surface_changed`, `idle_anchor` |
| `KeyframeDropReason` | `duplicate`, `low_delta`, `too_soon`, `budget_exceeded`, `scope_lost`, `sensitive_surface`, `permission_denied` |
| `HumanActionKind` | `click`, `scroll`, `hotkey`, `typing_pause`, `window_switch`, `tab_switch`, `user_mark` |
| `VideoArtifactState` | `not_recorded`, `recording`, `available`, `failed`, `deleted` |

核心模型：

- `ActiveCaptureSession`
- `RecordingScope`
- `RecordingCapturePolicy`
- `ContextKeyframe`
- `KeyframeDiffReport`
- `KeyframeQualityReport`
- `KeyframeEvidenceLink`
- `RecordingTimeline`
- `RecordingTimelineManifest`
- `RecordingSummary`
- `VideoArtifactRef`
- `HumanDemonstrationTrace`
- `HumanActionEvent`
- `WorkflowCandidate`
- `SkillDraft`

`RecordingScope` 需要为 window scope 打牢多屏和遮挡基础：

| 字段 | 用途 |
| --- | --- |
| `display_id` | 绑定显示器 |
| `display_scale` | Retina / 坐标换算 |
| `coordinate_space` | screen / display / window |
| `window_id` | 绑定窗口 |
| `app_pid` / `bundle_id` | App 身份 |
| `bounds_in_screen` / `bounds_in_display` | 截图、视频裁剪、citation 对齐 |
| `occlusion_state` | 是否被遮挡 |
| `scope_confidence` | 绑定是否可靠 |
| `last_seen_at` | 窗口丢失/恢复判断 |

## 存储设计

### Ledger tables

建议新增：

```text
active_capture_sessions
  active_capture_id
  event_id
  mode
  status
  scope_kind
  scope_ref_json
  primary_app_name
  primary_bundle_id
  primary_window_title
  started_at
  ended_at
  duration_ms
  user_note
  capture_policy_id
  keyframe_count
  summary_evidence_id
  video_artifact_id
  demonstration_trace_id
  created_by_user_id
  created_at
  updated_at
  payload_json

recording_timeline_manifests
  timeline_manifest_id
  active_capture_id
  event_id
  video_artifact_id
  clock_origin_wall_time
  clock_origin_monotonic_ms
  duration_ms
  alignment_error_ms
  keyframe_count
  action_count
  policy_version
  payload_json

context_keyframes
  keyframe_id
  active_capture_id
  event_id
  capture_run_id
  role
  trigger_kind
  keep_reason
  captured_at
  order_index
  bbox_json
  primary_surface_id
  screenshot_evidence_id
  appshot_evidence_id
  video_artifact_id
  nearest_video_segment_id
  media_time_ms
  captured_at_wall_time
  captured_at_monotonic_ms
  keyframe_full_text_hash
  quality_json
  diff_json
  policy_version
  payload_json

keyframe_evidence_links
  keyframe_id
  evidence_id
  evidence_kind
  provider_key
  source_scope
  route_id
  created_at

human_demonstration_traces
  demonstration_trace_id
  active_capture_id
  event_id
  status
  action_count
  policy_version
  created_at
  payload_json

human_action_events
  action_id
  demonstration_trace_id
  action_kind
  occurred_at
  media_time_ms
  order_index
  raw_signal_json
  target_ref_json
  semantic_hint_json
  evidence_refs_json
  redaction_state
  payload_json

workflow_candidates
  workflow_candidate_id
  demonstration_trace_id
  active_capture_id
  status
  title
  steps_json
  required_inputs_json
  generalization_scope
  created_at
  payload_json

active_capture_index_records
  active_capture_id
  keyframe_id
  index_backend
  indexed_fields_json
  text_hash
  policy_version
  created_at
```

### Vault 内容

默认保存：

- keyframe PNG/WebP。
- recording video artifact，给人回看。
- safe summary JSON。
- provider/evidence sidecar。
- demonstration trace JSON，低敏结构化事件。

默认不保存：

- 全局键盘输入内容。
- 全局音频。
- clipboard 原文。
- scope 外窗口原始内容。
- cookies/localStorage/sessionStorage/network response。

默认锁住：

- keyframe 原图。
- recording video。
- raw DOM。
- raw a11y tree。
- OCR boxes。
- provider raw diagnostics。

### RecordingTimelineManifest

录制最怕错位。必须有显式 timeline manifest，把视频时间、系统时间、关键帧、操作事件、证据引用对齐。

每个 keyframe 至少要能回答：

```text
captured_at_wall_time
captured_at_monotonic_ms
media_time_ms
order_index
trigger_kind
role
scope_ref
video_artifact_id
nearest_video_segment_id
evidence_bundle_id
```

`media_time_ms` 很关键。用户在视频里跳到 `01:23`，系统要能定位附近关键帧；Agent 引用第 8 张关键帧时，用户也要能在视频里看到同一位置。

## Index 与 Agent 可见性

录制的隐私风险比截图高。任何文本进入 index 前都必须先过策略。

建议链路：

```text
raw capture
  -> sensitive surface detection
  -> redaction / suppression
  -> safe text projection
  -> summary
  -> index
```

每条 index record 至少带：

```text
access_tier
redaction_state
policy_decision_id
sensitive_surface_type
raw_available
agent_visible_fields
```

对于敏感窗口，粗搜卡只能显示类似：

```text
记录片段 · 2 分钟
内容因策略被隐藏
可请求用户授权查看关键帧摘要
```

不能把 OCR 或网页正文先泄进 summary card。

### 粗搜 summary card

只给：

- event_id。
- active_capture_id。
- mode：截图关键帧或记录片段。
- captured_at 或 started_at / ended_at / duration。
- 主 App / title / sanitized URL。
- 用户 note。
- 过程摘要 1 到 3 句。
- keyframe_count。
- available fields：OCR、网页正文、关键帧、截图引用、视频可回看。
- hidden materials：raw keyframe images、recording video、raw DOM、raw a11y tree。

不要默认返回：

- 全部 OCR。
- 全部关键帧文本。
- 视频路径。
- raw screenshot。
- raw DOM / raw a11y。
- 操作事件明细。

### 精查 event inspect

可支持这些 view：

| View | 内容 |
| --- | --- |
| `active_capture_summary` | 用户可读过程摘要、主 App、时间范围 |
| `recording_timeline` | keyframe storyboard，角色、触发原因、安全 caption |
| `visual_ocr_text` | 关键帧 OCR 合并后的安全文本 |
| `clean_page_text` | Web provider 清洗正文 |
| `screenshot_ref` | keyframe screenshot refs，不内联 raw |
| `video_ref` | 人类回看视频 ref，不默认给 Agent raw |
| `human_demo_summary` | 操作步骤摘要，不含原始键盘文本 |
| `system_appshot` | anchor 或每帧系统底片摘要 |
| `evidence_refs` | 可引用 evidence refs |

### Citation

引用可以指向：

- 整个 active capture session。
- 某张 keyframe。
- 某个 OCR/Web/a11y evidence。
- 某段 text range。
- 某个 bbox。
- 某个 human action summary step。

回答里可以写：

> 这个结论来自 `cit_kf_...`，对应记录片段第 4 张关键帧，触发原因是 `scroll_stop`，文字来自 Apple Vision OCR。

## Workbench UI/UX

### 导航入口

Workbench 可以新增一个一级入口：

```text
记录片段
```

不建议叫“视频库”。原因是这里不是普通视频管理，而是可搜索、可审查、可引用的上下文片段。

也不建议把入口叫“录屏”或“智能录屏”。“录屏”会让用户以为这是一个视频工具；“智能录屏”又容易承诺过头。WorkRecorder 的心智应该是：

```text
记录一段操作
```

按钮说明可以写：

```text
选择一个窗口，WorkRecorder 会保存视频回放，并自动整理关键时刻和文字。
```

首页可以增加一个轻量 CTA：

```text
记录一段操作
选择一个窗口，WorkRecorder 会保存视频回放，并自动整理关键帧和文字。
```

### 录制浮层

录制时显示一个克制但明确的浮层：

```text
WorkRecorder 正在记录 · Google Chrome · 00:42
[标记此刻] [暂停] [结束]
已保存 7 张关键帧 · 视频本地保存中
```

状态文案：

- `正在记录`
- `已暂停`
- `窗口被遮挡，已记录质量提示`
- `窗口已关闭，要结束记录吗？`
- `文字识别中`
- `网页增强已完成`

### 记录片段卡片

卡片应展示：

- 主 App 图标。
- 标题/窗口名。
- 时间范围和时长。
- 用户 note。
- keyframe_count。
- OCR/Web/App provider 状态。
- 视频是否可回看。
- Agent 默认能看到什么。
- 锁住的原始材料。

示例：

```text
Chrome 操作片段 · 2 分 14 秒
14:02:10 - 14:04:24
用户备注：比较三个套餐差异

23 张关键帧 · 视频可回看 · OCR 完成 · 网页增强成功
默认可见：过程摘要、关键 OCR、网页正文摘要
锁定：关键帧原图、完整视频、DOM、a11y tree
```

### 详情页

建议四个主 tab：

| Tab | 用户看到什么 |
| --- | --- |
| 摘要 | 过程摘要、主 App、时间范围、关键发现 |
| 时间线 | keyframe storyboard，start/change/final/user mark |
| 文本 | OCR、网页正文、重要段落 |
| 回放 | 本地视频播放器 + keyframe gallery |

诊断折叠到高级区：

- provider outcomes。
- dropped frame reasons。
- surface confidence。
- permission state。
- policy version。
- demonstration trace raw metadata。

### 时间线视觉

不要第一版就做复杂视频剪辑器。更适合做 storyboard：

```text
Start      打开定价页
Scroll     套餐表进入视野
Change     切换企业版
Provider   网页正文补全
Mark       用户标记这一刻
Final      停在对比结论
```

每个节点：缩略图 + 一句安全 caption + 触发原因。用户点开后再看大图、文本和 evidence。

第一版不要做复杂剪辑器，也不要让用户修剪视频。用户最需要的是：

1. 快速确认这段记录有没有保存成功。
2. 能按关键时刻回看。
3. 能知道 Agent 默认看到了哪些安全文本。
4. 能在需要时点开原视频或关键帧，但这些 raw 材料仍走授权和审计。

## 隐私边界

Active Context Capture 必须比传统录屏更克制：

- 必须用户主动开始。
- 必须显示录制状态。
- 必须能一键停止。
- 必须有最大时长。
- scope 变化或窗口丢失时暂停/降级，不悄悄改成全屏。
- raw video 默认锁定。
- keyframe 原图默认锁定。
- demonstration trace 不记录普通键盘文本。
- 所有 inspect/raw 都进 agent run trace。

如果未来支持后台持续关键帧或音频，必须做单独授权和单独产品入口，不能混进这个模式。

## E2E 验收场景

第一批覆盖：

1. Chrome 普通网页：start/end keyframe + Web provider completed。
2. Chrome loading 页面：anchor 无正文，settle/provider frame 有正文。
3. 长网页滚动：scroll stop 产生关键帧。
4. PDF / Preview：OCR text 进入文本视图。
5. 下拉菜单：anchor 捕获菜单，settle 不误删 anchor。
6. 多窗口重叠：primary/secondary surfaces 正确。
7. 桌面空白区域：system appshot 仍能保存。
8. Chrome extension 离线：记录完成，Web outcome skipped。
9. a11y 无权限：permission diagnostic 入账，OCR fallback 尝试。
10. 敏感窗口：关键帧跳过，session 记录 policy skip。
11. 用户录制 Chrome 2 分钟：视频可回看，关键帧不超过预算。
12. 用户录制 Preview/PDF：视频、OCR、appshot、raw lock 全部正确。
13. 用户录制窗口被遮挡：记录 occlusion/secondary surfaces。
14. 用户忘记停止：max duration 自动结束。
15. 操作事件：click/scroll/hotkey/typing_pause 记录为低敏 demonstration trace。
16. Agent 粗搜：只返回 note/time/app/title/summary/keyframe_count/available_fields。
17. Agent 精查：能查看 timeline/OCR/网页正文/video_ref，但 raw video 仍需 gate。
18. Timeline 对齐：点击第 N 张关键帧能跳到视频里接近同一时刻。
19. 完成告警：视频成功但 OCR/Web provider 失败时，session 是 `completed_with_warnings`，不是 failed。
20. Skill 草稿：demo trace 可以生成 workflow candidate，但不能自动发布 skill。

## 验收指标

录制能力不能只看“能不能录下来”。建议从第一版就记录这些指标，帮助判断 timeline 是否真的对 Agent 有用。

| 指标 | 说明 |
| --- | --- |
| `time_to_searchable` | 用户结束记录后，多久能在粗搜里看到记录片段 |
| `finalization_latency` | 视频 artifact、summary、关键帧全部完成所需时间 |
| `timeline_alignment_error_ms` | keyframe 和视频时间线的平均对齐误差 |
| `keyframe_redundancy_ratio` | 重复或低价值关键帧比例 |
| `storage_mb_per_minute` | 每分钟本地存储成本 |
| `cpu_overhead_during_recording` | 录制期间 CPU 开销 |
| `provider_completion_delay` | OCR/Web/App provider 补全延迟 |
| `sensitive_text_leak_rate` | 默认 search card / index 是否泄漏敏感文本 |
| `citation_to_keyframe_accuracy` | Agent citation 是否能定位到正确关键帧 |
| `raw_material_gate_hit_rate` | raw video / raw keyframe / raw DOM 访问是否都经过 gate |

## 分阶段实现建议

### P7.1：RecordingSession 状态机 + window scope resolver

- 落 typed contracts、ledger、golden fixtures。
- 支持 `created/selecting_scope/recording/paused/scope_lost/stopping/finalizing/completed_with_warnings` 等状态。
- 实现 window scope 绑定：display、scale、window id、bundle id、bounds、occlusion、scope confidence。
- 暂不做完整 UI，只保证 session 生命周期可靠。

### P7.2：截图 anchor keyframe baseline

- 每次普通截图都生成 anchor keyframe。
- keyframe 链接 screenshot、system.appshot、a11y、OCR、Web refs。
- `events inspect` 能看到 keyframe summary 和 evidence refs。
- 这一步先不做录制，只把“截图关键帧”接进现有 ledger。

### P7.3：recording start/end keyframe + video artifact

- 支持“开始记录窗口 / 结束记录”。
- start/end keyframe 必留。
- 默认保存本地视频 artifact，raw video 默认锁定。
- 视频失败但 keyframe 可用时，session 进入 `completed_with_warnings`。

### P7.4：timeline manifest 与时间对齐

- 新增 `RecordingTimelineManifest`。
- 每个 keyframe 记录 `media_time_ms`、wall time、monotonic time、nearest video segment。
- Workbench 能从 keyframe 跳到视频对应时间附近。

### P7.5：Workbench 记录卡片 + storyboard 详情页

- 首页或上下文库显示“记录片段”卡片。
- 详情页展示：摘要、时间线、文本、回放。
- 第一版只做 storyboard，不做剪辑器。

### P7.6：user mark / pause / resume / max duration

- 录制浮层支持“标记此刻”“暂停”“继续”“结束”。
- 超过 max duration 自动结束，写入诊断。
- scope lost 时暂停或降级，不悄悄改成全屏。

### P7.7：事件驱动关键帧

- 增加 scroll_stop、click_settle、title/URL change、provider_completed、OCR completed。
- 加 visual/text diff、keep/drop diagnostics。
- 使用 A/B/C/D 关键帧优先级，不做低 FPS 截图。
- trusted producer 不能只写 trigger ledger：accepted trigger 必须返回 `capture_instruction`，native/headless owner 按 `execute_after_monotonic_ms` 提交带 `ActiveCaptureBinding(candidate_id=...)` 的截图。
- scroll 必须在 producer 侧合并为一次停顿事件；backend 只对 terminal scroll stop 生成截图候选，中间 `began/changed/momentum` 只能作为 action-only trace。
- `debounced/dropped` candidate 不能长期占用 pending budget；producer decision 要反映实际 candidate status/drop reason。
- window/region scoped session 中，keyboard/scroll 必须带 producer-observed scope/focus 证明；不能由 backend 自动把缺失 scope 替换成 session scope 后触发截图。

### P7.8：Agent inspect recording_timeline + citation

- search card 支持 active capture，但只返回安全摘要。
- inspect 支持 `active_capture_summary`、`recording_timeline`、`visual_ocr_text`、`video_ref`。
- citation 支持 keyframe、text range、bbox、action summary step。

### P7.9：policy-before-index

- 所有 OCR/Web/a11y/demo 文本进入 index 前先走敏感 surface detection、redaction/suppression、safe text projection。
- 敏感窗口默认只显示“内容因策略隐藏”的粗卡。
- raw video、raw keyframe、raw DOM、raw a11y tree 继续默认锁定。

### P7.10：低敏 demonstration event summary

- 记录 click/scroll/hotkey/typing_pause/window_switch/user_mark。
- 快捷键/热键存 exact chord；普通输入只存 aggregate typing summary，不记录普通键盘文本或 raw keystrokes。
- action event 必须带 evidence link，不能只是坐标日志。
- producer event 和 producer/backend decision 单独落 ledger，用于解释为何触发/丢弃关键帧，并给 P7.11 提供可审查的 skill distillation 输入。
- low-level `key_down/key_up` 不进入公共 producer ingestion；真实键盘输入必须先在 producer 侧归类成 known hotkey/command，或聚合后的 `typing_pause`。
- producer metadata 采用敏感 key/fragment denylist，validation error 不得回显 raw input value。
- P7.11 projection 只能暴露 safe target、exact known shortcut、typing aggregate、action/result evidence keyframe ids；不能暴露 selector、a11y name、DOM/a11y/raw typed text。
- producer-driven keyframe 捕获成功后必须回写 producer decision、action evidence link 和 result observation，否则后续 skill draft 会缺证据链。

### P7.11：Skill distillation interface

- 新增 `SkillDistillationService`。
- 只输出 `WorkflowCandidate` / `SkillDraft`，不自动发布 skill。
- 用户必须确认步骤、输入参数、泛化范围，并经过 dry-run / 测试后才能发布。

## 最重要的取舍

WorkRecorder 不应该追求“记录一切”。screenpipe 更像长期个人活动记忆，WorkRecorder 更像用户主动标记的可信上下文系统。

所以 Active Context Capture 的原则是：

> 用户主动开始，用户明确结束；视频给人回看，关键帧和文本给 Agent；操作事件只做低敏 demo trace，后续经用户确认再沉淀成 skill/workflow。

如果要实现，我建议先做 `P7.1 + P7.2`，把 session/ledger 和截图 anchor keyframe 铺好；然后做 `P7.3 + P7.4 + P7.5` 的窗口记录 MVP，把视频回看、start/end keyframe、timeline manifest 和 Workbench storyboard 跑通。
