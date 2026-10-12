# WorkRecorder

[English](README.md) | **简体中文** | [项目总览](../README.zh-CN.md)

**面向 macOS 和 Linux 的录制经验采集基础设施。**

WorkRecorder 记录一段完整的人类操作过程，将视频、操作事件、关键帧及可用的系统和网页证据组织到录制会话中，用于回看、导出、构建操作证据数据集和后续技能归纳。

## 录制流程

```text
开始录制 → 选择录制区域 → 确认开始 → 执行工作操作
    → 采集视频、操作事件与关键帧证据
    → 完成录制 → 在录制中心回看 → 导出到文件夹
```

当前用户入口是“区域录制”，默认快捷键为 **⌃⌥⌘R（Control + Option + Command + R）**，也可以从菜单栏选择“开始录制”。框选定义的是整个录制会话的工作区域。录制期间再次使用入口会唤起录制控制。

录制过程中生成关键帧图像，作为与操作时间线关联的证据。

## 采集内容

| 内容 | 用途与边界 |
| --- | --- |
| 录制视频 | 保存工作区域的操作过程，支持回看。 |
| 操作事件 | 记录鼠标、键盘等操作及时间信息；完整按键内容默认关闭。 |
| 关键帧 | 在录制过程中采集画面，并与操作和时间线关联。 |
| macOS AX Tree | 原生 Accessibility provider 采集与录制区域关联的 UI 层级、文本和位置。需要辅助功能权限，结果受应用暴露信息和遍历上限影响。 |
| 网页证据 | 浏览器 provider 可采 URL、标题、DOM、网页文本及定位信息；实际可用性取决于页面、插件连接和采集配置。 |
| 来源与诊断 | 关联应用、窗口、采集状态和证据来源，支持复盘与排查。 |

macOS AX 快照按采集范围过滤，文本经过脱敏；当前遍历限制为 16 层、1,600 个节点、每种子节点属性 200 个元素。不能保证每次操作都有完整 AX Tree。原始证据的存储、Agent 可见内容与导出内容也有不同边界。

## 平台范围

- **macOS**：当前目录包含原生录制 App、本地 daemon、浏览器 provider 和 AX 采集实现。
- **Linux**：已加入 [apps/linux_capture](apps/linux_capture/README.zh-CN.md) 单桌面 AT-SPI 服务，支持 X11/Xorg。Mac 负责录制远程桌面画面，Linux 提供树和操作证据。

## 两种录制模式

- **普通启动 → 录 Mac**：采本机操作和 macOS AX，关闭远端 probe，历史保存的启用设置也不会开启远端采集。
- **命令启动 → 录 Linux**：先在目标桌面启动 [Linux AT-SPI 服务](apps/linux_capture/README.zh-CN.md)，再执行 `./.venv/bin/python scripts/start_linux_recording.py --ssh linux-desktop`。使用独立 daemon 和数据目录，关闭 Mac AX 与浏览器 DOM 采集。

切换模式前先完成录制、导出并退出 App。旧外部启动脚本需要增加 `WORKRECORDER_RECORDING_TARGET=linux`；AT-SPI-only 流程请使用这里的新启动器。

### 录 Linux 时，分别在哪台机器运行？

| 运行位置 | 入口文件 | 用途 |
| --- | --- | --- |
| 被录制的 Linux 桌面 | [`apps/linux_capture/service.py`](apps/linux_capture/service.py) | 启动 AT-SPI 树、事件和点击控件采集 |
| Mac | [`scripts/start_linux_recording.py`](scripts/start_linux_recording.py) | 连接 Linux 采集服务，并启动 WorkRecorder 的 Linux 录制模式 |

**先在 Linux 上运行**：将仓库克隆或复制到 Linux，按 [Linux 安装说明](apps/linux_capture/README.zh-CN.md) 安装依赖，然后在被录制桌面的终端中执行：

