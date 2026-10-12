# WorkRecorder Linux AT-SPI 采集端

[English](README.md) | [简体中文](README.zh-CN.md)

[WorkRecorder 使用说明](../../README.zh-CN.md)

这是远端 Linux 的单桌面证据采集端。Mac 上的 WorkRecorder 负责录制远程桌面画面与本地输入，Linux 端提供 AT-SPI 树、焦点/选择等事件，以及真实鼠标点击对应的控件。

当前支持 **Linux X11/Xorg、Python 3.10+**。点击监听依赖 X RECORD；不支持 Wayland。AT-SPI 可见性取决于目标应用，树和点击定位都存在深度、数量或时间限制。

## 入口文件与运行位置

| 文件 | 运行位置 | 启动方式 |
| --- | --- | --- |
| [`service.py`](service.py) | 被录制的 Linux 桌面 | 在桌面终端运行 `python3 apps/linux_capture/service.py` |
| [`collectors/a11y_daemon.py`](collectors/a11y_daemon.py)、[`collectors/event_watch.py`](collectors/event_watch.py) | 同一个 Linux 桌面 | 由 `service.py` 自动启动，随目录一起保留 |
| [`scripts/start_linux_recording.py`](../../scripts/start_linux_recording.py) | Mac | Linux 服务就绪后，在 Mac 终端执行下方启动命令 |

以下命令均从各自机器上的 `Work2Skill/WorkRecorder/` 目录执行。启动顺序是 **Linux 服务 → Mac 启动器 → 开始录制**；录制和导出完成前，两端终端保持开启。

## 1. 在 Linux 桌面内启动采集服务

把本仓库放到 Linux 上，在被录制桌面的终端中运行，以桌面登录用户启动，不要以服务器 root 用户代替桌面用户。

Ubuntu/Debian 依赖示例：

```bash
sudo apt-get install python3 python3-gi gir1.2-atspi-2.0 python3-xlib xdotool x11-utils
# 使用 GNOME/GTK 时启用辅助功能；已启动的应用可能需要重启
gsettings set org.gnome.desktop.interface toolkit-accessibility true
# 如果需要录制 LibreOffice，可安装其 GTK 辅助功能桥接
sudo apt-get install libreoffice-gtk3
```

从 `WorkRecorder/` 运行：

```bash
python3 apps/linux_capture/service.py
```

服务继承当前桌面的 `DISPLAY`、`DBUS_SESSION_BUS_ADDRESS` 和 `XAUTHORITY`。如果通过 SSH 启动，应先正确设置目标桌面会话的环境，不能直接照抄另一台机器的用户 ID 或认证路径。

默认仅监听 Linux 本机 `127.0.0.1:7073`，内部树服务使用 `7070`。用 `--port` 和 `--tree-port` 可调整。Ctrl+C 会停止本次启动的采集进程。

每次启动创建独立的证据目录，默认为 `~/.local/share/workrecorder/linux/<run>/`：

- `raw-events.jsonl`：原始 AT-SPI 事件与点击解析记录。
- `events.jsonl`：统一序号的事件，附带最近可用的 `a11y_snapshot`。
- `trees.jsonl`：独立的树快照及采集起止时间。
- 采集进程日志。

默认每 2 秒采一份树，上限 6 层、400 个节点。可通过 `--tree-interval`、`--tree-depth` 和 `--tree-max-nodes` 调整。事件关联的是最近一次已完成的树采样，**不代表精确点击时刻的整棵树**；没有可用树时不附加快照。连续树序列保存在 Linux 本地，Mac 导出保留随事件返回的快照。现有导出格式中的 `dom_hit` / `dom_hits.jsonl` 是历史通用命中字段名，在此模式下承载 AT-SPI 控件信息，不表示进行了 DOM 采集。

## 2. 在 Mac 用命令启动 Linux 录制模式

先按 WorkRecorder README 安装依赖、构建 `dist/WorkRecorder.app`，退出已有录制 App，再从 `WorkRecorder/` 执行：

