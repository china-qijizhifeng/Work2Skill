"""Run a path-scoped NexAU agent that extracts skills from one episode."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parents[1]
PROXY_ENV_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")
OPENAI_ENV_ALIASES = {
    "LLM_API_KEY": "OPENAI_API_KEY",
    "LLM_BASE_URL": "OPENAI_BASE_URL",
    "LLM_MODEL": "OPENAI_MODEL",
}
REASONING_EFFORTS = ("low", "medium", "high", "xhigh")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

from examples.agentic_skill_induction.bindings import (  # noqa: E402
    configure_provenance,
    configure_roots,
    require_finalized_extraction,
)
from examples.agentic_skill_induction.run_logging import ExtractionRunLogger  # noqa: E402
from nexau import Agent, AgentConfig  # noqa: E402
from nexau.archs.main_sub.execution.middleware.agent_events_middleware import AgentEventsMiddleware  # noqa: E402


def _inline_system_prompt(config: AgentConfig) -> None:
    """Resolve a local prompt file before the request so the model receives plain text."""
    if config.system_prompt_type != "file":
        return
    if not isinstance(config.system_prompt, str):
        raise TypeError("The extractor expects a single system prompt file.")
    prompt_path = Path(config.system_prompt).expanduser().resolve(strict=True)
    prompt_text = prompt_path.read_text(encoding="utf-8")
    if not prompt_text.strip():
        raise ValueError(f"System prompt file is empty: {prompt_path}")
    config.system_prompt = prompt_text
    config.system_prompt_type = "string"


def _clear_proxy_environment() -> list[str]:
    """Remove proxy variables before constructing the LLM HTTP client."""
    removed: list[str] = []
    for name in PROXY_ENV_VARS:
        if name in os.environ:
            os.environ.pop(name)
            removed.append(name)
    return removed


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_value(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip()
    return value or None


def build_provenance(
    *,
    input_root: Path,
    config_path: Path,
    config: AgentConfig,
    reasoning_effort: str,
) -> dict[str, object]:
    """Build stable, credential-free metadata binding a run to this harness."""
    source_files = sorted(
        path
        for path in SCRIPT_DIR.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix.lower() in {".md", ".py", ".yaml", ".yml"}
    )
    file_hashes = {
        path.relative_to(SCRIPT_DIR).as_posix(): _sha256_file(path)
        for path in source_files
    }
    harness_material = json.dumps(file_hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    task_hashes = {
        path.relative_to(input_root).as_posix(): _sha256_file(path)
        for path in sorted(input_root.rglob("task.json"))
        if path.is_file()
    }
    dirty_status = _git_value("status", "--porcelain", "--", str(SCRIPT_DIR.relative_to(PROJECT_ROOT)))
    prompt_text = config.system_prompt if isinstance(config.system_prompt, str) else ""
    return {
        "harness": "agentic_skill_induction",
        "harness_schema_version": "1.0",
        "harness_sha256": hashlib.sha256(harness_material).hexdigest(),
        "harness_files": file_hashes,
        "git_commit": _git_value("rev-parse", "HEAD"),
        "git_dirty": dirty_status is not None,
        "config_path": str(config_path),
        "config_sha256": _sha256_file(config_path),
        "system_prompt_sha256": hashlib.sha256(prompt_text.encode("utf-8")).hexdigest(),
        "input_task_sha256": task_hashes,
        "model": os.environ["LLM_MODEL"],
        "api_type": str(config.llm_config.api_type),
        "reasoning_effort": reasoning_effort,
        "temperature": config.llm_config.temperature,
    }


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract reusable NexAU skills from a recorded GUI episode directory.")
    parser.add_argument("episode_dir", type=Path, help="Benchmark run or episode directory available to the extractor.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help=(
            "Generated skill directory. Defaults to "
            "generated_skills/agentic_skill_induction/<input-name>."
        ),
    )
    parser.add_argument("--config", type=Path, default=SCRIPT_DIR / "agent.yaml", help="Extractor agent YAML configuration.")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=PROJECT_ROOT / ".env",
        help="Environment file containing LLM_* or OPENAI_* credentials.",
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=REASONING_EFFORTS,
        default="high",
        help="Reasoning effort for the skill extraction agent.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = create_parser().parse_args(argv)
    load_dotenv(args.env_file.expanduser(), override=False)
    for llm_name, openai_name in OPENAI_ENV_ALIASES.items():
        if not os.environ.get(llm_name) and os.environ.get(openai_name):
            os.environ[llm_name] = os.environ[openai_name]
    removed_proxy_vars = _clear_proxy_environment()
    if removed_proxy_vars:
        print(f"Unset proxy environment variables: {', '.join(removed_proxy_vars)}")

    input_root = args.episode_dir.expanduser().resolve(strict=True)
    output_root = (
        args.output_dir.expanduser().resolve(strict=False)
        if args.output_dir
        else (
            PROJECT_ROOT
            / "generated_skills"
            / "agentic_skill_induction"
            / input_root.name
        ).resolve(strict=False)
    )
    configure_roots(input_root, output_root)

    missing = [name for name in ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL") if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variable(s): {', '.join(missing)}.")

    config_path = args.config.resolve()
    config = AgentConfig.from_yaml(config_path)
    _inline_system_prompt(config)
    max_tokens_override = os.environ.get("SKILL_INDUCTION_LLM_MAX_TOKENS", "").strip()
    if max_tokens_override:
        config.llm_config.max_tokens = int(max_tokens_override)
    config.llm_config.extra_params["reasoning_effort"] = args.reasoning_effort
    provenance = build_provenance(
        input_root=input_root,
        config_path=config_path,
        config=config,
        reasoning_effort=args.reasoning_effort,
    )
    configure_provenance(provenance)
    (output_root / "run-metadata.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    run_logger = ExtractionRunLogger(
        output_root,
        input_root=input_root,
        model=os.environ["LLM_MODEL"],
        provenance=provenance,
    )
    event_middleware = AgentEventsMiddleware(session_id=f"skill-extraction-{input_root.name}", on_event=run_logger.on_event)
    config.middlewares = [*(config.middlewares or []), event_middleware]
    agent = Agent(config=config)
    message = (
        "Extract one or more reusable skills from the benchmark artifacts available at logical input path '.'. "
        "First load skill-creator, then read the authoritative task before interpreting the trajectory. Write all "
        "generated files under the logical output root using write_file, then read and self-review every final Skill "
        "after its last write. Call finalize_extraction; the runtime writes the extraction manifest. "
        "A normal text response does not complete the task."
    )
    try:
        response = agent.run(message=message)
        require_finalized_extraction()
    except Exception as exc:
        run_logger.finish(status="error", error=str(exc), finalized=False)
        raise
    else:
        run_logger.finish(status="completed", finalized=True)
        print(response)
    print(f"Generated files: {output_root}")
    print(f"Run events: {run_logger.events_path}")
    print(f"Run summary: {run_logger.summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
