"""Common typed value objects used across WorkRecorder contracts."""

from __future__ import annotations

from datetime import datetime
from typing import TypeAlias

from pydantic import Field

from .base import ContractModel
from .enums import CoordinateSpace, IdentityProvider, ProviderCapability, SourceType

JsonScalar: TypeAlias = str | int | float | bool | None


class ActorRef(ContractModel):
    """Human, CLI, or agent actor reference.

    Attributes:
        actor_id: Stable local actor identifier.
        display_name: Optional user-facing label.
    """

    actor_id: str = Field(min_length=1)
    display_name: str | None = None


class UserRef(ContractModel):
    """Stable user identity used for ownership, sharing, and imports.

    Attributes:
        user_id: Local stable user id used for filters and provenance.
        display_name: Optional user-facing label.
        identity_provider: Provider that issued the user identity.
        feishu_open_id: Optional Feishu user id for tenant sharing.
        tenant_key: Optional organization or tenant boundary.
        email_hash: Optional hashed email for matching without raw email.
    """

    user_id: str = Field(min_length=1)
    display_name: str | None = None
    identity_provider: IdentityProvider = IdentityProvider.LOCAL
    feishu_open_id: str | None = None
    tenant_key: str | None = None
    email_hash: str | None = None

    @classmethod
    def from_actor(cls, actor: ActorRef) -> "UserRef":
        """Create a local user identity from an existing actor reference.

        Args:
            actor: Actor id and display name from capture or CLI auth.

        Returns:
            Local user reference derived from the actor.
        """

        return cls(user_id=actor.actor_id, display_name=actor.display_name, identity_provider=IdentityProvider.LOCAL)


class UserFilter(ContractModel):
    """Typed user filter shared by search, shares, and audit surfaces.

    Attributes:
        query: Loose user search string for CLI convenience.
        user_id: Exact local user id filter.
        display_name: Display-name substring filter.
        identity_provider: Optional typed identity provider.
        feishu_open_id: Exact Feishu user id filter.
        tenant_key: Exact tenant or organization filter.
    """

    query: str | None = Field(default=None, max_length=160)
    user_id: str | None = Field(default=None, max_length=160)
    display_name: str | None = Field(default=None, max_length=160)
    identity_provider: IdentityProvider | None = None
    feishu_open_id: str | None = Field(default=None, max_length=160)
    tenant_key: str | None = Field(default=None, max_length=160)

    @classmethod
    def from_query(cls, query: str | None) -> "UserFilter | None":
        """Build a conservative typed filter from one CLI/API query string.

        Args:
            query: Raw user filter text from CLI or API parameters.

        Returns:
            A typed filter, or None when the query is empty.
        """

        if query is None or not query.strip():
            return None
        return cls(query=query.strip())


class BoundingBox(ContractModel):
    """Rectangle in an explicit coordinate space.

    Attributes:
        x: Left coordinate.
        y: Top coordinate.
        width: Rectangle width.
        height: Rectangle height.
        coordinate_space: Coordinate system for all numeric fields.
    """

    x: int
    y: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    coordinate_space: CoordinateSpace = CoordinateSpace.SCREEN_PX


class FloatRect(ContractModel):
    """Rectangle that preserves fractional coordinates for Web mapping.

    Attributes:
        x: Left coordinate.
        y: Top coordinate.
        width: Rectangle width.
        height: Rectangle height.
        coordinate_space: Coordinate system for the numeric values.
    """

    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    coordinate_space: CoordinateSpace


class TextRange(ContractModel):
    """Inclusive-exclusive text character range.

    Attributes:
        start: Inclusive start character offset.
        end: Exclusive end character offset.
    """

    start: int = Field(ge=0)
    end: int = Field(gt=0)


class SourceRef(ContractModel):
    """Typed source reference without source-specific raw payloads.

    Attributes:
        source_type: Discriminator for the source family.
        title: Human-readable source title.
        app_name: Optional app or browser name.
        url: Optional web URL when source type is Web.
        origin: Optional web origin used by policy.
        connector_name: Optional provider name that produced the binding.
        external_id: Optional source-native id such as tab, thread, doc, or CRM id.
        version: Optional source snapshot version used for replay.
    """

    source_type: SourceType
    title: str = Field(min_length=1)
    app_name: str | None = None
    url: str | None = None
    origin: str | None = None
    connector_name: str | None = None
    external_id: str | None = None
    version: str | None = None


class BrowserTabRef(ContractModel):
    """Source-native reference for a browser tab.

    Attributes:
        browser: Browser family.
        tab_id: Browser tab id as reported by the provider.
        window_id: Browser window id as reported by the provider.
        url: Full current URL.
        origin: URL origin used by policy.
        title: Page title.
    """

    browser: str = Field(min_length=1)
    tab_id: str = Field(min_length=1)
    window_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    origin: str = Field(min_length=1)
    title: str = Field(min_length=1)


class WindowHint(ContractModel):
    """Best-effort app/window signal emitted by a system capture shell.

    Attributes:
        app_name: Owning application name.
        title: Optional window title.
        process_id: Optional OS process id.
        window_id: Optional OS/window-server or browser window id.
        frame: Optional window frame.
        overlap_ratio: Ratio of the user selection covered by this window.
        confidence: Capture-shell confidence for this hint.
    """

    app_name: str = Field(min_length=1)
    title: str | None = None
    process_id: int | None = None
    window_id: str | None = None
    bundle_id: str | None = None
    bundle_url: str | None = None
    window_layer: int | None = None
    window_order: int | None = Field(default=None, ge=0)
    display_id: str | None = None
    visible_area_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    is_frontmost: bool | None = None
    app_icon_ref: str | None = None
    frame: BoundingBox | None = None
    overlap_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class DetectedSurface(ContractModel):
    """A ranked local surface candidate for provider routing."""

    surface_id: str
    kind: str = Field(min_length=1)
    app_name: str
    title: str | None = None
    process_id: int | None = None
    window_id: str | None = None
    bundle_id: str | None = None
    bundle_url: str | None = None
    window_layer: int | None = None
    window_order: int | None = Field(default=None, ge=0)
    display_id: str | None = None
    visible_area_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    is_frontmost: bool | None = None
    app_icon_ref: str | None = None
    frame: BoundingBox | None = None
    overlap_ratio: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    capabilities: tuple[ProviderCapability, ...] = Field(default_factory=tuple)


class SurfaceDetectionResult(ContractModel):
    """Ranked surface detection output for one capture attempt."""

    trigger_id: str
    surfaces: tuple[DetectedSurface, ...] = Field(default_factory=tuple)
    selected_surface_id: str | None = None


class SourceBinding(ContractModel):
    """Binding between an event and a resolved source.

    Attributes:
        binding_id: Stable source binding id.
        source_ref: Normalized source reference.
        confidence: Resolver confidence between zero and one.
        resolved_at: Time the binding was created.
    """

    binding_id: str
    source_ref: SourceRef
    confidence: float = Field(ge=0.0, le=1.0)
    resolved_at: datetime
    provider_key: str | None = None
    provider_context_id: str | None = None
    matched_region: BoundingBox | None = None
    capabilities: tuple[ProviderCapability, ...] = Field(default_factory=tuple)
    expires_at: datetime | None = None
    requires_confirmation: bool = False
