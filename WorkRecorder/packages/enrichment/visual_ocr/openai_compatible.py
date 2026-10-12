"""OpenAI-compatible VLM OCR provider."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from io import BytesIO
from typing import Final

import httpx
from PIL import Image, ImageDraw
from pydantic import ValidationError

from packages.contracts import (
    SourceRef,
    SourceType,
    VisualOCRAPIStyle,
    VisualOCRElementRole,
    VisualOCRProviderKind,
    VisualOCRPublicSettings,
    VisualOCRRequest,
    VisualOCRResult,
    VisualOCRSettings,
)

from .ports import VisualOCRProvider
from .prompt import VisualOCRPromptBuilder

_JSON_FENCE_RE: Final[re.Pattern[str]] = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_PROBE_TEXT: Final[str] = "WorkRecorder OCR probe"


class VisualOCRProviderError(Exception):
    """Raised when a VLM OCR provider cannot return a typed result."""


@dataclass(frozen=True, slots=True)
class OpenAICompatibleVisualOCRProvider(VisualOCRProvider):
    """VLM OCR provider for OpenAI-compatible Responses or Chat APIs.

    The adapter deliberately owns only HTTP protocol details. It does not know
    persistence, policy, or job state; those remain in the service/worker
    layers so additional providers can be dropped in later.

    Attributes:
        settings: Provider endpoint, model, timeout, API profile, and API key.
        prompt_builder: Builder for extraction prompts and strict schemas.
    """

    settings: VisualOCRSettings
    prompt_builder: VisualOCRPromptBuilder

    async def run(self, request: VisualOCRRequest) -> VisualOCRResult:
        """Run OCR and validate the provider response as ``VisualOCRResult``.

        Args:
            request: Typed screenshot OCR request.

        Returns:
            Provider result normalized into the public OCR contract.

        Raises:
            VisualOCRProviderError: Raised when configuration is incomplete or
                provider output cannot be parsed into the contract.
            httpx.HTTPError: Raised for transport or non-fallback HTTP errors.
        """

        if self.settings.provider_kind != VisualOCRProviderKind.OPENAI_COMPATIBLE:
            raise VisualOCRProviderError("visual OCR provider kind is not openai-compatible")
        api_key = self.settings.api_key.get_secret_value() if self.settings.api_key else ""
        if not api_key:
            raise VisualOCRProviderError("visual OCR API key is not configured")
        timeout = httpx.Timeout(float(self.settings.timeout_seconds))
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                text = await self._post_and_extract(client=client, request=request, schema_mode=True)
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in {400, 422}:
                    raise VisualOCRProviderError(self._http_error_message(exc)) from exc
                try:
                    text = await self._post_and_extract(client=client, request=request, schema_mode=False)
                except httpx.HTTPStatusError as fallback_exc:
                    raise VisualOCRProviderError(self._http_error_message(fallback_exc)) from fallback_exc
            try:
                return self._parse_result(text, request=request)
            except VisualOCRProviderError:
                repaired = await self._post_and_extract(
                    client=client,
                    request=request,
                    schema_mode=False,
                    repair_source=text,
                )
                return self._parse_result(repaired, request=request)

    async def probe(self) -> None:
        """Make a tiny provider call to validate key, endpoint, model, and schema support."""

        request = VisualOCRRequest(
            request_id="vocr_probe",
            event_id="evt_probe",
            artifact_id="art_probe",
            source=SourceRef(source_type=SourceType.UNKNOWN, title="Visual OCR probe"),
            image_base64=base64.b64encode(_probe_png()).decode("ascii"),
            image_media_type="image/png",
            settings=VisualOCRPublicSettings(
                enabled=self.settings.enabled,
                auto_run_on_capture=self.settings.auto_run_on_capture,
                provider_kind=self.settings.provider_kind,
                api_style=self.settings.api_style,
                base_url=self.settings.base_url,
                allow_insecure_remote_base_url=self.settings.allow_insecure_remote_base_url,
                model=self.settings.model,
                timeout_seconds=self.settings.timeout_seconds,
                max_image_long_edge=self.settings.max_image_long_edge,
                api_key_configured=True,
            ),
        )
        await self.run(request)

    async def _post_and_extract(
        self,
        *,
        client: httpx.AsyncClient,
        request: VisualOCRRequest,
        schema_mode: bool,
        repair_source: str | None = None,
    ) -> str:
        response = await client.post(
            self._endpoint(),
            headers={
                "Authorization": f"Bearer {self.settings.api_key.get_secret_value() if self.settings.api_key else ''}",
                "Content-Type": "application/json",
            },
            json=self._payload(request, schema_mode=schema_mode, repair_source=repair_source),
        )
        response.raise_for_status()
        return self._extract_text(response.json())

    def _endpoint(self) -> str:
        base = str(self.settings.base_url).rstrip("/")
        if self.settings.api_style == VisualOCRAPIStyle.RESPONSES:
            return f"{base}/responses"
        return f"{base}/chat/completions"

    def _payload(
        self, request: VisualOCRRequest, *, schema_mode: bool = True, repair_source: str | None = None
    ) -> dict[str, object]:
        system_prompt = self.prompt_builder.system_prompt()
        user_text = (
            self.prompt_builder.repair_prompt(invalid_output=repair_source)
            if repair_source is not None
            else self.prompt_builder.user_prompt(request)
        )
        if self.settings.api_style == VisualOCRAPIStyle.RESPONSES:
            user_content: list[dict[str, object]] = [{"type": "input_text", "text": user_text}]
            if repair_source is None:
                user_content.append(
                    {"type": "input_image", "image_url": self._data_url(request.image_base64, request.image_media_type)}
                )
            payload: dict[str, object] = {
                "model": self.settings.model,
                "input": [
                    {
                        "role": "system",
                        "content": [{"type": "input_text", "text": system_prompt}],
                    },
                    {
                        "role": "user",
                        "content": user_content,
                    },
                ],
            }
            payload["text"] = self._response_format(schema_mode=schema_mode)
            return payload
        chat_user_content: list[dict[str, object]] = [{"type": "text", "text": user_text}]
        if repair_source is None:
            chat_user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": self._data_url(request.image_base64, request.image_media_type)},
                }
            )
        payload = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": chat_user_content},
            ],
        }
        payload["response_format"] = self._chat_response_format(schema_mode=schema_mode)
        return payload

    def _response_format(self, *, schema_mode: bool) -> dict[str, object]:
        if not schema_mode:
            return {"format": {"type": "json_object"}}
        return {
            "format": {
                "type": "json_schema",
                "name": "workrecorder_visual_ocr_result_v0",
                "schema": self.prompt_builder.json_schema(),
                "strict": True,
            }
        }

    def _chat_response_format(self, *, schema_mode: bool) -> dict[str, object]:
        if not schema_mode:
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "workrecorder_visual_ocr_result_v0",
                "schema": self.prompt_builder.json_schema(),
                "strict": True,
            },
        }

    def _extract_text(self, payload: object) -> str:
        if not isinstance(payload, dict):
            raise VisualOCRProviderError("visual OCR response was not a JSON object")
        direct = payload.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict):
                    content = message.get("content")
                    if isinstance(content, str):
                        return content
                    if isinstance(content, list):
                        message_parts = [
                            item.get("text", "")
                            for item in content
                            if isinstance(item, dict) and isinstance(item.get("text"), str)
                        ]
                        return "\n".join(message_parts)
        output = payload.get("output")
        if isinstance(output, list):
            parts: list[str] = []
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for content_item in content:
                    if not isinstance(content_item, dict):
                        continue
                    text = content_item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            if parts:
                return "\n".join(parts)
        raise VisualOCRProviderError("visual OCR response did not contain text")

    def _parse_result(self, text: str, *, request: VisualOCRRequest) -> VisualOCRResult:
        stripped = text.strip()
        fence_match = _JSON_FENCE_RE.fullmatch(stripped)
        if fence_match is not None:
            stripped = fence_match.group(1).strip()
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise VisualOCRProviderError("visual OCR response was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise VisualOCRProviderError("visual OCR JSON response was not an object")
        normalized = self._normalize_payload(payload, request=request)
        try:
            return VisualOCRResult.model_validate(normalized)
        except ValidationError as exc:
            raise VisualOCRProviderError("visual OCR response did not match schema") from exc

    def _normalize_payload(self, payload: dict[str, object], *, request: VisualOCRRequest) -> dict[str, object]:
        plain_text = str(payload.get("plain_text") or "").strip()
        readable_markdown = str(payload.get("readable_markdown") or plain_text).strip()
        quality = payload.get("quality")
        if not isinstance(quality, dict):
            quality = {}
        if "confidence" not in quality:
            quality["confidence"] = 0.0 if not plain_text else 0.35
            warnings = quality.get("warnings")
            if not isinstance(warnings, list):
                warnings = []
            warnings.append("Provider omitted quality confidence; defaulted to low confidence.")
            quality["warnings"] = warnings
        quality.setdefault("text_chars", len(plain_text))
        quality.setdefault("truncated", False)
        quality.setdefault("warnings", [])
        metadata = payload.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        metadata.setdefault("event_id", request.event_id)
        metadata.setdefault("source", "vlm_visual_ocr")
        return {
            "plain_text": plain_text,
            "readable_markdown": readable_markdown,
            "lines": payload.get("lines") if isinstance(payload.get("lines"), list) else [],
            "ui_elements": _normalized_ui_elements(payload.get("ui_elements")),
            "quality": quality,
            "raw_model_name": self.settings.model,
            "metadata": {key: value for key, value in metadata.items() if isinstance(value, (str, int, float, bool))},
        }

    def _data_url(self, image_base64: str, mime_type: str) -> str:
        base64.b64decode(image_base64, validate=True)
        return f"data:{mime_type};base64,{image_base64}"

    def _http_error_message(self, exc: httpx.HTTPStatusError) -> str:
        endpoint = self._endpoint()
        detail = exc.response.text[:1000].strip()
        if detail:
            return f"visual OCR provider rejected request at {endpoint}: {exc.response.status_code} {detail}"
        return f"visual OCR provider rejected request at {endpoint}: {exc.response.status_code}"


def _normalized_ui_elements(value: object) -> list[dict[str, object]]:
    """Normalize provider GUI roles before contract validation.

    Args:
        value: Raw provider ``ui_elements`` payload.

    Returns:
        List of element dictionaries with stable role enum values.
    """

    if not isinstance(value, list):
        return []
    normalized: list[dict[str, object]] = []
    valid_roles = {role.value for role in VisualOCRElementRole}
    for item in value:
        if not isinstance(item, dict):
            continue
        element = dict(item)
        raw_role = str(element.get("role") or "").strip().lower()
        if raw_role not in valid_roles:
            element["raw_role"] = raw_role or None
            element["role"] = VisualOCRElementRole.OTHER.value
        normalized.append(element)
    return normalized


def _probe_png() -> bytes:
    """Return a tiny real screenshot-like PNG for provider health checks.

    A blank 1px image is cheap, but several remote VLM gateways reject it or
    return no useful text. The probe intentionally looks like a small UI
    fragment so settings validation exercises the same image path as real OCR
    without uploading any user content.
    """

    image = Image.new("RGB", (360, 180), "#f7fbfc")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((24, 24, 336, 156), radius=22, fill="#ffffff", outline="#aee9e2", width=2)
    draw.text((48, 58), _PROBE_TEXT, fill="#1f5960")
    draw.text((48, 96), "visible text only", fill="#526a70")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
