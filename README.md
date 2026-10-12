# Work2Skill

[![Website](https://img.shields.io/badge/Website-Work2Skill-2457B8)](https://china-qijizhifeng.github.io/Work2Skill/)
[![arXiv](https://img.shields.io/badge/arXiv-2610.12984-b31b1b.svg)](https://arxiv.org/abs/2610.12984)
[![Hugging Face: WorkDemo-350](https://img.shields.io/badge/Hugging%20Face-WorkDemo--350-FFD21E?logo=huggingface&logoColor=FFD21E)](https://huggingface.co/datasets/yuqi777/WorkDemo-350)

**English** | [简体中文](README.zh-CN.md)

**Work2Skill connects human GUI demonstrations with reusable agent skills through operation recording, multimodal evidence inspection, and skill induction.**

Read the paper: [Work2Skill: Capturing Human GUI Experience for Reusable Agent Skill Induction](https://arxiv.org/abs/2610.12984).

Find the human operation demonstration dataset on Hugging Face: [WorkDemo-350](https://huggingface.co/datasets/yuqi777/WorkDemo-350).

![Work2Skill overview: human GUI demonstrations, multimodal recording, action-linked evidence, agentic skill induction, and execution-based evaluation](assets/work2skill-overview.png)

## Repository Structure

| Directory | Purpose | Current status |
| --- | --- | --- |
| [WorkRecorder](WorkRecorder/README.md) | Native macOS recording and remote Linux evidence collection | macOS recorder and Linux X11 AT-SPI service; live cross-platform acceptance testing pending |
| [DownstreamTasks](DownstreamTasks/README.md) | Perturbed task definitions, grading criteria, and demonstration task IDs | 64 MyPCBench perturbed tasks and grading criteria; IDs of 286 OSWorld tasks with demonstrations; runner/evaluation integration pending |
| [AgenticSkillInduction](AgenticSkillInduction/README.md) | An example built on NexAU for skill induction | Example source and NexAU setup instructions available |

```text
Work2Skill/
├── WorkRecorder/             # Recording infrastructure
├── DownstreamTasks/          # Downstream tasks with perturbations
└── AgenticSkillInduction/    # NexAU-based example
```

The intended workflow is: **record demonstrations → export task evidence → induce reusable skills → evaluate on downstream tasks**. The current release provides the recording and induction components plus task definitions; evaluation integration is still pending.

## Get Started

```bash
git clone https://github.com/china-qijizhifeng/Work2Skill.git
cd Work2Skill
```

1. **Explore demonstrations:** visit [WorkDemo-350 on Hugging Face](https://huggingface.co/datasets/yuqi777/WorkDemo-350). Recording data is hosted separately from this source repository.
2. **Record your own workflows:** follow the [WorkRecorder guide](WorkRecorder/README.md). Run installation, build, and test commands inside `WorkRecorder/`. Linux collection uses an X11/Xorg desktop together with the Mac recording app.
3. **Induce skills:** follow the [AgenticSkillInduction guide](AgenticSkillInduction/README.md) to install the example in a separate NexAU checkout, configure an image-capable model endpoint, and supply task evidence. This path requires Python 3.12+, `uv`, and `ffmpeg`/`ffprobe`. Complete the actual task instruction and inputs in `task.json` before extraction.
4. **Prepare downstream evaluation:** use the [task definitions and grading criteria](DownstreamTasks/README.md) in the corresponding benchmark environment. The task files require an execution runner and evaluator to produce results.

## Tasks and Release Scope

Original tasks come from [MyPCBench Bounded Action](https://github.com/ljang0/MyPCBench/tree/main/tasks/final) and [OSWorld-Verified](https://xlang.ai/blog/osworld-verified). This repository includes:

- [`tasks-jitter.json`](DownstreamTasks/tasks-jitter.json): 64 MyPCBench task variants (`f` original → `j` perturbed), with 366 weighted grading criteria.
- [`selected_task_ids.json`](DownstreamTasks/selected_task_ids.json): 286 unique OSWorld task IDs identifying tasks with recorded demonstrations.

Benchmark environment initialization, the task perturbation generator, execution runners, the evaluator, and end-to-end evaluation results are not included yet. The skill-induction example has offline tests; model-dependent extraction quality and live macOS/Linux recording still require end-to-end validation.

## License

Original Work2Skill code is licensed under the [MIT License](LICENSE). Third-party components retain their own licenses and notices; see [Third-party notices](THIRD_PARTY_NOTICES.md). Externally hosted datasets are governed by their own published terms.

## Contributing

Bug reports, documentation improvements, and reproducibility feedback are welcome through [issues](https://github.com/china-qijizhifeng/Work2Skill/issues) and pull requests. Include the affected module, operating system, and steps to reproduce when reporting a problem.
