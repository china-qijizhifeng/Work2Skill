# Agentic Skill Induction

[English](README.md) | [简体中文](README.zh-CN.md)

基于 [NexAU](https://github.com/nex-agi/NexAU) 的技能归纳示例，从任务指令和录制证据中生成可独立使用的 GUI 技能。Agent 自主选择工具，可在查看证据、编写草稿、回读和修改之间切换。`system_prompt.md` 定义运行边界，内置 `skill-creator` 定义技能编写规范。

## 放置到 NexAU/examples

需要 Python 3.12+、`uv`，以及 PATH 中的 `ffmpeg` 和 `ffprobe`。模型需要支持图像输入、结构化工具调用和 OpenAI 兼容的 Chat Completions 接口；根据服务商支持情况调整 `agent.yaml` 的模型参数。

NexAU 是外部依赖。离线检查不代表已验证特定模型的完整归纳效果。

```bash
git clone https://github.com/china-qijizhifeng/Work2Skill.git
git clone https://github.com/nex-agi/NexAU.git
cp -R Work2Skill/AgenticSkillInduction NexAU/examples/agentic_skill_induction
cd NexAU
uv sync
```

示例文件直接位于本目录。将整个目录复制到 `NexAU/examples/agentic_skill_induction/`；已有两个仓库时，只需执行复制步骤。目标目录名使用 `agentic_skill_induction`，Python 导入和 YAML 绑定使用 `examples.agentic_skill_induction`。以下命令均在 **NexAU 仓库根目录**执行。

视频工具安装示例：

```bash
# macOS
brew install ffmpeg
# Ubuntu/Debian
sudo apt-get install ffmpeg
```

## 配置模型

复制空白模板，然后填写自己的 API Key、模型名称和服务地址：

```bash
cp examples/agentic_skill_induction/.env.example \
   examples/agentic_skill_induction/.env
```

必需变量是 `LLM_API_KEY`、`LLM_MODEL`、`LLM_BASE_URL`。对应变量未设置时，也接受 `OPENAI_API_KEY`、`OPENAI_MODEL`、`OPENAI_BASE_URL`。已有环境变量优先于 env 文件。`--env-file` 指定文件，默认读取 NexAU 根目录的 `.env`。

默认最多 100 次迭代、模型单次输出上限 16,000 token。`--reasoning-effort` 支持 `low`、`medium`、`high`、`xhigh`，默认 `high`；`SKILL_INDUCTION_LLM_MAX_TOKENS` 可覆盖输出上限。启动器会清除 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY` 及其小写形式，模型服务需可直接访问。

## 准备输入

可输入包含 episode 的 benchmark run 目录，也可输入单个 episode 目录。WorkRecorder 导出示例：

```text
benchmark/normal/
├── run_manifest.json
└── episodes/<task-id>/
    ├── task.json
    ├── episode.json
    ├── trace/
    │   ├── actions.jsonl
    │   └── keylog.jsonl
    ├── evidence/
    └── video.mp4
```

实际文件取决于采集结果。`task.json` 应包含真实任务指令与任务输入。WorkRecorder 在未提供外部任务定义时可能只生成推断的 ID；归纳前需要补齐，不能把它当作完整任务定义。把需要的证据放在输入目录内，将凭据、评分细则、评测输出和参考答案放在该目录之外。

工具将输入目录表示为 `.`，生成目录表示为 `output/`。读取限制在这两个根目录，写入限制在输出根目录。输入和输出使用不同目录。每个进程处理一次提取，批量模式启动多个独立进程。

## 运行单次归纳

将 `/path/to/recording` 替换为实际录制导出路径：

```bash
uv run python examples/agentic_skill_induction/start.py \
  /path/to/recording/benchmark/normal \
  --env-file examples/agentic_skill_induction/.env \
  --output-dir generated_skills/agentic_skill_induction/recording-demo
```

不传 `--output-dir` 时，默认输出到 `generated_skills/agentic_skill_induction/<输入目录名>`。不同录制的输入目录若都叫 `normal`，应分别指定输出目录。

## 工具接口

| 工具 | 用途 |
| --- | --- |
| `list_directory`、`glob` | 在输入/输出根目录内查找文件 |
| `read_file` | 分页读取文本、JSON、JSONL、YAML、Markdown |
| `read_visual_evidence` | 一次查看 1–20 张有路径标记的有序图像 |
| `get_video_metadata` | 获取视频时长、尺寸、帧率、编码和大小 |
| `watch_video` | 按时间区间与间隔采样视频帧 |
| `extract_video_frames` | 请求指定毫秒时间点的视频帧 |
| `write_file` | 在输出根目录创建或完整覆盖文件 |
| `finalize_extraction` | 校验产物并原子写入归纳 manifest |

视频时间单位为**毫秒**，采样前必须先读取同一视频的元数据。`watch_video` 返回采样帧，没有 `with_annotation` 参数。靠近或超过视频结尾的抽帧请求可能向前调整，返回标签会说明实际采样时间。

```python
get_video_metadata(file_path="episodes/task-demo/video.mp4")
watch_video(
    file_path="episodes/task-demo/video.mp4",
    start_ms=16000, end_ms=18000, interval_ms=1000,
)
```

上面是 Agent 的工具调用示例，不是终端命令。NexAU 另提供 `LoadSkill`，用于加载内置编写规范。

## 完成校验与输出

`finalize_extraction` 是唯一成功结束入口。它检查：已读取 `task.json`、生成技能具有合法必要结构、最终 `SKILL.md` 通过 `write_file` 创建且在最后一次写入后由 `read_file` 回读、视频元数据读取先于采样。校验失败会返回错误供 Agent 修复重试。这些检查不等于技能已通过实际执行验证。

每个输出目录包含：

- `<skill-name>/SKILL.md`：可复用技能及其支持资源。
- `extraction-manifest.json`：技能哈希、查看过的证据、校验结果和来源信息。
- `run-metadata.json`：示例代码、配置与任务的哈希及模型配置信息。
- `run-events.jsonl`：模型、工具、文本、用量和生命周期事件。
- `run-summary.json`：状态、耗时、工具调用和 token 用量。

运行时文件由程序管理，Agent 不应自行写入。没有成功 finalize 的普通文本回复不会被视为完成。

## 批量归纳

递归查找包含 `run_manifest.json` 的目录：

```bash
uv run python examples/agentic_skill_induction/batch_start.py \
  /path/to/recordings \
  --env-file examples/agentic_skill_induction/.env \
  --jobs 2
```

默认输出父目录为 `generated_skills/agentic_skill_induction/`，子目录名由 run 相对路径和 `-image-prompt` 后缀组成，可用 `--output-root`、`--output-suffix` 调整。仅当 summary、manifest 来源信息和技能哈希匹配时跳过已完成任务。`--rerun-completed` 强制重新运行；`--nested-only`、`--nested-prefix` 筛选嵌套目录。

## 可选看板

```bash
uv run --with streamlit streamlit run \
  examples/agentic_skill_induction/dashboard.py \
  --server.address 127.0.0.1
```

可用 `NEXAU_SKILL_RUNS_ROOT` 指定其他输出目录。看板展示状态、工具活动、用量、事件和生成文件。

## 本地检查与发布

```bash
uv run python -m unittest discover \
  -s examples/agentic_skill_induction/tests -v
```

测试只使用临时合成数据，不调用模型 API；视频测试需要 `ffmpeg` 和 `ffprobe`。

发布源码已去除个人部署路径、Python 缓存、凭据与运行产物。填写后的 `.env` 保留在本地。Agent 查看过的证据会发送给所配置的模型服务；运行日志可能含任务文本、路径和模型/工具输出，不会自动匿名化，分享前需单独检查。
