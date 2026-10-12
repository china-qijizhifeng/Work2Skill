# Work2Skill

[![Website](https://img.shields.io/badge/Website-Work2Skill-2457B8)](https://china-qijizhifeng.github.io/Work2Skill/)
[![arXiv](https://img.shields.io/badge/arXiv-2610.12984-b31b1b.svg)](https://arxiv.org/abs/2610.12984)
[![Hugging Face: WorkDemo-350](https://img.shields.io/badge/Hugging%20Face-WorkDemo--350-FFD21E?logo=huggingface&logoColor=FFD21E)](https://huggingface.co/datasets/yuqi777/WorkDemo-350)

[English](README.md) | **简体中文**

**Work2Skill 通过操作录制、多模态证据分析与技能归纳，将人类 GUI 操作演示转化为可复用的 Agent 技能。**

访问项目主页：[Work2Skill](https://china-qijizhifeng.github.io/Work2Skill/)，了解研究概览、浏览数据集结构，并交互查看评测结果。

论文：[Work2Skill: Capturing Human GUI Experience for Reusable Agent Skill Induction](https://arxiv.org/abs/2610.12984)。

人类操作演示数据集请访问 Hugging Face：[WorkDemo-350](https://huggingface.co/datasets/yuqi777/WorkDemo-350)。

![Work2Skill 流程总览：人类 GUI 演示、多模态录制、动作关联证据构建、Agent 技能归纳与执行评测](assets/work2skill-overview.png)

## 仓库结构

| 目录 | 定位 | 当前状态 |
| --- | --- | --- |
| [WorkRecorder](WorkRecorder/README.zh-CN.md) | macOS 原生录制与远程 Linux 操作证据采集 | 已包含 macOS 录制端与 Linux X11 AT-SPI 服务，跨端实机链路待验收 |
| [DownstreamTasks](DownstreamTasks/README.zh-CN.md) | 扰动任务定义、评分条目与演示任务 ID | 已提供 64 个 MyPCBench 扰动任务及评分定义、286 个含演示的 OSWorld 任务 ID；运行与评测实现待接入 |
| [AgenticSkillInduction](AgenticSkillInduction/README.zh-CN.md) | 基于 NexAU 的技能归纳 example | 示例源码与 NexAU 安装运行说明已提供 |

```text
Work2Skill/
├── WorkRecorder/             # 录制经验采集基础设施
├── DownstreamTasks/          # 带抖动或扰动的下游任务
└── AgenticSkillInduction/    # NexAU 上的技能归纳示例
```

预期流程：**录制人类演示 → 导出任务证据 → 归纳可复用技能 → 在下游任务上评测**。当前已提供录制、技能归纳组件及任务定义，评测链路仍待接入。

## 使用入口

```bash
git clone https://github.com/china-qijizhifeng/Work2Skill.git
cd Work2Skill
```

1. **查看已有演示：** 访问 [Hugging Face 上的 WorkDemo-350](https://huggingface.co/datasets/yuqi777/WorkDemo-350)。录制数据独立托管于 Hugging Face。
2. **录制自己的操作：** 按照 [WorkRecorder 说明](WorkRecorder/README.zh-CN.md)配置环境，在 `WorkRecorder/` 目录执行安装、构建和测试命令。Linux 采集需要 X11/Xorg 桌面，并配合 Mac 录制应用使用。
3. **归纳技能：** 按照 [AgenticSkillInduction 说明](AgenticSkillInduction/README.zh-CN.md)，将示例安装到单独的 NexAU 仓库，配置支持图像输入的模型端点并提供任务证据。此流程需要 Python 3.12+、`uv` 和 `ffmpeg`/`ffprobe`；提取前请补齐 `task.json` 中的真实任务指令与输入。
4. **准备下游评测：** 在对应 benchmark 环境中使用[任务定义与评分条目](DownstreamTasks/README.zh-CN.md)，并接入任务执行器与评测器以产出结果。

## 任务与发布范围

原始任务来自 [MyPCBench Bounded Action](https://github.com/ljang0/MyPCBench/tree/main/tasks/final) 和 [OSWorld-Verified](https://xlang.ai/blog/osworld-verified)。本仓库包含：

- [`tasks-jitter.json`](DownstreamTasks/tasks-jitter.json)：64 个 MyPCBench 扰动任务（原始 `f` → 扰动 `j`），含 366 条带权评分条目。
- [`selected_task_ids.json`](DownstreamTasks/selected_task_ids.json)：286 个唯一的 OSWorld 任务 ID，用于索引已有录制演示的任务。

Benchmark 环境初始化、任务扰动生成器、任务执行器、评测器和端到端评测结果尚未包含。技能归纳示例已提供离线测试；具体模型的提取质量及 macOS/Linux 实机录制链路仍需端到端验证。

## 许可证

Work2Skill 自有代码采用 [MIT 许可证](LICENSE)。第三方组件保留原有许可证及声明，详见[第三方声明](THIRD_PARTY_NOTICES.md)。外部托管的数据集遵循其各自发布的使用条款。

## 参与贡献

欢迎通过 [Issues](https://github.com/china-qijizhifeng/Work2Skill/issues) 和 Pull Requests 提交问题、改进文档或反馈复现情况。报告问题时请注明涉及的模块、操作系统和复现步骤。
