"""Typed contracts for asynchronous VLM OCR enrichment."""

from __future__ import annotations

from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator

from .base import ContractModel
from .common import BoundingBox, JsonScalar, SourceRef
from .enums import EventChangeType, VisualOCRAPIStyle, VisualOCRElementRole, VisualOCRProviderKind, VisualOCRStatus


class VisualOCRSettings(ContractModel):
    """Local configuration for screenshot visual OCR enrichment."""

    enabled: bool = True
    auto_run_on_capture: bool = True
    provider_kind: VisualOCRProviderKind = VisualOCRProviderKind.APPLE_VISION
    api_style: VisualOCRAPIStyle = VisualOCRAPIStyle.RESPONSES
    base_url: str = Field(default="https://api.openai.com/v1", min_length=1)
    allow_insecure_remote_base_url: bool = False
    model: str = Field(default="gpt-5.5", min_length=1)
    timeout_seconds: int = Field(default=120, ge=10, le=600)
    max_image_long_edge: int = Field(default=1800, ge=320, le=4096)
    api_key: SecretStr | None = None

    @model_validator(mode="after")
    def _validate_endpoint(self) -> "VisualOCRSettings":
        _validated_base_url(
            self.base_url,
            allow_insecure_remote=self.allow_insecure_remote_base_url,
        )
        return self


class VisualOCRPublicSettings(ContractModel):
    """Workbench-safe settings with secrets masked."""

    enabled: bool
    auto_run_on_capture: bool
    provider_kind: VisualOCRProviderKind
    api_style: VisualOCRAPIStyle
    base_url: str
    allow_insecure_remote_base_url: bool
    model: str
    timeout_seconds: int
    max_image_long_edge: int
    api_key_configured: bool


class VisualOCRSettingsUpdate(ContractModel):
    """Workbench settings payload for visual OCR configuration."""

    enabled: bool
    auto_run_on_capture: bool
    provider_kind: VisualOCRProviderKind = VisualOCRProviderKind.APPLE_VISION
    api_style: VisualOCRAPIStyle = VisualOCRAPIStyle.RESPONSES
    base_url: str = Field(min_length=1)
    allow_insecure_remote_base_url: bool = False
    model: str = Field(min_length=1)
    timeout_seconds: int = Field(ge=10, le=600)
    max_image_long_edge: int = Field(ge=320, le=4096)
    api_key: SecretStr | None = None

    @model_validator(mode="after")
    def _validate_endpoint(self) -> "VisualOCRSettingsUpdate":
        _validated_base_url(
            self.base_url,
            allow_insecure_remote=self.allow_insecure_remote_base_url,
        )
        return self

    @field_validator("base_url")
    @classmethod
    def _normalize_base_url(cls, value: str) -> str:
        return value.strip().rstrip("/")


class VisualOCRLine(ContractModel):
    """One line or short block of visible text read from the screenshot."""

    text: str = Field(min_length=1)
    reading_order: int = Field(ge=0)
    bbox: BoundingBox | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    uncertain: bool = False
    truncated: bool = False


class VisualOCRElement(ContractModel):
    """Agent-friendly GUI element detected in the screenshot."""

    label: str = Field(min_length=1)
    role: VisualOCRElementRole = VisualOCRElementRole.OTHER
    raw_role: str | None = None
    state: str | None = None
    nearby_context: str | None = None
    bbox: BoundingBox | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class VisualOCRQuality(ContractModel):
    """Quality diagnostics for one VLM OCR result."""

    confidence: float = Field(ge=0.0, le=1.0)
    text_chars: int = Field(ge=0)
    language_hint: str | None = None
    truncated: bool = False
    warnings: tuple[str, ...] = Field(default_factory=tuple)


class VisualOCRRequest(ContractModel):
    """Provider input for one screenshot visual OCR job."""

    request_id: str
    event_id: str
    artifact_id: str
    source: SourceRef
    user_note: str | None = None
    selection_bbox: BoundingBox | None = None
    image_base64: str
    image_media_type: str = "image/png"
    settings: VisualOCRPublicSettings


class VisualOCRResult(ContractModel):
    """Validated VLM OCR output persisted as derived evidence."""

    plain_text: str = ""
    readable_markdown: str = ""
    lines: tuple[VisualOCRLine, ...] = Field(default_factory=tuple)
    ui_elements: tuple[VisualOCRElement, ...] = Field(default_factory=tuple)
    quality: VisualOCRQuality
    raw_model_name: str | None = None
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)


class VisualOCRJobState(ContractModel):
    """Workbench-facing visual OCR state for an event."""

    event_id: str
    status: VisualOCRStatus
    job_id: str | None = None
    message: str | None = None
    artifact_id: str | None = None
    updated_at: str | None = None


class EventChange(ContractModel):
    """Small event update record used by Workbench long-polling."""

    change_id: int
    event_id: str
    change_type: EventChangeType
    payload: dict[str, JsonScalar] = Field(default_factory=dict)
    created_at: str


def _validated_base_url(value: str, *, allow_insecure_remote: bool = False) -> str:
    """Return a normalized provider URL that cannot smuggle credentials."""

    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise ValueError("base_url must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not contain query or fragment")
    if (
        parsed.scheme == "http"
        and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        and not allow_insecure_remote
    ):
        raise ValueError("http base_url is only allowed for localhost development endpoints")
    return normalized
