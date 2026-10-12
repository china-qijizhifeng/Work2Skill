"""Configurable policy for primary/secondary source routing."""

from __future__ import annotations

from dataclasses import dataclass

from packages.contracts import DetectedSurface


@dataclass(frozen=True)
class ProviderRoutePolicyConfig:
    """Thresholds and scoring weights used by provider routing.

    The router deliberately depends on this small policy object instead of
    hard-coding primary/secondary route rules. New app families can tune
    overlap thresholds, fanout limits, and score weights without rewriting the
    orchestration path.

    Attributes:
        min_provider_confidence: Minimum detection/freshness score required
            before an app provider may be selected.
        min_secondary_overlap_ratio: Minimum bbox overlap for non-primary
            surfaces to participate as secondary sources.
        max_app_routes: Maximum number of app provider routes selected for one
            capture run.
        overlap_weight: Weight applied to bbox overlap when scoring primary
            surfaces.
        confidence_weight: Weight applied to detection confidence when scoring
            primary surfaces.
        visible_area_weight: Weight applied to visible window area, when known.
        frontmost_bonus: Small bonus for the frontmost window. This must remain
            lower than the overlap term so focus cannot steal primary ownership.
        z_order_base_bonus: Starting z-order bonus for top-most candidates.
        z_order_decay: Per-order decay subtracted from ``z_order_base_bonus``.
    """

    min_provider_confidence: float = 0.55
    min_secondary_overlap_ratio: float = 0.08
    max_app_routes: int = 4
    overlap_weight: float = 0.58
    confidence_weight: float = 0.31
    visible_area_weight: float = 0.06
    frontmost_bonus: float = 0.03
    z_order_base_bonus: float = 0.04
    z_order_decay: float = 0.002


@dataclass(frozen=True)
class SurfaceRouteAssignment:
    """Primary source and eligible secondary surfaces for one capture.

    Attributes:
        primary_surface_id: Surface selected as the capture's primary source.
        eligible_surface_ids: Surfaces allowed to run app provider fanout.
    """

    primary_surface_id: str | None
    eligible_surface_ids: tuple[str, ...]

    def is_eligible(self, surface: DetectedSurface) -> bool:
        """Return whether a surface should be considered for app provider fanout.

        Args:
            surface: Detected surface being checked.

        Returns:
            True when the policy selected the surface for app provider fanout.
        """

        return surface.surface_id in self.eligible_surface_ids

    def is_primary(self, surface: DetectedSurface) -> bool:
        """Return whether a surface is the capture's primary source.

        Args:
            surface: Detected surface being checked.

        Returns:
            True when the surface is the policy-selected primary source.
        """

        return surface.surface_id == self.primary_surface_id


class ProviderRoutePolicy:
    """Assign primary and secondary source roles from detected surfaces."""

    def __init__(self, config: ProviderRoutePolicyConfig | None = None) -> None:
        self.config = config or ProviderRoutePolicyConfig()

    def assign_surfaces(self, surfaces: tuple[DetectedSurface, ...]) -> SurfaceRouteAssignment:
        """Select primary source and provider-eligible secondary surfaces.

        Args:
            surfaces: Candidate surfaces discovered under the user's bbox.

        Returns:
            Primary source id plus the subset of surfaces eligible for app
            provider fanout.
        """

        if not surfaces:
            return SurfaceRouteAssignment(primary_surface_id=None, eligible_surface_ids=())
        ranked = self.rank_surfaces(surfaces)
        primary = ranked[0]
        eligible: list[str] = []
        for surface in ranked:
            if surface.confidence < self.config.min_provider_confidence:
                continue
            if (
                surface.surface_id != primary.surface_id
                and surface.overlap_ratio < self.config.min_secondary_overlap_ratio
            ):
                continue
            eligible.append(surface.surface_id)
            if len(eligible) >= self.config.max_app_routes:
                break
        return SurfaceRouteAssignment(
            primary_surface_id=primary.surface_id,
            eligible_surface_ids=tuple(eligible),
        )

    def surface_score(self, surface: DetectedSurface) -> float:
        """Score a surface for primary-source selection.

        Args:
            surface: Detected surface to rank.

        Returns:
            Normalized score combining bbox overlap, confidence, visibility,
            and small ordering hints. Bbox overlap intentionally dominates so a
            high-confidence frontmost sliver cannot become the primary app.
        """

        visible_ratio = surface.visible_area_ratio or 0.0
        frontmost_bonus = self.config.frontmost_bonus if surface.is_frontmost else 0.0
        z_order_bonus = 0.0
        if surface.window_order is not None:
            z_order_bonus = max(
                0.0,
                self.config.z_order_base_bonus - (surface.window_order * self.config.z_order_decay),
            )
        return min(
            1.0,
            max(
                0.0,
                (surface.overlap_ratio * self.config.overlap_weight)
                + (surface.confidence * self.config.confidence_weight)
                + (visible_ratio * self.config.visible_area_weight)
                + frontmost_bonus
                + z_order_bonus,
            ),
        )

    def surface_sort_key(self, surface: DetectedSurface) -> tuple[float, bool, int, float, float]:
        """Return primary-source ordering key.

        The score remains useful for diagnostics, but primary selection needs a
        deterministic tie-breaker for overlapping stacked windows. Equal bbox
        overlap means the visible top-most window should own the capture.
        """

        window_order = surface.window_order if surface.window_order is not None else 1_000_000
        return (
            round(surface.overlap_ratio, 3),
            bool(surface.is_frontmost),
            -window_order,
            surface.confidence,
            surface.visible_area_ratio or 0.0,
        )

    def rank_surfaces(self, surfaces: tuple[DetectedSurface, ...]) -> tuple[DetectedSurface, ...]:
        """Return surfaces ordered by primary-source policy."""

        return tuple(sorted(surfaces, key=self.surface_sort_key, reverse=True))
