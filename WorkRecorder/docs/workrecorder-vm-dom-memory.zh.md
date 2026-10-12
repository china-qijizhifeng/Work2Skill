# WorkRecorder VM DOM Hit 记忆

这份记录专门保存这次 WorkRecorder active capture 接入 VM Firefox DOM hit
接口的经验。重点是怎么启动、怎么判断链路健康、常见坏象、以及几次真实
导出的结论。

## 目标

WorkRecorder 现在不要再导出 VM 浏览器对应的 macOS host a11y 树。对于本地
可信的鼠标点击，优先走 guest 里的 event-watch HTTP 接口：

```text
WorkRecorder click -> Mac 本地 127.0.0.1:7072/events
  -> SSH 隧道 -> guest event-watch -> 最近的 focus/click 事件及 DOM 元素
```

旧的主动按点查询接口仍然保留，主要用于回退和排查：

```text
WorkRecorder click -> Mac 本地 127.0.0.1:7071/dom_at_point
  -> SSH 隧道 -> guest dom-daemon -> Firefox 当前 tab 的 x/y DOM
```

导出后应该在关键帧目录里看到：

- `vm_a11y.json`
- `vm_a11y.jsonl`

注意：文件名还叫 `vm_a11y` 是历史包袱，但里面现在放的是
VM 侧 DOM/event hit 信息，不是 host a11y。

## 启动方式

使用：

```bash
bash scripts/start_workrecorder_vm_a11y.sh
```

这个脚本应该做这些事：

- 确保 Mac 能通过 host 端口 `2222` SSH 进 guest。
- 建好或重建 `7071 -> guest:7071` 和 `7072 -> guest:7072` 的本地隧道。
- 注入 WorkRecorder daemon 需要的环境变量：
  - `WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_ENABLED=true`
  - `WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_SOURCE=event_watch`
  - `WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_URL=http://127.0.0.1:7072`
  - `WORKRECORDER_ACTIVE_CAPTURE_VM_A11Y_PROBE_EVENTS_PATH=/events`
  - VM 屏幕尺寸和 titlebar 高度，用于坐标换算。
- 先由脚本启动 daemon，让 daemon 继承这些环境变量。
- 再用 `WORKRECORDER_EXTERNAL_DAEMON=1` 启动 WorkRecorder app，让 app 只复用这个
  脚本管理的 daemon，不要再自己启动、停止、替换 daemon。
- app 启动后再复查一次 daemon 健康和 VM a11y 配置，防止 app-side daemon
  supervisor 把一个本来健康的外部 daemon 停掉。

如果重建了 VM 或 overlay，Mac 这边的 SSH 隧道可能会断。第一反应应该是重跑
启动脚本。

## 录制前必须检查

在 Mac 上跑：

```bash
curl -i 'http://127.0.0.1:7072/health'
curl -i 'http://127.0.0.1:7072/events?n=20'
```

正常应该是：

- HTTP 200。
- `/health` 返回 ok/count 之类的状态。
- `/events` 返回最近事件，且每条事件有单调递增的 `seq`。
- 在 VM 里点击后，最新事件应该能描述被点击或获得焦点的控件。

旧的 DOM-at-point 排查命令是：

```bash
curl -i 'http://127.0.0.1:7071/dom_at_point?x=451&y=434'
```

正常应该是：

- HTTP 200。
- JSON 里有 `hit`、`path`、`cx`、`cy`、`url`、`title`。
- `url` 应该对应 Firefox 当前前台 tab。

典型坏象：

- `Connection refused`
  - Mac 本地 7071/7072 没监听，通常是 SSH 隧道断了。

- `404 {"error": "use /a11y or /health"}`
  - 连到了旧服务或旧隧道目标，不是新的 DOM hit 服务。

- `400 {"error": "need x & y"}`
  - 旧版 daemon 对坐标格式更严格；当前 WorkRecorder 会把 x/y round 成整数。

- `500 {"error": "[Errno 111] Connection refused"}`
  - guest 的 dom-daemon 在，但它连不上 Firefox/Marionette。

- `vm_event_watch_no_event`
  - 7072 能访问，但 `/events` 在轮询次数内没有吐出新事件。

还要确认 WorkRecorder daemon 自己是健康的：