```bash
cd /path/to/Work2Skill/WorkRecorder
python3 apps/linux_capture/service.py
```

`/path/to/Work2Skill` 替换为该机器上的实际仓库路径。使用 Linux 桌面的登录用户运行，并保持终端开启。`service.py` 会自动启动同目录 `collectors/` 下的两个采集程序；保留整个 `apps/linux_capture/` 目录即可，无需逐个启动。

**再在 Mac 上运行**：完成下方 App 构建后，退出已有 App，在 Mac 终端中执行：

```bash
cd /path/to/Work2Skill/WorkRecorder
./.venv/bin/python scripts/start_linux_recording.py \
  --ssh linux-desktop
```

将 `linux-desktop` 换成连接到被录制 Linux 桌面的 SSH 别名或 `user@host`。启动器会自动读取 Linux 桌面分辨率；需要手动指定时，同时传入 `--width` 和 `--height`。打开远程桌面客户端，按 `⌃⌥⌘R` 选择远程桌面区域开始录制。两端终端保持运行，直到录制和导出完成。详细参数见 [Linux 采集说明](apps/linux_capture/README.zh-CN.md)。

## 快速开始

包名、daemon、Swift 模块、脚本及配置均统一使用 WorkRecorder。以下命令在总仓库的 `WorkRecorder/` 目录内执行。

### 构建并启动 macOS App

```bash
git clone https://github.com/china-qijizhifeng/Work2Skill.git
cd Work2Skill/WorkRecorder
uv sync --extra dev
./.venv/bin/python -m scripts.repair_uv_editable_install
npm --prefix apps/browser_extension install
./.venv/bin/python scripts/package_workrecorder_app.py --dev --verify
open dist/WorkRecorder.app
```

打开 App 后：

1. 按权限引导授权屏幕录制、辅助功能，以及操作监听所需的输入监控权限。
2. 需要网页证据时，构建并在 Chrome/Edge 的扩展管理页加载 `apps/browser_extension`，确认 provider 连接正常。
3. 按 `⌃⌥⌘R`，或从菜单栏选择“开始录制”。
4. 框选录制区域，确认后开始执行工作操作。
5. 通过录制控制暂停、继续或完成录制。
6. 打开“录制中心”，回看视频和操作时间线，并按需“导出到文件夹”。

向其他人分发时生成独立安装包：

```bash
./.venv/bin/python scripts/package_workrecorder_distribution.py --dev --verify --archive both
```

### 开发环境

```bash
# Run from WorkRecorder/
uv sync --extra dev
./.venv/bin/python -m scripts.repair_uv_editable_install
npm --prefix apps/browser_extension install
npm --prefix apps/browser_extension run build
./.venv/bin/workrecorder-daemon
```

另开终端启动原生 App：

```bash
cd apps/macos_capture
swift run WorkRecorderCapture
```

在 `WorkRecorder/` 目录检查服务和代码：

```bash
./.venv/bin/workrecorder daemon health --json
./.venv/bin/python -m scripts.quality_gate
```

已有工作区迁移到当前目录结构后，请在 `WorkRecorder/` 内重新执行 `uv sync --extra dev`，创建对应的虚拟环境。

### 可选：完整按键记录

完整按键记录默认关闭。启用后会记录每个 `key_down` / `key_up` 的物理键码、字符、修饰键和时间，可能包含密码等敏感文本。启动 App 前可设置：

```bash
defaults write app.workrecorder.local WorkRecorder.ActiveCapture.RecordFullKeystrokes -bool true
```

设置为 `false` 可关闭；也支持启动进程时设置 `WORKRECORDER_ACTIVE_CAPTURE_FULL_KEYSTROKES=1`，设为 `0` 关闭。

## 回看与导出