```bash
./.venv/bin/python scripts/start_linux_recording.py \
  --ssh linux-desktop
```

`linux-desktop` 是你自己的 SSH 别名或 `user@host`，必须能访问采集服务所在 Linux 桌面的 loopback。若桌面在虚拟机内，请让 SSH 别名连接到该虚拟机（可使用自己的 ProxyJump）；SSH 到物理宿主机并不自动等于连接到 guest。

- 默认通过 Linux 服务自动获取桌面分辨率（使用 `x11-utils` 中的 `xdpyinfo`）。`--width`、`--height` 为可选覆盖参数，需同时指定；检测失败时会提示修复或手动填写。录制期间保持分辨率不变，调整后重新启动 Mac 启动器。
- `--title-bar` 是 Mac 远程桌面窗口顶部非桌面区域的高度，单位为点，默认 28；无边框视图用 `0`。
- 用 `--app /path/to/WorkRecorder.app` 指定应用；`--remote-port` 指定远端服务端口。
- 启动器建立独立 SSH 转发和本地 daemon，使用动态端口、独立凭据和 `~/.workrecorder/linux/<host-id>/` 数据目录，避免复用 Mac 模式 daemon。
- 启动器会检查远端服务类型、健康状态和两端时钟偏差。两端时间应同步。
- 远程桌面连接由你已有的 VNC/远程桌面客户端负责；本启动器只建立证据通道。
- 打开远程桌面后按 `⌃⌥⌘R`，将录制区域对齐远程桌面内容，完成录制并导出，再退出 App。终端和 SSH 通道需在录制期间保持运行。

普通启动 WorkRecorder 默认 `macos` 模式，关闭远端 probe；命令启动设置 `WORKRECORDER_RECORDING_TARGET=linux`，关闭 Mac AX 和浏览器 provider，仅接收 Linux AT-SPI 证据。完整按键内容默认关闭。

## 接口（开发与调试参考）

正常录制时由程序自动调用以下接口，用户无需手动输入这些 URL 或填写坐标。表中的数字是请求示例，不是固定的录制配置。

| 接口 | 内容 |
| --- | --- |
| `/health` | `linux_atspi_v1` 标识、采集状态、服务时间、当前桌面像素宽高 `display` |
| `/events?n=100` 或 `/events?since_seq=42` | 事件流的轮询接口，最多保留最近 5,000 条用于传输 |
| `/clicks?n=100` | 点击及点击解析记录 |
| `/a11y?depth=6&max_nodes=400` | 按需 AT-SPI 树快照 |
| `/at_point?x=100&y=200` | 查询 Linux 桌面像素坐标 `(100, 200)` 处的可访问性控件 |

`/at_point` 用于把“点击某个位置”关联到具体控件，例如“保存”按钮。`x`、`y` 是 Linux 桌面坐标，单位为像素，原点位于左上角；示例 `x=100&y=200` 表示向右 100 像素、向下 200 像素。程序会将 Mac 录制区域中的点击位置换算为 Linux 桌面坐标后发起查询，获取该处控件可用的名称、角色和边界等信息。

服务本身不提供公网认证入口，只绑定 loopback，通过 SSH 访问。输出可能包含界面文本，按本机录制数据管理；不把实际录制日志或密钥提交进源码仓库。

## 来源与验证边界

`collectors/a11y_daemon.py` 整理自 MyPCBench 的 persist-introspection；`collectors/event_watch.py` 整理自 OSWorld 的通用 AT-SPI watcher，保留其应用级控件定位逻辑，未引入槽位 02 的特殊分支或候选实验版本。详见 [NOTICE](NOTICE.md) 和 [licenses](licenses/)。

自动化测试覆盖 HTTP 游标、证据快照传输、Mac probe 接入及两种模式隔离。完整的真实 Linux 桌面 → SSH → Mac 视频录制链路仍需在目标桌面环境做验收。