```bash
curl -i 'http://127.0.0.1:8765/health'
```

现在启动脚本会自动做更强的检查：

- app 启动前 `/health` 必须健康。
- app 启动后 `/health` 仍然必须健康。
- `/v1/settings/vm-a11y-probe` 必须是 `source=event_watch`。
- 里面的 URL 必须匹配当前选中的 event-watch 本地端口，例如
  `http://127.0.0.1:7072` 或 fallback `http://127.0.0.1:17072`。

## 导出后怎么判断健康

先看有没有 sidecar：

```bash
find <export_dir> -maxdepth 2 -name 'vm_a11y.json' | sort
```

健康导出应该满足：

- `recording.json` 里的 `vm_a11y_files` 非空。
- `trajectory.json` 里部分 action step 有 `dom_hit` 和 `dom_hit_label`。
- `summary.md` 里出现类似：
  - `点击 listitem ...`
  - `点击 button ...`
  - `点击 div ...`
- 如果录制里有打字，`keylog.jsonl` 应该有 press/release 记录。

不健康导出：

- `vm_a11y_files: []` 且所有关键帧目录都没有 `vm_a11y.json`
  - 说明 capture-time DOM probe 记录没有进 exporter 能读到的存储。
  - 优先查 7072 隧道和 daemon 环境变量。

- click actions 有，但 DOM label 全没了
  - 可能是 VM DOM/event probe 没启用、没配置、或者录制时 7072 断了。

- 出现 `source: export_live_dom_probe`
  - 这是危险的历史导出补救方式，会在导出时采当前 Firefox 页面，容易把旧截图配上当前页面 DOM。
  - 当前默认已关闭。

## 已知好/坏样本

好样本：

`/Users/example/Desktop/WorkRecorder_dev/20260627T053040_546_acs_7WyD8-c5qtUGXAjh`

- DOM probe 工作正常。
- 5 条 probe 记录，4 条命中，0 个 error。
- 一个 `hit:null` 的记录里 `cy < 0`，说明点击在网页视口上方。

好样本：

`/Users/example/Desktop/WorkRecorder_dev/20260627T054339_359_acs_FkMrFU5vquEE6Wgx`

- 重建 7071 隧道后 DOM probe 恢复正常。
- `recording.json` 里有 10 个 VM DOM sidecar 文件条目。
- 5 个 action step 有 `dom_hit`。
- `keylog.jsonl` 正确记录了 `apple` 的按下/松开。

坏样本：

`/Users/example/Desktop/WorkRecorder_dev/20260627T053716_996_acs_f2w4d_eOSFfXHPsY`

- `vm_a11y_files: []`。
- 没有任何 `vm_a11y.json` sidecar。
- 排查时 `curl http://127.0.0.1:7071/dom_at_point?...` 是 connection refused。
- `lsof` 也看不到本地 7071 listener。
- 结论：那次录制时 DOM 隧道或服务不可用，不是 exporter label 挂载问题。

2026-06-29 daemon 生命周期问题导致的坏样本：

`/Users/example/Desktop/WorkRecorder_dev/20260629T070012_777_acs_epNeCGSRkHaUAW2I`

`/Users/example/Desktop/WorkRecorder_dev/20260629T070501_875_acs_FSd_dNWbeaIJ31TQ`

- `keylog.jsonl` 和 click actions 都有，但 `recording.json` 里是
  `vm_a11y_files: []`。
- `/tmp/workrecorder-daemon.log` 在录制中间出现 `uvicorn.error Shutting down`。
- app 日志随后出现 `failed to submit producer event` / `无法连接服务器`。
- 根因不是 7072 不通，而是 daemon 生命周期冲突：启动脚本已经用正确 env
  启了 daemon，但 macOS app 自己的 daemon supervisor 仍可能把这个外部 daemon
  当成旧 daemon 或密钥不匹配 daemon 停掉/替换。VM a11y records 存在 daemon
  内存里，daemon 一停，导出时就没有 records 了。
- 修复：给 app 加 `WORKRECORDER_EXTERNAL_DAEMON=1` 模式。这个模式下 app 只复用
  脚本管理的 daemon，不再启动、停止、替换 daemon。启动脚本现在是：
  先启动 daemon -> 校验 VM a11y 配置 -> 启动 app -> 再次校验 daemon/config。