点击“导出到文件夹”并选择目标目录后，会导出一份 `normal` 录制并自动转换为 benchmark，无需运行额外脚本。原始文件位于 `<目标目录>/<录制备注>/video/`，转换结果位于同级 `benchmark/`，成功后自动在 Finder 中打开。转换需要 `uv`、`ffmpeg`（含 `ffprobe`）；Pillow 随项目依赖安装。没有外部任务元数据时生成基础任务信息。若转换失败，保留原始导出并显示错误。

录制中心用于查看录制会话，回看视频、操作与关键帧。导出器将录制整理为可浏览的目录；文件随实际采集结果而变化：

```text
<recording>/
  recording.json          # Session metadata and file index
  trajectory.json         # Ordered keyframe and action timeline
  summary.md              # Operation summary
  dom_hits.jsonl          # Available action-aligned DOM hits
  video.mp4 | video/      # Video, when available
  0000_<timestamp>/       # Keyframe evidence, when available
    screenshot.png
    actions.json
    meta.json
    ...
```

OCR、虚拟机可访问性等补充文件只在存在相应证据时生成。默认本地导出会省略部分原始 AX 和网页证据，不应将文件夹导出理解为完整原始证据库的副本。

导出结果可衔接 [AgenticSkillInduction](../AgenticSkillInduction/README.zh-CN.md) 和 [DownstreamTasks](../DownstreamTasks/README.zh-CN.md)。AgenticSkillInduction 已提供 NexAU 示例，DownstreamTasks 已提供扰动任务及评分定义；人类操作演示数据集见 [Hugging Face 上的 WorkDemo-350](https://huggingface.co/datasets/yuqi777/WorkDemo-350)。

## 代码与文档

| 目录 | 职责 |
| --- | --- |
| `apps/macos_capture/` | 原生录制入口、控制、回看和 macOS AX provider |
| `apps/linux_capture/` | Linux AT-SPI 树、事件、点击命中及本地服务 |
| `apps/browser_extension/` | Chrome/Edge 网页证据 provider |
| `services/context_daemon/` | 本地服务与采集编排 |
| `packages/active_capture/` | 录制会话、操作、关键帧、时间线及导出 |
| `packages/capture/` | 底层证据采集与持久化 |
| `packages/providers/` | Provider 接入与路由 |
| `packages/storage/` | 本地 ledger 与 artifact vault |
| `apps/cli/`、`apps/skill/` | 已有上下文检索和 Agent 接口 |

参见[文档总览](docs/README.zh-CN.md)和 [macOS 开发说明](apps/macos_capture/README.md)。早期上下文事件、截图入口相关文档保留为架构参考；当前产品入口以本 README 描述的录制流程为准。

## 已有安装的升级

请一起重新构建 App 和浏览器插件，并通过 `uv sync --extra dev` 更新开发环境，再使用该环境执行 `python -m scripts.repair_uv_editable_install`。daemon 命令为 `workrecorder-daemon`，环境变量前缀为 `WORKRECORDER_`，新安装默认使用 `.workrecorder` 数据目录。协议标识也已同步改名，客户端与 daemon 应成套更新。

CLI 命令统一为 `workrecorder`，Agent skill 包装脚本为 `scripts/workrecorder-cli`。重新构建并加载浏览器插件，再一起重启 App 和 daemon，以使用 `workrecorder-token.` 认证协议。已有本地凭据会继续复用，新生成的凭据使用 `workrecorder_` 前缀。

已有录制目录不会自动移动或删除。如需继续使用原 App 数据目录，启动前设置 `WORKRECORDER_APP_DATA_ROOT`，并通过 `WORKRECORDER_DATABASE_PATH` 明确指定原数据库文件；独立启动 daemon 时，还需通过 `WORKRECORDER_ARTIFACT_STAGING_DIR` 和 `WORKRECORDER_ARTIFACT_VAULT_DIR` 指向原目录。升级前备份数据库、vault、staging 和本地凭据文件，并保持它们配套使用；App 偏好设置按新配置键重新设置。升级过程中不要让两个 daemon 同时访问同一数据库。
