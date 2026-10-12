"""Provider routing for capture attempts."""

from __future__ import annotations

from packages.contracts import (
    DetectedSurface,
    ProviderDecision,
    ProviderDecisionStatus,
    ProviderKind,
    ProviderRouteCandidate,
    ProviderRoutePlan,
    ProviderRouteRole,
    SurfaceDetectionResult,
    UnsupportedReason,
)
from packages.providers.registry import SourceProviderRegistry

from .route_policy import ProviderRoutePolicy


class ProviderRoutingService:
    """Select source providers without route-level source-specific branching."""

    def __init__(self, providers: SourceProviderRegistry, policy: ProviderRoutePolicy | None = None) -> None:
        """Create a provider router."""

        self.providers = providers
        self.policy = policy or ProviderRoutePolicy()

    async def route(self, detection: SurfaceDetectionResult) -> tuple[ProviderRoutePlan, UnsupportedReason | None]:
        """Return a route plan and optional unsupported reason.

        Args:
            detection: Ranked surfaces discovered from system/window hints.

        Returns:
            Provider route diagnostics plus ``None`` when a provider was
            selected, otherwise a structured unsupported reason.
        """

        decisions: list[ProviderDecision] = []
        routes: list[ProviderRouteCandidate] = []
        ranked_surfaces = self.policy.rank_surfaces(detection.surfaces)
        if not ranked_surfaces:
            return ProviderRoutePlan(trigger_id=detection.trigger_id), None
        assignment = self.policy.assign_surfaces(ranked_surfaces)
        for surface in ranked_surfaces:
            if surface.confidence < self.policy.config.min_provider_confidence:
                decisions.append(
                    self._decision(
                        surface,
                        "system.surface_detection",
                        ProviderDecisionStatus.SKIPPED,
                        surface.confidence,
                        reason=UnsupportedReason.LOW_CONFIDENCE.value,
                    )
                )
                continue
            if not assignment.is_eligible(surface):
                decisions.append(
                    self._decision(
                        surface,
                        "system.surface_detection",
                        ProviderDecisionStatus.SKIPPED,
                        surface.confidence,
                        reason="outside_route_policy",
                    )
                )
                continue
            for provider in self.providers.list():
                if not provider.supports(surface):
                    decisions.append(self._decision(surface, provider.name, ProviderDecisionStatus.UNSUPPORTED, 0.0))
                    continue
                score = min(surface.confidence, await provider.freshness_score(surface))
                status = (
                    ProviderDecisionStatus.SELECTED
                    if score >= self.policy.config.min_provider_confidence
                    else ProviderDecisionStatus.STALE
                )
                reason = (
                    None
                    if status == ProviderDecisionStatus.SELECTED
                    else UnsupportedReason.STALE_PROVIDER_CONTEXT.value
                )
                decisions.append(self._decision(surface, provider.name, status, score, reason=reason))
                route = ProviderRouteCandidate(
                    route_id=self._route_id(detection.trigger_id, len(routes)),
                    provider_key=provider.name,
                    provider_kind=getattr(provider.manifest, "provider_kind", ProviderKind.SOURCE),
                    role=(
                        ProviderRouteRole.PRIMARY_SOURCE
                        if assignment.is_primary(surface)
                        else ProviderRouteRole.SECONDARY_SOURCE
                    ),
                    surface_id=surface.surface_id,
                    confidence=score,
                    selected=status == ProviderDecisionStatus.SELECTED,
                    reason=reason,
                    target=self._route_target(surface),
                )
                routes.append(route)
        selected_routes = tuple(route for route in routes if route.selected)
        primary_route = next(
            (
                route
                for route in selected_routes
                if route.surface_id is not None and route.surface_id == assignment.primary_surface_id
            ),
            None,
        )
        selected_route_ids = tuple(route.route_id for route in selected_routes)
        plan = ProviderRoutePlan(
            trigger_id=detection.trigger_id,
            routes=tuple(routes),
            primary_surface_id=assignment.primary_surface_id,
            primary_route_id=primary_route.route_id if primary_route is not None else None,
            selected_route_ids=selected_route_ids,
            selected_provider_key=primary_route.provider_key if primary_route is not None else None,
            selected_surface_id=assignment.primary_surface_id,
            decisions=tuple(decisions),
        )
        return plan, None

    def selected_surface(self, detection: SurfaceDetectionResult, plan: ProviderRoutePlan) -> DetectedSurface | None:
        """Return the surface selected by a route plan.

        Args:
            detection: Original surface detection result.
            plan: Provider route plan produced for that detection.

        Returns:
            The selected surface, or ``None`` when the plan has no selection.
        """

        selected_surface_id = plan.selected_surface_id
        if selected_surface_id is None and plan.primary_route_id is not None:
            primary = next((route for route in plan.routes if route.route_id == plan.primary_route_id), None)
            selected_surface_id = primary.surface_id if primary is not None else None
        if selected_surface_id is None:
            return None
        return next((surface for surface in detection.surfaces if surface.surface_id == selected_surface_id), None)

    def selected_routes(self, plan: ProviderRoutePlan) -> tuple[ProviderRouteCandidate, ...]:
        """Return app provider routes selected for fanout.

        Args:
            plan: Multi-route plan produced for one capture attempt.

        Returns:
            Selected provider routes in the same stable order they were planned.
        """

        selected_ids = set(plan.selected_route_ids)
        return tuple(route for route in plan.routes if route.selected and route.route_id in selected_ids)

    def _route_id(self, trigger_id: str, index: int) -> str:
        return f"{trigger_id}:route:{index + 1}"

    def _route_target(self, surface: DetectedSurface) -> dict[str, str | int | float | bool | None]:
        return {
            "surface_kind": surface.kind,
            "app_name": surface.app_name,
            "title": surface.title,
            "process_id": surface.process_id,
            "window_id": surface.window_id,
            "bundle_id": surface.bundle_id,
            "bundle_url": None,
            "window_layer": surface.window_layer,
            "window_order": surface.window_order,
            "display_id": surface.display_id,
            "visible_area_ratio": surface.visible_area_ratio,
            "is_frontmost": surface.is_frontmost,
            "app_icon_ref": surface.app_icon_ref,
            "overlap_ratio": surface.overlap_ratio,
            "confidence": surface.confidence,
        }

    def _decision(
        self,
        surface: DetectedSurface,
        provider_key: str,
        status: ProviderDecisionStatus,
        confidence: float,
        reason: str | None = None,
    ) -> ProviderDecision:
        return ProviderDecision(
            provider_key=provider_key,
            status=status,
            confidence=confidence,
            reason=reason,
            surface_id=surface.surface_id,
        )