## 怎么理解 `hit:null`

`hit:null` 不一定是 bug。

如果 daemon 返回的网页坐标里 `cy < 0`，说明点击点在 Firefox 网页内容区域上方，
例如：

- tab bar
- 地址栏
- bookmarks bar
- Firefox titlebar
- VM/window chrome

因为我们现在刻意不导出 host a11y，这些区域没有网页 DOM 元素，所以返回 null
是合理的。

点在窗口边缘、VM 外面、或非网页区域，也可能合理地没有 DOM hit。

## Marionette 限制

当前设计里 Firefox Marionette 基本只能稳定给一个客户端使用。

guest `dom-daemon` 会占用 Marionette session 来做自动 DOM hit 解析。不要同时
再跑另一个直接连 Marionette 的自动化脚本，否则可能抢 session、切 tab、或者
把前台上下文搞乱。

如果以后确实要“自动 DOM hit”和“另一个 Marionette 自动化”并存，需要改方案：

- 让 dom-daemon 兼做 Marionette proxy；
- 或改成 WebDriver BiDi 多会话方案；
- 或明确切换所有权。

## Proxy 坑

调用 guest/local control API 的脚本如果继承了 proxy 环境变量，localhost 也可能
被代理劫持。

修复方式：

```bash
unset http_proxy https_proxy ALL_PROXY all_proxy HTTP_PROXY HTTPS_PROXY
```

或：

```bash
export NO_PROXY=127.0.0.1,localhost
```

见过的坏象是：访问 `127.0.0.1:5000/execute` 被发到 `127.0.0.1:7897` 代理，
然后返回 502。

## 当前代码预期

`packages/active_capture/application/vm_a11y_probe.py`

- 根据配置可消费 `event_watch` 的 `/events`，也可回退到 `dom_at_point`。
- 启动脚本现在默认使用本地 7072 的 `event_watch`。
- event-watch 首次用 `n=20`，之后用 `since_seq=<last>` 增量消费。
- event-watch probe 会串行执行，因为 `seq` 消费是有状态的。
- 7071 `dom_at_point` 仍然保留给回退和排查。
- 记录 `hit_dom`、`sample`、`alignment` 和 error。
- 默认不做 periodic polling。

`packages/active_capture/application/export/recording_export.py`

- 把 DOM hit 挂到 `actions.json`、`trajectory.json`、`summary.md`。
- 默认不启用 live export fallback。
- 过滤没有 media time 的 keyframe summary 行，避免 `summary.md` 出现
  `--:--.---`。
- sidecar metadata 使用 timeline 投影后的 media time。

`apps/macos_capture/.../ActiveCaptureInputEventProducer.swift`

- 输入事件提交遇到 daemon 暂时连不上时会 retry。
- event tap 是 listen-only，不应该吞 TigerVNC 输入。

`apps/macos_capture/.../WorkbenchRuntime.swift`

- `DaemonSupervisor` 支持 `WORKRECORDER_EXTERNAL_DAEMON=1`。
- 在 external-daemon 模式下，app 不拥有 daemon 生命周期，只检查健康并复用
  已经运行的 daemon。
- `scripts/start_workrecorder_vm_a11y.sh` 必须使用这个模式，因为 VM a11y 相关 env
  和严格启动检查都由脚本负责。

`scripts/start_workrecorder_vm_a11y.sh`

- 先用 Python `subprocess.Popen(..., start_new_session=True)` 启动独立 daemon。
- 给 app 导出 `WORKRECORDER_EXTERNAL_DAEMON=1`。
- 录制前如果 daemon health 或 `vm-a11y-probe` 配置不对，直接失败。
- app 启动后会再校验一次 daemon/config，防止 app 侧 daemon 生命周期回归。

## 常用测试

```bash
uv run pytest tests/unit/test_recording_export.py tests/unit/test_vm_a11y_probe.py
```

最近一次相关测试结果：

```text
32 passed
```

Swift app target 曾用下面命令验证过：

```bash
swift build
```

本机 `swift test` 可能因为当前 toolchain 没有 Swift `Testing` module 而失败；
这不等于 app target 构建失败。
