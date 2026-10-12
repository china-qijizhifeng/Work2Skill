"""Local Apple Vision OCR provider."""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import shutil
import tempfile
from pathlib import Path

from packages.contracts import VisualOCRRequest, VisualOCRResult, VisualOCRSettings

from .openai_compatible import VisualOCRProviderError
from .ports import VisualOCRProvider


class AppleVisionVisualOCRProvider(VisualOCRProvider):
    """Run OCR locally through Apple's Vision framework helper.

    The provider never uploads screenshot bytes. When the Swift helper or
    Vision runtime is unavailable, callers should treat it as a local
    configuration gap and keep the capture as system-only.
    """

    def __init__(self, *, settings: VisualOCRSettings) -> None:
        self.settings = settings

    async def run(self, request: VisualOCRRequest) -> VisualOCRResult:
        """Run local OCR for one screenshot request.

        Args:
            request: Prepared OCR request containing a PNG image encoded as
                base64 plus the public OCR settings snapshot.

        Returns:
            A typed OCR result parsed from the local Vision helper output.

        Raises:
            VisualOCRProviderError: If the helper is unavailable, the input
                image is invalid, the helper times out, or its output does not
                match the WorkRecorder OCR schema.
        """

        helper_command = _helper_command()
        if helper_command is None:
            raise VisualOCRProviderError("apple_vision_unavailable")
        try:
            image_bytes = base64.b64decode(request.image_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise VisualOCRProviderError("visual OCR image payload is not valid base64") from exc
        with tempfile.NamedTemporaryFile(suffix=".png") as image_file:
            image_file.write(image_bytes)
            image_file.flush()
            process = await asyncio.create_subprocess_exec(
                *helper_command,
                image_file.name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=self.settings.timeout_seconds)
            except TimeoutError as exc:
                process.kill()
                await process.communicate()
                raise VisualOCRProviderError("apple_vision_timeout") from exc
        if process.returncode != 0:
            raise VisualOCRProviderError(_safe_helper_error(stderr, fallback="apple_vision_failed"))
        try:
            payload = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VisualOCRProviderError("apple_vision_output_was_not_json") from exc
        try:
            return VisualOCRResult.model_validate(payload)
        except ValueError as exc:
            raise VisualOCRProviderError("apple_vision_output_did_not_match_schema") from exc

    async def probe(self) -> None:
        """Check that the local helper can be invoked.

        Raises:
            VisualOCRProviderError: If Swift or the bundled helper script is
                unavailable on the current machine.
        """

        helper_command = _helper_command()
        if helper_command is None:
            raise VisualOCRProviderError("apple_vision_unavailable")
        process = await asyncio.create_subprocess_exec(
            *helper_command,
            "--probe",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=10)
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise VisualOCRProviderError("apple_vision_probe_timeout") from exc
        if process.returncode != 0:
            raise VisualOCRProviderError(_safe_helper_error(stderr, fallback="apple_vision_runtime_unavailable"))


def apple_vision_unavailable_reason() -> str | None:
    """Return why the local Apple Vision provider cannot run, if known.

    Returns:
        ``None`` when the local Swift runtime and bundled helper appear
        available; otherwise a stable skip reason suitable for job diagnostics.
    """

    if _helper_binary_path().exists() and os.access(_helper_binary_path(), os.X_OK):
        return None
    helper = _helper_path()
    if not helper.exists():
        return "apple_vision_helper_missing"
    if shutil.which("swift") is None:
        return "apple_vision_swift_missing"
    return None


def _helper_path() -> Path:
    return Path(__file__).with_name("apple_vision_ocr.swift")


def _helper_binary_path() -> Path:
    return Path(__file__).with_name("apple_vision_ocr_helper")


def _helper_command() -> tuple[str, ...] | None:
    binary = _helper_binary_path()
    if binary.exists() and os.access(binary, os.X_OK):
        return (str(binary),)
    helper = _helper_path()
    swift = shutil.which("swift")
    if swift is not None and helper.exists():
        return (swift, str(helper))
    return None


def _safe_helper_error(stderr: bytes, *, fallback: str) -> str:
    message = stderr.decode("utf-8", errors="replace").strip() or fallback
    lowered = message.lower()
    if "no such module" in lowered or "compile" in lowered:
        return "apple_vision_compile_failed"
    if "vision" in lowered:
        return "apple_vision_runtime_unavailable"
    return message[:160]
