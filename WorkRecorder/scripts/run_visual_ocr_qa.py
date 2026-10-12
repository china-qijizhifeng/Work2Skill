"""Run Visual OCR QA against local screenshot artifacts.

This tool intentionally uses the same provider adapter, prompt builder, and
image preparation code as the daemon. It is meant for prompt tuning and remote
OpenAI-compatible endpoint validation, not for persistence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import yaml
from pydantic import SecretStr

from packages.artifacts.vault import LocalArtifactVault
from packages.contracts import (
    Artifact,
    ContextEvent,
    SourceRef,
    SourceType,
    VisualOCRAPIStyle,
    VisualOCRProviderKind,
    VisualOCRPublicSettings,
    VisualOCRRequest,
    VisualOCRResult,
    VisualOCRSettings,
)
from packages.enrichment.visual_ocr.image_preparer import VisualOCRImagePreparer
from packages.enrichment.visual_ocr.openai_compatible import OpenAICompatibleVisualOCRProvider
from packages.enrichment.visual_ocr.prompt import VisualOCRPromptBuilder
from packages.shared.ids import IdFactory

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = Path.home() / ".workrecorder" / "workrecorder.db"
DEFAULT_VAULT = Path.home() / ".workrecorder" / "artifacts"
DEFAULT_STAGING = Path.home() / ".workrecorder" / "staging"
DEFAULT_OUTPUT_DIR = REPO_ROOT / ".qa" / "visual-ocr-gpt55"
DEFAULT_NORTHCUA_CONFIG = Path.home() / ".config" / "workrecorder" / "agent.local.yaml"
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QAScreenshotArtifact:
    """Screenshot artifact row selected for QA.

    Attributes:
        event: Typed context event that owns the screenshot artifact.
        artifact: Screenshot artifact persisted in the local vault.
    """

    event: ContextEvent
    artifact: Artifact


@dataclass(frozen=True, slots=True)
class NorthCUAConfig:
    """Minimal LLM settings loaded from a NorthCUA-style local config.

    Attributes:
        model: Remote model name to call for Visual OCR.
        base_url: OpenAI-compatible API base URL.
        api_key: API key loaded from the local config file.
        api_style: Request protocol supported by the endpoint.
        timeout_seconds: HTTP timeout copied from the source config.
    """

    model: str
    base_url: str
    api_key: str
    api_style: VisualOCRAPIStyle
    timeout_seconds: int

    def visual_ocr_settings(self, *, max_image_long_edge: int) -> VisualOCRSettings:
        """Convert the local config into typed Visual OCR settings.

        Args:
            max_image_long_edge: Maximum image edge sent to the remote API.

        Returns:
            Runtime Visual OCR settings using the loaded remote endpoint.
        """

        return VisualOCRSettings(
            enabled=True,
            auto_run_on_capture=False,
            provider_kind=VisualOCRProviderKind.OPENAI_COMPATIBLE,
            api_style=self.api_style,
            base_url=self.base_url,
            allow_insecure_remote_base_url=_is_remote_http(self.base_url),
            model=self.model,
            timeout_seconds=self.timeout_seconds,
            max_image_long_edge=max_image_long_edge,
            api_key=SecretStr(self.api_key),
        )


def build_argument_parser() -> argparse.ArgumentParser:
    """Build CLI arguments for the Visual OCR QA runner.

    Returns:
        Configured CLI argument parser.
    """

    parser = argparse.ArgumentParser(description="Run Visual OCR QA on WorkRecorder screenshot artifacts.")
    parser.add_argument("--config-yaml", type=Path, default=DEFAULT_NORTHCUA_CONFIG)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--vault", type=Path, default=DEFAULT_VAULT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--event-id", action="append", default=[])
    parser.add_argument("--max-image-long-edge", type=int, default=1800)
    return parser


def main() -> int:
    """Run Visual OCR QA and write a JSON report plus per-event markdown.

    Returns:
        Process exit status.
    """

    args = build_argument_parser().parse_args()
    config = _load_northcua_config(args.config_yaml)
    settings = config.visual_ocr_settings(max_image_long_edge=args.max_image_long_edge)
    screenshots = _load_screenshot_artifacts(db_path=args.db, event_ids=tuple(args.event_id), limit=args.limit)
    if not screenshots:
        print("No screenshot artifacts found.")
        return 1
    report = asyncio.run(_run_qa(settings=settings, screenshots=screenshots, vault_dir=args.vault, output_dir=args.out))
    report_path = args.out / "results.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote Visual OCR QA report: {report_path}")
    return 0


def _load_northcua_config(path: Path) -> NorthCUAConfig:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("NorthCUA config must be a YAML object")
    llm_config = payload.get("llm_config")
    if not isinstance(llm_config, dict):
        raise ValueError("NorthCUA config is missing llm_config")
    api_type = str(llm_config.get("api_type") or "openai_responses")
    return NorthCUAConfig(
        model=str(llm_config.get("model") or "gpt-5.5"),
        base_url=str(llm_config.get("base_url") or "https://api.openai.com/v1"),
        api_key=str(llm_config.get("api_key") or ""),
        api_style=_api_style(api_type),
        timeout_seconds=int(llm_config.get("timeout") or 300),
    )


def _api_style(value: str) -> VisualOCRAPIStyle:
    normalized = value.strip().lower()
    if normalized in {"openai_responses", "responses"}:
        return VisualOCRAPIStyle.RESPONSES
    if normalized in {"openai_chat", "openai_chat_completions", "chat_completions"}:
        return VisualOCRAPIStyle.CHAT_COMPLETIONS
    raise ValueError(f"Unsupported NorthCUA api_type for Visual OCR QA: {value}")


def _is_remote_http(base_url: str) -> bool:
    parsed = urlparse(base_url)
    return parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}


def _load_screenshot_artifacts(
    *,
    db_path: Path,
    event_ids: tuple[str, ...],
    limit: int,
) -> tuple[QAScreenshotArtifact, ...]:
    placeholders = ""
    parameters: list[str | int] = []
    if event_ids:
        placeholders = " AND event_id IN (" + ",".join("?" for _ in event_ids) + ")"
        parameters.extend(event_ids)
    parameters.append(limit)
    query = (
        "SELECT event_id, payload FROM artifacts "
        "WHERE artifact_type = 'screenshot'"
        f"{placeholders} "
        "ORDER BY created_at DESC LIMIT ?"
    )
    with sqlite3.connect(db_path) as conn:
        artifact_rows = conn.execute(query, parameters).fetchall()
        if not artifact_rows:
            return ()
        event_payloads = {
            event_id: payload
            for event_id, payload in conn.execute(
                "SELECT event_id, payload FROM context_events "
                "WHERE event_id IN (" + ",".join("?" for _ in artifact_rows) + ")",
                [row[0] for row in artifact_rows],
            ).fetchall()
        }
    screenshots: list[QAScreenshotArtifact] = []
    for event_id, artifact_payload in artifact_rows:
        event_payload = event_payloads.get(event_id)
        if not isinstance(event_payload, str):
            continue
        screenshots.append(
            QAScreenshotArtifact(
                event=ContextEvent.model_validate_json(event_payload),
                artifact=Artifact.model_validate_json(artifact_payload),
            )
        )
    return tuple(screenshots)


async def _run_qa(
    *,
    settings: VisualOCRSettings,
    screenshots: Iterable[QAScreenshotArtifact],
    vault_dir: Path,
    output_dir: Path,
) -> dict[str, object]:
    provider = OpenAICompatibleVisualOCRProvider(settings=settings, prompt_builder=VisualOCRPromptBuilder())
    preparer = VisualOCRImagePreparer(vault=LocalArtifactVault(staging_dir=DEFAULT_STAGING, vault_dir=vault_dir))
    ids = IdFactory()
    results: list[dict[str, object]] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for item in screenshots:
        results.append(
            await _run_one(
                provider=provider, preparer=preparer, ids=ids, settings=settings, item=item, output_dir=output_dir
            )
        )
    return {
        "model": settings.model,
        "api_style": settings.api_style.value,
        "base_url": _redacted_url(settings.base_url),
        "allow_insecure_remote_base_url": settings.allow_insecure_remote_base_url,
        "count": len(results),
        "results": results,
    }


async def _run_one(
    *,
    provider: OpenAICompatibleVisualOCRProvider,
    preparer: VisualOCRImagePreparer,
    ids: IdFactory,
    settings: VisualOCRSettings,
    item: QAScreenshotArtifact,
    output_dir: Path,
) -> dict[str, object]:
    try:
        prepared = preparer.prepare_artifact(storage_uri=item.artifact.storage_uri, settings=settings)
        result = await provider.run(
            VisualOCRRequest(
                request_id=ids.new("vocr_qa"),
                event_id=item.event.event_id,
                artifact_id=item.artifact.artifact_id,
                source=item.event.source_binding.source_ref
                or SourceRef(source_type=SourceType.UNKNOWN, title="Unknown"),
                user_note=item.event.intent_text or item.event.trigger.intent_text,
                selection_bbox=item.event.trigger.selection,
                image_base64=prepared.image_base64,
                image_media_type=prepared.image_media_type,
                settings=_public_settings(settings),
            )
        )
    except Exception as exc:  # noqa: BLE001 - QA report needs typed failure rows.
        logger.debug(
            "visual OCR QA failed for event %s artifact %s",
            item.event.event_id,
            item.artifact.artifact_id,
            exc_info=exc,
        )
        return {
            "event_id": item.event.event_id,
            "artifact_id": item.artifact.artifact_id,
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
    markdown_path = output_dir / f"{item.event.event_id}.md"
    markdown_path.write_text(result.readable_markdown or result.plain_text, encoding="utf-8")
    return _success_row(
        result=result, event_id=item.event.event_id, artifact_id=item.artifact.artifact_id, markdown_path=markdown_path
    )


def _public_settings(settings: VisualOCRSettings) -> VisualOCRPublicSettings:
    return VisualOCRPublicSettings(
        enabled=settings.enabled,
        auto_run_on_capture=settings.auto_run_on_capture,
        provider_kind=settings.provider_kind,
        api_style=settings.api_style,
        base_url=settings.base_url,
        allow_insecure_remote_base_url=settings.allow_insecure_remote_base_url,
        model=settings.model,
        timeout_seconds=settings.timeout_seconds,
        max_image_long_edge=settings.max_image_long_edge,
        api_key_configured=bool(settings.api_key),
    )


def _success_row(
    *,
    result: VisualOCRResult,
    event_id: str,
    artifact_id: str,
    markdown_path: Path,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "artifact_id": artifact_id,
        "ok": True,
        "text_chars": len(result.plain_text),
        "line_count": len(result.lines),
        "element_count": len(result.ui_elements),
        "confidence": result.quality.confidence,
        "warnings": list(result.quality.warnings),
        "markdown_path": str(markdown_path),
        "result": result.model_dump(mode="json"),
    }


def _redacted_url(value: str) -> str:
    parsed = urlparse(value)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


if __name__ == "__main__":
    raise SystemExit(main())
