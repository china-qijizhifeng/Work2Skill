# Downstream Tasks

[English](README.md) | [简体中文](README.zh-CN.md) · [项目总览](../README.zh-CN.md)

本目录提供 **64 个 MyPCBench Bounded Action 扰动任务**及 **366 条带权重的评分条目**，以及 **286 个已有人工录制演示的 OSWorld-Verified 任务 ID**。

## 原始任务来源与发布文件

原始任务请参见 **MyPCBench Bounded Action** 和 **OSWorld-Verified**：

| Benchmark | 原始任务来源 | 本目录文件 |
| --- | --- | --- |
| MyPCBench Bounded Action | [MyPCBench 任务定义](https://github.com/ljang0/MyPCBench/tree/main/tasks/final)；通过 [`task_types.json`](https://github.com/ljang0/MyPCBench/blob/main/tasks/final/task_types.json) 中的 `bounded_action` 筛选 | [`tasks-jitter.json`](tasks-jitter.json)：64 个扰动后的 `j` 任务，各自对应一个原始 `f` 任务 |
| OSWorld-Verified | [OSWorld 任务定义](https://github.com/xlang-ai/OSWorld/tree/main/evaluation_examples/examples)；版本说明见 [OSWorld-Verified 介绍](https://xlang.ai/blog/osworld-verified) | [`selected_task_ids.json`](selected_task_ids.json)：286 个已有人工录制演示的原始任务 ID |

`selected_task_ids.json` 是包含 286 个唯一 UUID 字符串的 JSON 数组。每个 ID 对应上游的 `evaluation_examples/examples/<application>/<task_id>.json`。它用于索引已有录制演示的任务，录制数据见 [Hugging Face 上的 WorkDemo-350](https://huggingface.co/datasets/yuqi777/WorkDemo-350)。本目录提供任务 ID 清单。

## MyPCBench 任务扰动

这里的“抖动/扰动”指任务指令层面的变化，包括目标对象、数量、参数、选择规则、输出要求和流程约束。例如更换操作持仓及再投资目标、调整止损比例，或指定特定航线、文档和保存结果。文件描述的是任务变体，不是鼠标随机抖动或界面视觉扰动的实现。

## 文件内容

`tasks-jitter.json` 为 UTF-8 编码的 JSON 数组，每项包含：

| 字段 | 含义 |
| --- | --- |
| `id` | 唯一任务标识，如 `hard_app-j003` |
| `app` | 应用标识；跨应用任务使用 `multi_app` |
| `instruction` | 提供给执行 Agent 的任务指令 |
| `apps_involved` | 任务涉及的应用名称 |
| `category` | 任务类别；分类统计以此字段为准 |
| `difficulty` | 难度：`easy`、`medium`、`hard` |
| `grading.type` | 本次发布均为 `llm_judge` |
| `grading.rubrics` | 评分条目，每条含 `criterion`、`type`、`weight` |
| `grading.rubric_rule` | 可选额外评分规则，目前一项任务包含此字段 |

**对于 MyPCBench，`f` 表示原始任务，`j` 表示对应的扰动任务。** 两者保留相同前缀与编号，例如 `hard_app-f003 → hard_app-j003`。64 个原始任务均属于上游的 `bounded_action` 子集；原始 `f` 任务定义见上方 MyPCBench 链接。OSWorld 任务保留原始 UUID。

下表的 `category` 标签沿用所提供的任务文件，与上游的行为类型 `bounded_action` 属于不同分类。ID 前缀也不一定等于当前类别：有 32 项的前缀与 `category` 不同。

## 任务分布

| 类别 | 数量 |
| --- | ---: |
| `situated_action` | 48 |
| `long_horizon` | 13 |
| `cua_only` | 2 |
| `hard_app` | 1 |
| **合计** | **64** |

难度分布为 **48 hard、15 medium、1 easy**。`app` 字段共 19 种取值，其中包括 `multi_app`；26 项标记为跨应用任务。场景覆盖表格与文档、文件、邮件/聊天、项目管理、购物、旅行及模拟金融应用。

## 读取与使用

在本目录运行：

```python
import json
from pathlib import Path

tasks = json.loads(Path("tasks-jitter.json").read_text(encoding="utf-8"))
task = next(item for item in tasks if item["id"] == "hard_app-j003")

# 任务字段交给执行 Agent；评分配置留给 evaluator。
agent_task = {key: value for key, value in task.items() if key != "grading"}
evaluator_config = task["grading"]
```

任务需要在对应 benchmark 应用状态中执行，依赖场景账号、已有记录、本地文档和保存状态；JSON 本身不负责初始化环境。指令与评分条目中的姓名、联系人和地址是场景实体引用，需要与环境中的记录对应。

进行技能评测时，将选定任务及 [AgenticSkillInduction](../AgenticSkillInduction/README.zh-CN.md) 生成的相应技能提供给执行 Agent。`grading` 与执行、技能归纳输入分开。记录结果时保留原始任务 ID，由 evaluator 解释带权评分条目以及可选 `rubric_rule`。

评分权重之和近似为 1，文件中的实际范围为 `0.999997` 到 `1.000108`，不宜用浮点数严格相等判断。具体如何归一化权重及应用额外规则，应在 evaluator 中明确。

## 发布范围

当前已提供 MyPCBench 扰动任务的指令、应用/类别/难度标签与评分定义，以及 286 个 OSWorld 演示任务的 ID 清单。环境初始化、扰动生成器、任务运行器、judge 实现和评测结果尚未接入。

已检查 JSON 可解析性、ID 唯一性、必要字段类型及评分权重非负。发布检查未发现硬编码凭据、私有网络地址或个人机器路径。保留场景引用以维持任务语义；本目录不附带录制证据、账号密钥或运行输出。
