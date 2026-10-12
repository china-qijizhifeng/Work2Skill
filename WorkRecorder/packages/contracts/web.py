"""Contracts for the browser/Web provider adapter."""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import Field

from .artifacts import ArtifactManifest
from .base import ContractModel
from .capture import SelectionMap
from .common import BoundingBox, BrowserTabRef, FloatRect, JsonScalar
from .enums import BrowserKind, DomCaptureMode, ProviderCapability


class BrowserPageMetadata(ContractModel):
    """Web page identity collected at capture time."""

    url: str = Field(min_length=1)
    origin: str = Field(min_length=1)
    title: str = Field(min_length=1)
    browser: BrowserKind | str
    tab_id: str = Field(min_length=1)
    window_id: str = Field(min_length=1)
    provider: str = Field(min_length=1)


class BrowserViewport(ContractModel):
    """Viewport geometry reported by a browser extension."""

    rect: FloatRect
    device_pixel_ratio: float = Field(gt=0.0)
    browser_zoom: float = Field(default=1.0, gt=0.0)
    scroll_x: float = 0.0
    scroll_y: float = 0.0


class BrowserWindowRef(ContractModel):
    """Browser window geometry used to match OS selections to tabs."""

    window_id: str = Field(min_length=1)
    native_window_id: str | None = None
    screen_rect: BoundingBox | None = None


class FullDomSnapshot(ContractModel):
    """Default full DOM capture returned by the command-driven Web provider."""

    capture_mode: DomCaptureMode = DomCaptureMode.FULL
    html: str = Field(max_length=2_000_000)
    text_content: str | None = Field(default=None, max_length=250_000)
    node_count: int = Field(default=0, ge=0)
    truncated: bool = False
    sanitizer_version: str = "full_dom_v2_privacy"


class BrowserPageTextSnapshot(ContractModel):
    """Agent-readable page text source captured from the loaded browser DOM."""

    markdown: str = Field(max_length=250_000)
    plain_text: str = Field(max_length=250_000)
    method: str = Field(default="dom_text_snapshot_v1", min_length=1)
    title: str | None = None
    byline: str | None = None
    site_name: str | None = None
    language: str | None = None
    content_hash: str | None = None
    char_count: int = Field(default=0, ge=0)
    truncated: bool = False
    omitted_reasons: tuple[str, ...] = Field(default_factory=tuple)
    frame_count: int = Field(default=0, ge=0)
    shadow_root_count: int = Field(default=0, ge=0)
    extractor_version: str = "browser_page_text_v1"


class BrowserSelectionMap(SelectionMap):
    """Selection map produced by the Web provider."""


class BrowserEvidenceBundle(ContractModel):
    """Typed Web evidence produced in response to a collect command."""

    page_metadata: BrowserPageMetadata
    viewport: BrowserViewport
    selected_text: str | None = Field(default=None, max_length=16000)
    visible_text: str | None = Field(default=None, max_length=64000)
    page_text: BrowserPageTextSnapshot | None = None
    selection_map: BrowserSelectionMap | None = None
    full_dom: FullDomSnapshot
    diagnostics: dict[str, JsonScalar] = Field(default_factory=dict)


class BrowserContextRegistration(ContractModel):
    """Short-lived browser tab context registered with the local daemon."""

    schema_version: int = Field(default=1, ge=1)
    provider_key: str = Field(default="web.browser_extension", min_length=1)
    provider_context_id: str = Field(min_length=1, max_length=160)
    browser: BrowserKind
    extension_id: str = Field(min_length=1)
    window: BrowserWindowRef
    tab: BrowserTabRef
    viewport: BrowserViewport
    capabilities: tuple[ProviderCapability, ...] = Field(default_factory=tuple)
    registered_at: datetime
    ttl_ms: int = Field(default=2500, ge=100, le=60000)
    metadata: dict[str, JsonScalar] = Field(default_factory=dict)

    def expires_at(self) -> datetime:
        """Return the wall-clock expiry for this registration.

        Returns:
            Registration timestamp plus the browser context TTL.
        """

        return self.registered_at + timedelta(milliseconds=self.ttl_ms)
