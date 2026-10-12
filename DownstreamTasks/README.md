# Downstream Tasks

[English](README.md) | [简体中文](README.zh-CN.md) · [Project overview](../README.md)

This directory provides **64 perturbed MyPCBench Bounded Action tasks** with **366 weighted grading criteria**, plus the IDs of **286 OSWorld-Verified tasks with recorded human demonstrations**.

## Original Tasks and Published Files

Original task definitions come from **MyPCBench Bounded Action** and **OSWorld-Verified**:

| Benchmark | Original task source | File in this directory |
| --- | --- | --- |
| MyPCBench Bounded Action | [MyPCBench task definitions](https://github.com/ljang0/MyPCBench/tree/main/tasks/final); select `bounded_action` in [`task_types.json`](https://github.com/ljang0/MyPCBench/blob/main/tasks/final/task_types.json) | [`tasks-jitter.json`](tasks-jitter.json): 64 perturbed `j` tasks, each corresponding to an original `f` task |
| OSWorld-Verified | [OSWorld task definitions](https://github.com/xlang-ai/OSWorld/tree/main/evaluation_examples/examples); see the [OSWorld-Verified introduction](https://xlang.ai/blog/osworld-verified) | [`selected_task_ids.json`](selected_task_ids.json): 286 original task IDs identifying tasks with recorded human demonstrations |

`selected_task_ids.json` is a JSON array of 286 unique UUID strings. Each ID maps to an upstream task at `evaluation_examples/examples/<application>/<task_id>.json`. It indexes the tasks with demonstrations; see [WorkDemo-350 on Hugging Face](https://huggingface.co/datasets/yuqi777/WorkDemo-350) for the recordings. This directory contains the task ID list.

## MyPCBench Task Perturbations

Here, *jitter* means changes to task instructions: target entities, quantities, parameters, selection rules, requested outputs, or workflow constraints. For example, a task may use a different holding and reinvestment target, change a stop-order percentage, or require a particular route, document, or saved result. The file describes task variants; it does not implement randomized mouse movement or visual perturbations.

## Contents

`tasks-jitter.json` is a UTF-8 JSON array. Each item has these fields:

| Field | Meaning |
| --- | --- |
| `id` | Unique task identifier, such as `hard_app-j003` |
| `app` | Application identifier, or `multi_app` for a cross-application task |
| `instruction` | Task instruction for the execution agent |
| `apps_involved` | Named applications involved in the task |
| `category` | Task category; use this field for grouping |
| `difficulty` | `easy`, `medium`, or `hard` |
| `grading.type` | `llm_judge` for all tasks in this release |
| `grading.rubrics` | Criteria with `criterion`, `type`, and `weight` |
| `grading.rubric_rule` | Optional additional scoring rule; present in one task |

**For MyPCBench, `f` identifies an original task; `j` identifies its perturbed counterpart.** The prefix and task number are preserved, for example `hard_app-f003 → hard_app-j003`. All 64 originals belong to the upstream `bounded_action` subset. The original `f` task definitions are available from MyPCBench above. OSWorld task IDs retain their original UUIDs.

The `category` labels below are preserved from the supplied task file and differ from the upstream behavioral type `bounded_action`. An ID prefix is not necessarily the current category: 32 entries have different prefix and category values.

## Task Distribution

| Category | Tasks |
| --- | ---: |
| `situated_action` | 48 |
| `long_horizon` | 13 |
| `cua_only` | 2 |
| `hard_app` | 1 |
| **Total** | **64** |

Difficulty labels: **48 hard, 15 medium, 1 easy**. The `app` field has 19 distinct values, including `multi_app`; 26 tasks are labeled `multi_app`. Scenarios cover spreadsheets and documents, files, email/chat, project management, shopping, travel, and simulated financial applications.

## Load and Use

From this directory:

```python
import json
from pathlib import Path

tasks = json.loads(Path("tasks-jitter.json").read_text(encoding="utf-8"))
task = next(item for item in tasks if item["id"] == "hard_app-j003")

# Give the execution agent the task fields; keep grading with the evaluator.
agent_task = {key: value for key, value in task.items() if key != "grading"}
evaluator_config = task["grading"]
```

Run a selected task in the corresponding benchmark application state. These tasks depend on scenario accounts, existing records, local documents, and saved state; the JSON alone does not prepare that environment. Names, contacts, and addresses in the instructions and criteria identify benchmark scenario entities and must resolve in that environment.

For skill-based evaluation, provide the selected task and the appropriate skill from [AgenticSkillInduction](../AgenticSkillInduction/README.md) to the execution agent. Keep `grading` separate from execution and skill-induction inputs. Retain the original task ID when recording results, and let the evaluator interpret both the weighted criteria and any `rubric_rule`.

Rubric weights sum approximately to one; supplied totals range from `0.999997` to `1.000108`. Do not rely on exact floating-point equality. Define weight normalization and additional-rule handling explicitly in the evaluator.

## Release Scope

This release supplies the MyPCBench perturbed task instructions, application/category/difficulty labels, and grading definitions, together with the 286-task OSWorld demonstration ID list. Environment initialization, the perturbation generator, execution runners, judge implementation, and evaluation results are not included yet.

The task file was checked for valid JSON, unique IDs, required field types, and nonnegative rubric weights. Publication review found no hardcoded credentials, private network addresses, or personal machine paths. Scenario references were retained to preserve task semantics; no recording evidence, account secrets, or run outputs are bundled here.
