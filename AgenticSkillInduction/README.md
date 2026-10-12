# Agentic Skill Induction

[English](README.md) | [简体中文](README.zh-CN.md)

A [NexAU](https://github.com/nex-agi/NexAU) example for inducing self-contained GUI skills from recorded task evidence. Evidence exploration and skill authoring are agent-directed: the agent can inspect more evidence after writing a draft, revise it, and read it back. The system prompt defines the execution boundaries; the bundled `skill-creator` defines the authoring policy.

## Install under NexAU/examples

Requires Python 3.12+, `uv`, and `ffmpeg`/`ffprobe` on `PATH`. Use an image-capable model with structured tool calling through an OpenAI-compatible Chat Completions endpoint. The model must support the parameters configured in `agent.yaml`; adapt that file to your provider when necessary.

NexAU is an external dependency, not bundled here. The offline checks do not establish end-to-end extraction quality for a particular model.

From a directory where you want both repositories:

```bash
git clone https://github.com/china-qijizhifeng/Work2Skill.git
git clone https://github.com/nex-agi/NexAU.git
cp -R Work2Skill/AgenticSkillInduction NexAU/examples/agentic_skill_induction
cd NexAU
uv sync
```

The example files live directly in this directory. Copy this entire directory to `NexAU/examples/agentic_skill_induction/`. If both repositories already exist, only the copy step is needed. Use the destination folder name `agentic_skill_induction`: imports and YAML bindings use `examples.agentic_skill_induction`. All commands below run from the **NexAU repository root**.

Install the video tools if needed:

```bash
# macOS
brew install ffmpeg
# Ubuntu/Debian
sudo apt-get install ffmpeg
```

## Configure the model

Copy the blank template and fill it with your own endpoint, model identifier, and key:

```bash
cp examples/agentic_skill_induction/.env.example \
   examples/agentic_skill_induction/.env
```

Required variables are `LLM_API_KEY`, `LLM_MODEL`, and `LLM_BASE_URL`. Their aliases `OPENAI_API_KEY`, `OPENAI_MODEL`, and `OPENAI_BASE_URL` are also accepted when the corresponding `LLM_*` variable is unset. Existing environment values take precedence over the env file. `--env-file` selects the file; its default is NexAU's root `.env`.

The default configuration uses structured tool calls, up to 100 iterations, and a 16,000-token model output limit. `--reasoning-effort` accepts `low`, `medium`, `high`, or `xhigh` (default `high`); `SKILL_INDUCTION_LLM_MAX_TOKENS` overrides the output limit. The launcher clears `HTTP_PROXY`, `HTTPS_PROXY`, `ALL_PROXY` and their lowercase variants before creating the model client, so the endpoint must be directly reachable.

## Prepare the input

Pass a benchmark run directory containing episodes, or one episode directory. For example, WorkRecorder produces:

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

Files depend on the evidence collected. `task.json` must contain the actual task instruction and task inputs. WorkRecorder can emit a placeholder with only an inferred ID when external task metadata was not supplied; replace or complete that placeholder before skill extraction. Include the recording evidence the agent needs inside the input directory. Keep private credentials, grading rubrics, judge output, and reference answers outside it.

The agent sees the input directory as `.` and the generated directory as `output/`. Reads are restricted to those roots; writes are restricted to the output root. Choose separate input and output directories. One extraction process handles one run; batch mode starts separate processes.

## Extract skills

Replace `/path/to/recording` with your recording export's actual location:

```bash
uv run python examples/agentic_skill_induction/start.py \
  /path/to/recording/benchmark/normal \
  --env-file examples/agentic_skill_induction/.env \
  --output-dir generated_skills/agentic_skill_induction/recording-demo
```

Without `--output-dir`, output goes to `generated_skills/agentic_skill_induction/<input-name>`. Choose distinct output directories for recordings whose input folders share a name such as `normal`.

## Tool contracts

| Tool | Purpose |
| --- | --- |
| `list_directory`, `glob` | Find files inside the input/output roots |
| `read_file` | Read text, JSON, JSONL, YAML, or Markdown with pagination |
| `read_visual_evidence` | Inspect 1–20 ordered, path-labeled images |
| `get_video_metadata` | Read duration, dimensions, frame rate, codec, and size |
| `watch_video` | Inspect timestamped frames sampled over an interval |
| `extract_video_frames` | Request frames at selected millisecond timestamps |
| `write_file` | Create or replace a complete file under the output root |
| `finalize_extraction` | Validate outputs and atomically write the extraction manifest |

Video times use **milliseconds**, and metadata for the same video must be inspected before sampling. `watch_video` returns frames rather than continuous playback; it has no `with_annotation` parameter. Frame requests near or beyond the video end may be adjusted backwards, with the returned label reporting the actual sampling time.

```python
get_video_metadata(file_path="episodes/task-demo/video.mp4")
watch_video(
    file_path="episodes/task-demo/video.mp4",
    start_ms=16000, end_ms=18000, interval_ms=1000,
)
```

These are agent tool-call examples, not shell commands. NexAU also supplies `LoadSkill` for loading the bundled authoring policy.

## Finalization and output

`finalize_extraction` is the only successful completion path. It checks that a `task.json` was read, each generated Skill has valid required structure, each final `SKILL.md` was created with `write_file` and read back after its last write, and metadata inspection preceded video sampling. Validation errors return to the agent for correction. These checks do not prove that a generated skill will execute successfully.

Each output directory contains Skill folders and runtime files:

- `<skill-name>/SKILL.md`: the reusable skill, with any supporting resources.
- `extraction-manifest.json`: Skill hashes, inspected sources, validation results, and provenance.
- `run-metadata.json`: harness/config/input hashes and model configuration metadata.
- `run-events.jsonl`: recorded model, tool, text, usage, and lifecycle events.
- `run-summary.json`: run status, timing, tool calls, and token usage.

The agent must not write the runtime files itself. A normal text response without successful finalization leaves the extraction incomplete.

## Batch extraction

Batch discovery finds `run_manifest.json` recursively:

```bash
uv run python examples/agentic_skill_induction/batch_start.py \
  /path/to/recordings \
  --env-file examples/agentic_skill_induction/.env \
  --jobs 2
```

Outputs default to `generated_skills/agentic_skill_induction/`, using each run's relative path and an `-image-prompt` suffix. Change that with `--output-root` and `--output-suffix`. Completed runs are skipped only when summary/manifest provenance and Skill hashes match. Use `--rerun-completed` to rerun them. `--nested-only` and `--nested-prefix` filter discovered runs.

## Optional dashboard

Run the dashboard locally with its optional dependency:

```bash
uv run --with streamlit streamlit run \
  examples/agentic_skill_induction/dashboard.py \
  --server.address 127.0.0.1
```

Set `NEXAU_SKILL_RUNS_ROOT` to view another output root. The dashboard shows status, tool activity, usage, logged events, and generated text files.

## Local checks and publication

```bash
uv run python -m unittest discover \
  -s examples/agentic_skill_induction/tests -v
```

Tests use temporary synthetic data and make no model API calls. Video tests require `ffmpeg` and `ffprobe`.

The published source excludes personal deployment paths, Python bytecode, credentials, and run artifacts. Keep populated `.env` files local. Evidence inspected by the agent is sent to the configured model endpoint; run logs may contain task text, file paths, and model/tool output. They are not automatically anonymized and should be reviewed separately before sharing.
