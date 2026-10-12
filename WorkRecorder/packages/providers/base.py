"""Provider ports for capture-time source resolution and evidence collection."""

from __future__ import annotations

from typing import Protocol

from packages.contracts import (
    CaptureAttemptRequest,
    CollectEvidenceCommand,
    CollectEvidenceResult,
    DetectedSurface,
    EventType,
    EvidenceKind,
    ProviderCapability,
    ProviderEvidenceBundle,
    ProviderManifest,
    ProviderRouteCandidate,
    ProviderRoutePlan,
)


class NamedProvider(Protocol):
    """Provider protocol for registry membership."""

    name: str


class SourceCaptureProvider(NamedProvider, Protocol):
    """App/source provider selected by the capture routing layer."""

    manifest: ProviderManifest
    capabilities: tuple[ProviderCapability, ...]
    event_type: EventType
    capture_evidence_kind: EvidenceKind

    def supports(self, surface: DetectedSurface) -> bool:
        """Return whether this provider can handle the detected surface.

        Args:
            surface: Surface produced by system detection.

        Returns:
            ``True`` when this provider can participate in routing.
        """
        ...

    async def freshness_score(self, surface: DetectedSurface) -> float:
        """Return a score from zero to one for currently registered context.

        Args:
            surface: Surface currently being routed.

        Returns:
            Freshness/confidence score where zero means unavailable.
        """
        ...

    def collect_command(
        self, *, attempt: CaptureAttemptRequest, surface: DetectedSurface, route: ProviderRouteCandidate | None = None
    ) -> CollectEvidenceCommand:
        """Build the capture-time command for the selected provider session.

        Args:
            attempt: Capture attempt containing trigger and selection geometry.
            surface: Detected surface selected for this provider.

        Returns:
            Command sent by the daemon to the provider session.
        """
        ...

    def bundle_from_result(
        self,
        *,
        attempt: CaptureAttemptRequest,
        surface: DetectedSurface,
        result: CollectEvidenceResult,
        route: ProviderRouteCandidate | None = None,
    ) -> ProviderEvidenceBundle | None:
        """Convert a command result into a provider evidence bundle.

        Args:
            attempt: Capture attempt being persisted.
            surface: Surface selected by the router.
            result: Provider command result.

        Returns:
            Provider bundle containing typed evidence drafts.
        """
        ...


class SystemEvidenceProvider(NamedProvider, Protocol):
    """System evidence provider run for every accepted capture attempt."""

    manifest: ProviderManifest
    evidence_kind: EvidenceKind
    capabilities: tuple[ProviderCapability, ...]

    async def collect(
        self,
        *,
        attempt: CaptureAttemptRequest,
        primary_surface: DetectedSurface | None,
        detected_surfaces: tuple[DetectedSurface, ...],
        route_plan: ProviderRoutePlan,
    ) -> ProviderEvidenceBundle:
        """Collect or describe system evidence for one capture attempt.

        Args:
            attempt: Capture attempt submitted by the shell.
            primary_surface: Highest-ranked detected surface, if any.
            detected_surfaces: All surfaces overlapped by the selected bbox.
            route_plan: App provider route plan for the same capture.

        Returns:
            Provider bundle containing system evidence drafts or diagnostics.
        """
        ...
