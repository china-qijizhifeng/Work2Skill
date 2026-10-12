"""Command-driven Web source provider backed by browser sessions."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from packages.contracts import (
    CaptureAttemptRequest,
    CollectEvidenceCommand,
    CollectEvidenceResult,
    DetectedSurface,
    DomCaptureMode,
    EventType,
    EvidenceKind,
    ProviderCapability,
    ProviderCommandStatus,
    ProviderEvidenceBundle,
    ProviderKind,
    ProviderManifest,
    ProviderMode,
    ProviderRouteCandidate,
    SourceRef,
    SourceType,
)
from packages.providers.base import SourceCaptureProvider
from packages.providers.sessions import ProviderSessionService
from packages.shared.ids import IdFactory
from packages.shared.time import Clock

SUPPORTED_BROWSER_NAMES = ("chrome", "microsoft edge", "edge", "arc")


class WebCaptureProvider(SourceCaptureProvider):
    """Resolve and collect browser evidence through event-time commands."""

    name = "web.browser_extension"
    event_type = EventType.WEBPAGE_SELECTION_CAPTURED
    capture_evidence_kind = EvidenceKind.WEB
    capabilities = (
        ProviderCapability.RESOLVE_SOURCE,
        ProviderCapability.COLLECT_PAGE_METADATA,
        ProviderCapability.COLLECT_VISIBLE_TEXT,
        ProviderCapability.COLLECT_SELECTED_TEXT,
        ProviderCapability.COLLECT_PAGE_TEXT,
        ProviderCapability.COLLECT_READABILITY_TEXT,
        ProviderCapability.COLLECT_SANITIZED_DOM,
        ProviderCapability.COLLECT_FULL_DOM,
        ProviderCapability.MAP_SELECTION,
    )
    manifest = ProviderManifest(
        provider_key=name,
        display_name="Browser Extension",
        provider_kind=ProviderKind.SOURCE,
        modes=(ProviderMode.CAPTURE,),
        source_types=(SourceType.WEB,),
        capabilities=capabilities,
        evidence_kinds=(
            EvidenceKind.PAGE_METADATA,
            EvidenceKind.VISIBLE_TEXT,
            EvidenceKind.SELECTED_TEXT,
            EvidenceKind.PAGE_TEXT,
            EvidenceKind.SELECTION_MAP,
            EvidenceKind.FULL_DOM,
        ),
        policy_tags=("chrome_web_v1", "extension_live_dom", "safe_summary_card"),
        disclosure_profile_key="app.chrome.web_capture",
        command_schema_version=1,
        default_deadline_ms=5000,
    )

    def __init__(self, *, sessions: ProviderSessionService, ids: IdFactory, clock: Clock) -> None:
        """Create the Web provider."""

        self.sessions = sessions
        self.ids = ids
        self.clock = clock

    def supports(self, surface: DetectedSurface) -> bool:
        """Return whether this surface is a supported browser window.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        normalized_app_name = surface.app_name.strip().lower()
        return any(browser_name in normalized_app_name for browser_name in SUPPORTED_BROWSER_NAMES)

    async def freshness_score(self, surface: DetectedSurface) -> float:
        """Return session freshness for browser providers matching a surface.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        return await self.sessions.freshness_score(
            provider_key=self.name,
            surface=surface,
            required_capabilities=self.capabilities,
        )

    def collect_command(
        self, *, attempt: CaptureAttemptRequest, surface: DetectedSurface, route: ProviderRouteCandidate | None = None
    ) -> CollectEvidenceCommand:
        """Build the command that asks the extension to collect Web evidence now.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        return CollectEvidenceCommand(
            command_id=self.ids.new("cmd"),
            provider_key=self.name,
            attempt=attempt,
            surface=surface,
            evidence_kinds=(EvidenceKind.WEB,),
            required_capabilities=self.capabilities,
            dom_capture_mode=DomCaptureMode.FULL,
            deadline_ms=5000,
            metadata={
                "provider_version": "web_command_v1",
                "route_id": route.route_id if route is not None else None,
            },
        )

    def bundle_from_result(
        self,
        *,
        attempt: CaptureAttemptRequest,
        surface: DetectedSurface,
        result: CollectEvidenceResult,
        route: ProviderRouteCandidate | None = None,
    ) -> ProviderEvidenceBundle | None:
        """Convert successful Web command output into typed evidence.

        Args:
            See the typed signature for the accepted parameters and validation boundary.

        Returns:
            The typed result described by the method contract."""

        bundle = result.evidence_bundle
        source_binding = result.source_binding or (bundle.source_binding if bundle is not None else None)
        if result.status != ProviderCommandStatus.SUCCEEDED or bundle is None or source_binding is None:
            return None
        binding = source_binding
        sanitized_url = self._sanitized_url(binding.source_ref.url or "")
        if sanitized_url is None:
            return None
        binding = binding.model_copy(
            update={
                "source_ref": SourceRef(
                    source_type=SourceType.WEB,
                    title=binding.source_ref.title,
                    app_name=surface.app_name,
                    url=sanitized_url,
                    origin=self._origin_for_url(sanitized_url),
                    connector_name=self.name,
                    external_id=binding.source_ref.external_id,
                    version=f"command:{result.command_id}",
                ),
                "provider_key": self.name,
                "matched_region": attempt.selection_geometry.selected_region,
                "capabilities": self.capabilities,
                "resolved_at": self.clock.now(),
            }
        )
        return bundle.model_copy(
            update={
                "source_binding": binding,
                "provider_key": self.name,
                "provider_session_id": result.provider_session_id or bundle.provider_session_id,
                "command_id": result.command_id,
                "status": result.status,
                "diagnostics": {
                    **bundle.diagnostics,
                    "route_id": route.route_id if route is not None else None,
                },
            }
        )

    def _sanitized_url(self, raw_url: str) -> str | None:
        parsed = urlsplit(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    def _origin_for_url(self, sanitized_url: str) -> str:
        parsed = urlsplit(sanitized_url)
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
